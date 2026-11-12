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

import spectrum_sync
from sign_in import (BROWSER_DIED, LOGIN_TIMEOUT, NOT_OPEN, OK, PASSWORD,
                     manual_login, start_sign_in)

BASE_DIR = spectrum_sync.app_dir()
CONFIG_PATH = BASE_DIR / "config.json"
TOKEN_PATH = BASE_DIR / "token.txt"
SIGNED_PATH = BASE_DIR / "signed.json"
LOG_DIR = BASE_DIR / "logs"

DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CHECK_INTERVAL = 10          # 引擎多少秒检查一次
RETRY_GAP = 180              # 同一条签到失败后至少隔多久再试（3 分钟）
MAX_ATTEMPTS = 10            # 同一条签到一天最多试几次（约覆盖半小时）
AUTO_SYNC_HOURS = 6          # 距上次同步超过几小时，启动时自动同步


# --------------------------------------------------------------------------- #
# 配置文件
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    data = {"classes": [], "ignored": [], "last_sync": None}
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


def save_config(classes, ignored, last_sync) -> None:
    payload = {
        "classes": classes,
        "ignored": sorted(ignored),
        "last_sync": last_sync,
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


def today_at(text, now: datetime.datetime):
    parsed = parse_hhmm(text)
    if parsed is None:
        return None
    return now.replace(hour=parsed[0], minute=parsed[1], second=0, microsecond=0)


def entry_time_text(entry) -> str:
    day = entry.get("day")
    try:
        day_label = DAY_LABELS[int(day)]
    except (TypeError, ValueError, IndexError):
        day_label = "?"

    def pretty(value):
        parsed = parse_hhmm(value)
        return f"{parsed[0]:02d}:{parsed[1]:02d}" if parsed else str(value)

    return f"{day_label}  {pretty(entry.get('start', '?'))} - {pretty(entry.get('end', '?'))}"


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

    # ---------------------------- 组件 ---------------------------- #
    course_list = ft.Column(spacing=10)
    count_text = ft.Text("0 节课", color="grey", size=12)

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
            content=ft.Text("自动" if is_auto else "手动", size=10, color="white"),
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
        count_text.value = f"{len(state['classes'])} 节课"
        try:
            page.update()
        except Exception:
            pass

    def persist() -> None:
        save_config(state["classes"], state["ignored"], state["last_sync"])

    def delete_course(course: dict) -> None:
        if course in state["classes"]:
            state["classes"].remove(course)
        if course.get("source") == "sync" and course.get("url"):
            state["ignored"].add(course["url"])
        persist()
        refresh_cards()
        write_log(f"已删除：{course.get('name', '?')}")

    # ---------------------------- 引擎 ---------------------------- #
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

    def check_once() -> None:
        now = datetime.datetime.now()
        today = now.date().isoformat()
        if state["day"] != today:
            state["day"] = today
            state["signed"].clear()
            state["attempts"].clear()
            save_signed()

        for course in list(state["classes"]):
            try:
                day = int(course.get("day"))
            except (TypeError, ValueError):
                continue
            if day != now.weekday():
                continue

            start = today_at(course.get("start"), now)
            end = today_at(course.get("end"), now)
            if start is None:
                continue
            if end is None or end <= start:
                end = start + datetime.timedelta(minutes=15)
            if not (start <= now <= end):
                continue

            key = f"{today}|{course.get('url')}|{course.get('start')}"
            if key in state["signed"]:
                continue

            tries, last_at = state["attempts"].get(key, (0, None))
            if tries >= MAX_ATTEMPTS:
                continue
            if last_at is not None and (now - last_at).total_seconds() < RETRY_GAP:
                continue

            state["attempts"][key] = (tries + 1, now)
            write_log(f"👉 到点了：{course.get('name', '?')}（{entry_time_text(course)}）")
            status = start_sign_in(course.get("url", ""),
                                   log=lambda message: write_log(message, color="grey"))

            if status == OK:
                state["signed"].add(key)
                save_signed()
                write_log(f"✅ 已签到：{course.get('name', '?')}", color="#66bb6a")
            elif status == PASSWORD:
                state["attempts"][key] = (MAX_ATTEMPTS, now)
                write_log(f"🚨 需要动态密码：{course.get('name', '?')}，请立刻手动签到！", color="red")
                alert_box(
                    "UM Auto Attendance - 需要手动处理",
                    f"老师的这次签到设置了动态密码：\n{course.get('name', '')}\n\n"
                    "请立刻打开浏览器手动输入密码完成签到！",
                )
            elif status == LOGIN_TIMEOUT:
                write_log("⚠️ 浏览器里还没登录完成，请点「Log In Spectrum」登录一次。", color="orange")
            elif status == NOT_OPEN:
                write_log("⚠️ 现在还不能签到（可能还没开始），稍后再试。", color="orange")
            elif status == BROWSER_DIED:
                write_log("⚠️ 浏览器启动后立刻退出了，这次跳过；请先关掉残留的 Edge 签到窗口再试。",
                          color="orange")
            else:
                write_log("❌ 签到失败，稍后再试（原因见上面几行日志）。", color="red")

    def bot_loop(run_id: int) -> None:
        write_log("🤖 自动签到引擎已启动，每 10 秒检查一次。")
        while state["engine"] and state.get("run_id") == run_id:
            try:
                check_once()
            except Exception as exc:  # 后台线程不能死
                write_log(f"❌ 引擎异常：{exc}", color="red")
            time.sleep(CHECK_INTERVAL)
        write_log("🛑 引擎已停止。")

    def toggle_engine(_event) -> None:
        if not state["engine"]:
            if not (BASE_DIR / "bot_profile").exists():
                notify("请先点「Log In Spectrum」登录一次 Spectrum！", "#c62828")
                return
            if not state["classes"]:
                notify("课表是空的，请先同步或手动添加。", "#c62828")
                return
            persist()
            state["engine"] = True
            state["run_id"] = state.get("run_id", 0) + 1
            engine_btn.text = "⏹️ 停止引擎"
            engine_btn.bgcolor = "#c62828"
            write_log("配置已保存，准备启动…")
            threading.Thread(target=bot_loop, args=(state["run_id"],), daemon=True).start()
        else:
            state["engine"] = False
            state["run_id"] = state.get("run_id", 0) + 1   # 让正在跑的线程自己退出
            engine_btn.text = "🚀 启动自动签到"
            engine_btn.bgcolor = "#1565c0"
        page.update()

    # ---------------------------- 同步 ---------------------------- #
    def token_from_disk():
        site, token, path = spectrum_sync.find_token()
        if token:
            state["site"] = site
            token_input.value = token
            sync_status.value = f"已找到 {path.name}，点右边按钮即可同步。"
            sync_status.color = "grey"
        return token

    def apply_sync_result(result: dict) -> None:
        entries = result["entries"]
        if not entries:
            sync_status.value = "没有抓到任何考勤时段，课表保持不变。"
            sync_status.color = "orange"
            write_log("⚠️ 同步结果为空，没有改动课表。", color="orange")
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
        extra = f"，按组别过滤掉 {filtered} 个不是你的 OCC" if filtered else ""
        sync_status.value = (
            f"同步完成 {stamp}：{len(synced)} 个时段（课程 {result['courses']} 门，"
            f"保留活动 {result['activities']} 个{extra}）。"
        )
        sync_status.color = "#66bb6a"
        write_log(f"✅ 同步完成：{len(entries)} 个每周时段，日历范围 {result['months']}")
        expired = sum(1 for item in result["dropped"] if item.get("reason") == "expired")
        irregular = len(result["dropped"]) - expired
        if irregular:
            write_log(f"ℹ️ 忽略了 {irregular} 个临时/补课时段。")
        if expired:
            write_log(f"ℹ️ {expired} 个时段已经上完，不用再挂机。")
        for item in result.get("filtered") or []:
            write_log(
                f"🧹 跳过 {item['course']} 的「{item['title'][:40]}」"
                f"（OCC {item['occ']} 不是你所在的组 {item['my_groups']}）",
                color="grey",
            )
        if result["missing"]:
            write_log(f"ℹ️ 有 {len(result['missing'])} 个考勤活动还没排 session，已跳过。")
        for message in result["errors"][:5]:
            write_log(f"⚠️ {message}", color="orange")

    def run_sync(token: str) -> None:
        state["syncing"] = True
        sync_btn.disabled = True
        sync_status.value = "正在从 Spectrum 抓取课表…"
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
            sync_status.value = f"同步失败：{exc}"
            sync_status.color = "red"
            write_log(f"❌ 同步失败：{exc}", color="red")
        except Exception as exc:
            sync_status.value = f"同步失败：{exc}"
            sync_status.color = "red"
            write_log(f"❌ 同步失败：{exc}", color="red")
        finally:
            state["syncing"] = False
            sync_btn.disabled = False
            page.update()

    def start_sync(_event=None) -> None:
        token = (token_input.value or "").strip()
        if not token:
            notify("还差一个 token：先看卡片里的获取方法。", "#c62828")
            sync_status.value = "缺少 token，先把 token 粘进上面的输入框。"
            sync_status.color = "red"
            page.update()
            return
        if state["syncing"]:
            notify("正在同步，请稍等…", "#1565c0")
            return

        try:
            TOKEN_PATH.write_text(
                f"{state['site']}\n{token}\n"
                if state["site"] != spectrum_sync.DEFAULT_SITE
                else f"{token}\n",
                encoding="utf-8",
            )
        except OSError as exc:
            write_log(f"⚠️ token.txt 写入失败：{exc}", color="orange")

        threading.Thread(target=run_sync, args=(token,), daemon=True).start()

    def restore_ignored(_event) -> None:
        if not state["ignored"]:
            notify("没有被忽略的课。", "#455a64")
            return
        state["ignored"].clear()
        persist()
        write_log("已清空忽略列表，重新同步一次就会把它们加回来。")
        start_sync()

    # ---------------------------- 手动添加 ---------------------------- #
    day_input = ft.Dropdown(
        label="星期",
        width=120,
        filled=True,
        options=[ft.dropdown.Option(key=str(i), text=label) for i, label in enumerate(DAY_LABELS)],
    )
    start_input = ft.TextField(label="开始 08:00", width=130, filled=True)
    end_input = ft.TextField(label="结束 08:15", width=130, filled=True)
    name_input = ft.TextField(label="课程名（如 WIA2007）", expand=True, filled=True)
    url_input = ft.TextField(label="Attendance 页面 URL", expand=True, filled=True)

    def add_course(_event) -> None:
        if not day_input.value or not start_input.value or not name_input.value:
            notify("星期、开始时间、课程名至少要有。", "#c62828")
            return
        if not (url_input.value or "").strip():
            notify("Attendance 页面的 URL 不能为空。", "#c62828")
            return
        if parse_hhmm(start_input.value) is None:
            notify("开始时间格式不对，例如 08:00。", "#c62828")
            return
        end_value = (end_input.value or "").strip()
        if not end_value:
            start_dt = datetime.datetime.strptime(
                "%02d:%02d" % parse_hhmm(start_input.value), "%H:%M"
            )
            end_value = (start_dt + datetime.timedelta(minutes=15)).strftime("%H:%M")
        if parse_hhmm(end_value) is None:
            notify("结束时间格式不对，例如 08:15。", "#c62828")
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
        write_log("正在打开浏览器，请在里面登录 Spectrum…")
        threading.Thread(target=manual_login,
                         kwargs={"log": lambda message: write_log(message, color="grey")},
                         daemon=True).start()

    engine_btn = ft.FilledButton("🚀 启动自动签到", height=46, bgcolor="#1565c0",
                                 color="white", on_click=toggle_engine)
    login_btn = ft.Button(content=ft.Text("🔑 Log In Spectrum"), height=46, bgcolor="#ef6c00",
                          color="white", on_click=handle_login)

    token_input = ft.TextField(
        label="Spectrum token",
        password=True,
        can_reveal_password=True,
        expand=True,
        filled=True,
        dense=True,
    )
    sync_btn = ft.Button(content=ft.Text("🔄 自动同步课表"), height=44, on_click=start_sync)

    def toggle_theme():
        if page.theme_mode == ft.ThemeMode.DARK:
            page.theme_mode = ft.ThemeMode.LIGHT
            theme_btn.text = "🌙 Dark"
        else:
            page.theme_mode = ft.ThemeMode.DARK
            theme_btn.text = "☀️ Light"
        page.update()

    theme_btn = ft.TextButton("☀️ Light", on_click=lambda _e: toggle_theme())
    page.appbar = ft.AppBar(title=ft.Text("Auto Attendance"), actions=[theme_btn])

    # ---------------------------- 布局 ---------------------------- #
    sync_card = ft.Card(
        content=ft.Container(
            padding=16,
            content=ft.Column(
                spacing=10,
                controls=[
                    ft.Text("从 Spectrum 自动更新课表", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "登录后填一次 token，点一下就会把「对你可见」的考勤活动和上课时间全部抓下来，"
                        "不用再手抄 URL 和时间。token 会存进 token.txt，下次启动自动同步。",
                        size=12,
                        color="grey",
                    ),
                    ft.Row([token_input, sync_btn], spacing=8),
                    sync_status,
                    ft.Text(
                        "没有 token？浏览器打开 https://spectrum.um.edu.my/user/managetoken.php "
                        "→ Create token → 选 Moodle mobile web service → 复制。\n"
                        "（如果你已经在用 att.py，把它的 token.txt 复制到本程序目录即可。）",
                        size=11,
                        color="#9e9e9e",
                    ),
                    ft.Row([ft.TextButton("↺ 恢复被忽略的课", on_click=restore_ignored)],
                           alignment=ft.MainAxisAlignment.END),
                ],
            ),
        ),
        elevation=4,
    )

    add_card = ft.Card(
        content=ft.Container(
            padding=16,
            content=ft.Column(
                spacing=10,
                controls=[
                    ft.Text("手动添加（同步漏掉时用）", size=16, weight=ft.FontWeight.BOLD),
                    ft.Row([day_input, start_input, end_input], spacing=8),
                    name_input,
                    url_input,
                    ft.Row(
                        [ft.Button(content=ft.Text("➕ 添加到课表"), on_click=add_course)],
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
    root = ft.Column(
        width=content_width,
        spacing=12,
        controls=[
            ft.Row([login_btn, engine_btn], spacing=10),
            ft.Text("浏览器只需登录一次；自动签到时整晚只用一个窗口。", size=11, color="grey"),
            log_container,
            sync_card,
            add_card,
            ft.Row([ft.Text("我的课表", size=18, weight=ft.FontWeight.BOLD), count_text],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            course_list,
            ft.Container(height=20),
        ],
    )
    page.add(root)

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
        write_log("检测到 token，启动后台自动同步…", color="grey")
        threading.Thread(target=run_sync, args=(token,), daemon=True).start()
    else:
        write_log(
            f"已启动：课表 {len(state['classes'])} 条，token {'已加载' if token else '未设置'}。"
            f"日志会同时写进 logs/ 目录。",
            color="grey",
        )


if __name__ == "__main__":
    ft.run(main)
