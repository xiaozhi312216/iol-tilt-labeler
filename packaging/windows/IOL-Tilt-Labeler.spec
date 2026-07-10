# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "00_工具程序"
ICON_PATH = PROJECT_ROOT / "resources" / "windows" / "IOLTiltLabeler.ico"

analysis = Analysis(
    [str(TOOLS_DIR / "iol_tilt_labeler_qt.py")],
    pathex=[str(TOOLS_DIR)],
    binaries=[],
    datas=[(str(ICON_PATH), "resources/windows")],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PIL.Image",
        "openpyxl",
    ],
    hookspath=[],
    hooksconfig={
        "PySide6": {
            "modules": ["QtCore", "QtGui", "QtWidgets"],
        },
    },
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="IOL Tilt Labeler",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICON_PATH),
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="IOL Tilt Labeler",
)
