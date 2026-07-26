# -*- mode: python ; coding: utf-8 -*-
"""macOS 打包配置：生成独立 .app，不依赖系统 Python。

构建：.venv/bin/python -m PyInstaller --noconfirm --clean \
        --distpath dist --workpath build packaging/macos/IOL-Tilt-Labeler.spec
"""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "00_工具程序"
ICNS = PROJECT_ROOT / "resources" / "macos" / "IOLTiltLabeler.icns"
ICO = PROJECT_ROOT / "resources" / "windows" / "IOLTiltLabeler.ico"
VERSION = "1.2.0"

analysis = Analysis(
    [str(TOOLS_DIR / "iol_tilt_labeler_qt.py")],
    pathex=[str(TOOLS_DIR)],
    binaries=[],
    datas=[(str(ICO), "resources/windows")],
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
    excludes=[
        "tkinter", "numpy", "pandas", "matplotlib", "scipy",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtNetwork", "PySide6.QtCharts",
    ],
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
    icon=str(ICNS),
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
app = BUNDLE(
    coll,
    name="IOL 倾斜标注.app",
    icon=str(ICNS),
    bundle_identifier="local.xiao.ioltiltlabeler",
    version=VERSION,
    info_plist={
        "CFBundleName": "IOL 倾斜标注",
        "CFBundleDisplayName": "IOL 倾斜标注",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "NSHumanReadableCopyright": "© 2026 xiao",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "OCT 图片",
                "CFBundleTypeRole": "Editor",
                "LSItemContentTypes": ["public.jpeg", "public.png", "public.tiff",
                                       "com.microsoft.bmp"],
            }
        ],
    },
)
