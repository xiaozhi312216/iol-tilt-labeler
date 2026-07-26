#!/usr/bin/env python3
"""IOL Tilt Labeler — 桌面版（macOS / Windows 通用）。

界面：左侧控制栏 + 右侧影像工作区 + 底部状态条，跟随系统浅色/深色。
算法与数据层完全复用 iol_core：自动轴优先，第 5 步只做校验，Excel 只导四列。
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QEvent, QPointF, QSize, QTimer
from PySide6.QtGui import (
    QAction, QActionGroup, QBrush, QColor, QFont, QIcon, QKeySequence,
    QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

import iol_core as core
from iol_core import (
    MODE_META, SUPPORTED_EXTS, as_points, atomic_write_text, compute_result,
    default_label, final_angle_text, fmt_number, fmt_point,
    generate_calibration_images, row_for_image, save_annotated_image,
    unique_suffix, write_xlsx,
)
from platform_utils import open_path, resource_path, ui_font_families
import theme
from theme import ANN
from canvas import ImageCanvas, KEY_COLOR

APP_NAME = "IOL Tilt Labeler"
APP_VERSION = "1.2.0"
SIDEBAR_WIDTH = 292

_MAC = sys.platform == "darwin"
CMD = "⌘" if _MAC else "Ctrl+"
OPT = "⌥" if _MAC else "Alt+"
SHIFT = "⇧" if _MAC else "Shift+"
ENTER = "⏎" if _MAC else "Enter"

MODES = ("guide", "pupil", "anterior", "posterior", "manual_axis")
MODE_KEY = {"pupil": "pupil_plane", "manual_axis": "manual_iol_axis"}
# 步骤名尽量短，说明文字放 tooltip
MODE_SHORT = {
    "guide": "C-D 参考线",
    "pupil": "A-B 瞳孔平面",
    "anterior": "晶体前表面",
    "posterior": "晶体后表面",
    "manual_axis": "自动轴校验",
}
MAX_POINTS = {"guide": 12, "pupil": 2, "anterior": 8, "posterior": 12, "manual_axis": 2}

FONT_FAMILY, MONO_FAMILY = ui_font_families()


def key_of(mode: str) -> str:
    return MODE_KEY.get(mode, mode)


_DOT_CACHE: dict[str, QIcon] = {}


def dot_icon(color: str, size: int = 9) -> QIcon:
    cached = _DOT_CACHE.get(color)
    if cached is not None:
        return cached
    pm = QPixmap(size + 6, size + 6)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(3, 3, size, size)
    p.end()
    icon = QIcon(pm)
    _DOT_CACHE[color] = icon
    return icon


def brand_pixmap(size: int = 22) -> QPixmap:
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    s = size * 2
    grad = QLinearGradient(0, 0, s, s)
    grad.setColorAt(0.0, QColor("#2f7cf6"))
    grad.setColorAt(1.0, QColor("#1a4fd6"))
    path = QPainterPath()
    path.addRoundedRect(0, 0, s, s, s * 0.27, s * 0.27)
    p.fillPath(path, QBrush(grad))
    pen = QPen(QColor(255, 255, 255, 235))
    pen.setWidthF(s * 0.055)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(s * 0.24, s * 0.24, s * 0.52, s * 0.52)
    pen.setWidthF(s * 0.05)
    p.setPen(pen)
    p.drawLine(s * 0.16, s * 0.68, s * 0.84, s * 0.36)
    p.end()
    return pm


# ============================================================
#  小部件
# ============================================================
class Section(QWidget):
    """左栏分组：小标题 + 内容，没有大卡片。"""

    def __init__(self, title: str, action: QWidget | None = None):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(7)
        head = QHBoxLayout()
        head.setContentsMargins(2, 0, 2, 0)
        head.setSpacing(6)
        lab = QLabel(title)
        lab.setObjectName("SectionTitle")
        head.addWidget(lab)
        head.addStretch(1)
        if action is not None:
            head.addWidget(action)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(6)
        outer.addLayout(self.body)

    def add(self, w):
        if isinstance(w, QWidget):
            self.body.addWidget(w)
        else:
            self.body.addLayout(w)


class StepRow(QFrame):
    """一行步骤：色点(兼图例) + 名称 + 计数 + 序号。"""

    def __init__(self, mode: str, on_click):
        super().__init__()
        self.mode = mode
        self.on_click = on_click
        self.setObjectName("Step")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{MODE_META[mode][1]} — {MODE_META[mode][2]}（按 {MODE_META[mode][0]}）")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 9, 5)
        lay.setSpacing(8)

        self.dot = QLabel()
        self.dot.setFixedSize(9, 9)
        self.dot.setStyleSheet(
            f"background:{ANN[KEY_COLOR[key_of(mode)]]};border-radius:4px;")
        self.num = QLabel(MODE_META[mode][0])
        self.num.setObjectName("StepNum")
        self.name = QLabel(MODE_SHORT[mode])
        self.name.setObjectName("StepName")
        self.count = QLabel("0")
        self.count.setObjectName("StepCount")
        lay.addWidget(self.num)
        lay.addWidget(self.dot)
        lay.addWidget(self.name, 1)
        lay.addWidget(self.count)

    def mousePressEvent(self, e):
        self.on_click(self.mode)

    def set_state(self, active: bool, ready: bool, count_text: str):
        self.count.setText(count_text)
        state = "active" if active else ("ready" if ready else "idle")
        self.setProperty("state", state)
        for w in (self, self.num, self.name, self.count):
            w.setProperty("state", state)
            w.style().unpolish(w)
            w.style().polish(w)


class UndoStack:
    """按图片独立的撤销/重做栈，存 label 的 JSON 快照。"""

    LIMIT = 100

    def __init__(self):
        self.past: list[str] = []
        self.future: list[str] = []

    def push(self, label: dict):
        self.past.append(json.dumps(label, ensure_ascii=False))
        if len(self.past) > self.LIMIT:
            self.past.pop(0)
        self.future.clear()


# ============================================================
#  主窗口
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 840)
        self.setMinimumSize(1000, 640)
        self.setAcceptDrops(True)

        self.folder: Path | None = None
        self.output_dir: Path | None = None
        self.labels_path: Path | None = None
        self.images: list[Path] = []
        self.image_keys: dict[Path, str] = {}
        self.index = 0
        self.labels: dict[str, dict[str, Any]] = {}
        self.original_image = None
        self.mode = "pupil"
        self.step_rows: dict[str, StepRow] = {}
        self.undo_stacks: dict[str, UndoStack] = {}
        self._loading = False

        self._build_ui()
        self._build_menu()
        self.apply_theme()
        app = QApplication.instance()
        app.installEventFilter(self)
        try:
            app.styleHints().colorSchemeChanged.connect(lambda _: self.apply_theme())
        except (AttributeError, RuntimeError):
            pass
        self._refresh_all()

    # ---------------- 主题 ----------------
    def is_dark(self) -> bool:
        forced = os.environ.get("IOL_FORCE_THEME", "")
        if forced in ("dark", "light"):
            return forced == "dark"
        try:
            return QApplication.instance().styleHints().colorScheme() == Qt.ColorScheme.Dark
        except (AttributeError, RuntimeError):
            return False

    def apply_theme(self):
        c = theme.palette(self.is_dark())
        self.setStyleSheet(theme.qss(c, FONT_FAMILY, MONO_FAMILY))

    # ---------------- 界面 ----------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        body = QWidget()
        body_l = QHBoxLayout(body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(0)
        body_l.addWidget(self._build_sidebar())
        body_l.addWidget(self._build_canvas_area(), 1)
        root.addWidget(body, 1)

        root.addWidget(self._build_statusbar())

    # ---- 顶栏 ----
    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(52)
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(10)

        mark = QLabel()
        mark.setPixmap(brand_pixmap(22))
        mark.setFixedSize(22, 22)
        name = QLabel("IOL 倾斜标注")
        name.setObjectName("AppName")
        h.addWidget(mark)
        h.addWidget(name)

        sep = QLabel("·")
        sep.setObjectName("FileMeta")
        self.file_label = QLabel("未打开图片")
        self.file_label.setObjectName("FileName")
        self.index_label = QLabel("")
        self.index_label.setObjectName("FileMeta")
        h.addSpacing(4)
        h.addWidget(sep)
        h.addWidget(self.file_label)
        h.addWidget(self.index_label)
        h.addStretch(1)

        self.btn_open = QPushButton("打开")
        self.btn_open.setToolTip(f"选择包含 OCT 图片的文件夹（{CMD}O）")
        self.btn_open.clicked.connect(self.open_folder)
        self.btn_undo = QPushButton("撤销")
        self.btn_undo.setToolTip(f"撤销上一步（{CMD}Z）")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_prev = QPushButton("‹")
        self.btn_prev.setFixedWidth(34)
        self.btn_prev.setToolTip("上一张（P）")
        self.btn_prev.clicked.connect(self.prev_image)
        self.btn_next = QPushButton("›")
        self.btn_next.setFixedWidth(34)
        self.btn_next.setToolTip("下一张（N）")
        self.btn_next.clicked.connect(self.next_image)
        self.btn_save = QPushButton("保存")
        self.btn_save.setToolTip(f"保存当前结果（{CMD}S）")
        self.btn_save.clicked.connect(self.save_current)
        self.btn_save_next = QPushButton("保存并下一张")
        self.btn_save_next.setObjectName("Primary")
        self.btn_save_next.setToolTip(f"保存并跳到下一张（{CMD}{ENTER}）")
        self.btn_save_next.clicked.connect(self.save_and_next)

        for b in (self.btn_open, self.btn_undo, self.btn_prev, self.btn_next,
                  self.btn_save, self.btn_save_next):
            b.setCursor(Qt.PointingHandCursor)
        h.addWidget(self.btn_open)
        h.addWidget(self.btn_undo)
        h.addSpacing(6)
        h.addWidget(self.btn_prev)
        h.addWidget(self.btn_next)
        h.addSpacing(6)
        h.addWidget(self.btn_save)
        h.addWidget(self.btn_save_next)
        return bar

    # ---- 左栏 ----
    def _build_sidebar(self) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("Sidebar")
        wrap.setFixedWidth(SIDEBAR_WIDTH)
        col = QVBoxLayout(wrap)
        col.setContentsMargins(12, 12, 12, 10)
        col.setSpacing(12)

        col.addWidget(self._build_steps_section())
        col.addWidget(self._hairline())
        col.addWidget(self._build_result_section())
        col.addWidget(self._hairline())
        col.addWidget(self._build_image_section())
        col.addWidget(self._build_note_section())
        col.addWidget(self._hairline())
        col.addWidget(self._build_files_section(), 1)
        return wrap

    def _hairline(self) -> QFrame:
        ln = QFrame()
        ln.setObjectName("Hairline")
        ln.setFrameShape(QFrame.HLine)
        ln.setFixedHeight(1)
        return ln

    def _build_steps_section(self) -> QWidget:
        sec = Section("标注步骤")
        for mode in MODES:
            row = StepRow(mode, self.set_mode)
            self.step_rows[mode] = row
            sec.add(row)
        return sec

    def _build_result_section(self) -> QWidget:
        self.btn_copy = QPushButton("复制")
        self.btn_copy.setObjectName("Quiet")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.setToolTip("复制“IOL轴 / A-B / 最终夹角”到剪贴板")
        self.btn_copy.clicked.connect(self.copy_result)
        sec = Section("测量结果", self.btn_copy)

        row = QHBoxLayout()
        row.setSpacing(3)
        row.setContentsMargins(2, 0, 0, 0)
        self.result_value = QLabel("—")
        self.result_value.setObjectName("ResultValue")
        row.addWidget(self.result_value)
        row.addStretch(1)
        sec.add(row)

        self.result_caption = QLabel("完成 A-B 与前/后表面后自动预览")
        self.result_caption.setObjectName("ResultCaption")
        self.result_caption.setWordWrap(True)
        self.result_caption.setContentsMargins(2, 0, 0, 0)
        sec.add(self.result_caption)

        grid = QGridLayout()
        grid.setContentsMargins(2, 4, 2, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.detail_labels: dict[str, QLabel] = {}
        specs = [("iol_angle", "IOL 轴"), ("pupil_angle", "A-B"),
                 ("difference", "有符号差"), ("manual_delta", "校验差"),
                 ("rms", "拟合 RMS"), ("counts", "前/后点数")]
        for i, (key, name) in enumerate(specs):
            r, cpos = divmod(i, 2)
            k = QLabel(name)
            k.setObjectName("DetailKey")
            v = QLabel("—")
            v.setObjectName("DetailVal")
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.detail_labels[key] = v
            grid.addWidget(k, r, cpos * 2)
            grid.addWidget(v, r, cpos * 2 + 1)
        sec.add(grid)
        return sec

    def _build_image_section(self) -> QWidget:
        self.btn_reset_adjust = QPushButton("复位")
        self.btn_reset_adjust.setObjectName("Quiet")
        self.btn_reset_adjust.setCursor(Qt.PointingHandCursor)
        self.btn_reset_adjust.clicked.connect(self.reset_adjust)
        sec = Section("图像调节", self.btn_reset_adjust)

        self.slider_bright = QSlider(Qt.Horizontal)
        self.slider_bright.setRange(-100, 100)
        self.slider_bright.setToolTip("亮度")
        self.slider_contrast = QSlider(Qt.Horizontal)
        self.slider_contrast.setRange(-100, 100)
        self.slider_contrast.setToolTip("对比度")
        for s, name in ((self.slider_bright, "亮度"), (self.slider_contrast, "对比度")):
            s.valueChanged.connect(self.apply_adjust)
            line = QHBoxLayout()
            line.setSpacing(8)
            lab = QLabel(name)
            lab.setObjectName("DetailKey")
            lab.setFixedWidth(30)
            line.addWidget(lab)
            line.addWidget(s, 1)
            sec.add(line)

        self.btn_invert = QPushButton("反相显示")
        self.btn_invert.setCheckable(True)
        self.btn_invert.setCursor(Qt.PointingHandCursor)
        self.btn_invert.setToolTip("反相有时更容易看清晶体边界，不影响测量结果")
        self.btn_invert.toggled.connect(self.apply_adjust)
        sec.add(self.btn_invert)
        return sec

    def _build_note_section(self) -> QWidget:
        sec = Section("病例备注")
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("病例编号 / 术眼 / 备注")
        self.note_edit.editingFinished.connect(self.save_note)
        sec.add(self.note_edit)
        return sec

    def _build_files_section(self) -> QWidget:
        self.files_count = QLabel("")
        self.files_count.setObjectName("SectionTitle")
        sec = Section("图片列表", self.files_count)
        self.file_list = QListWidget()
        self.file_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.file_list.setMinimumHeight(130)
        self.file_list.setIconSize(QSize(14, 14))
        self.file_list.currentRowChanged.connect(self.on_file_selected)
        sec.add(self.file_list)
        return sec

    # ---- 画布 ----
    def _build_canvas_area(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.canvas = ImageCanvas()
        self.canvas.overlay_getter = self.current_label
        self.canvas.mode_key_getter = lambda: key_of(self.mode)
        self.canvas.pointClicked.connect(self.on_canvas_click)
        self.canvas.pointGrabbed.connect(self.on_point_grabbed)
        self.canvas.pointMoved.connect(self.on_point_moved)
        self.canvas.pointReleased.connect(self.on_point_released)
        self.canvas.pointDeleteRequested.connect(self.delete_point)
        self.canvas.cursorMoved.connect(self.on_cursor_move)
        self.canvas.viewChanged.connect(self._refresh_status_meta)
        lay.addWidget(self.canvas)

        self.canvas_bar = self._build_canvas_toolbar(self.canvas)
        return wrap

    def _build_canvas_toolbar(self, parent: QWidget) -> QWidget:
        bar = QFrame(parent)
        bar.setObjectName("CanvasBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(5, 4, 5, 4)
        h.setSpacing(2)

        def btn(text, tip, slot, checkable=False, width=0):
            b = QPushButton(text)
            b.setObjectName("CanvasBtn")
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            if width:
                b.setFixedWidth(width)
            h.addWidget(b)
            return b

        btn("−", f"缩小（{CMD}-）", lambda: self.canvas.zoom_by(1 / 1.2), width=28)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("CanvasZoom")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setFixedWidth(46)
        h.addWidget(self.zoom_label)
        btn("+", f"放大（{CMD}+）", lambda: self.canvas.zoom_by(1.2), width=28)
        h.addWidget(self._vsep())
        btn("适配", f"适配窗口（{CMD}0）", self.canvas.fit)
        btn("1:1", f"实际像素（{CMD}1）", self.canvas.actual_size)
        h.addWidget(self._vsep())
        self.btn_loupe = btn("放大镜", f"光标处放大镜（{CMD}L）", self.toggle_loupe, checkable=True)
        self.btn_loupe.setChecked(True)
        self.btn_cross = btn("准星", f"十字准星（{CMD}K）", self.toggle_crosshair, checkable=True)
        bar.adjustSize()
        return bar

    def _vsep(self) -> QWidget:
        w = QFrame()
        w.setObjectName("CanvasSep")
        w.setFixedWidth(1)
        w.setFixedHeight(16)
        return w

    def _build_statusbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(26)
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(14)
        self.status_text = QLabel("准备就绪")
        self.status_text.setObjectName("StatusText")
        self.status_meta = QLabel("")
        self.status_meta.setObjectName("StatusMeta")
        h.addWidget(self.status_text, 1)
        h.addWidget(self.status_meta)
        return bar

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_canvas_bar()

    def _place_canvas_bar(self):
        if hasattr(self, "canvas_bar"):
            self.canvas_bar.adjustSize()
            self.canvas_bar.move(self.canvas.width() - self.canvas_bar.width() - 14, 12)
            self.canvas_bar.raise_()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._place_canvas_bar)
        QTimer.singleShot(0, self.canvas.setFocus)

    # ---------------- 菜单 ----------------
    def _act(self, menu, text, shortcut, slot, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("文件")
        self._act(m, "打开文件夹…", "Ctrl+O", self.open_folder)
        self._act(m, "打开图片…", "Ctrl+Shift+O", self.open_files)
        m.addSeparator()
        self._act(m, "保存当前", "Ctrl+S", self.save_current)
        self._act(m, "保存并下一张", "Ctrl+Return", self.save_and_next)
        m.addSeparator()
        self._act(m, "打开 Excel", "Ctrl+E", self.open_excel)
        self._act(m, "打开输出文件夹", "Ctrl+Shift+E", self.open_output_folder)

        m = mb.addMenu("编辑")
        self.act_undo = self._act(m, "撤销", QKeySequence.Undo, self.undo)
        self.act_redo = self._act(m, "重做", QKeySequence.Redo, self.redo)
        m.addSeparator()
        self._act(m, "删除选中点", "Backspace", self.delete_selected)
        self._act(m, "清空当前步骤", "", self.clear_current_mode)
        self._act(m, "清空本图全部点位…", "", self.clear_all_points)

        m = mb.addMenu("视图")
        self._act(m, "放大", "Ctrl++", lambda: self.canvas.zoom_by(1.2))
        self._act(m, "缩小", "Ctrl+-", lambda: self.canvas.zoom_by(1 / 1.2))
        self._act(m, "适配窗口", "Ctrl+0", self.canvas.fit)
        self._act(m, "实际像素", "Ctrl+1", self.canvas.actual_size)
        m.addSeparator()
        self.act_loupe = self._act(m, "放大镜", "Ctrl+L", self.toggle_loupe_menu, checkable=True)
        self.act_loupe.setChecked(True)
        self.act_cross = self._act(m, "十字准星", "Ctrl+K", self.toggle_crosshair_menu, checkable=True)
        m.addSeparator()
        self._act(m, "上一张", "Ctrl+Left", self.prev_image)
        self._act(m, "下一张", "Ctrl+Right", self.next_image)

        m = mb.addMenu("步骤")
        group = QActionGroup(self)
        self.mode_actions = {}
        for mode in MODES:
            a = QAction(f"{MODE_META[mode][0]}. {MODE_SHORT[mode]}", self)
            a.setCheckable(True)
            a.setShortcut(QKeySequence(f"Ctrl+{MODE_META[mode][0]}"))
            a.triggered.connect(lambda _=False, md=mode: self.set_mode(md))
            group.addAction(a)
            m.addAction(a)
            self.mode_actions[mode] = a

        m = mb.addMenu("帮助")
        self._act(m, "快捷键与用法", "", self.show_help)
        self._act(m, "生成校准测试图", "", self.gen_calibration)
        self._act(m, f"关于 {APP_NAME}", "", self.show_about)

    # ---------------- 数据 ----------------
    def build_image_keys(self):
        counts: dict[str, int] = {}
        for image in self.images:
            counts[image.name] = counts.get(image.name, 0) + 1
        self.image_keys = {}
        for image in self.images:
            if counts.get(image.name, 0) == 1:
                self.image_keys[image] = image.name
            else:
                self.image_keys[image] = f"{image.stem}__{unique_suffix(image)}{image.suffix.lower()}"

    def image_key(self, image: Path) -> str:
        return self.image_keys.get(image, image.name)

    def output_stem(self, image: Path) -> str:
        return Path(self.image_key(image)).stem

    def current_image_path(self) -> Path | None:
        if not self.images:
            return None
        return self.images[self.index]

    def current_label(self) -> dict[str, Any]:
        path = self.current_image_path()
        if path is None:
            return default_label()
        self.labels.setdefault(self.image_key(path), default_label())
        return self.labels[self.image_key(path)]

    def current_stack(self) -> UndoStack:
        path = self.current_image_path()
        key = self.image_key(path) if path else "__none__"
        return self.undo_stacks.setdefault(key, UndoStack())

    def push_undo(self):
        self.current_stack().push(self.current_label())

    def load_labels(self):
        self.labels = {}
        if self.labels_path and self.labels_path.exists():
            try:
                data = json.loads(self.labels_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.labels = data
            except Exception:
                QMessageBox.warning(self, "读取 labels.json 失败", traceback.format_exc())
        for image in self.images:
            key = self.image_key(image)
            if key not in self.labels and image.name in self.labels:
                self.labels[key] = self.labels[image.name]
            self.labels.setdefault(key, default_label())

    def save_labels_json(self):
        if not self.labels_path:
            return
        atomic_write_text(self.labels_path,
                          json.dumps(self.labels, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    def export_tables_if_exists(self):
        if self.output_dir is None:
            return
        if ((self.output_dir / "iol_tilt_results.csv").exists()
                or (self.output_dir / "iol_tilt_results.xlsx").exists()):
            self.export_tables()

    def invalidate_result(self, reason: str):
        self.current_label()["result"] = None
        self.save_labels_json()
        try:
            self.export_tables_if_exists()
        except Exception as exc:
            self.set_status(f"{reason}；刷新表格失败：{exc}")
            return
        self.set_status(reason)

    # ---------------- 交互 ----------------
    def set_status(self, text: str):
        self.status_text.setText(text)

    def set_mode(self, mode: str):
        self.mode = mode
        if mode in self.mode_actions:
            self.mode_actions[mode].setChecked(True)
        self.canvas.selected = None
        self._refresh_steps()
        self.canvas.update()

    def on_cursor_move(self, x, y):
        self._cursor_xy = (x, y)
        self._refresh_status_meta()

    def _refresh_status_meta(self):
        parts = []
        xy = getattr(self, "_cursor_xy", None)
        if xy and self.images:
            parts.append(f"x {xy[0]:.0f}  y {xy[1]:.0f}")
        if self.images:
            parts.append(f"{self.canvas.scale * 100:.0f}%")
            parts.append(f"已完成 {self.done_count()}/{len(self.images)}")
        self.status_meta.setText("     ".join(parts))
        if hasattr(self, "zoom_label"):
            self.zoom_label.setText(f"{self.canvas.scale * 100:.0f}%")

    def done_count(self) -> int:
        return sum(1 for img in self.images
                   if (self.labels.get(self.image_key(img)) or {}).get("result"))

    def on_canvas_click(self, x, y):
        if not self.images:
            return
        label = self.current_label()
        key = key_of(self.mode)
        limit = MAX_POINTS[self.mode]
        if len(label.get(key, [])) >= limit:
            self.set_status(f"{MODE_SHORT[self.mode]} 最多 {limit} 个点；拖动已有点可微调，⌥点击可删除")
            return
        self.push_undo()
        label.setdefault(key, [])
        label[key].append([round(x, 3), round(y, 3)])
        self.canvas.selected = (key, len(label[key]) - 1)
        self.invalidate_result(f"已添加 {MODE_SHORT[self.mode]} 第 {len(label[key])} 点")
        self.canvas.update()
        self._refresh_side()
        # A-B 点满自动进入下一步，少点一次
        if self.mode == "pupil" and len(label[key]) == 2:
            self.set_mode("anterior")

    def on_point_grabbed(self, key: str, idx: int):
        self.push_undo()
        self._drag_dirty = False

    def on_point_moved(self, key: str, idx: int, x: float, y: float):
        label = self.current_label()
        pts = label.get(key)
        if not pts or idx >= len(pts):
            return
        pts[idx] = [round(x, 3), round(y, 3)]
        self._drag_dirty = True
        self._refresh_side(light=True)

    def on_point_released(self):
        if getattr(self, "_drag_dirty", False):
            self.invalidate_result("已移动点位，需重新保存")
            self._refresh_side()
        else:
            # 只是点了一下没真拖动，撤销栈不留空快照
            stack = self.current_stack()
            if stack.past:
                stack.past.pop()
        self._drag_dirty = False

    def delete_point(self, key: str, idx: int):
        label = self.current_label()
        pts = label.get(key)
        if not pts or idx >= len(pts):
            return
        self.push_undo()
        removed = pts.pop(idx)
        self.canvas.selected = None
        self.invalidate_result(f"已删除点 {fmt_point(tuple(removed))}")
        self.canvas.update()
        self._refresh_side()

    def delete_selected(self):
        if self.canvas.selected:
            self.delete_point(*self.canvas.selected)
        else:
            self.set_status("先点选一个点，再按 Delete 删除")

    def nudge_selected(self, dx: float, dy: float):
        if not self.canvas.selected:
            return False
        key, idx = self.canvas.selected
        pts = self.current_label().get(key)
        if not pts or idx >= len(pts):
            return False
        self.push_undo()
        pts[idx] = [round(pts[idx][0] + dx, 3), round(pts[idx][1] + dy, 3)]
        self.invalidate_result(f"已微调点位 {fmt_point(tuple(pts[idx]))}")
        self.canvas.update()
        self._refresh_side()
        return True

    def undo(self):
        stack = self.current_stack()
        if not stack.past:
            self.set_status("没有可撤销的操作")
            return
        path = self.current_image_path()
        if path is None:
            return
        key = self.image_key(path)
        stack.future.append(json.dumps(self.labels.get(key, default_label()), ensure_ascii=False))
        self.labels[key] = json.loads(stack.past.pop())
        self.canvas.selected = None
        self.note_edit.setText(str(self.labels[key].get("note", "")))
        self.save_labels_json()
        self.export_tables_if_exists()
        self.set_status("已撤销")
        self.canvas.update()
        self._refresh_all()

    def redo(self):
        stack = self.current_stack()
        if not stack.future:
            self.set_status("没有可重做的操作")
            return
        path = self.current_image_path()
        if path is None:
            return
        key = self.image_key(path)
        stack.past.append(json.dumps(self.labels.get(key, default_label()), ensure_ascii=False))
        self.labels[key] = json.loads(stack.future.pop())
        self.canvas.selected = None
        self.note_edit.setText(str(self.labels[key].get("note", "")))
        self.save_labels_json()
        self.export_tables_if_exists()
        self.set_status("已重做")
        self.canvas.update()
        self._refresh_all()

    def clear_current_mode(self):
        if not self.images:
            return
        label = self.current_label()
        key = key_of(self.mode)
        if not label.get(key):
            self.set_status(f"{MODE_SHORT[self.mode]} 本来就没有点")
            return
        if QMessageBox.question(self, "清空当前步骤",
                                f"清空「{MODE_SHORT[self.mode]}」的全部点？") != QMessageBox.Yes:
            return
        self.push_undo()
        label[key] = []
        self.canvas.selected = None
        self.invalidate_result(f"已清空 {MODE_SHORT[self.mode]}")
        self.canvas.update()
        self._refresh_all()

    def clear_all_points(self):
        if not self.images:
            return
        if QMessageBox.question(self, "清空本图", "清空这张图的所有点位和结果？") != QMessageBox.Yes:
            return
        self.push_undo()
        path = self.current_image_path()
        self.labels[self.image_key(path)] = default_label()
        self.note_edit.setText("")
        self.canvas.selected = None
        self.save_labels_json()
        try:
            self.export_tables_if_exists()
        except Exception as exc:
            self.set_status(f"已清空；刷新表格失败：{exc}")
        else:
            self.set_status("已清空本图全部点位")
        self.canvas.update()
        self._refresh_all()

    def save_note(self):
        if not self.images:
            return
        self.current_label()["note"] = self.note_edit.text()
        self.save_labels_json()

    def copy_result(self):
        label = self.current_label()
        result = label.get("result") or self._preview_result(label)
        if not result:
            self.set_status("还没有可复制的结果")
            return
        text = (f"IOL轴角度 {fmt_number(result.get('iol_angle'))}°\t"
                f"A-B角度 {fmt_number(result.get('pupil_angle'))}°\t"
                f"最终夹角 {final_angle_text(result)}°")
        QApplication.clipboard().setText(text)
        self.set_status("结果已复制到剪贴板")

    # ---------------- 图像调节 ----------------
    def apply_adjust(self):
        self.canvas.set_adjust(self.slider_bright.value(),
                               self.slider_contrast.value(),
                               self.btn_invert.isChecked())

    def reset_adjust(self):
        self.slider_bright.setValue(0)
        self.slider_contrast.setValue(0)
        self.btn_invert.setChecked(False)

    def toggle_loupe(self):
        self.canvas.show_loupe = self.btn_loupe.isChecked()
        self.act_loupe.setChecked(self.canvas.show_loupe)
        self.canvas.update()

    def toggle_loupe_menu(self):
        self.btn_loupe.setChecked(self.act_loupe.isChecked())
        self.toggle_loupe()

    def toggle_crosshair(self):
        self.canvas.show_crosshair = self.btn_cross.isChecked()
        self.act_cross.setChecked(self.canvas.show_crosshair)
        self.canvas.update()

    def toggle_crosshair_menu(self):
        self.btn_cross.setChecked(self.act_cross.isChecked())
        self.toggle_crosshair()

    # ---------------- 打开 / 切换 ----------------
    def open_folder(self):
        selected = QFileDialog.getExistingDirectory(self, "选择包含 OCT 图片的文件夹")
        if not selected:
            return
        folder = Path(selected)
        images = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_EXTS)
        self.start_session(images, folder)

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择一张或多张 OCT 图片", "",
            "图片文件 (*.jpg *.jpeg *.png *.tif *.tiff *.bmp);;所有文件 (*.*)")
        if not files:
            return
        images = sorted(Path(p) for p in files if Path(p).suffix.lower() in SUPPORTED_EXTS)
        if not images:
            QMessageBox.warning(self, "没有图片", "没有选中 jpg / png / tif / bmp 图片")
            return
        self.start_session(images, images[0].parent)

    def start_session(self, images: list[Path], output_base: Path):
        if not images:
            QMessageBox.warning(self, "没有图片", "这里没有 jpg / png / tif / bmp 图片")
            self.set_status("没有找到图片")
            return
        self.folder = output_base
        self.images = images
        self.build_image_keys()
        self.undo_stacks = {}
        self.output_dir = output_base / "IOL_Tilt_Output"
        try:
            self.output_dir.mkdir(exist_ok=True)
            (self.output_dir / "annotated").mkdir(exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "无法创建结果文件夹", f"{self.output_dir}\n{exc}")
            return
        self.labels_path = self.output_dir / "labels.json"
        self.load_labels()
        self.index = 0
        self._rebuild_file_list()
        self.load_current_image(fit=True)
        self.set_status(f"已载入 {len(images)} 张图片 · 结果写入 {self.output_dir.name}/")

    def _rebuild_file_list(self):
        self._loading = True
        self.file_list.clear()
        for image in self.images:
            item = QListWidgetItem(image.name)
            item.setToolTip(str(image))
            self.file_list.addItem(item)
        self.file_list.setCurrentRow(self.index)
        self._loading = False
        self._refresh_file_list_state()

    def _refresh_file_list_state(self):
        if self.file_list.count() != len(self.images):
            return
        for i, image in enumerate(self.images):
            label = self.labels.get(self.image_key(image), {})
            has_points = any(label.get(k) for k in
                             ("guide", "pupil_plane", "anterior", "posterior", "manual_iol_axis"))
            if label.get("result"):
                color, tip = "#30d158", "已保存"
            elif has_points:
                color, tip = "#ff9f0a", "标注中，未保存"
            else:
                color, tip = "#8e8e93", "未开始"
            item = self.file_list.item(i)
            item.setIcon(dot_icon(color))
            item.setToolTip(f"{image.name}\n{tip}")
        self.files_count.setText(f"{self.done_count()}/{len(self.images)} 已完成")

    def on_file_selected(self, row: int):
        if self._loading or row < 0 or row >= len(self.images) or row == self.index:
            return
        self.save_note()
        self.index = row
        self.load_current_image(fit=True)

    def load_current_image(self, fit=False):
        path = self.current_image_path()
        if path is None:
            return
        try:
            from PIL import Image
            self.original_image = Image.open(path).convert("RGB")
        except Exception as exc:
            QMessageBox.critical(self, "打开图片失败", f"{path}\n{exc}")
            return
        self.canvas.selected = None
        self.canvas.set_image(self.original_image)
        self.note_edit.setText(str(self.current_label().get("note", "")))
        if fit:
            # 延到布局稳定后再适配，否则启动时带参数打开会按初始尺寸算缩放
            self.canvas.fit()
            QTimer.singleShot(0, self.canvas.fit)
        self._loading = True
        self.file_list.setCurrentRow(self.index)
        self._loading = False
        self.setWindowTitle(f"{path.name} — {APP_NAME}")
        self._refresh_all()

    def prev_image(self):
        if not self.images:
            return
        if self.index == 0:
            self.set_status("已经是第一张")
            return
        self.save_note()
        self.index -= 1
        self.load_current_image(fit=True)

    def next_image(self):
        if not self.images:
            return
        if self.index >= len(self.images) - 1:
            self.set_status("已经是最后一张")
            return
        self.save_note()
        self.index += 1
        self.load_current_image(fit=True)

    # ---------------- 计算 / 保存 ----------------
    def _preview_result(self, label) -> dict | None:
        try:
            return compute_result(label)
        except Exception:
            return None

    def save_current(self) -> bool:
        if self.original_image is None or self.output_dir is None:
            self.set_status("先打开图片再保存")
            return False
        path = self.current_image_path()
        if path is None:
            return False
        try:
            label = self.current_label()
            result = compute_result(label)
            result["annotated_file"] = ""
            annotated = save_annotated_image(self.output_dir, self.output_stem(path),
                                             path, label, result)
            result["annotated_file"] = str(annotated) if annotated else ""
            label["result"] = result
            label["note"] = self.note_edit.text()
            self.save_labels_json()
            self.export_tables()
            self.set_status(f"已保存 {path.name} · 最终夹角 {final_angle_text(result)}°")
            self.canvas.update()
            self._refresh_all()
            return True
        except Exception as exc:
            QMessageBox.warning(self, "还不能保存", str(exc))
            self.set_status(f"保存失败：{exc}")
            return False

    def save_and_next(self):
        if not self.save_current():
            return
        if self.index >= len(self.images) - 1:
            self.set_status(f"全部完成 · {self.done_count()}/{len(self.images)}")
            QMessageBox.information(self, "完成",
                                    f"已保存最后一张。\n共完成 {self.done_count()}/{len(self.images)} 张。")
            return
        self.next_image()

    def export_tables(self):
        if self.output_dir is None:
            return
        headers = ["IOL轴角度", "A-B角度", "最终夹角", "备注"]
        rows = []
        for image in self.images:
            label = self.labels.get(self.image_key(image), default_label())
            full = row_for_image(image, label, label.get("result"))
            rows.append({
                "IOL轴角度": full.get("iol_angle", ""),
                "A-B角度": full.get("pupil_plane_angle", ""),
                "最终夹角": full.get("final_angle", ""),
                "备注": full.get("note", ""),
            })
        csv_path = self.output_dir / "iol_tilt_results.csv"
        import csv as _csv
        tmp_csv = csv_path.with_name(f".{csv_path.stem}.tmp{csv_path.suffix}")
        with tmp_csv.open("w", newline="", encoding="utf-8-sig") as f:
            writer = _csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        tmp_csv.replace(csv_path)
        write_xlsx(self.output_dir / "iol_tilt_results.xlsx", headers, rows)

    def open_output_folder(self):
        if self.output_dir is None:
            QMessageBox.information(self, "还没有结果文件夹",
                                    "先打开图片；保存后会生成 IOL_Tilt_Output 文件夹。")
            return
        self.output_dir.mkdir(exist_ok=True)
        open_path(self.output_dir)

    def open_excel(self):
        if self.output_dir is None:
            QMessageBox.information(self, "还没有 Excel", "先打开图片并保存一次。")
            return
        xlsx_path = self.output_dir / "iol_tilt_results.xlsx"
        if not xlsx_path.exists():
            QMessageBox.information(self, "还没有 Excel", "先点“保存”，软件才会生成 Excel。")
            return
        open_path(xlsx_path)

    def gen_calibration(self):
        try:
            out_dir = generate_calibration_images(self.output_dir)
        except Exception as exc:
            QMessageBox.critical(self, "生成失败", str(exc))
            return
        open_path(out_dir)
        self.set_status(f"已生成校准测试图：{out_dir}")

    def show_help(self):
        QMessageBox.information(self, "快捷键与用法", HELP_TEXT)

    def show_about(self):
        QMessageBox.about(self, f"关于 {APP_NAME}",
                          f"<b>{APP_NAME}</b> {APP_VERSION}<br><br>"
                          "人工晶体（IOL）相对 A-B 参考线的二维夹角标注工具。<br>"
                          "测量口径：最终夹角 = IOL 轴角度 − A-B 角度（取锐角）。<br><br>"
                          "<span style='color:#888'>结果为二维夹角，不是三维临床 IOL tilt。</span>")

    # ---------------- 拖放 ----------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        if len(paths) == 1 and paths[0].is_dir():
            folder = paths[0]
            images = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_EXTS)
            self.start_session(images, folder)
            return
        images = sorted(p for p in paths if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS)
        if images:
            self.start_session(images, images[0].parent)
        else:
            self.set_status("拖进来的东西里没有可用图片")

    # ---------------- 刷新 ----------------
    def _refresh_all(self):
        self._refresh_steps()
        self._refresh_side()
        self._refresh_file_list_state()
        self._refresh_header()
        self._refresh_status_meta()

    def _refresh_header(self):
        path = self.current_image_path()
        if path is None:
            self.file_label.setText("未打开图片")
            self.index_label.setText("")
        else:
            self.file_label.setText(path.name)
            self.index_label.setText(f"{self.index + 1}/{len(self.images)}")
        has = bool(self.images)
        for b in (self.btn_save, self.btn_save_next, self.btn_undo):
            b.setEnabled(has)
        self.btn_prev.setEnabled(has and self.index > 0)
        self.btn_next.setEnabled(has and self.index < len(self.images) - 1)

    def _refresh_steps(self):
        label = self.current_label()
        counts = {m: len(label.get(key_of(m), [])) for m in MODES}
        ready = {
            "guide": counts["guide"] > 0,
            "pupil": counts["pupil"] == 2,
            "anterior": counts["anterior"] >= 3,
            "posterior": counts["posterior"] >= 3,
            "manual_axis": counts["manual_axis"] == 2,
        }
        text = {
            "guide": f"{counts['guide']}",
            "pupil": f"{counts['pupil']}/2",
            "anterior": f"{counts['anterior']}",
            "posterior": f"{counts['posterior']}",
            "manual_axis": f"{counts['manual_axis']}/2",
        }
        for mode, row in self.step_rows.items():
            row.set_state(mode == self.mode, ready[mode], text[mode])

    def _refresh_side(self, light: bool = False):
        label = self.current_label()
        saved = label.get("result")
        result = saved or self._preview_result(label)

        if result:
            self.result_value.setText(f"{final_angle_text(result) or 'N/A'}°")
            quality = result.get("fit_quality", "")
            tone = {"good": "ok", "fair": "warn", "poor": "danger"}.get(quality, "")
            axis = "参考轴（无自动轴）" if result.get("axis_source") == "manual_reference" else "自动轴"
            note = {"good": "拟合良好", "fair": "拟合一般，建议复核点位",
                    "poor": "拟合偏差大，建议重标", "manual": "仅参考轴"}.get(quality, "")
            state = "已保存" if saved else "未保存"
            self.result_caption.setText(f"{axis} · {note} · {state}")
            self.result_caption.setProperty("tone", tone)
            self.result_caption.style().unpolish(self.result_caption)
            self.result_caption.style().polish(self.result_caption)
            rms = [v for v in (result.get("front_fit_rms_px"), result.get("back_fit_rms_px"))
                   if v not in (None, "")]
            self._set_detail({
                "iol_angle": fmt_number(result.get("iol_angle")) + "°",
                "pupil_angle": fmt_number(result.get("pupil_angle")) + "°",
                "difference": (f"{float(result['difference']):+.3f}°"
                               if result.get("difference") not in (None, "") else "—"),
                "manual_delta": (fmt_number(result.get("manual_vs_auto_delta")) + "°"
                                 if result.get("manual_vs_auto_delta") not in (None, "") else "—"),
                "rms": (f"{max(float(v) for v in rms):.2f} px" if rms else "—"),
                "counts": f"{result.get('anterior_n', 0)} / {result.get('posterior_n', 0)}",
            })
        else:
            self.result_value.setText("—")
            self.result_caption.setText(self._next_hint(label))
            self.result_caption.setProperty("tone", "")
            self.result_caption.style().unpolish(self.result_caption)
            self.result_caption.style().polish(self.result_caption)
            self._set_detail({k: "—" for k in self.detail_labels})

        if not light:
            self._refresh_steps()
            self._refresh_file_list_state()

    def _next_hint(self, label) -> str:
        if not self.images:
            return "打开图片后开始标注"
        if len(label.get("pupil_plane", [])) != 2:
            return "下一步：在第 2 步点 A、B 两点"
        if len(label.get("anterior", [])) < 3:
            return "下一步：第 3 步前表面至少 3 点"
        if len(label.get("posterior", [])) < 3:
            return "下一步：第 4 步后表面至少 3 点"
        return "点位不足或拟合失败，检查前/后表面取点"

    def _set_detail(self, mapping: dict[str, str]):
        for key, lab in self.detail_labels.items():
            lab.setText(mapping.get(key, "—"))

    # ---------------- 键盘 ----------------
    def eventFilter(self, obj, event):
        if event.type() != QEvent.KeyPress:
            return super().eventFilter(obj, event)
        if not self.isActiveWindow():
            return super().eventFilter(obj, event)
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            return super().eventFilter(obj, event)
        if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier | Qt.AltModifier):
            return super().eventFilter(obj, event)

        key = event.key()
        step = 5.0 if event.modifiers() & Qt.ShiftModifier else 1.0
        arrows = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0),
                  Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
        if key in arrows and self.canvas.selected:
            if self.nudge_selected(*arrows[key]):
                return True
        text = event.text().lower()
        digits = {m[0]: k for k, m in MODE_META.items()}
        if text in digits:
            self.set_mode(digits[text])
            return True
        if text == "s":
            self.save_current()
            return True
        if text == "n":
            self.next_image()
            return True
        if text == "p":
            self.prev_image()
            return True
        if text == "f":
            self.canvas.fit()
            return True
        if text == "l":
            self.btn_loupe.setChecked(not self.btn_loupe.isChecked())
            self.toggle_loupe()
            return True
        if text in ("+", "="):
            self.canvas.zoom_by(1.2)
            return True
        if text == "-":
            self.canvas.zoom_by(1 / 1.2)
            return True
        return super().eventFilter(obj, event)

    def closeEvent(self, e):
        try:
            self.save_note()
        except Exception:
            pass
        super().closeEvent(e)


HELP_TEXT = f"""标注流程
1. 打开文件夹，或把图片/文件夹直接拖进窗口
2. 第 2 步点 A、B 两点（瞳孔平面），点满自动进入第 3 步
3. 第 3/4 步在晶体前、后表面各点 3 个以上，自动拟合出 IOL 轴
4. 第 5 步可选：点 2 个参考点，只用来校验自动轴
5. 保存并下一张，结果自动写入 Excel

鼠标
左键：取点 · 拖动已有点：微调 · {OPT}点击：删除该点
右键 / 中键拖动：平移 · 滚轮：缩放 · 双击空白：适配窗口

键盘
1–5 切换步骤 · S 保存 · P / N 上下一张 · F 适配 · L 放大镜
方向键微调选中点（{SHIFT}加速）· Delete 删除选中点
{CMD}Z 撤销 · {SHIFT}{CMD}Z 重做 · {CMD}S 保存 · {CMD}{ENTER} 保存并下一张
{CMD}0 适配 · {CMD}1 实际像素 · {CMD}L 放大镜 · {CMD}K 准星 · {CMD}E 打开 Excel

结果
最终夹角 = IOL 轴角度 − A-B 角度（取锐角），自动轴优先。
Excel 只导四列：IOL轴角度 / A-B角度 / 最终夹角 / 备注。"""


def _demo_points(win: MainWindow) -> None:
    """调试用：给当前图注入一组示例点位，方便离线看界面效果。"""
    if not win.images:
        return
    w, h = win.original_image.size
    label = win.current_label()

    def curve(x, base):
        return base + 0.00055 * (x - w / 2) ** 2

    xs = [w * 0.36, w * 0.44, w * 0.56, w * 0.64]
    label["pupil_plane"] = [[round(w * 0.16, 3), round(h * 0.512, 3)],
                            [round(w * 0.84, 3), round(h * 0.500, 3)]]
    label["anterior"] = [[round(x, 3), round(curve(x, h * 0.434), 3)] for x in xs]
    label["posterior"] = [[round(x, 3), round(curve(x, h * 0.513), 3)] for x in xs]
    label["note"] = "示例数据"
    win.set_mode("posterior")
    win.canvas.update()
    win._refresh_all()


def main():
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName("")
    QApplication.setOrganizationName("xiao")
    app = QApplication(sys.argv)
    icon_path = resource_path("windows", "IOLTiltLabeler.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    argv = [a for a in sys.argv[1:]]
    shot_path = None
    if "--shot" in argv:
        i = argv.index("--shot")
        shot_path = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
    demo = "--demo" in argv
    argv = [a for a in argv if not a.startswith("--")]

    win = MainWindow()
    win.show()
    if argv:
        target = Path(argv[0]).expanduser()
        if target.is_dir():
            images = sorted(p for p in target.iterdir() if p.suffix.lower() in SUPPORTED_EXTS)
            win.start_session(images, target)
        elif target.is_file() and target.suffix.lower() in SUPPORTED_EXTS:
            win.start_session([target], target.parent)
    if demo:
        _demo_points(win)
    if shot_path:
        def grab_and_quit():
            win.grab().save(shot_path)
            app.quit()
        QTimer.singleShot(900, grab_and_quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
