# -*- coding: utf-8 -*-
"""gui.py —— UM Auto Attendance Manager

界面分三块：
  1. 顶部：登录 Spectrum / 启动自动签到引擎
  2. Spectrum 同步：填一次 token，点一下按钮，课表（含上课时间）自动生成
  3. 手动添加：同步漏掉的课可以自己补一条
"""
import datetime
import json
import re
import threading
import time

import flet as ft

import i18n
import spectrum_sync
from i18n import t
from sign_in import (BROWSER_DIED, LOGIN_TIMEOUT, NOT_OPEN, OK, PASSWORD,
                     manual_login, start_sign_in)

BASE_DIR = spectrum_sync.app_dir()
CONFIG_PATH = BASE_DIR / "config.json"
TOKEN_PATH = BASE_DIR / "token.txt"
SIGNED_PATH = BASE_DIR / "signed.json"
LOG_DIR = BASE_DIR / "logs"

DAY_LABELS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_LABELS_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def day_labels():
    """星期标签跟着界面语言走（下拉框、课程卡片、日志都用它）。"""
    return DAY_LABELS_ZH if i18n.LANG == "zh" else DAY_LABELS_EN
RETRY_GAP = 180              # 同一条签到失败后至少隔多久再试（3 分钟）
MAX_ATTEMPTS = 10            # 同一条签到一天最多试几次（约覆盖半小时）
AUTO_SYNC_HOURS = 6          # 距上次同步超过几小时，启动时自动同步
MAX_WAIT = 1800              # 单次最长睡眠（秒）：只为系统时间被改动后能重新对表，不是轮询签到
KEEP_AWAKE = True            # 引擎运行期间阻止 Windows 自动休眠
RESUME_POLL = 30             # 多少秒对一次表，用来发现「刚从休眠里醒来」
RESUME_DRIFT = 5             # 墙钟比单调钟多走几秒，就认为中间被挂起过


# --------------------------------------------------------------------------- #
# 配置文件
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    data = {"classes": [], "ignored": [], "last_sync": None, "lang": None}
    if not CONFIG_PATH.is_file():
        return data
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return data

    if isinstance(raw, list):                 # 旧版本：直接是一个列表
        data["classes"] = raw
    elif isinstance(raw, dict):
        data["classes"] = raw.get("classes") or []
        data["ignored"] = raw.get("ignored") or []
        data["last_sync"] = raw.get("last_sync")
        data["lang"] = raw.get("lang")
    if not isinstance(data["classes"], list):
        data["classes"] = []
    if not isinstance(data["ignored"], list):
        data["ignored"] = []

    # 旧配置里的名字常常带着 \r（从网页复制来的），顺手清掉
    for course in data["classes"]:
        if not isinstance(course, dict):
            continue
        for key in ("name", "start", "end", "url"):
            value = course.get(key)
            if isinstance(value, str):
                course[key] = value.strip()
    return data


def save_config(classes, ignored, last_sync, lang) -> None:
    payload = {
        "classes": classes,
        "ignored": sorted(ignored),
        "last_sync": last_sync,
        "lang": lang,
    }
    try:
        CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"保存 config.json 失败: {exc}")


# --------------------------------------------------------------------------- #
# 时间小工具（兼容 "8.00" / "8:00" / "08:00" / "800"）
# --------------------------------------------------------------------------- #
def parse_hhmm(text):
    if text is None:
        return None
    value = str(text).strip().replace("：", ":")
    match = re.match(r"^(\d{1,2})\s*[:.]\s*(\d{1,2})$", value)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        return (hour, minute) if 0 <= hour < 24 and 0 <= minute < 60 else None
    if re.fullmatch(r"\d{3,4}", value):
        return int(value[:-2]) % 24, int(value[-2:]) % 60
    if re.fullmatch(r"\d{1,2}", value):
        return int(value) % 24, 0
    return None


def human_delay(seconds: float) -> str:
    """把「还有多少秒」说成人话，给日志用。"""
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if i18n.LANG == "en":
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m"
        return f"{seconds}s"
    if days:
        return f"{days} 天 {hours} 小时"
    if hours:
        return f"{hours} 小时 {minutes} 分"
    if minutes:
        return f"{minutes} 分钟"
    return f"{seconds} 秒"


def entry_time_text(entry) -> str:
    day = entry.get("day")
    try:
        day_label = day_labels()[int(day)]
    except (TypeError, ValueError, IndexError):
        day_label = "?"

    def pretty(value):
        parsed = parse_hhmm(value)
        return f"{parsed[0]:02d}:{parsed[1]:02d}" if parsed else str(value)

    return f"{day_label}  {pretty(entry.get('start', '?'))} - {pretty(entry.get('end', '?'))}"


# --------------------------------------------------------------------------- #
# 排期：算出「下一次该动手的时刻」，引擎睡到那个点再醒
# --------------------------------------------------------------------------- #
def sign_key(course: dict, day: datetime.date) -> str:
    return f"{day.isoformat()}|{course.get('url')}|{course.get('start')}"


def occurrence_at(course: dict, day: datetime.date):
    """这门课在 day 那天的 (开始, 结束)；时间写坏了返回 None。"""
    parsed_start = parse_hhmm(course.get("start"))
    if parsed_start is None:
        return None
    start = datetime.datetime.combine(day, datetime.time(*parsed_start))
    parsed_end = parse_hhmm(course.get("end"))
    end = datetime.datetime.combine(day, datetime.time(*parsed_end)) if parsed_end else None
    if end is None or end <= start:
        end = start + datetime.timedelta(minutes=15)
    return start, end


def next_trigger(classes, signed, attempts, now: datetime.datetime):
    """下一次该动手的时刻 -> (时间, 课程, key, 那天)；没得签返回 None。

    已经进入时段但还没签的，直接返回 now（立刻签）；
    签失败的按 RETRY_GAP 排下一次，剩的时间不够就不再排。
    """
    best = None
    for course in list(classes):
        try:
            weekday = int(course.get("day"))
        except (TypeError, ValueError):
            continue
        for offset in range(8):                # 今天 + 往后 7 天，够覆盖下周同一节课
            day = now.date() + datetime.timedelta(days=offset)
            if day.weekday() != weekday:
                continue
            window = occurrence_at(course, day)
            if window is None:
                continue
            start, end = window
            if now > end:
                continue                       # 这一节已经上完了
            key = sign_key(course, day)
            if key in signed:
                continue                       # 这一节已经签过
            if now < start:
                candidate = start
            else:
                tries, last_at = attempts.get(key, (0, None))
                if tries >= MAX_ATTEMPTS:
                    continue
                candidate = now if last_at is None else max(
                    now, last_at + datetime.timedelta(seconds=RETRY_GAP))
                if candidate > end:
                    continue                   # 剩下的时间不够再试一次
            if best is None or candidate < best[0]:
                best = (candidate, course, key, day)
            break                              # 这门课最近的一次算过了，别再看下周
    return best


def missed_since(classes, signed, attempted, since: datetime.datetime,
                 now: datetime.datetime):
    """since..now 之间「悄悄过去」的时段：没签、也一次都没试过。

    只会在一种情况下出现——那段时间电脑在休眠，引擎根本没醒。
    返回 [(结束时间, 课程, 那天)]，用来给用户一个明确的交代。
    """
    hits = []
    day = since.date()
    while day <= now.date():
        for course in classes:
            try:
                if int(course.get("day")) != day.weekday():
                    continue                   # 这门课不在这一天
            except (TypeError, ValueError):
                continue
            window = occurrence_at(course, day)
            if window is None:
                continue
            start, end = window
            if end <= since or end > now:
                continue                       # 这一节不是在这段空档里结束的
            key = sign_key(course, day)
            if key in signed or key in attempted:
                continue                       # 签过了 / 试过了，不算「悄悄错过」
            hits.append((end, course, day))
        day += datetime.timedelta(days=1)
    return hits


# --------------------------------------------------------------------------- #
# 电源：引擎跑着的时候别让 Windows 自己睡过去
# --------------------------------------------------------------------------- #
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake(on: bool) -> None:
    """阻止 Windows 自动休眠（屏幕照样可以关，不费电）。

    这是「按线程」的：必须在跑引擎的那个线程里调用，线程退出时自动失效。
    注意：它只能挡住「空闲休眠」，合上盖子 / 手动点睡眠仍然会睡——那种情况靠
    resume_watch 在唤醒后立刻补签。
    """
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 主界面
# --------------------------------------------------------------------------- #
def main(page: ft.Page):
    page.title = "UM Auto Attendance Manager"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 560
    page.window.height = 900
    page.window.min_width = 480
    page.window.min_height = 640
    page.padding = 24
    page.scroll = ft.ScrollMode.ADAPTIVE
    # 让内容按窗口宽度约束，否则长文本/带 expand 的 Row 会按自身宽度排版，把按钮挤出窗口
    page.horizontal_alignment = ft.CrossAxisAlignment.STRETCH

    config = load_config()
    i18n.set_lang(config.get("lang"))
    state = {
        "classes": config["classes"],
        "ignored": set(config["ignored"]),
        "last_sync": config["last_sync"],
        "site": spectrum_sync.DEFAULT_SITE,
        "engine": False,
        "signed": set(),
        "attempts": {},
        "day": None,
        "syncing": False,
    }

    def labels() -> dict:
        """界面文案集中在这里：创建控件和切换语言都从这里取，不会两处走样。"""
        return {
            "engine_start": t("🚀 启动自动签到", "🚀 Start engine"),
            "engine_stop": t("⏹️ 停止引擎", "⏹️ Stop engine"),
            "login": t("🔑 登录 Spectrum", "🔑 Log In Spectrum"),
            "hint": t("浏览器只需登录一次；自动签到时整晚只用一个窗口。",
                      "Log in once — the engine keeps a single browser window all day."),
            "sync_title": t("从 Spectrum 自动更新课表", "Sync timetable from Spectrum"),
            "sync_desc": t(
                "登录后填一次 token，点一下就会把「对你可见」的考勤活动和上课时间全部抓下来，"
                "不用再手抄 URL 和时间。token 会存进 token.txt，下次启动自动同步。",
                "Paste your token once and click Sync: every attendance activity you can see "
                "— with its class time — is pulled in automatically, no more copying URLs by "
                "hand. The token is saved to token.txt and re-synced on the next launch.",
            ),
            "sync_btn": t("🔄 自动同步课表", "🔄 Sync timetable"),
            "help": t(
                "没有 token？浏览器打开 https://spectrum.um.edu.my/user/managetoken.php "
                "→ Create token → 选 Moodle mobile web service → 复制。\n"
                "（如果你已经在用 att.py，把它的 token.txt 复制到本程序目录即可。）",
                "No token? Open https://spectrum.um.edu.my/user/managetoken.php in a browser "
                "→ Create token → pick Moodle mobile web service → copy it.\n"
                "(Already using att.py? Copy its token.txt into this folder.)",
            ),
            "restore": t("↺ 恢复被忽略的课", "↺ Restore ignored"),
            "add_title": t("手动添加（同步漏掉时用）", "Add manually (when sync misses one)"),
            "day": t("星期", "Day"),
            "start": t("开始 08:00", "Start 08:00"),
            "end": t("结束 08:15", "End 08:15"),
            "name": t("课程名（如 WIA2007）", "Course name (e.g. WIA2007)"),
            "url": t("Attendance 页面 URL", "Attendance page URL"),
            "add_btn": t("➕ 添加到课表", "➕ Add to timetable"),
            "list_title": t("我的课表", "My timetable"),
            "lang_btn": t("EN", "中文"),
        }

    # ---------------------------- 组件 ---------------------------- #
    course_list = ft.Column(spacing=10)
    count_text = ft.Text(t("0 节课", "0 classes"), color="grey", size=12)

    def count_label() -> str:
        return t(f"{len(state['classes'])} 节课", f"{len(state['classes'])} classes")

    log_view = ft.ListView(expand=True, spacing=4, height=160)
    log_container = ft.Container(
        content=log_view,
        border=ft.Border.all(1, "grey"),
        border_radius=8,
        padding=10,
        visible=False,
        bgcolor="#1e1e1e",
    )
    log_lock = threading.Lock()

    sync_status = ft.Text("", size=12, color="grey")

    def write_log(message: str, color: str = "green") -> None:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        with log_lock:
            log_container.visible = True
            # 新的放最上面：这样永远能看到最新一行，又不用去动页面滚动位置
            log_view.controls.insert(0, ft.Text(f"[{stamp}] {message}", size=12, color=color))
            if len(log_view.controls) > 120:
                log_view.controls.pop()
            # 同时写一份到 logs/，出问题时可以把文件发出来
            try:
                LOG_DIR.mkdir(exist_ok=True)
                log_file = LOG_DIR / f"app-{datetime.date.today().isoformat()}.log"
                with log_file.open("a", encoding="utf-8") as handle:
                    handle.write(f"[{stamp}] {message}\n")
            except OSError:
                pass
            try:
                page.update()
            except Exception:
                pass

    def notify(message: str, color: str = "#2e7d32") -> None:
        try:
            page.show_dialog(ft.SnackBar(ft.Text(message, color="white"), bgcolor=color))
        except Exception:
            write_log(message)

    # ---------------------------- 课表卡片 ---------------------------- #
    def make_card(course: dict) -> ft.Card:
        is_auto = course.get("source") == "sync"
        tag = ft.Container(
            content=ft.Text(t("自动", "auto") if is_auto else t("手动", "manual"),
                            size=10, color="white"),
            bgcolor="#2e7d32" if is_auto else "#455a64",
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
            border_radius=4,
        )

        def delete_card(_event):
            delete_course(course)

        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Column(
                            spacing=3,
                            expand=True,
                            controls=[
                                ft.Row(
                                    [tag, ft.Text(course.get("name", "?"), size=15,
                                                  weight=ft.FontWeight.BOLD, selectable=True)],
                                    spacing=8,
                                    wrap=True,
                                ),
                                ft.Text(entry_time_text(course), color="grey", size=13),
                                ft.Text(course.get("url", ""), size=10, color="blue",
                                        selectable=True),
                            ],
                        ),
                        ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="删除",
                                      icon_color="red", on_click=delete_card),
                    ],
                ),
                padding=14,
            ),
            elevation=3,
        )

    def refresh_cards() -> None:
        course_list.controls.clear()
        for course in state["classes"]:
            course_list.controls.append(make_card(course))
        count_text.value = count_label()
        try:
            page.update()
        except Exception:
            pass

    def persist() -> None:
        save_config(state["classes"], state["ignored"], state["last_sync"], i18n.LANG)
        wake_event.set()          # 课表变了，让引擎醒过来重算下一次触发时间

    def delete_course(course: dict) -> None:
        if course in state["classes"]:
            state["classes"].remove(course)
        if course.get("source") == "sync" and course.get("url"):
            state["ignored"].add(course["url"])
        persist()
        refresh_cards()
        write_log(f"已删除：{course.get('name', '?')}")

    # ---------------------------- 引擎 ---------------------------- #
    wake_event = threading.Event()   # 停止引擎 / 课表变化时，用它把正在睡的线程叫醒

    def load_signed() -> None:
        state["day"] = datetime.date.today().isoformat()
        if not SIGNED_PATH.is_file():
            return
        try:
            data = json.loads(SIGNED_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if data.get("date") == state["day"]:
            state["signed"] = set(data.get("keys") or [])

    def save_signed() -> None:
        try:
            SIGNED_PATH.write_text(
                json.dumps({"date": state["day"], "keys": sorted(state["signed"])}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def alert_box(title: str, message: str) -> None:
        """动态密码这种必须人工处理的事，弹一个系统消息框。"""
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
        except Exception:
            write_log(f"🚨 {title}: {message}", color="red")

    def roll_day(now: datetime.datetime) -> None:
        """跨天时把「今天签过 / 试过几次」清空。"""
        today = now.date().isoformat()
        if state["day"] == today:
            return
        state["day"] = today
        state["signed"].clear()
        state["attempts"].clear()
        save_signed()

    def sign_course(course: dict, key: str, now: datetime.datetime) -> None:
        tries, _ = state["attempts"].get(key, (0, None))
        state["attempts"][key] = (tries + 1, now)
        write_log(t(f"👉 到点了：{course.get('name', '?')}（{entry_time_text(course)}）",
                    f"👉 Time to sign in: {course.get('name', '?')} "
                    f"({entry_time_text(course)})"))
        status = start_sign_in(course.get("url", ""),
                               log=lambda message: write_log(message, color="grey"))

        if status == OK:
            state["signed"].add(key)
            save_signed()
            write_log(t(f"✅ 已签到：{course.get('name', '?')}",
                        f"✅ Signed in: {course.get('name', '?')}"), color="#66bb6a")
        elif status == PASSWORD:
            state["attempts"][key] = (MAX_ATTEMPTS, now)
            write_log(t(f"🚨 需要动态密码：{course.get('name', '?')}，请立刻手动签到！",
                        f"🚨 Password required for {course.get('name', '?')} — sign in "
                        "manually now!"),
                      color="red")
            alert_box(
                t("UM Auto Attendance - 需要手动处理", "UM Auto Attendance - Action needed"),
                t(f"老师的这次签到设置了动态密码：\n{course.get('name', '')}\n\n"
                  "请立刻打开浏览器手动输入密码完成签到！",
                  f"The lecturer set a session password for this attendance:\n"
                  f"{course.get('name', '')}\n\n"
                  "Open the browser and sign in manually right now!"),
            )
        elif status == LOGIN_TIMEOUT:
            write_log(t("⚠️ 浏览器里还没登录完成，请点「Log In Spectrum」登录一次。",
                        "⚠️ Login is not finished in the browser — click Log In Spectrum once."),
                      color="orange")
        elif status == NOT_OPEN:
            write_log(t("⚠️ 现在还不能签到（可能还没开始），稍后再试。",
                        "⚠️ Sign-in is not open yet (maybe not started) — retrying later."),
                      color="orange")
        elif status == BROWSER_DIED:
            write_log(t("⚠️ 浏览器启动后立刻退出了，这次跳过；请先关掉残留的 Edge 签到窗口再试。",
                        "⚠️ The browser exited right after launch — skipped this round; "
                        "close any leftover Edge windows first."),
                      color="orange")
        else:
            write_log(t("❌ 签到失败，稍后再试（原因见上面几行日志）。",
                        "❌ Sign-in failed, will retry (see the lines above)."), color="red")

    def resume_watch(stop: threading.Event) -> None:
        """对表小雷达：墙钟比单调钟多走一截，说明电脑刚从休眠里醒过来。

        每 30 秒只读两个时钟、什么课表都不碰；发现被挂起过就立刻叫醒引擎补签。
        """
        wall, mono = time.time(), time.monotonic()
        while not stop.wait(RESUME_POLL):
            now_wall, now_mono = time.time(), time.monotonic()
            if now_wall - wall - (now_mono - mono) > RESUME_DRIFT:
                write_log(t("⏰ 电脑刚从休眠中唤醒，立刻重新对表…",
                            "⏰ Just woke up from sleep — re-syncing the clock…"),
                          color="#64b5f6")
                wake_event.set()
            wall, mono = now_wall, now_mono

    def bot_loop(run_id: int) -> None:
        """按课表时间点触发：算出下一个时刻，然后一直睡到那个点。"""
        write_log(t("🤖 自动签到引擎已启动：只在上课时间点触发，不再每 10 秒轮询。",
                    "🤖 Engine started: it fires exactly at class time, no 10-second polling."))
        if KEEP_AWAKE:
            keep_awake(True)
            write_log(t("💡 引擎运行期间已阻止电脑自动休眠（屏幕可以关；合盖仍会睡）。",
                        "💡 Sleep is blocked while the engine runs (screen may turn off; "
                        "closing the lid still sleeps)."),
                      color="grey")
        stop_watch = threading.Event()
        threading.Thread(target=resume_watch, args=(stop_watch,), daemon=True).start()

        announced = None
        last_seen = datetime.datetime.now()
        try:
            while state["engine"] and state.get("run_id") == run_id:
                try:
                    now = datetime.datetime.now()
                    roll_day(now)
                    # 上一次算完到现在，有没有哪节在「没人醒着」的时候悄悄过去了
                    for end, course, day in missed_since(
                            state["classes"], state["signed"], state["attempts"],
                            last_seen, now):
                        write_log(
                            t(f"⚠️ 错过了 {day_labels()[day.weekday()]} {end:%H:%M} 前"
                              f"「{course.get('name', '?')}」的签到——那段时间电脑在休眠。",
                              f"⚠️ Missed the {day_labels()[day.weekday()]} {end:%H:%M} "
                              f"sign-in for {course.get('name', '?')} — the PC was asleep."),
                            color="orange")
                    last_seen = now

                    plan = next_trigger(state["classes"], state["signed"],
                                        state["attempts"], now)
                    if plan is None:
                        announced = None
                        write_log(t("😴 课表里没有待签到的时段，等课表变化后再算。",
                                    "😴 Nothing to sign in — waiting for the timetable to change."),
                                  color="grey")
                        wake_event.wait()
                        wake_event.clear()
                        continue

                    target, course, key, day = plan
                    delay = (target - now).total_seconds()
                    if delay > 0:
                        if announced != (key, target):
                            announced = (key, target)
                            write_log(
                                t(f"⏰ 下次签到：{day_labels()[day.weekday()]} {target:%H:%M} "
                                  f"{course.get('name', '?')}（还有 {human_delay(delay)}）",
                                  f"⏰ Next sign-in: {day_labels()[day.weekday()]} {target:%H:%M} "
                                  f"{course.get('name', '?')} (in {human_delay(delay)})"),
                                color="#64b5f6",
                            )
                        # 一次睡到点；MAX_WAIT 只是防系统时间被改，不是轮询
                        if wake_event.wait(min(delay, MAX_WAIT)):
                            wake_event.clear()
                            announced = None
                        continue

                    announced = None
                    window = occurrence_at(course, day)
                    if window is not None and (now - window[0]).total_seconds() > 90:
                        late = human_delay((now - window[0]).total_seconds())
                        write_log(t(f"⏱️ 已经比开课晚了 {late}，立刻补签。",
                                    f"⏱️ {late} late — signing in now."),
                                  color="orange")
                    sign_course(course, key, now)
                except Exception as exc:  # 后台线程不能死
                    write_log(f"❌ 引擎异常：{exc}", color="red")
                    wake_event.wait(5)
                    wake_event.clear()
        finally:
            stop_watch.set()
            if KEEP_AWAKE:
                keep_awake(False)      # 引擎停了就把「别睡」的请求还回去
            write_log(t("🛑 引擎已停止。", "🛑 Engine stopped."))

    def toggle_engine(_event) -> None:
        if not state["engine"]:
            if not (BASE_DIR / "bot_profile").exists():
                notify(t("请先点「Log In Spectrum」登录一次 Spectrum！",
                         "Click Log In Spectrum first to sign in once!"), "#c62828")
                return
            if not state["classes"]:
                notify(t("课表是空的，请先同步或手动添加。",
                         "The timetable is empty — sync it or add a class first."), "#c62828")
                return
            persist()
            state["engine"] = True
            state["run_id"] = state.get("run_id", 0) + 1
            wake_event.clear()
            engine_label.value = labels()["engine_stop"]
            engine_btn.bgcolor = "#c62828"
            write_log(t("配置已保存，正在计算下一次签到时间…",
                        "Config saved, working out the next sign-in time…"))
            threading.Thread(target=bot_loop, args=(state["run_id"],), daemon=True).start()
        else:
            state["engine"] = False
            state["run_id"] = state.get("run_id", 0) + 1   # 让正在跑的线程自己退出
            wake_event.set()                              # 立刻叫醒它，别等睡满
            engine_label.value = labels()["engine_start"]
            engine_btn.bgcolor = "#1565c0"
        page.update()

    # ---------------------------- 同步 ---------------------------- #
    def token_from_disk():
        site, token, path = spectrum_sync.find_token()
        if token:
            state["site"] = site
            token_input.value = token
            sync_status.value = t(f"已找到 {path.name}，点右边按钮即可同步。",
                                   f"Found {path.name} — click Sync to pull the timetable.")
            sync_status.color = "grey"
        return token

    def apply_sync_result(result: dict) -> None:
        entries = result["entries"]
        if not entries:
            sync_status.value = t("没有抓到任何考勤时段，课表保持不变。",
                                   "No attendance slots found; timetable unchanged.")
            sync_status.color = "orange"
            write_log(t("⚠️ 同步结果为空，没有改动课表。",
                        "⚠️ Sync returned nothing; timetable unchanged."), color="orange")
            return

        manual = [c for c in state["classes"] if c.get("source") == "manual"]
        manual_urls = {c.get("url") for c in manual if c.get("url")}
        # 手动加过的 URL 视为「用户特意微调过」，同步结果不要覆盖它
        synced = [e for e in entries if e["url"] not in manual_urls]
        state["classes"][:] = synced + manual
        state["last_sync"] = datetime.datetime.now().isoformat(timespec="seconds")
        persist()
        refresh_cards()

        stamp = datetime.datetime.now().strftime("%H:%M")
        filtered = len(result.get("filtered") or [])
        extra = t(f"，按组别过滤掉 {filtered} 个不是你的 OCC",
                  f", {filtered} other-group OCC filtered out") if filtered else ""
        sync_status.value = t(
            f"同步完成 {stamp}：{len(synced)} 个时段（课程 {result['courses']} 门，"
            f"保留活动 {result['activities']} 个{extra}）。",
            f"Synced at {stamp}: {len(synced)} slots ({result['courses']} courses, "
            f"{result['activities']} activities kept{extra}).",
        )
        sync_status.color = "#66bb6a"
        write_log(t(f"✅ 同步完成：{len(entries)} 个每周时段，日历范围 {result['months']}",
                    f"✅ Sync done: {len(entries)} weekly slots, "
                    f"calendar range {result['months']}"))
        expired = sum(1 for item in result["dropped"] if item.get("reason") == "expired")
        irregular = len(result["dropped"]) - expired
        if irregular:
            write_log(t(f"ℹ️ 忽略了 {irregular} 个临时/补课时段。",
                        f"ℹ️ Skipped {irregular} ad-hoc / replacement slots."))
        if expired:
            write_log(t(f"ℹ️ {expired} 个时段已经上完，不用再挂机。",
                        f"ℹ️ {expired} slots are already over — nothing to watch."))
        for item in result.get("filtered") or []:
            write_log(
                t(f"🧹 跳过 {item['course']} 的「{item['title'][:40]}」"
                  f"（OCC {item['occ']} 不是你所在的组 {item['my_groups']}）",
                  f"🧹 Skipped {item['course']} / {item['title'][:40]} "
                  f"(OCC {item['occ']} is not your group {item['my_groups']})"),
                color="grey",
            )
        if result["missing"]:
            write_log(t(f"ℹ️ 有 {len(result['missing'])} 个考勤活动还没排 session，已跳过。",
                        f"ℹ️ {len(result['missing'])} activities have no sessions yet — skipped."))
        for message in result["errors"][:5]:
            write_log(f"⚠️ {message}", color="orange")

    def run_sync(token: str) -> None:
        state["syncing"] = True
        sync_btn.disabled = True
        sync_status.value = t("正在从 Spectrum 抓取课表…", "Fetching timetable from Spectrum…")
        sync_status.color = "grey"
        page.update()
        try:
            result = spectrum_sync.sync(
                token=token,
                site=state["site"],
                progress=lambda message: write_log(message, color="grey"),
                ignored=state["ignored"],
            )
            apply_sync_result(result)
        except spectrum_sync.SpectrumError as exc:
            sync_status.value = t(f"同步失败：{exc}", f"Sync failed: {exc}")
            sync_status.color = "red"
            write_log(t(f"❌ 同步失败：{exc}", f"❌ Sync failed: {exc}"), color="red")
        except Exception as exc:
            sync_status.value = t(f"同步失败：{exc}", f"Sync failed: {exc}")
            sync_status.color = "red"
            write_log(t(f"❌ 同步失败：{exc}", f"❌ Sync failed: {exc}"), color="red")
        finally:
            state["syncing"] = False
            sync_btn.disabled = False
            page.update()

    def start_sync(_event=None) -> None:
        token = (token_input.value or "").strip()
        if not token:
            notify(t("还差一个 token：先看卡片里的获取方法。",
                     "A token is required — see the instructions in the card above."), "#c62828")
            sync_status.value = t("缺少 token，先把 token 粘进上面的输入框。",
                                  "No token yet — paste it into the field above.")
            sync_status.color = "red"
            page.update()
            return
        if state["syncing"]:
            notify(t("正在同步，请稍等…", "Syncing, hang on…"), "#1565c0")
            return

        try:
            TOKEN_PATH.write_text(
                f"{state['site']}\n{token}\n"
                if state["site"] != spectrum_sync.DEFAULT_SITE
                else f"{token}\n",
                encoding="utf-8",
            )
        except OSError as exc:
            write_log(t(f"⚠️ token.txt 写入失败：{exc}",
                        f"⚠️ Could not write token.txt: {exc}"), color="orange")

        threading.Thread(target=run_sync, args=(token,), daemon=True).start()

    def restore_ignored(_event) -> None:
        if not state["ignored"]:
            notify(t("没有被忽略的课。", "Nothing is ignored."), "#455a64")
            return
        state["ignored"].clear()
        persist()
        write_log(t("已清空忽略列表，重新同步一次就会把它们加回来。",
                    "Ignore list cleared — sync again to bring them back."))
        start_sync()

    # ---------------------------- 手动添加 ---------------------------- #
    day_input = ft.Dropdown(
        label=labels()["day"],
        width=120,
        filled=True,
        options=[ft.dropdown.Option(key=str(i), text=label)
                 for i, label in enumerate(day_labels())],
    )
    start_input = ft.TextField(label=labels()["start"], width=130, filled=True)
    end_input = ft.TextField(label=labels()["end"], width=130, filled=True)
    name_input = ft.TextField(label=labels()["name"], expand=True, filled=True)
    url_input = ft.TextField(label=labels()["url"], expand=True, filled=True)

    def add_course(_event) -> None:
        if not day_input.value or not start_input.value or not name_input.value:
            notify(t("星期、开始时间、课程名至少要有。",
                     "Day, start time and course name are required."), "#c62828")
            return
        if not (url_input.value or "").strip():
            notify(t("Attendance 页面的 URL 不能为空。",
                     "The attendance page URL is required."), "#c62828")
            return
        if parse_hhmm(start_input.value) is None:
            notify(t("开始时间格式不对，例如 08:00。",
                     "Bad start time format, e.g. 08:00."), "#c62828")
            return
        end_value = (end_input.value or "").strip()
        if not end_value:
            start_dt = datetime.datetime.strptime(
                "%02d:%02d" % parse_hhmm(start_input.value), "%H:%M"
            )
            end_value = (start_dt + datetime.timedelta(minutes=15)).strftime("%H:%M")
        if parse_hhmm(end_value) is None:
            notify(t("结束时间格式不对，例如 08:15。",
                     "Bad end time format, e.g. 08:15."), "#c62828")
            return

        course = {
            "day": int(day_input.value),
            "start": start_input.value.strip(),
            "end": end_value,
            "name": name_input.value.strip(),
            "url": url_input.value.strip(),
            "source": "manual",
        }
        state["classes"].append(course)
        persist()
        refresh_cards()
        name_input.value = ""
        url_input.value = ""
        start_input.value = ""
        end_input.value = ""
        page.update()

    # ---------------------------- 顶部按钮 ---------------------------- #
    def handle_login(_event) -> None:
        write_log(t("正在打开浏览器，请在里面登录 Spectrum…",
                    "Opening the browser — log in to Spectrum there…"))
        threading.Thread(target=manual_login,
                         kwargs={"log": lambda message: write_log(message, color="grey")},
                         daemon=True).start()

    engine_label = ft.Text(labels()["engine_start"])
    engine_btn = ft.FilledButton(content=engine_label, height=46, bgcolor="#1565c0",
                                 color="white", on_click=toggle_engine)
    login_label = ft.Text(labels()["login"])
    login_btn = ft.Button(content=login_label, height=46, bgcolor="#ef6c00",
                          color="white", on_click=handle_login)

    token_input = ft.TextField(
        label="Spectrum token",
        password=True,
        can_reveal_password=True,
        expand=True,
        filled=True,
        dense=True,
    )
    sync_label = ft.Text(labels()["sync_btn"])
    sync_btn = ft.Button(content=sync_label, height=44, on_click=start_sync)

    def toggle_theme():
        if page.theme_mode == ft.ThemeMode.DARK:
            page.theme_mode = ft.ThemeMode.LIGHT
            theme_label.value = "🌙 Dark"
        else:
            page.theme_mode = ft.ThemeMode.DARK
            theme_label.value = "☀️ Light"
        page.update()

    def toggle_lang() -> None:
        """中英切换：换全局语言 → 存盘 → 把现有控件全部换字。"""
        i18n.set_lang("en" if i18n.LANG == "zh" else "zh")
        persist()
        relabel()
        refresh_cards()
        write_log(t("界面语言已切换为中文。", "UI language switched to English."))

    lang_label = ft.Text(labels()["lang_btn"])
    lang_btn = ft.TextButton(content=lang_label, on_click=lambda _e: toggle_lang())
    theme_label = ft.Text("☀️ Light")
    theme_btn = ft.TextButton(content=theme_label, on_click=lambda _e: toggle_theme())
    page.appbar = ft.AppBar(title=ft.Text("Auto Attendance"), actions=[lang_btn, theme_btn])

    # ---------------------------- 布局 ---------------------------- #
    hint_text = ft.Text(labels()["hint"], size=11, color="grey")
    sync_title = ft.Text(labels()["sync_title"], size=16, weight=ft.FontWeight.BOLD)
    sync_desc = ft.Text(labels()["sync_desc"], size=12, color="grey")
    help_text = ft.Text(labels()["help"], size=11, color="#9e9e9e")
    restore_label = ft.Text(labels()["restore"])

    sync_card = ft.Card(
        content=ft.Container(
            padding=16,
            content=ft.Column(
                spacing=10,
                controls=[
                    sync_title,
                    sync_desc,
                    ft.Row([token_input, sync_btn], spacing=8),
                    sync_status,
                    help_text,
                    ft.Row([ft.TextButton(content=restore_label, on_click=restore_ignored)],
                           alignment=ft.MainAxisAlignment.END),
                ],
            ),
        ),
        elevation=4,
    )

    add_title = ft.Text(labels()["add_title"], size=16, weight=ft.FontWeight.BOLD)
    add_label = ft.Text(labels()["add_btn"])
    add_card = ft.Card(
        content=ft.Container(
            padding=16,
            content=ft.Column(
                spacing=10,
                controls=[
                    add_title,
                    ft.Row([day_input, start_input, end_input], spacing=8),
                    name_input,
                    url_input,
                    ft.Row(
                        [ft.Button(content=add_label, on_click=add_course)],
                        alignment=ft.MainAxisAlignment.END,
                    ),
                ],
            ),
        ),
        elevation=4,
    )

    # 固定一个内容宽度：Flet 的页面滚动容器不会把宽度约束传给子控件，
    # 如果不这样包一层，长文本和带 expand 的 Row 会按自身宽度排版、把按钮挤出窗口。
    content_width = 480
    list_title = ft.Text(labels()["list_title"], size=18, weight=ft.FontWeight.BOLD)
    root = ft.Column(
        width=content_width,
        spacing=12,
        controls=[
            ft.Row([login_btn, engine_btn], spacing=10),
            hint_text,
            log_container,
            sync_card,
            add_card,
            ft.Row([list_title, count_text],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            course_list,
            ft.Container(height=20),
        ],
    )
    page.add(root)

    def relabel() -> None:
        """语言切换后把现有控件换字（已经写进日志的历史不重写）。"""
        L = labels()
        engine_label.value = L["engine_stop"] if state["engine"] else L["engine_start"]
        login_label.value = L["login"]
        hint_text.value = L["hint"]
        sync_title.value = L["sync_title"]
        sync_desc.value = L["sync_desc"]
        sync_label.value = L["sync_btn"]
        help_text.value = L["help"]
        restore_label.value = L["restore"]
        add_title.value = L["add_title"]
        day_input.label = L["day"]
        day_input.options = [ft.dropdown.Option(key=str(i), text=label)
                             for i, label in enumerate(day_labels())]
        start_input.label = L["start"]
        end_input.label = L["end"]
        name_input.label = L["name"]
        url_input.label = L["url"]
        add_label.value = L["add_btn"]
        list_title.value = L["list_title"]
        count_text.value = count_label()
        lang_label.value = L["lang_btn"]
        page.update()

    load_signed()
    refresh_cards()

    # 启动时：有 token 且上次同步超过 6 小时 -> 后台自动同步一次
    token = token_from_disk()
    should_sync = False
    if token:
        try:
            last = datetime.datetime.fromisoformat(state["last_sync"]) if state["last_sync"] else None
        except (TypeError, ValueError):
            last = None
        should_sync = (last is None
                       or (datetime.datetime.now() - last).total_seconds() > AUTO_SYNC_HOURS * 3600)
    if should_sync:
        write_log(t("检测到 token，启动后台自动同步…",
                    "Token found — auto-syncing in the background…"), color="grey")
        threading.Thread(target=run_sync, args=(token,), daemon=True).start()
    else:
        write_log(
            t(f"已启动：课表 {len(state['classes'])} 条，token "
              f"{'已加载' if token else '未设置'}。日志会同时写进 logs/ 目录。",
              f"Ready: {len(state['classes'])} classes, token "
              f"{'loaded' if token else 'not set'}. Logs also go to logs/."),
            color="grey",
        )


if __name__ == "__main__":
    ft.run(main)
