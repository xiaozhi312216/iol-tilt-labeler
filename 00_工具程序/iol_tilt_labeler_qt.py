#!/usr/bin/env python3
"""IOL Tilt Labeler — PySide6 版本。

界面按苹果风设计稿重写；测量算法与数据层完全复用 iol_core（与旧 Tkinter 版一致）。
两栏布局：左=全部操作区（结果面板/开始/工作流/保存/备注/明细/视图/图例/编辑），右=影像画布。
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QColor, QFont, QImage, QPainter, QPen, QBrush, QPixmap,
    QLinearGradient, QPainterPath, QFontMetrics, QIcon, QKeySequence, QAction,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QFrame,
    QHBoxLayout, QVBoxLayout, QGridLayout, QScrollArea, QLineEdit,
    QPlainTextEdit, QFileDialog, QMessageBox, QSizePolicy,
)

from platform_utils import open_path, resource_path, ui_font_families

import iol_core as core
from iol_core import (
    SUPPORTED_EXTS, MODE_META, as_points, default_label, fmt_number,
    fmt_point, final_angle_text, atomic_write_text, unique_suffix,
    compute_result, save_annotated_image, row_for_image, write_xlsx,
    generate_calibration_images,
)

Point = tuple[float, float]

# ---- palette (design tokens) ----
C = {
    "bg": "#ffffff",
    "surface": "#ffffff",
    "surface2": "#fbfcfe",
    "surface3": "#f5f7fb",
    "topbar": "#f2f4f7",
    "topbar_line": "#dcdfe5",
    "canvas": "#070a12",
    "text": "#1d1d1f",
    "text2": "#5f6673",
    "text3": "#8a91a0",
    "line": "#e3e8f0",
    "line2": "#eef2f7",
    "primary": "#155bd0",
    "primary_hover": "#0f49aa",
    "primary_soft": "#eef5ff",
    "accent1": "#6e56cf",
    "accent2": "#0a84ff",
    "success": "#167a3c",
    "success_soft": "#f7fbf8",
    "success_line": "#dcece1",
    "danger": "#c9152b",
    "danger_soft": "#fff0f3",
    "dark": "#0f1a2e",
    "dark2": "#16233d",
}

# annotation colors (RGB tuples for overlay pens)
ANN = {
    "guide": "#ff9500",
    "pupil": "#00b8d9",
    "anterior": "#f5c400",
    "posterior": "#ff8a3d",
    "iol": "#28c46a",
    "manual": "#a35cf0",
    "intersection": "#ff2828",
}

FONT_FAMILY, MONO_FAMILY = ui_font_families()


def label_key_for_mode(mode: str) -> str:
    return {"pupil": "pupil_plane", "manual_axis": "manual_iol_axis"}.get(mode, mode)


# ============================================================
#  Image canvas
# ============================================================
class ImageCanvas(QWidget):
    pointClicked = Signal(float, float)      # image coords
    cursorMoved = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 360)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.image: QImage | None = None
        self.img_w = 0
        self.img_h = 0
        self.scale = 1.0
        self.offset = QPointF(0, 0)
        self._panning = False
        self._pan_start = QPoint()
        self._offset_start = QPointF()
        self.overlay_getter = None   # callable -> label dict
        self.result_getter = None    # callable -> result/preview dict or None

    # ---- image management ----
    def set_image(self, pil_image):
        if pil_image is None:
            self.image = None
            self.update()
            return
        rgb = pil_image.convert("RGB")
        data = rgb.tobytes("raw", "RGB")
        self.img_w, self.img_h = rgb.size
        self.image = QImage(data, self.img_w, self.img_h, self.img_w * 3, QImage.Format_RGB888).copy()
        self.update()

    def fit(self):
        if not self.image:
            return
        cw = max(200, self.width() - 24)
        ch = max(200, self.height() - 24)
        self.scale = max(0.15, min(cw / self.img_w, ch / self.img_h, 1.3))
        self._center()
        self.update()

    def _center(self):
        vis_w = self.img_w * self.scale
        vis_h = self.img_h * self.scale
        self.offset = QPointF((self.width() - vis_w) / 2, (self.height() - vis_h) / 2)

    def set_zoom(self, new_scale, center=None):
        if not self.image:
            return
        new_scale = max(0.15, min(6.0, new_scale))
        if center is None:
            center = QPointF(self.width() / 2, self.height() / 2)
        img_pt = self.widget_to_image(center)
        self.scale = new_scale
        # keep img_pt under the same screen point
        self.offset = QPointF(center.x() - img_pt[0] * self.scale,
                              center.y() - img_pt[1] * self.scale)
        self.update()

    # ---- coordinate transforms ----
    def image_to_widget(self, x, y) -> QPointF:
        return QPointF(x * self.scale + self.offset.x(), y * self.scale + self.offset.y())

    def widget_to_image(self, pt: QPointF):
        return ((pt.x() - self.offset.x()) / self.scale,
                (pt.y() - self.offset.y()) / self.scale)

    # ---- events ----
    def mousePressEvent(self, e):
        if not self.image:
            return
        if e.button() == Qt.LeftButton:
            x, y = self.widget_to_image(QPointF(e.position()))
            if 0 <= x < self.img_w and 0 <= y < self.img_h:
                self.pointClicked.emit(x, y)
        elif e.button() in (Qt.RightButton, Qt.MiddleButton):
            self._panning = True
            self._pan_start = e.position().toPoint()
            self._offset_start = QPointF(self.offset)
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if not self.image:
            return
        if self._panning:
            delta = e.position().toPoint() - self._pan_start
            self.offset = QPointF(self._offset_start.x() + delta.x(),
                                  self._offset_start.y() + delta.y())
            self.update()
        else:
            x, y = self.widget_to_image(QPointF(e.position()))
            self.cursorMoved.emit(x, y)

    def mouseReleaseEvent(self, e):
        if e.button() in (Qt.RightButton, Qt.MiddleButton):
            self._panning = False
            self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, e):
        if not self.image:
            return
        factor = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
        self.set_zoom(self.scale * factor, QPointF(e.position()))

    # ---- painting ----
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C["canvas"]))
        if not self.image:
            p.setPen(QColor(C["text3"]))
            f = QFont(FONT_FAMILY, 13)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, "打开图片文件夹开始标注\n左键取点 · 右键/中键平移 · 滚轮缩放")
            return
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.Antialiasing, True)
        target = QRectF(self.offset.x(), self.offset.y(),
                        self.img_w * self.scale, self.img_h * self.scale)
        p.drawImage(target, self.image)
        self._draw_overlays(p)

    def _pen(self, key, width=2.0):
        pen = QPen(QColor(ANN[key]))
        pen.setWidthF(width)
        pen.setCosmetic(True)
        return pen

    def _draw_marker(self, p, x, y, key, radius=5, text=None):
        w = self.image_to_widget(x, y)
        p.setPen(self._pen(key, 2.2))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(w, radius, radius)
        if text:
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor(ANN[key]))
            f = QFont(FONT_FAMILY, 10, QFont.Bold)
            p.setFont(f)
            p.drawText(QPointF(w.x() + 8, w.y() - 6), text)

    def _draw_polyline(self, p, pts, key, width=2.0):
        if len(pts) < 2:
            return
        p.setPen(self._pen(key, width))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        first = self.image_to_widget(*pts[0])
        path.moveTo(first)
        for pt in pts[1:]:
            path.lineTo(self.image_to_widget(*pt))
        p.drawPath(path)

    def _draw_overlays(self, p):
        if not self.overlay_getter:
            return
        label = self.overlay_getter()
        guide = as_points(label.get("guide", []))
        pupil = as_points(label.get("pupil_plane", []))
        anterior = as_points(label.get("anterior", []))
        posterior = as_points(label.get("posterior", []))
        manual = as_points(label.get("manual_iol_axis", []))

        self._draw_polyline(p, guide, "guide", 2)
        for i, pt in enumerate(guide):
            if i in (0, len(guide) - 1):
                self._draw_marker(p, pt[0], pt[1], "guide", 4, "C/D" if i == 0 else None)

        if len(pupil) == 2:
            self._draw_polyline(p, pupil, "pupil", 2.4)
        for i, pt in enumerate(pupil):
            self._draw_marker(p, pt[0], pt[1], "pupil", 5, "A" if i == 0 else "B")

        for i, pt in enumerate(anterior):
            self._draw_marker(p, pt[0], pt[1], "anterior", 4, f"F{i+1}")
        for i, pt in enumerate(posterior):
            self._draw_marker(p, pt[0], pt[1], "posterior", 4, f"B{i+1}")

        if len(manual) == 2:
            self._draw_polyline(p, manual, "manual", 3)
        for i, pt in enumerate(manual):
            self._draw_marker(p, pt[0], pt[1], "manual", 5, "M1" if i == 0 else "M2")

        # auto fit arcs + axis
        try:
            if len(anterior) >= 3 and len(posterior) >= 3:
                front = core.fit_circle(anterior)
                back = core.fit_circle(posterior)
                iol_l, iol_r = core.circle_intersections(front, back)
                y_front = sum(q[1] for q in anterior) / len(anterior)
                y_back = sum(q[1] for q in posterior) / len(posterior)
                x_min = min(q[0] for q in anterior + posterior + [iol_l, iol_r]) - 40
                x_max = max(q[0] for q in anterior + posterior + [iol_l, iol_r]) + 40
                fa = core.arc_points(front, x_min, x_max, y_front, y_front - 60, y_front + 60)
                ba = core.arc_points(back, x_min, x_max, y_back, y_back - 60, y_back + 60)
                self._draw_polyline(p, fa, "anterior", 2)
                self._draw_polyline(p, ba, "posterior", 2)
                self._draw_polyline(p, [iol_l, iol_r], "iol", 2.4)
                self._draw_marker(p, iol_l[0], iol_l[1], "intersection", 5)
                self._draw_marker(p, iol_r[0], iol_r[1], "intersection", 5)
        except Exception:
            pass


# ============================================================
#  Small UI helpers
# ============================================================
def card(title: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(10)
    if title:
        t = QLabel(title)
        t.setObjectName("CardTitle")
        lay.addWidget(t)
    return frame, lay


def divider(text: str) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(2, 2, 2, 0)
    h.setSpacing(10)
    def line():
        ln = QFrame()
        ln.setFrameShape(QFrame.HLine)
        ln.setObjectName("Divider")
        ln.setFixedHeight(1)
        return ln
    lbl = QLabel(text)
    lbl.setObjectName("DividerLabel")
    h.addWidget(line(), 1)
    h.addWidget(lbl, 0)
    h.addWidget(line(), 1)
    return w


class CollapseSection(QFrame):
    def __init__(self, title: str, expanded: bool = True):
        super().__init__()
        self.setObjectName("CollapseSection")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QPushButton()
        self.header.setObjectName("CollapseHeader")
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.toggled.connect(self.set_expanded)
        outer.addWidget(self.header)

        self.body = QWidget()
        self.body.setObjectName("CollapseBody")
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 10, 0, 0)
        self.body_lay.setSpacing(12)
        outer.addWidget(self.body)

        self.title = title
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool):
        self.body.setVisible(expanded)
        self.header.setText(("⌄  " if expanded else "›  ") + self.title)
        self.header.setProperty("expanded", "true" if expanded else "false")
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)

    def addWidget(self, widget: QWidget):
        self.body_lay.addWidget(widget)


class StepRow(QFrame):
    clicked = Signal(str)

    def __init__(self, mode: str):
        super().__init__()
        self.mode = mode
        self.setObjectName("Step")
        number, name, hint = MODE_META[mode]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(9)
        self.badge = QLabel(number)
        self.badge.setObjectName("StepBadge")
        self.badge.setFixedSize(22, 22)
        self.badge.setAlignment(Qt.AlignCenter)
        self.name = QLabel(name)
        self.name.setObjectName("StepName")
        self.count = QLabel("0")
        self.count.setObjectName("StepCount")
        top.addWidget(self.badge)
        top.addWidget(self.name, 1)
        top.addWidget(self.count)
        self.hint = QLabel(hint)
        self.hint.setObjectName("StepHint")
        outer.addLayout(top)
        outer.addWidget(self.hint)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        self.clicked.emit(self.mode)

    def set_state(self, is_active: bool, is_ready: bool, count_text: str, hint_text: str):
        self.count.setText(count_text)
        self.hint.setText(hint_text)
        state = "active" if is_active else ("ready" if is_ready else "idle")
        self.setProperty("state", state)
        self.badge.setProperty("state", state)
        self.count.setProperty("state", state)
        self.hint.setProperty("state", state)
        for w in (self, self.badge, self.count, self.hint):
            w.style().unpolish(w)
            w.style().polish(w)


# ============================================================
#  Main window
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IOL Tilt Labeler")
        self.resize(1500, 940)

        # state
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

        self._build_ui()
        self._install_shortcuts()
        self._apply_style()
        self._refresh_all()

    # ---------- data helpers (mirror old logic) ----------
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
        atomic_write_text(self.labels_path, json.dumps(self.labels, ensure_ascii=False, indent=2), encoding="utf-8")

    def export_tables_if_exists(self):
        if self.output_dir is None:
            return
        if (self.output_dir / "iol_tilt_results.csv").exists() or (self.output_dir / "iol_tilt_results.xlsx").exists():
            self.export_tables()

    def invalidate_result(self, reason: str):
        self.current_label()["result"] = None
        self.save_labels_json()
        try:
            self.export_tables_if_exists()
        except Exception as exc:
            self.set_status(f"{reason}；但刷新表格失败：{exc}")
            return
        self.set_status(reason)

    # ---------- UI construction ----------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        body = QWidget()
        body_l = QHBoxLayout(body)
        body_l.setContentsMargins(16, 16, 16, 16)
        body_l.setSpacing(16)
        body_l.addWidget(self._build_left(), 0)
        body_l.addWidget(self._build_canvas_panel(), 1)
        root.addWidget(body, 1)

    def _install_shortcuts(self):
        undo_action = QAction(self)
        undo_action.setShortcut(QKeySequence.Undo)
        undo_action.triggered.connect(self.undo_shortcut)
        self.addAction(undo_action)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(22, 14, 24, 10)
        h.setSpacing(14)

        mark = QLabel()
        mark.setFixedSize(38, 38)
        mark.setObjectName("BrandMark")
        mark.setPixmap(self._brand_pixmap())

        h.addWidget(mark)

        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusText")
        self.status_label.hide()

        h.addStretch(1)

        self.btn_excel = QPushButton("打开 Excel")
        self.btn_finder = QPushButton("在 Finder 中显示")
        self.btn_savenext_top = QPushButton("保存并下一张")
        for b in (self.btn_excel, self.btn_finder):
            b.setObjectName("Secondary")
        self.btn_savenext_top.setObjectName("Primary")
        self.btn_excel.clicked.connect(self.open_excel)
        self.btn_finder.clicked.connect(self.open_output_folder)
        self.btn_savenext_top.clicked.connect(self.save_and_next)
        buttons_box = QVBoxLayout()
        buttons_box.setContentsMargins(0, 0, 0, 0)
        buttons_box.addStretch(1)
        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(14)
        buttons_row.addWidget(self.btn_excel)
        buttons_row.addWidget(self.btn_finder)
        buttons_row.addWidget(self.btn_savenext_top)
        buttons_box.addLayout(buttons_row)
        h.addLayout(buttons_box)
        return bar

    def _brand_pixmap(self) -> QPixmap:
        pm = QPixmap(38, 38)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        grad = QLinearGradient(0, 0, 38, 38)
        grad.setColorAt(0, QColor(C["accent1"]))
        grad.setColorAt(1, QColor(C["accent2"]))
        path = QPainterPath()
        path.addRoundedRect(0, 0, 38, 38, 11, 11)
        p.fillPath(path, QBrush(grad))
        p.setPen(QPen(QColor(255, 255, 255, 72), 1.1))
        p.drawEllipse(8, 8, 22, 22)
        p.drawEllipse(13, 13, 12, 12)
        p.drawLine(7, 19, 31, 19)
        p.drawLine(19, 7, 19, 31)
        p.setPen(QColor(255, 255, 255))
        f = QFont(FONT_FAMILY, 10)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, "LOL")
        p.end()
        return pm

    def _build_left(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("LeftScroll")
        scroll.setFixedWidth(446)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(2, 0, 8, 0)
        col.setSpacing(12)

        col.addWidget(self._build_result_card())

        start = CollapseSection("开始 / 导航", expanded=True)
        start.addWidget(self._build_start_card())
        col.addWidget(start)

        workflow = CollapseSection("标注工作流", expanded=True)
        workflow.addWidget(self._build_workflow_card())
        col.addWidget(workflow)

        save = CollapseSection("保存 / 备注 / 明细", expanded=False)
        save.addWidget(self._build_save_card())
        save.addWidget(self._build_note_card())
        save.addWidget(self._build_detail_card())
        col.addWidget(save)

        tools = CollapseSection("视图 / 图例 / 编辑", expanded=False)
        tools.addWidget(self._build_view_card())
        tools.addWidget(self._build_legend_card())
        tools.addWidget(self._build_edit_card())
        col.addWidget(tools)

        foot = QLabel("快捷键：⌘Z 撤销 · S 保存 · P/N 切图 · 5 自动轴校验")
        foot.setObjectName("Footnote")
        foot.setAlignment(Qt.AlignCenter)
        col.addWidget(foot)
        col.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _build_result_card(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("ResultCard")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        pad = QVBoxLayout()
        pad.setContentsMargins(18, 16, 18, 16)
        pad.setSpacing(4)
        lab = QLabel("FINAL TILT 最终倾斜角")
        lab.setObjectName("ResultLabel")
        self.result_value = QLabel("--")
        self.result_value.setObjectName("ResultValue")
        self.result_caption = QLabel("点完 A/B、前/后表面，生成自动轴后计算差值")
        self.result_caption.setObjectName("ResultCaption")
        self.result_caption.setWordWrap(True)
        pad.addWidget(lab)
        pad.addWidget(self.result_value)
        pad.addWidget(self.result_caption)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chip_dir = QLabel("方向 --")
        self.chip_quality = QLabel("质量 --")
        self.chip_axis = QLabel("轴 --")
        self.chip_dir.setObjectName("ChipBlue")
        self.chip_quality.setObjectName("ChipGreen")
        self.chip_axis.setObjectName("ChipPurple")
        for c in (self.chip_dir, self.chip_quality, self.chip_axis):
            chips.addWidget(c)
        chips.addStretch(1)
        pad.addLayout(chips)
        lay.addLayout(pad)
        return frame

    def _mk_btn(self, text, kind="Secondary", slot=None):
        b = QPushButton(text)
        b.setObjectName(kind)
        b.setCursor(Qt.PointingHandCursor)
        if slot:
            b.clicked.connect(slot)
        return b

    def _build_start_card(self) -> QWidget:
        frame, lay = card("开始工作")
        r1 = QHBoxLayout(); r1.setSpacing(8)
        r1.addWidget(self._mk_btn("选择文件夹", "Primary", self.open_folder), 3)
        r1.addWidget(self._mk_btn("打开图片", "Secondary", self.open_files), 2)
        r2 = QHBoxLayout(); r2.setSpacing(8)
        r2.addWidget(self._mk_btn("← 上一张 P", "Secondary", self.prev_image))
        r2.addWidget(self._mk_btn("下一张 N →", "Secondary", self.next_image))
        lay.addLayout(r1)
        lay.addLayout(r2)
        return frame

    def _build_workflow_card(self) -> QWidget:
        frame, lay = card("标注工作流")
        desc = QLabel("按 1–5 切换步骤。先完成 A-B，再标前/后表面生成自动轴；第 5 步可点 2 个参考点校验自动轴。")
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        for mode in ("guide", "pupil", "anterior", "posterior", "manual_axis"):
            row = StepRow(mode)
            row.clicked.connect(self.set_mode)
            self.step_rows[mode] = row
            lay.addWidget(row)
        return frame

    def _build_save_card(self) -> QWidget:
        frame, lay = card("保存")
        r = QHBoxLayout(); r.setSpacing(8)
        r.addWidget(self._mk_btn("保存当前 S", "Secondary", self.save_current))
        r.addWidget(self._mk_btn("保存并下一张", "Primary", self.save_and_next))
        lay.addLayout(r)
        return frame

    def _build_note_card(self) -> QWidget:
        frame, lay = card("病例备注")
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("可填写病例编号、术眼、备注…")
        self.note_edit.setObjectName("Note")
        self.note_edit.editingFinished.connect(self.save_note)
        lay.addWidget(self.note_edit)
        hint = QLabel("切图时会自动保存备注。")
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        return frame

    def _build_detail_card(self) -> QWidget:
        frame, lay = card("点位与计算明细")
        self.detail_grid = QGridLayout()
        self.detail_grid.setHorizontalSpacing(12)
        self.detail_grid.setVerticalSpacing(2)
        self.detail_labels: dict[str, QLabel] = {}
        specs = [
            ("iol_angle", "当前 IOL 角度"), ("auto_iol_angle", "自动轴角度"), ("pupil_angle", "A-B 角度"),
            ("difference", "有符号差"), ("final_angle", "最终差值"), ("axis", "当前轴来源"),
            ("front_rms", "前表面 RMS"), ("back_rms", "后表面 RMS"), ("manual_delta", "自动轴校验差"),
            ("counts", "前/后点数"),
        ]
        for i, (key, name) in enumerate(specs):
            r, cpos = divmod(i, 3)
            box = QVBoxLayout(); box.setSpacing(0)
            k = QLabel(name); k.setObjectName("DetailKey")
            v = QLabel("--"); v.setObjectName("DetailVal")
            self.detail_labels[key] = v
            box.addWidget(k); box.addWidget(v)
            wrap = QWidget(); wrap.setLayout(box)
            self.detail_grid.addWidget(wrap, r, cpos)
        lay.addLayout(self.detail_grid)

        self.points_box = QPlainTextEdit()
        self.points_box.setReadOnly(True)
        self.points_box.setObjectName("PointsBox")
        self.points_box.setFixedHeight(150)
        lay.addWidget(self.points_box)
        return frame

    def _build_view_card(self) -> QWidget:
        frame, lay = card("视图缩放")
        seg = QFrame()
        seg.setObjectName("Segmented")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(4, 4, 4, 4)
        sl.setSpacing(4)
        for text, slot in [("缩小", lambda: self.zoom_step(1/1.2)),
                            ("适配", self.fit_zoom),
                            ("放大", lambda: self.zoom_step(1.2))]:
            b = QPushButton(text)
            b.setObjectName("SegBtn")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            sl.addWidget(b)
        lay.addWidget(seg)
        return frame

    def _build_legend_card(self) -> QWidget:
        frame, lay = card("颜色图例")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(9)
        items = [
            ("pupil", "A-B 瞳孔平面"), ("iol", "自动 IOL 轴"),
            ("anterior", "晶体前表面"), ("manual", "自动轴校验"),
            ("posterior", "晶体后表面"),
        ]
        for i, (key, name) in enumerate(items):
            r, cpos = divmod(i, 2)
            row = QHBoxLayout(); row.setSpacing(9)
            dot = QLabel(); dot.setFixedSize(11, 11)
            dot.setStyleSheet(f"background:{ANN[key]};border-radius:5px;")
            txt = QLabel(name); txt.setObjectName("LegendText")
            row.addWidget(dot); row.addWidget(txt, 1)
            wrap = QWidget(); wrap.setLayout(row)
            grid.addWidget(wrap, r, cpos)
        lay.addLayout(grid)
        return frame

    def _build_edit_card(self) -> QWidget:
        frame, lay = card("编辑")
        r = QHBoxLayout(); r.setSpacing(8)
        r.addWidget(self._mk_btn("撤销 U", "Secondary", self.undo))
        r.addWidget(self._mk_btn("清空当前", "Secondary", self.clear_current_mode))
        lay.addLayout(r)
        lay.addWidget(self._mk_btn("清空本图全部点位…", "Danger", self.clear_all_points))
        return frame

    def _build_canvas_panel(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("CanvasCard")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QWidget()
        head.setObjectName("CanvasHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 12, 16, 12)
        title = QLabel("影像标注")
        title.setObjectName("CanvasTitle")
        info = QLabel("左键取点 · 右键/中键平移 · 滚轮缩放")
        info.setObjectName("CanvasInfo")
        self.cursor_label = QLabel("")
        self.cursor_label.setObjectName("CursorLabel")
        hl.addWidget(title)
        hl.addWidget(info)
        hl.addStretch(1)
        hl.addWidget(self.cursor_label)
        lay.addWidget(head)

        self.canvas = ImageCanvas()
        self.canvas.overlay_getter = self.current_label
        self.canvas.pointClicked.connect(self.on_canvas_click)
        self.canvas.cursorMoved.connect(self.on_cursor_move)
        lay.addWidget(self.canvas, 1)
        return frame

    # ---------- interactions ----------
    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_mode(self, mode: str):
        self.mode = mode
        self._refresh_steps()

    def on_cursor_move(self, x, y):
        self.cursor_label.setText(f"x={x:.1f}, y={y:.1f} · zoom {self.canvas.scale:.2f}×")

    def on_canvas_click(self, x, y):
        label = self.current_label()
        mode = self.mode
        if mode == "pupil" and len(label["pupil_plane"]) >= 2:
            self.set_status("A-B 已有 2 个点；如需重取，先点“清空当前”")
            return
        if mode == "anterior" and len(label["anterior"]) >= 8:
            self.set_status("前表面最多先放 8 个点；推荐 4 个")
            return
        if mode == "posterior" and len(label["posterior"]) >= 12:
            self.set_status("后表面点过多；建议 4-8 个")
            return
        if mode == "manual_axis" and len(label.get("manual_iol_axis", [])) >= 2:
            self.set_status("自动轴校验点已有 2 个；如需重取，先点“清空当前”")
            return
        key = label_key_for_mode(mode)
        label.setdefault(key, [])
        label[key].append([round(x, 3), round(y, 3)])
        self.invalidate_result("点位已修改，当前结果需重新保存")
        self.canvas.update()
        self._refresh_side()

    def undo_shortcut(self):
        if isinstance(self.focusWidget(), (QLineEdit, QPlainTextEdit)):
            return
        self.undo()

    def undo(self):
        label = self.current_label()
        key = label_key_for_mode(self.mode)
        if label.get(key):
            removed = label[key].pop()
            self.invalidate_result(f"已撤销 {self.mode} 点 {fmt_point(tuple(removed))}")
            self.canvas.update()
            self._refresh_side()
        else:
            self.set_status(f"当前模式 {self.mode} 没有可撤销点")

    def clear_current_mode(self):
        label = self.current_label()
        key = label_key_for_mode(self.mode)
        if QMessageBox.question(self, "确认", f"清空当前模式 {self.mode} 的点？") == QMessageBox.Yes:
            label[key] = []
            self.invalidate_result(f"已清空 {self.mode} 点位")
            self.canvas.update()
            self._refresh_side()

    def clear_all_points(self):
        if not self.images:
            return
        if QMessageBox.question(self, "确认", "清空本图所有点位和结果？") != QMessageBox.Yes:
            return
        path = self.current_image_path()
        self.labels[self.image_key(path)] = default_label()
        self.note_edit.setText("")
        self.save_labels_json()
        try:
            self.export_tables_if_exists()
        except Exception as exc:
            self.set_status(f"已清空；刷新表格失败：{exc}")
        else:
            self.set_status("已清空本图全部点位，需重新保存")
        self.canvas.update()
        self._refresh_side()

    def save_note(self):
        if not self.images:
            return
        self.current_label()["note"] = self.note_edit.text()
        self.save_labels_json()

    # ---------- folder / images ----------
    def open_folder(self):
        selected = QFileDialog.getExistingDirectory(self, "选择包含 OCT 图片的文件夹")
        if not selected:
            return
        self.folder = Path(selected)
        images = sorted(p for p in self.folder.iterdir() if p.suffix.lower() in SUPPORTED_EXTS)
        self.start_session(images, self.folder)

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择一张或多张 OCT 图片", "",
            "图片文件 (*.jpg *.jpeg *.png *.tif *.tiff *.bmp);;所有文件 (*.*)")
        if not files:
            return
        images = sorted(Path(p) for p in files if Path(p).suffix.lower() in SUPPORTED_EXTS)
        if not images:
            QMessageBox.warning(self, "没有图片", "没有选中 jpg/png/tif/bmp 图片")
            return
        self.folder = images[0].parent
        self.start_session(images, self.folder)

    def start_session(self, images: list[Path], output_base: Path):
        self.images = images
        if not self.images:
            QMessageBox.warning(self, "没有图片", "这里没有 jpg/png/tif/bmp 图片")
            self.set_status("没有找到图片，未创建输出目录")
            return
        self.build_image_keys()
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
        self.canvas.set_image(self.original_image)
        self.note_edit.setText(str(self.current_label().get("note", "")))
        if fit:
            self.canvas.fit()
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

    def fit_zoom(self):
        self.canvas.fit()
        self._refresh_progress()

    def zoom_step(self, factor):
        self.canvas.set_zoom(self.canvas.scale * factor)
        self._refresh_progress()

    # ---------- compute / save ----------
    def save_current(self) -> bool:
        if self.original_image is None or self.output_dir is None:
            return False
        path = self.current_image_path()
        if path is None:
            return False
        try:
            result = compute_result(self.current_label())
            label = self.current_label()
            result["annotated_file"] = ""
            annotated = save_annotated_image(self.output_dir, self.output_stem(path), path, label, result)
            result["annotated_file"] = str(annotated)
            label["result"] = result
            label["note"] = self.note_edit.text()
            self.save_labels_json()
            self.export_tables()
            self.set_status(f"已保存：{path.name}")
            self.canvas.update()
            self._refresh_side()
            return True
        except Exception as exc:
            QMessageBox.critical(self, "计算/保存失败", str(exc))
            self.set_status(f"失败：{exc}")
            return False

    def save_and_next(self):
        if self.save_current():
            if self.index >= len(self.images) - 1:
                self.set_status("已保存最后一张，全部完成")
                QMessageBox.information(self, "完成", "已经保存最后一张。所有图片处理完成。")
                return
            self.next_image()

    def export_tables(self):
        if self.output_dir is None:
            return
        rows = []
        headers = ["IOL轴角度", "A-B角度", "最终夹角", "备注"]
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
        xlsx_path = self.output_dir / "iol_tilt_results.xlsx"
        import csv as _csv
        tmp_csv = csv_path.with_name(f".{csv_path.stem}.tmp{csv_path.suffix}")
        with tmp_csv.open("w", newline="", encoding="utf-8-sig") as f:
            writer = _csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        tmp_csv.replace(csv_path)
        write_xlsx(xlsx_path, headers, rows)

    def open_output_folder(self):
        if self.output_dir is None:
            QMessageBox.information(self, "还没有结果文件夹", "先打开图片文件夹/图片；保存后会生成 IOL_Tilt_Output。")
            return
        self.output_dir.mkdir(exist_ok=True)
        open_path(self.output_dir)

    def open_excel(self):
        if self.output_dir is None:
            QMessageBox.information(self, "还没有 Excel", "先打开图片并点“保存当前”或“保存并下一张”。")
            return
        xlsx_path = self.output_dir / "iol_tilt_results.xlsx"
        if not xlsx_path.exists():
            QMessageBox.information(self, "还没有 Excel", "先点“保存当前”或“保存并下一张”，软件才会生成 Excel。")
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
        QMessageBox.information(self, "已生成",
                                f"校准测试图已放到：\n{out_dir}\n\n先完成前/后表面生成自动轴；第 5 步可用紫色校验轴对照，结果应接近 00_标准答案.csv。")

    # ---------- refresh ----------
    def _refresh_all(self):
        self._refresh_steps()
        self._refresh_side()
        self._refresh_progress()

    def _refresh_progress(self):
        if self.images:
            path = self.current_image_path()
            self.set_status(f"{self.index + 1}/{len(self.images)} · {path.name if path else ''}")

    def _refresh_steps(self):
        label = self.current_label()
        counts = {
            "guide": len(label.get("guide", [])),
            "pupil": len(label.get("pupil_plane", [])),
            "anterior": len(label.get("anterior", [])),
            "posterior": len(label.get("posterior", [])),
            "manual_axis": len(label.get("manual_iol_axis", [])),
        }
        ready = {
            "guide": counts["guide"] > 0,
            "pupil": counts["pupil"] == 2,
            "anterior": counts["anterior"] >= 3,
            "posterior": counts["posterior"] >= 3,
            "manual_axis": counts["manual_axis"] == 2,
        }
        count_text = {
            "guide": f"{counts['guide']} 点",
            "pupil": f"{counts['pupil']}/2",
            "anterior": f"{counts['anterior']} 点",
            "posterior": f"{counts['posterior']} 点",
            "manual_axis": f"{counts['manual_axis']}/2",
        }
        for mode, row in self.step_rows.items():
            is_active = (mode == self.mode)
            is_ready = ready[mode]
            if is_active:
                hint = "当前步骤 · 点击影像取点"
            elif is_ready:
                hint = "已就绪"
            elif mode == "guide":
                hint = "可选 · 多点参考"
            else:
                hint = MODE_META[mode][2]
            row.set_state(is_active, is_ready, count_text[mode], hint)

    def _refresh_side(self):
        label = self.current_label()
        # points text
        lines = []
        for key, title in [("guide", "C-D"), ("pupil_plane", "A-B"),
                           ("anterior", "前表面"), ("posterior", "后表面"),
                           ("manual_iol_axis", "校验轴")]:
            pts = as_points(label.get(key, []))
            if not pts:
                continue
            lines.append(f"{title} 坐标：")
            for i, p in enumerate(pts, 1):
                lines.append(f"  {i}. {fmt_point(p)}")
        self.points_box.setPlainText("\n".join(lines) if lines else "还没有取点")

        result = label.get("result")
        if not result:
            try:
                result = compute_result(label)
                preview = True
            except Exception:
                result = None
                preview = False
        else:
            preview = False

        if result:
            val = final_angle_text(result) or "N/A"
            suffix = "" if str(val).endswith("°") else "°"
            self.result_value.setText(f"{val}{suffix}")
            note = result.get("fit_quality_note", "")
            prefix = "预览未保存。" if preview else "已保存。"
            self.result_caption.setText(f"{prefix}{note}")
            self.chip_dir.setText(f"方向 {fmt_number(result.get('difference'))}°")
            self.chip_quality.setText(f"质量 {str(result.get('fit_quality','--')).upper()}")
            self.chip_axis.setText("参考轴" if result.get("axis_source") == "manual_reference" else "自动轴")
            self._set_detail(result)
        else:
            self.result_value.setText("待测")
            self.result_caption.setText("按步骤取点后自动预览，保存后写入结果")
            self.chip_dir.setText("方向 待定")
            self.chip_quality.setText("质量 待定")
            self.chip_axis.setText("轴 待定")
            for v in self.detail_labels.values():
                v.setText("—")
                v.setProperty("tone", "")
                v.style().unpolish(v); v.style().polish(v)

    def _set_detail(self, r: dict):
        def q(v): return fmt_number(v)
        mapping = {
            "iol_angle": q(r.get("iol_angle")) + "°",
            "auto_iol_angle": (q(r.get("auto_iol_angle")) + "°") if r.get("auto_iol_angle") not in (None, "") else "—",
            "pupil_angle": q(r.get("pupil_angle")) + "°",
            "difference": q(r.get("difference")) + "°",
            "final_angle": (final_angle_text(r) or "N/A") + "°",
            "front_rms": (q(r.get("front_fit_rms_px")) + " px") if r.get("front_fit_rms_px") not in (None, "") else "—",
            "back_rms": (q(r.get("back_fit_rms_px")) + " px") if r.get("back_fit_rms_px") not in (None, "") else "—",
            "manual_delta": (q(r.get("manual_vs_auto_delta")) + "°") if r.get("manual_vs_auto_delta") not in (None, "") else "—",
            "axis": "参考轴" if r.get("axis_source") == "manual_reference" else "自动轴",
            "counts": f"{r.get('anterior_n', 0)} / {r.get('posterior_n', 0)}",
        }
        tone = {"good": "good", "fair": "warn", "poor": "warn", "manual": ""}.get(r.get("fit_quality"), "")
        for key, text in mapping.items():
            lbl = self.detail_labels[key]
            lbl.setText(text)
            if key in ("front_rms", "back_rms"):
                lbl.setProperty("tone", tone)
            else:
                lbl.setProperty("tone", "")
            lbl.style().unpolish(lbl); lbl.style().polish(lbl)

    # ---------- keyboard ----------
    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Undo):
            self.undo_shortcut()
            return
        if isinstance(self.focusWidget(), (QLineEdit, QPlainTextEdit)):
            return super().keyPressEvent(e)
        k = e.text().lower()
        mapping = {"1": "guide", "2": "pupil", "3": "anterior", "4": "posterior", "5": "manual_axis"}
        if k in mapping:
            self.set_mode(mapping[k])
        elif k == "u":
            self.undo()
        elif k == "s":
            self.save_current()
        elif k == "n":
            self.next_image()
        elif k == "p":
            self.prev_image()
        elif k in ("+", "="):
            self.zoom_step(1.2)
        elif k == "-":
            self.zoom_step(1 / 1.2)
        else:
            super().keyPressEvent(e)

    # ---------- style ----------
    def _apply_style(self):
        self.setStyleSheet(QSS)


QSS = f"""
QMainWindow, QWidget {{ background: {C['bg']}; color: {C['text']}; font-family: "{FONT_FAMILY}"; }}
#TopBar {{ background: {C['topbar']}; border-bottom: 1px solid {C['topbar_line']}; }}
#BrandMark {{ background: transparent; }}
#BrandTitle {{ font-size: 17px; font-weight: 700; color: {C['text']}; background: transparent; }}
#BrandSub {{ font-size: 12px; color: {C['text3']}; background: transparent; }}
#StatusText {{ color: {C['primary']}; font-weight: 600; font-size: 13px; background: transparent; }}

QPushButton#Primary {{
  background: {C['primary']}; color: white; border: none; border-radius: 11px;
  padding: 9px 16px; font-size: 13px; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {C['primary_hover']}; }}
QPushButton#Secondary {{
  background: {C['surface']}; color: {C['text']}; border: 1px solid {C['line']};
  border-radius: 11px; padding: 9px 16px; font-size: 13px; font-weight: 600;
}}
QPushButton#Secondary:hover {{ background: {C['surface3']}; border-color: #d4dbe6; }}
QPushButton#Danger {{
  background: {C['danger_soft']}; color: {C['danger']}; border: 1px solid #ffd9df;
  border-radius: 11px; padding: 9px 16px; font-size: 13px; font-weight: 600;
}}
QPushButton#Danger:hover {{ background: #ffe4e9; }}

#LeftScroll {{ border: none; background: {C['bg']}; }}
#LeftScroll > QWidget > QWidget {{ background: {C['bg']}; }}

#Card {{ background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 16px; }}
#CardTitle {{ font-size: 12px; font-weight: 700; color: {C['text3']}; }}
#Muted {{ font-size: 12px; color: {C['text3']}; }}
#CollapseSection {{ background: transparent; border: none; }}
#CollapseHeader {{
  background: {C['surface']}; color: {C['text2']}; border: 1px solid {C['line']}; border-radius: 14px;
  padding: 10px 14px; text-align: left; font-size: 13px; font-weight: 700;
}}
#CollapseHeader:hover {{ background: {C['surface2']}; color: {C['text']}; }}
#CollapseHeader[expanded="true"] {{ background: {C['surface2']}; color: {C['text']}; border-color: #d8e0eb; }}
#CollapseBody {{ background: transparent; }}
#Divider {{ color: {C['line2']}; background: {C['line2']}; border: none; }}
#DividerLabel {{ font-size: 11px; font-weight: 700; color: {C['text3']}; }}
#Footnote {{ font-size: 12px; color: {C['text3']}; padding: 4px; }}

#Step {{ background: {C['surface2']}; border: 1px solid {C['line2']}; border-radius: 12px; }}
#Step[state="active"] {{ background: {C['primary_soft']}; border: 1px solid {C['primary']}; }}
#Step[state="ready"] {{ background: {C['success_soft']}; border: 1px solid {C['success_line']}; }}
#StepBadge {{ background: {C['surface3']}; color: {C['text2']}; border: 1px solid {C['line']};
  border-radius: 7px; font-size: 12px; font-weight: 700; }}
#StepBadge[state="active"] {{ background: {C['primary']}; color: white; border: 1px solid {C['primary']}; }}
#StepBadge[state="ready"] {{ background: {C['success']}; color: white; border: 1px solid {C['success']}; }}
#StepName {{ font-size: 13px; font-weight: 600; color: {C['text']}; }}
#StepCount {{ font-size: 12px; font-weight: 700; color: {C['text3']}; }}
#StepCount[state="active"] {{ color: {C['primary']}; }}
#StepHint {{ font-size: 11px; color: {C['text3']}; padding-left: 31px; }}
#StepHint[state="active"] {{ color: {C['primary']}; }}

#ResultCard {{ background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 16px; }}
#ResultLabel {{ color: {C['text3']}; font-size: 11px; font-weight: 700; letter-spacing: 2px; background: transparent; }}
#ResultValue {{ color: {C['text']}; font-size: 48px; font-weight: 700; background: transparent; }}
#ResultCaption {{ color: {C['text2']}; font-size: 12px; background: transparent; }}
#ChipBlue {{ background: {C['primary_soft']}; color: {C['primary']}; border-radius: 9px; padding: 6px 10px; font-size: 11px; font-weight: 600; }}
#ChipGreen {{ background: {C['success_soft']}; color: {C['success']}; border-radius: 9px; padding: 6px 10px; font-size: 11px; font-weight: 600; }}
#ChipPurple {{ background: #f4f0ff; color: {C['accent1']}; border-radius: 9px; padding: 6px 10px; font-size: 11px; font-weight: 600; }}

#DetailKey {{ font-size: 10px; color: {C['text3']}; }}
#DetailVal {{ font-size: 12px; font-weight: 600; color: {C['text']}; font-family: "{MONO_FAMILY}"; }}
#DetailVal[tone="good"] {{ color: {C['success']}; }}
#DetailVal[tone="warn"] {{ color: #b26a00; }}
#PointsBox {{ background: {C['surface2']}; border: 1px solid {C['line']}; border-radius: 10px;
  color: {C['text2']}; font-family: "{MONO_FAMILY}"; font-size: 11px; padding: 6px; }}
#Note {{ background: {C['surface2']}; border: 1px solid {C['line']}; border-radius: 11px;
  padding: 9px 12px; font-size: 13px; color: {C['text']}; }}
#Note:focus {{ border: 1px solid {C['primary']}; background: white; }}

#Segmented {{ background: {C['surface3']}; border: 1px solid {C['line']}; border-radius: 12px; }}
#SegBtn {{ background: transparent; color: {C['text2']}; border: none; border-radius: 9px;
  padding: 8px 6px; font-size: 13px; font-weight: 600; }}
#SegBtn:hover {{ background: white; color: {C['text']}; }}
#LegendText {{ font-size: 12px; color: {C['text2']}; }}

#CanvasCard {{ background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 16px; }}
#CanvasHead {{ background: {C['surface']}; border-bottom: 1px solid {C['line2']};
  border-top-left-radius: 16px; border-top-right-radius: 16px; }}
#CanvasTitle {{ font-size: 14px; font-weight: 700; color: {C['text']}; }}
#CanvasInfo {{ font-size: 12px; color: {C['text3']}; }}
#CursorLabel {{ font-size: 12px; color: {C['text3']}; font-family: "{MONO_FAMILY}"; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #d4dbe6; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #b9c4d4; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def main():
    app = QApplication(sys.argv)
    icon_path = resource_path("windows", "IOLTiltLabeler.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1]).expanduser()
        if folder.exists() and folder.is_dir():
            images = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_EXTS)
            win.start_session(images, folder)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
