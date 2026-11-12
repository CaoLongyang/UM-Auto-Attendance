# -*- coding: utf-8 -*-
"""spectrum_sync.py —— 从 Spectrum (Moodle) 自动抓取考勤课表，不再手动填时间。

原理（全部走官方 Web Services，不需要浏览器）：
  1. core_webservice_get_site_info          确认 token 属于谁
  2. core_enrol_get_users_courses           你在读哪些课
  3. core_group_get_course_user_groups      你在这门课的分组（GROUP 6 之类）
  4. core_course_get_contents               每门课里「对你可见」的 Attendance 活动
  5. core_calendar_get_calendar_monthly_view 日历里每一次考勤 session 的开始时间/时长
     （mod_attendance 会把每个 session 写进日历，这是学生能拿到的唯一权威时间源）

注意：老师经常**不设分组限制**，于是所有 OCC 的考勤活动对你都 visible。
所以第 3 步拿到的组号会和活动名里的 OCC 编号对一下：
  - 名字里只有一个 OCC 编号，且不是你的组  -> 丢掉（比如你是 OCC 3，却看到 OCC 4/10）
  - 名字里没有 OCC，或一次列了多个 OCC      -> 保留，宁可多一条让你自己删
  - 名字里有 OCC 但整个时段都已经上完        -> 丢掉（机器人不用再为它醒着）

然后把「同一个活动、同一个星期几、同一个开始时间」的 session 归并成一条每周课表，
连同活动的 URL 一起交给 config.json。

token 从 token.txt 读取，格式与 att.py 相同：
    一行  ->  www.spectrum.um.edu.my 的 token
    两行  ->  第一行站点地址，第二行 token

命令行自测：
    python spectrum_sync.py            # 打印抓取结果
    python spectrum_sync.py --json     # 输出 JSON
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_SITE = "https://spectrum.um.edu.my"
DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
TOKEN_FILENAMES = ("token.txt", "token.text")
USER_AGENT = "UM-Auto-Attendance/2.0"

# 活动名里的 "OCC"/"Occurrence" 标记（编号在它后面一小段里）
OCC_MARKER = re.compile(r"occ(?:urrence)?", re.IGNORECASE)
# 分组名里的编号，例如 "GROUP 6 2026/2027_1"
GROUP_PATTERN = re.compile(r"group\s*[#:.\-]?\s*(\d+)", re.IGNORECASE)


class SpectrumError(RuntimeError):
    """网络 / token / Moodle 返回的错误，统一在这里抛出，方便 GUI 显示。"""


class TokenMissing(SpectrumError):
    pass


def app_dir() -> Path:
    """脚本所在目录；打包成 exe 后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def parse_token_file(path) -> tuple[str, str]:
    """读 token.txt：一行是 token，两行是（站点, token）。"""
    lines = [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise TokenMissing(f"{Path(path).name} 是空的。")
    if len(lines) == 1:
        return DEFAULT_SITE, lines[0]
    return lines[0].rstrip("/"), lines[1]


def find_token() -> tuple[str, str, Path] | tuple[None, None, None]:
    """按顺序找工作目录里的 token 文件，返回 (site, token, 路径)。"""
    for folder in (app_dir(), Path.cwd()):
        for name in TOKEN_FILENAMES:
            candidate = folder / name
            if not candidate.is_file():
                continue
            try:
                site, token = parse_token_file(candidate)
            except (OSError, TokenMissing):
                continue
            if token:
                return site, token, candidate
    return None, None, None


def group_numbers_from_names(names) -> set[int]:
    """从「GROUP 6 2026/2027_1」这种分组名里取出 6。"""
    numbers = set()
    for name in names or ():
        match = GROUP_PATTERN.search(str(name))
        if match:
            numbers.add(int(match.group(1)))
    return numbers


def occ_numbers_in_title(title: str) -> set[int]:
    """活动名里的 OCC 编号。

    只看 "OCC" 后面紧跟的一小段，避免把年份之类算进来：
      "Attendance (Occ5)"                  -> {5}
      "Attendance for Lecture (OCC 3, 4, 5, 6, 7)" -> {3,4,5,6,7}
      "OCC3-OCC5-OCC8-OCC9"                -> {3,5,8,9}
    """
    numbers: set[int] = set()
    for match in OCC_MARKER.finditer(title or ""):
        tail = (title or "")[match.end(): match.end() + 24]
        numbers.update(int(number) for number in re.findall(r"\d+", tail))
    return numbers


def split_by_occ(modules: dict[int, dict]) -> tuple[dict[int, dict], list[dict]]:
    """把「名字里写了单一 OCC、但不是我的组」的活动挑出来。

    只在一个活动名里出现**唯一一个** OCC 编号时才敢过滤：
      "OCC 4 Lab/Tutorial Attendance"  + 我是 GROUP 3  -> 不是我的，丢掉
      "Lecture Group 2 Attendance (OCC3-OCC5-OCC8-OCC9)" -> 多个编号，分不清，保留
      "Attendance（没有 OCC）"                            -> 保留
    """
    kept: dict[int, dict] = {}
    rejected: list[dict] = []
    for cmid, module in modules.items():
        my_groups = module.get("group_numbers") or set()
        occ = occ_numbers_in_title(module["title"])
        if my_groups and len(occ) == 1:
            number = next(iter(occ))
            if number not in my_groups:
                rejected.append({
                    "course": module["course"],
                    "title": module["title"],
                    "url": module["url"],
                    "occ": number,
                    "my_groups": sorted(my_groups),
                })
                continue
        kept[cmid] = module
    return kept, rejected


def month_span(back: int, ahead: int) -> list[tuple[int, int]]:
    """今天往前 back 个月、往后 ahead 个月，返回 [(年, 月), ...]。"""
    today = date.today()
    y, m = today.year, today.month
    for _ in range(max(0, back)):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    out = []
    for _ in range(max(0, back) + max(0, ahead) + 1):
        out.append((y, m))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


class SpectrumClient:
    """极简 Moodle Web Services 客户端（GET + JSON）。"""

    def __init__(self, token: str, site: str = DEFAULT_SITE, timeout: int = 30):
        if not token:
            raise TokenMissing("缺少 token。")
        self.token = token.strip()
        self.site = (site or DEFAULT_SITE).rstrip("/")
        self.timeout = timeout
        self._info: dict | None = None

    def ws(self, function: str, **params):
        payload = {
            "wstoken": self.token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
            **params,
        }
        url = f"{self.site}/webservice/rest/server.php?{urlencode(payload)}"
        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except HTTPError as exc:
            raise SpectrumError(f"Spectrum 返回 HTTP {exc.code}，请稍后再试。") from exc
        except (URLError, OSError) as exc:
            raise SpectrumError(f"连不上 {self.site}（网络问题？）：{exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SpectrumError("Spectrum 返回的不是 JSON，可能是维护页或登录页。") from exc

        if isinstance(data, dict) and data.get("exception"):
            code = str(data.get("errorcode") or "")
            message = data.get("message") or data["exception"]
            if code in {"invalidtoken", "accessexception", "invalidtokenid"}:
                raise SpectrumError("token 无效或已被吊销，请到 Spectrum 重新生成一个。")
            if code == "webservicesnotenabled":
                raise SpectrumError("站点没有开放 Web Services。")
            raise SpectrumError(f"{function}: {message}")
        return data

    def site_info(self) -> dict:
        if self._info is None:
            self._info = self.ws("core_webservice_get_site_info")
        return self._info

    def my_courses(self) -> list[dict]:
        return self.ws("core_enrol_get_users_courses", userid=self.site_info()["userid"]) or []

    def attendance_modules(self, courseid: int) -> list[dict]:
        """一门课里对我可见的 Attendance 活动（隐藏/分组不符的会被 uservisible 标出来）。"""
        modules = []
        for section in self.ws("core_course_get_contents", courseid=courseid) or []:
            for module in section.get("modules") or []:
                if module.get("modname") != "attendance":
                    continue
                if module.get("uservisible") is False:
                    continue
                if module.get("visible") == 0:
                    continue
                modules.append({
                    "cmid": int(module["id"]),
                    "url": module.get("url") or "",
                    "title": (module.get("name") or "").strip(),
                })
        return modules

    def my_groups(self, courseid: int) -> set[int]:
        """我在这门课里的分组编号，例如 {6}。拿不到就返回空集合。"""
        try:
            data = self.ws("core_group_get_course_user_groups", courseid=courseid)
        except SpectrumError:
            return set()
        groups = data.get("groups") if isinstance(data, dict) else data
        return group_numbers_from_names([group.get("name", "") for group in groups or []])

    def month_events(self, year: int, month: int) -> list[dict]:
        view = self.ws("core_calendar_get_calendar_monthly_view", year=str(year), month=str(month))
        events = []
        if not isinstance(view, dict):
            return events
        for week in view.get("weeks") or []:
            for day in week.get("days") or []:
                for event in day.get("events") or []:
                    events.append(event)
        return events


def derive_slots(modules: dict[int, dict], events: list[dict]) -> tuple[list[dict], list[dict]]:
    """把 session 事件归并成每周固定时段。

    返回 (课表条目, 被丢弃的统计)。
    """
    buckets: dict[tuple[int, int, str], list[tuple[int, int]]] = {}
    for event in events:
        if str(event.get("component") or "") not in {"mod_attendance", "attendance"}:
            continue
        try:
            cmid = int(event.get("instance"))
        except (TypeError, ValueError):
            continue
        if cmid not in modules:
            continue
        moment = datetime.fromtimestamp(int(event["timestart"]))
        key = (cmid, moment.weekday(), moment.strftime("%H:%M"))
        buckets.setdefault(key, []).append((int(event.get("timeduration") or 0),
                                            int(event["timestart"])))

    per_module: dict[int, int] = {}
    for key, items in buckets.items():
        per_module[key[0]] = max(per_module.get(key[0], 0), len(items))

    now = datetime.now().timestamp()
    entries: list[dict] = []
    dropped: list[dict] = []
    for (cmid, weekday, start_text), items in sorted(
        buckets.items(), key=lambda item: (item[0][1], item[0][2], item[0][0])
    ):
        module = modules[cmid]
        seen = len(items)
        dominant = per_module.get(cmid, seen)
        last_ts = max(ts for _, ts in items)

        base = {
            "day": weekday,
            "start": start_text,
            "sessions": seen,
            "title": module["title"],
            "url": module["url"],
        }

        # 整个时段都已经过去了，机器人没必要再为它醒着
        if last_ts < now:
            dropped.append({**base, "reason": "expired"})
            continue

        # 每周都有的时段才保留；偶尔一次的补课/讲座会被丢掉，避免机器人跑错时间。
        # 整个活动只排过一次 session 时，仍然保留（例如只有一次的 briefing）。
        keep = seen >= max(2, dominant * 0.4) or (seen == 1 and dominant == 1)
        if not keep:
            dropped.append({**base, "reason": "irregular"})
            continue

        durations = [duration for duration, _ts in items]
        positive = [d for d in durations if d > 0]
        duration = int(statistics.median(positive)) if positive else 15 * 60
        if duration <= 0:
            duration = 15 * 60

        start_dt = datetime(2000, 1, 1, int(start_text[:2]), int(start_text[3:]))
        end_dt = start_dt + timedelta(seconds=duration)
        if end_dt.date() != start_dt.date():
            end_dt = start_dt.replace(hour=23, minute=59)

        entries.append({
            "day": weekday,
            "start": start_text,
            "end": end_dt.strftime("%H:%M"),
            "name": f"{module['course']} | {module['title']}",
            "url": module["url"],
            "source": "sync",
            "course": module["course"],
            "cmid": cmid,
            "sessions": seen,
        })
    return entries, dropped


def sync(
    token: str | None = None,
    site: str | None = None,
    months_back: int = 1,
    months_ahead: int = 3,
    progress=None,
    ignored: set[str] | None = None,
) -> dict:
    """抓取整份课表。

    返回 {
        "entries": [...],        # 可以直接写进 config.json 的课表
        "courses": int,          # 课程数
        "activities": int,       # 保留的 Attendance 活动数（已去掉不是我的 OCC）
        "filtered": [...],       # 因为 OCC 编号不是我的组而被丢掉的
        "dropped": [...],        # 被判定为临时 session 而忽略的时段
        "missing": [...],        # 没有排任何 session 的活动
        "errors": [...],         # 单门课抓取失败的原因（不影响其它课）
        "months": "2026-10 ~ 2027-02",
        "username": "...",
        "site": "...",
    }
    """
    log = progress or (lambda _message: None)
    ignored = ignored or set()

    client = SpectrumClient(token or "", site or DEFAULT_SITE)
    info = client.site_info()
    log(f"已连接 {client.site}，账号 {info.get('username', '?')}")

    courses = client.my_courses()
    log(f"共 {len(courses)} 门课，正在读取 Attendance 活动…")

    modules: dict[int, dict] = {}
    errors: list[str] = []
    for index, course in enumerate(courses, 1):
        shortname = course.get("shortname") or str(course.get("id"))
        try:
            found = client.attendance_modules(course["id"])
        except SpectrumError as exc:
            errors.append(f"{shortname}: {exc}")
            continue
        if not found:
            continue
        groups = client.my_groups(course["id"])   # 例如 {6}
        for module in found:
            module["course"] = shortname
            module["courseid"] = course["id"]
            module["group_numbers"] = groups
            modules[module["cmid"]] = module
        group_text = f"，我的组 {sorted(groups)}" if groups else ""
        log(f"  [{index}/{len(courses)}] {shortname}: {len(found)} 个考勤活动{group_text}")

    before = len(modules)
    modules, wrong_occ = split_by_occ(modules)
    if wrong_occ:
        log(f"按组别丢掉 {len(wrong_occ)} 个不是我的 OCC 活动（见下面的清单）")

    log(f"可见的 Attendance 活动共 {before} 个，保留 {len(modules)} 个，正在读取日历…")

    months = month_span(months_back, months_ahead)
    events: list[dict] = []
    for (year, month) in months:
        try:
            month_events = client.month_events(year, month)
        except SpectrumError as exc:
            errors.append(f"{year}-{month:02d} 日历: {exc}")
            continue
        used = 0
        for event in month_events:
            if str(event.get("component") or "") != "mod_attendance":
                continue
            try:
                if int(event.get("instance")) in modules:
                    events.append(event)
                    used += 1
            except (TypeError, ValueError):
                continue
        log(f"  {year}-{month:02d}: {used} 次考勤 session")

    entries, dropped = derive_slots(modules, events)

    seen_cmid = {int(event["instance"]) for event in events if str(event.get("instance", "")).isdigit()}
    missing = [
        {"course": module["course"], "title": module["title"], "url": module["url"]}
        for cmid, module in modules.items()
        if cmid not in seen_cmid
    ]

    if ignored:
        before = len(entries)
        entries = [entry for entry in entries if entry["url"] not in ignored]
        if before != len(entries):
            log(f"按你的忽略列表跳过了 {before - len(entries)} 个时段")

    return {
        "entries": entries,
        "courses": len(courses),
        "activities": len(modules),
        "filtered": wrong_occ,
        "dropped": dropped,
        "missing": missing,
        "errors": errors,
        "months": f"{months[0][0]}-{months[0][1]:02d} ~ {months[-1][0]}-{months[-1][1]:02d}",
        "username": info.get("username"),
        "site": client.site,
    }


def sync_from_file(token_file=None, **kwargs) -> dict:
    """从 token.txt 读 token 并同步。"""
    if token_file is not None:
        site, token = parse_token_file(token_file)
    else:
        site, token, path = find_token()
        if not token:
            raise TokenMissing(
                "找不到 token.txt。请把 Spectrum 的 Web Services token 写进程序目录下的 token.txt。"
            )
    return sync(token=token, site=site, **kwargs)


def _print_report(result: dict) -> None:
    entries = result["entries"]
    print(f"账号: {result['username']} @ {result['site']}")
    print(f"课程 {result['courses']} 门 / 保留考勤活动 {result['activities']} 个 / 日历范围 {result['months']}")
    print(f"整理出 {len(entries)} 个每周时段：\n")
    for entry in entries:
        print(f"  {DAY_LABELS[entry['day']]} {entry['start']}-{entry['end']}  "
              f"{entry['name']}  ({entry['sessions']} 次)")
    if result.get("filtered"):
        print(f"\n不是你的组、已丢掉的 OCC 活动 {len(result['filtered'])} 个：")
        for item in result["filtered"]:
            print(f"  {item['course']} | {item['title']}  (OCC {item['occ']} / 我是 {item['my_groups']})")
    expired = [item for item in result["dropped"] if item.get("reason") == "expired"]
    irregular = [item for item in result["dropped"] if item.get("reason") != "expired"]
    if expired:
        print(f"\n已经上完、不用再挂机的时段 {len(expired)} 个：")
        for item in expired:
            print(f"  {DAY_LABELS[item['day']]} {item['start']}  {item['title']}")
    if irregular:
        print(f"\n忽略的临时时段 {len(irregular)} 个：")
        for item in irregular:
            print(f"  {DAY_LABELS[item['day']]} {item['start']} x{item['sessions']}  {item['title']}")
    if result["missing"]:
        print(f"\n没有任何 session 的活动 {len(result['missing'])} 个：")
        for item in result["missing"]:
            print(f"  {item['course']} | {item['title']}")
    if result["errors"]:
        print("\n警告：")
        for item in result["errors"]:
            print(f"  {item}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="从 Spectrum 自动抓取考勤课表")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--token-file", help="token 文件路径（默认找 token.txt）")
    parser.add_argument("--months-back", type=int, default=1)
    parser.add_argument("--months-ahead", type=int, default=3)
    args = parser.parse_args(argv)

    try:
        result = sync_from_file(
            args.token_file,
            months_back=args.months_back,
            months_ahead=args.months_ahead,
            progress=lambda message: print(message, file=sys.stderr),
        )
    except SpectrumError as exc:
        print(f"同步失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
