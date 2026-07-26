"""界面配色与样式表（浅色 / 深色两套，跟随系统外观）。"""

from __future__ import annotations

# 标注颜色：两套外观通用（画布始终是深色底）
ANN = {
    "guide": "#ff9f0a",
    "pupil": "#32ade6",
    "anterior": "#ffd60a",
    "posterior": "#ff9f45",
    "iol": "#30d158",
    "manual": "#bf5af2",
    "intersection": "#ff453a",
}

LIGHT = {
    "window": "#ededf0",
    "sidebar": "#f7f7f9",
    "card": "#ffffff",
    "field": "#ffffff",
    "canvas": "#0b0d12",
    "text": "#1d1d1f",
    "text2": "#66666c",
    "text3": "#96969c",
    "line": "#d9d9df",
    "line2": "#e7e7ec",
    "hover": "rgba(0,0,0,0.05)",
    "accent": "#007aff",
    "accent_text": "#ffffff",
    "accent_soft": "#e9f2ff",
    "ok": "#1d8b45",
    "warn": "#b45309",
    "danger": "#d70015",
    "danger_soft": "#fff0f1",
    "scroll": "#c8c8ce",
}

DARK = {
    "window": "#1c1c1e",
    "sidebar": "#242426",
    "card": "#2c2c2e",
    "field": "#1f1f21",
    "canvas": "#07080c",
    "text": "#f2f2f5",
    "text2": "#a0a0a8",
    "text3": "#76767e",
    "line": "#3a3a3e",
    "line2": "#323236",
    "hover": "rgba(255,255,255,0.07)",
    "accent": "#0a84ff",
    "accent_text": "#ffffff",
    "accent_soft": "#17335c",
    "ok": "#30d158",
    "warn": "#ff9f0a",
    "danger": "#ff453a",
    "danger_soft": "#3a1d20",
    "scroll": "#4a4a50",
}


def palette(dark: bool) -> dict[str, str]:
    return dict(DARK if dark else LIGHT)


def qss(c: dict[str, str], ui_font: str, mono_font: str) -> str:
    return f"""
* {{ font-family: "{ui_font}"; }}
QMainWindow, QWidget {{ background: {c['window']}; color: {c['text']}; font-size: 12px; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {c['card']}; color: {c['text']}; border: 1px solid {c['line']};
  padding: 4px 7px; border-radius: 5px; font-size: 11px; }}

/* ---------- 顶栏 ---------- */
#TopBar {{ background: {c['sidebar']}; border-bottom: 1px solid {c['line']}; }}
#AppName {{ font-size: 13px; font-weight: 600; color: {c['text']}; }}
#FileName {{ font-size: 12px; color: {c['text2']}; }}
#FileMeta {{ font-size: 11px; color: {c['text3']}; font-family: "{mono_font}"; }}

/* ---------- 按钮 ---------- */
QPushButton {{
  background: {c['card']}; color: {c['text']}; border: 1px solid {c['line']};
  border-radius: 6px; padding: 5px 12px; font-size: 12px;
}}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton:pressed {{ background: {c['line2']}; }}
QPushButton:disabled {{ color: {c['text3']}; border-color: {c['line2']}; background: transparent; }}
QPushButton#Primary {{
  background: {c['accent']}; color: {c['accent_text']}; border: 1px solid {c['accent']}; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {c['accent']}; }}
QPushButton#Primary:disabled {{ background: {c['line2']}; border-color: {c['line2']}; color: {c['text3']}; }}
QPushButton#Quiet {{ background: transparent; border: none; color: {c['text2']}; padding: 4px 8px; }}
QPushButton#Quiet:hover {{ background: {c['hover']}; color: {c['text']}; }}
QPushButton#Danger {{ color: {c['danger']}; }}
QPushButton#Danger:hover {{ background: {c['danger_soft']}; }}
QPushButton:checked {{ background: {c['accent_soft']}; border-color: {c['accent']}; color: {c['accent']}; }}

/* ---------- 画布悬浮工具条 ---------- */
#CanvasBar {{ background: rgba(24,26,32,0.86); border: 1px solid rgba(255,255,255,0.14);
  border-radius: 8px; }}
#CanvasBar QPushButton#CanvasBtn {{
  background: transparent; border: none; color: #e8e8ea; padding: 3px 9px;
  border-radius: 5px; font-size: 11px;
}}
#CanvasBar QPushButton#CanvasBtn:hover {{ background: rgba(255,255,255,0.14); }}
#CanvasBar QPushButton#CanvasBtn:checked {{ background: {c['accent']}; color: #ffffff; }}
#CanvasZoom {{ color: #c8c8cc; font-size: 11px; font-family: "{mono_font}"; background: transparent; }}
#CanvasSep {{ background: rgba(255,255,255,0.16); border: none; }}

/* ---------- 左栏 ---------- */
#Sidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['line']}; }}
#SectionTitle {{ font-size: 11px; font-weight: 600; color: {c['text3']}; }}
#Hairline {{ background: {c['line2']}; max-height: 1px; min-height: 1px; border: none; }}

/* ---------- 步骤行 ---------- */
#Step {{ background: transparent; border: 1px solid transparent; border-radius: 6px; }}
#Step:hover {{ background: {c['hover']}; }}
#Step[state="active"] {{ background: {c['accent_soft']}; border-color: {c['accent']}; }}
#StepNum {{ font-family: "{mono_font}"; font-size: 10px; color: {c['text3']}; }}
#StepNum[state="active"] {{ color: {c['accent']}; }}
#StepName {{ font-size: 12px; color: {c['text']}; }}
#StepName[state="active"] {{ font-weight: 600; color: {c['accent']}; }}
#StepCount {{ font-family: "{mono_font}"; font-size: 11px; color: {c['text3']}; }}
#StepCount[state="ready"] {{ color: {c['ok']}; }}
#StepCount[state="active"] {{ color: {c['accent']}; }}

/* ---------- 结果 ---------- */
#ResultValue {{ font-size: 27px; font-weight: 600; color: {c['text']}; font-family: "{mono_font}"; }}
#ResultUnit {{ font-size: 14px; color: {c['text2']}; }}
#ResultCaption {{ font-size: 11px; color: {c['text3']}; }}
#ResultCaption[tone="ok"] {{ color: {c['ok']}; }}
#ResultCaption[tone="warn"] {{ color: {c['warn']}; }}
#ResultCaption[tone="danger"] {{ color: {c['danger']}; }}
#DetailKey {{ font-size: 11px; color: {c['text3']}; }}
#DetailVal {{ font-size: 11px; color: {c['text2']}; font-family: "{mono_font}"; }}

/* ---------- 输入 ---------- */
QLineEdit {{
  background: {c['field']}; border: 1px solid {c['line']}; border-radius: 6px;
  padding: 5px 8px; font-size: 12px; color: {c['text']}; selection-background-color: {c['accent']};
}}
QLineEdit:focus {{ border-color: {c['accent']}; }}

/* ---------- 文件列表 ---------- */
QListWidget {{
  background: {c['field']}; border: 1px solid {c['line']}; border-radius: 6px;
  font-size: 12px; color: {c['text']}; outline: none; padding: 2px;
}}
QListWidget::item {{ padding: 4px 6px; border-radius: 4px; }}
QListWidget::item:hover {{ background: {c['hover']}; }}
QListWidget::item:selected {{ background: {c['accent']}; color: {c['accent_text']}; }}

/* ---------- 滑块 ---------- */
QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{ height: 3px; background: {c['line']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; height: 3px; border-radius: 2px; }}
QSlider::handle:horizontal {{
  background: {c['card']}; border: 1px solid {c['line']}; width: 13px; height: 13px;
  margin: -6px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ border-color: {c['accent']}; }}

/* ---------- 状态条 ---------- */
#StatusBar {{ background: {c['sidebar']}; border-top: 1px solid {c['line']}; }}
#StatusText {{ font-size: 11px; color: {c['text2']}; }}
#StatusMeta {{ font-size: 11px; color: {c['text3']}; font-family: "{mono_font}"; }}

/* ---------- 滚动条 ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 4px; min-height: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['scroll']}; border-radius: 4px; min-width: 28px; }}
"""
