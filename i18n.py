# -*- coding: utf-8 -*-
"""i18n.py —— 界面语言（中文 / English）。

用法：
    from i18n import t
    write_log(t("已签到", "Signed in"))

    i18n.set_lang("en")      # 切到英文
    i18n.LANG                # 当前语言

刻意保持极简：不依赖 flet，gui / sign_in / spectrum_sync 都能直接用。
"""

LANG = "zh"                      # 当前界面语言：zh / en
SUPPORTED = ("zh", "en")


def set_lang(lang) -> None:
    """切换语言；不认识的值一律当回中文。"""
    global LANG
    LANG = lang if lang in SUPPORTED else "zh"


def t(zh: str, en: str) -> str:
    """按当前语言二选一。"""
    return en if LANG == "en" else zh


def is_zh() -> bool:
    return LANG == "zh"
