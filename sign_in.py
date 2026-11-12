# -*- coding: utf-8 -*-
"""sign_in.py —— Selenium 自动签到。

对外接口：
    start_sign_in(url)  ->  状态字符串
        OK            签到成功（页面上出现了 "recorded" 的确认）
        PASSWORD      老师开了动态密码，需要你手动处理
        NOT_OPEN      这个页面现在没有可提交的签到（时间不对 / 已经签过 / 活动关闭）
        LOGIN_TIMEOUT 登录没完成
        ERROR         浏览器/页面出错（网络、元素找不到等）

    manual_login()      打开浏览器让你手动登录一次（保存到 bot_profile）
    close_browser()     关掉本程序复用的那个浏览器

为了不重复启动新窗口（旧版每 10 秒开一个 Edge，还会因为 profile 被锁直接报错），
这里复用同一个 driver：整晚只开一个浏览器窗口，后续签到都在里面换页面。
"""
import datetime
import os
import re
import sys
import threading
import time

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from spectrum_sync import app_dir

SITE = "https://spectrum.um.edu.my"

OK = "ok"
PASSWORD = "password"
NOT_OPEN = "not_open"
LOGIN_TIMEOUT = "login_timeout"
BROWSER_DIED = "browser_died"
ERROR = "error"

MONTHS = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

_driver = None
_driver_lock = threading.Lock()
_variant = 0

# Edge 升级后偶尔会出现 "tab crashed" / 启动即崩。按顺序试启动参数；
# 这台机器上 Edge 156 只有「兼容模式」稳定，所以把它放在第一组，其余作为备用。
LAUNCH_VARIANTS = (
    ("兼容模式", (
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-features=Translate,BackForwardCache,AcceptCHFrame,MediaRouter",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    )),
    ("默认", ()),
    ("禁用 GPU", ("--disable-gpu", "--disable-software-rasterizer")),
    ("无窗口模式", (
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    )),
)


def _profile_dir() -> str:
    return str(app_dir() / "bot_profile")


def _kill_profile_browsers(say=None) -> None:
    """关掉还占着 bot_profile 的残留 Edge（只杀命令行里带这个目录的进程）。"""
    profile = _profile_dir().replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{profile}*' }} | "
        "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force } catch {} }"
    )
    try:
        import subprocess
        subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       capture_output=True, timeout=20)
    except Exception:
        if say:
            say("（无法自动结束残留 Edge 进程，请手动关掉）")


def _temp_dir() -> str:
    """给 Edge / msedgedriver 用的临时目录。

    必须是自己创建、确定可写的目录：msedgedriver 启动时会解压 automation extension
    到 TEMP 下，如果进程继承到的 TEMP 指向一个不存在的路径（比如从别的终端/工具里
    启动时），就会报 "cannot create temp dir for unpacking extensions"。
    """
    folder = app_dir() / "tmp"
    try:
        folder.mkdir(exist_ok=True)
        probe = folder / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return str(folder)
    except OSError:
        return os.environ.get("TEMP") or os.environ.get("TMP") or "C:\\Windows\\Temp"


def _service() -> Service:
    env = dict(os.environ)
    temp = _temp_dir()
    env["TEMP"] = temp
    env["TMP"] = temp
    return Service(env=env)


def _options(detach: bool = True) -> Options:
    options = Options()
    options.add_argument(f"user-data-dir={_profile_dir()}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    for flag in LAUNCH_VARIANTS[_variant][1]:
        options.add_argument(flag)
    if detach:
        options.add_experimental_option("detach", True)
    return options


def _close_current() -> None:
    global _driver
    if _driver is None:
        return
    try:
        _driver.close()      # detach 模式下 quit() 不会关窗口，先手动关掉，释放 profile 锁
    except Exception:
        pass
    try:
        _driver.quit()
    except Exception:
        pass
    _driver = None


def _advance_variant() -> str:
    """切到下一组启动参数，返回新参数的名字。"""
    global _variant
    _variant = (_variant + 1) % len(LAUNCH_VARIANTS)
    return LAUNCH_VARIANTS[_variant][0]


def _reset_variant() -> None:
    global _variant
    _variant = 0


def get_driver(fresh: bool = False, say=None):
    """拿到一个可用的 Edge（复用同一个窗口）。调用方负责加锁使用。"""
    global _driver
    if _driver is not None and not fresh:
        try:
            _driver.title  # 浏览器还活着吗
            return _driver
        except WebDriverException:
            _close_current()
    elif fresh:
        _close_current()

    _kill_profile_browsers(say)
    try:
        _driver = webdriver.Edge(options=_options(), service=_service())
    except WebDriverException as exc:
        _driver = None
        detail = exc.msg if hasattr(exc, "msg") else str(exc)
        hint = "如果之前自动开过签到窗口，请先把它全部关掉再试。"
        if "temp dir" in detail.lower():
            hint = "无法创建临时目录：程序会用自带的 tmp/ 目录，请确认它可写。"
        raise RuntimeError(f"{hint}\n原始错误：{detail}") from exc
    return _driver


def close_browser() -> None:
    with _driver_lock:
        _close_current()


def _body_text(driver) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text.lower()
    except WebDriverException:
        return ""


def _wait_body(driver, timeout: float = 20) -> None:
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception:
        pass
    time.sleep(0.5)


def _click_first(driver, locators, timeout: float = 8) -> bool:
    """按顺序尝试多个定位方式，点中第一个可见元素就返回 True。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for by, selector in locators:
            try:
                elements = driver.find_elements(by, selector)
            except WebDriverException:
                continue
            for element in elements:
                try:
                    if element.is_displayed():
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
                        element.click()
                        return True
                except WebDriverException:
                    continue
        time.sleep(0.4)
    return False


def _ensure_login(driver) -> bool:
    """打开 Spectrum；如果被踢到登录页，就点 Log in 走 SSO，等它跳回来。"""
    driver.get(SITE)
    _wait_body(driver)

    needs_login = "login" in (driver.current_url or "").lower()
    if not needs_login:
        # 已登录的首页通常没有 "Log in" 链接；有的话说明 session 过期了
        try:
            needs_login = any(
                el.is_displayed() for el in driver.find_elements(By.LINK_TEXT, "Log in")
            )
        except WebDriverException:
            needs_login = False

    if needs_login:
        _click_first(driver, [
            (By.LINK_TEXT, "Log in"),
            (By.PARTIAL_LINK_TEXT, "Log in"),
            (By.XPATH, "//a[contains(normalize-space(.), 'Log in')]"),
        ], timeout=10)
        for _ in range(90):
            if "login" not in (driver.current_url or "").lower():
                _wait_body(driver)
                return True
            time.sleep(1)
        return False
    return True


def _session_dead(exc: Exception) -> bool:
    """判断这个 WebDriver 异常是不是「浏览器已经没了」。"""
    text = str(exc).lower()
    return any(marker in text for marker in (
        "invalid session id",
        "browser has closed",
        "not connected to devtools",
        "no such window",
        "chrome not reachable",
        "disconnected",
        "target window already closed",
    ))


def _row_date(text: str):
    """从签到表格的一行里认出日期，例如 "Thu 12 Nov 2026\\n11AM - 12PM" -> date(2026,11,12)。"""
    if not text:
        return None
    for pattern, order in (
        (r"(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", "dmy"),
        (r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", "mdy"),
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            if order == "dmy":
                day, month_name, year = match.group(1), match.group(2), match.group(3)
            else:
                month_name, day, year = match.group(1), match.group(2), match.group(3)
            month = MONTHS.get(month_name[:3].lower())
            if not month:
                continue
            return datetime.date(int(year), month, int(day))
        except (TypeError, ValueError):
            continue
    return None


def _find_today_submit(driver, say):
    """在 view.php 的 session 表格里找「今天这一行」的 Submit attendance 链接。

    返回 (link 或 None, 今天是否已经签过)。
    关键点：一个活动下面会列出很多天的 session，老师常常把过去几次的链接也留着；
    直接点第一个链接会签到别的日期上，页面还会显示成功。
    """
    today = datetime.date.today()
    try:
        rows = driver.find_elements(
            By.XPATH,
            "//tr[.//a[contains(normalize-space(.), 'Submit attendance')]]"
            " | //tr[.//button[contains(normalize-space(.), 'Submit attendance')]]",
        )
    except WebDriverException:
        rows = []

    candidates = []
    for row in rows:
        try:
            link = row.find_element(
                By.XPATH, ".//a[contains(normalize-space(.), 'Submit attendance')]")
        except WebDriverException:
            continue
        try:
            text = row.text
        except WebDriverException:
            continue
        candidates.append((_row_date(text), text, link))

    if candidates:
        exact = [item for item in candidates if item[0] == today]
        if exact:
            return exact[0][2], False
        if len(candidates) == 1:
            say(f"ℹ️ 只找到一个可签到 session（识别日期：{candidates[0][0] or '未知'}），尝试提交。")
            return candidates[0][2], False
        dates = ", ".join(str(item[0]) for item in candidates)
        say(f"⚠️ 有 {len(candidates)} 个可签到 session（{dates}），都不是今天，跳过以免签错。")
        return None, False

    # 表格结构认不出来时的兜底：页面上只有一个签到链接就直接用；多个就不猜
    try:
        loose_links = driver.find_elements(
            By.XPATH, "//a[contains(normalize-space(.), 'Submit attendance')]")
    except WebDriverException:
        loose_links = []
    if len(loose_links) == 1:
        say("ℹ️ 没从表格里认出日期，但页面上只有一个签到链接，直接用它。")
        return loose_links[0], False
    if len(loose_links) > 1:
        say(f"⚠️ 页面上有 {len(loose_links)} 个签到链接，分不清哪个是今天的，跳过以免签错。")
        return None, False

    # 没有任何 Submit attendance：如果今天那一行已经显示 Present / Self-recorded，就算签过了
    try:
        all_rows = driver.find_elements(By.XPATH, "//tr")
    except WebDriverException:
        all_rows = []
    for row in all_rows:
        try:
            text = row.text
        except WebDriverException:
            continue
        if _row_date(text) == today:
            lowered = text.lower()
            if "present" in lowered or "self-recorded" in lowered:
                return None, True
    return None, False


def _run_sign_in(driver, target_url: str, say) -> str:
    """真正的签到流程（浏览器已经就绪）。"""
    if not _ensure_login(driver):
        say("❌ 等了 90 秒还没登录完成。")
        return LOGIN_TIMEOUT

    say(f"→ 打开签到页面: {target_url}")
    driver.get(target_url)
    _wait_body(driver, timeout=30)

    # SSO 过期时，Moodle 会把签到页也重定向到登录页
    if "login" in (driver.current_url or "").lower():
        say("→ 登录已过期，先重新登录…")
        if not _ensure_login(driver):
            return LOGIN_TIMEOUT
        driver.get(target_url)
        _wait_body(driver, timeout=30)

    text = _body_text(driver)
    if "you must enter the session password" in text or "password required" in text:
        say("🔒 这个签到需要老师设置的动态密码。")
        return PASSWORD

    link, already_signed = _find_today_submit(driver, say)
    if already_signed:
        say("✅ 今天这一行已经显示 Present / Self-recorded。")
        return OK
    if link is None:
        say("⚠️ 这个页面现在没有今天可提交的签到（还没开始 / 已结束）。")
        return NOT_OPEN

    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
        link.click()
    except WebDriverException as exc:
        say(f"❌ 点不开签到链接：{exc}")
        return ERROR

    time.sleep(1.0)
    _wait_body(driver, timeout=20)

    body = _body_text(driver)
    if "you must enter the session password" in body or "password required" in body:
        say("🔒 需要动态密码。")
        return PASSWORD

    # 选 Present：先点 label，再退回点文字
    selected = _click_first(driver, [
        (By.XPATH, "//label[.//input[@type='radio']][contains(normalize-space(.), 'Present')]"),
        (By.XPATH, "//label[contains(normalize-space(.), 'Present')]"),
        (By.XPATH, "//span[contains(normalize-space(text()), 'Present')]"),
    ], timeout=10)
    if not selected:
        say("❌ 找到了签到页，但找不到 Present 选项（页面结构可能变了）。")
        return ERROR

    time.sleep(0.5)
    submitted = _click_first(driver, [
        (By.ID, "id_submitbutton"),
        (By.XPATH, "//input[@type='submit' and (@id='id_submitbutton' or @value='Save')]"),
        (By.XPATH, "//button[contains(normalize-space(.), 'Save')]"),
    ], timeout=10)
    if not submitted:
        say("❌ 勾了 Present，但找不到提交按钮。")
        return ERROR

    time.sleep(3)
    _wait_body(driver, timeout=20)
    result = _body_text(driver)

    if "you must enter the session password" in result or "password required" in result:
        say("🔒 需要动态密码。")
        return PASSWORD
    if ("your attendance in this session has been recorded" in result
            or "self-recorded" in result
            or "has been recorded" in result):
        say("✅ 页面确认签到成功。")
        return OK

    say("⚠️ 点了提交，但没看到成功提示，稍后重试。")
    return NOT_OPEN


def _is_browser_crash(exc: Exception) -> bool:
    text = str(exc).lower()
    return _session_dead(exc) or "tab crashed" in text or "renderer" in text


def start_sign_in(target_url: str, site: str = SITE, log=None) -> str:
    """对某个 Attendance 活动页执行一次签到，返回状态字符串。

    log: 可选的日志回调（GUI 会传进来写进界面日志 + 文件），默认 print。
    """
    say = log or print
    with _driver_lock:
        for attempt in range(len(LAUNCH_VARIANTS)):
            name = LAUNCH_VARIANTS[_variant][0]
            say(f"→ 浏览器模式：{name}")
            try:
                driver = get_driver(fresh=(attempt > 0), say=say)
            except RuntimeError as exc:
                say(f"❌ 启动浏览器失败（{name}）：{exc}")
                _advance_variant()
                continue

            try:
                return _run_sign_in(driver, target_url, say)
            except WebDriverException as exc:
                if _is_browser_crash(exc):
                    first_line = str(exc).splitlines()[0][:160]
                    say(f"⚠️ 浏览器崩溃（{name}）：{first_line}")
                    _close_current()
                    if attempt + 1 < len(LAUNCH_VARIANTS):
                        say(f"   换「{_advance_variant()}」参数再试一次…")
                        time.sleep(1.5)
                    continue
                say(f"❌ 浏览器操作失败：{exc}")
                _close_current()
                return ERROR
            except Exception as exc:  # 兜底，别让后台线程死掉
                say(f"❌ 签到过程出错：{exc}")
                return ERROR

        say("❌ Edge 连续崩溃，所有启动参数都没成功。")
        say("   建议：把 bot_profile 改名成 bot_profile_old，点 Log In Spectrum 重新登录一次；")
        say("   如果仍然崩溃，说明是 Edge 本身的问题，可以考虑换 Chrome。")
        _reset_variant()
        return BROWSER_DIED


def manual_login(log=None) -> None:
    """打开浏览器，让用户自己登录一次（之后 bot_profile 里就有 session 了）。"""
    say = log or print
    global _variant
    with _driver_lock:
        saved_variant = _variant
        _variant = 0          # 登录一定要有可见窗口
        try:
            driver = get_driver(fresh=True, say=say)
            driver.get(SITE)
            say("已在浏览器中打开 Spectrum：请在里面登录，登录成功后这个窗口可以留着，也可以关掉。")
        except RuntimeError as exc:
            say(f"❌ 打开浏览器失败：{exc}")
        except WebDriverException as exc:
            say(f"❌ 浏览器崩溃：{str(exc).splitlines()[0][:160]}")
            _close_current()
        finally:
            _variant = saved_variant


if __name__ == "__main__":
    # 手动调试：python sign_in.py <attendance url>
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    if not target:
        manual_login()
    else:
        print(start_sign_in(target))
