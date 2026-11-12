# -*- coding: utf-8 -*-
"""手动测试一次签到（不会看时间，立刻执行）。

用法：
    python test.py                      # 用 config.json 里的第一条
    python test.py <attendance url>     # 指定某条
"""
import json
import sys
from pathlib import Path

from sign_in import start_sign_in

CONFIG = Path(__file__).resolve().parent / "config.json"


def first_url() -> str | None:
    if not CONFIG.is_file():
        return None
    try:
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    classes = raw.get("classes", []) if isinstance(raw, dict) else raw
    for course in classes:
        if isinstance(course, dict) and course.get("url"):
            return course["url"]
    return None


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else first_url()
    if not target:
        print("没有可用的 Attendance URL，请在 config.json 里放一条，或直接把 URL 作为参数传进来。")
        return 1

    print("--- 测试模式：立刻执行一次签到 ---")
    print(f"目标网址：{target}")
    status = start_sign_in(target)
    print(f"结果：{status}")
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
