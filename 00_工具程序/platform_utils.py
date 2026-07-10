"""跨平台运行辅助函数。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_path(path: Path) -> None:
    """用系统默认程序打开文件或目录。"""
    target = Path(path)
    if sys.platform == "win32":
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(target)], check=False)
    else:
        subprocess.run(["xdg-open", str(target)], check=False)


def resource_path(*parts: str) -> Path:
    """返回源码运行和 PyInstaller onedir 运行时都可用的资源路径。"""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    return base.joinpath("resources", *parts)


def ui_font_families() -> tuple[str, str]:
    """返回当前系统优先使用的界面与等宽字体。"""
    if sys.platform == "win32":
        return "Microsoft YaHei UI", "Cascadia Mono"
    if sys.platform == "darwin":
        return "PingFang SC", "Menlo"
    return "Noto Sans CJK SC", "DejaVu Sans Mono"
