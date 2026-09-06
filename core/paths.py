# -*- coding: utf-8 -*-
"""数据目录解析：源码运行 / PyInstaller 运行共用。"""
from __future__ import annotations

import os
import sys


def get_data_dir() -> str:
    """数据目录：源码 = 项目根/data；打包 = exe 旁/data（首启从包内解包复制）。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        bundled = os.path.join(getattr(sys, "_MEIPASS", base), "data")
        data = os.path.join(base, "data")
        if not os.path.isdir(data) and os.path.isdir(bundled):
            import shutil
            shutil.copytree(bundled, data)
        return data
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "data")


def ensure_data_dirs(data_dir: str) -> str:
    for sub in ("templates", "fonts", "presets", "output"):
        os.makedirs(os.path.join(data_dir, sub), exist_ok=True)
    return data_dir
