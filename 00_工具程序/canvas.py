"""影像画布：缩放 / 平移 / 取点 / 拖点 / 放大镜 / 亮度对比度。"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QColor, QFont, QImage, QPainter, QPen, QBrush, QPainterPath, QFontMetrics,
)
from PySide6.QtWidgets import QWidget

import iol_core as core
from iol_core import as_points
from theme import ANN

Point = tuple[float, float]

# 各步骤在画布上的点位键与颜色
POINT_KEYS = ("guide", "pupil_plane", "anterior", "posterior", "manual_iol_axis")
KEY_COLOR = {
    "guide": "guide",
    "pupil_plane": "pupil",
    "anterior": "anterior",
    "posterior": "posterior",
    "manual_iol_axis": "manual",
}
KEY_PREFIX = {
    "guide": "C",
    "pupil_plane": "AB",
    "anterior": "F",
    "posterior": "B",
    "manual_iol_axis": "M",
}

HIT_RADIUS = 11.0     # 命中已有点的屏幕半径（px）
MIN_SCALE = 0.05
MAX_SCALE = 24.0


def build_lut(brightness: int, contrast: int, invert: bool) -> list[int] | None:
    """把亮度/对比度/反相折叠成一张 256 级查找表，Pillow 用 C 实现，速度够快。"""
    if brightness == 0 and contrast == 0 and not invert:
        return None
    k = (contrast + 100) / 100.0
    k = k * k                      # 让滑块两端更有感觉
    offset = brightness * 1.28
    lut = []
    for i in range(256):
        v = (i - 128) * k + 128 + offset
        if invert:
            v = 255 - v
        lut.append(max(0, min(255, int(round(v)))))
    return lut


class ImageCanvas(QWidget):
    pointClicked = Signal(float, float)                 # 空白处左键：新增点
    pointGrabbed = Signal(str, int)                     # 抓住已有点（拖动前）
    pointMoved = Signal(str, int, float, float)         # 拖动中
    pointReleased = Signal()                            # 拖动结束
    pointDeleteRequested = Signal(str, int)             # ⌥ 点击已有点
    cursorMoved = Signal(float, float)
    viewChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.image: QImage | None = None
        self._source = None            # PIL.Image，原图
        self.img_w = 0
        self.img_h = 0
        self.scale = 1.0
        self.offset = QPointF(0, 0)

        self.brightness = 0
        self.contrast = 0
        self.invert = False

        self.show_loupe = True
        self.show_crosshair = False
        self.selected: tuple[str, int] | None = None

        self.overlay_getter = None     # callable -> label dict
        self.mode_key_getter = None    # callable -> 当前步骤对应的点位键

        self._panning = False
        self._pan_start = QPoint()
        self._offset_start = QPointF()
        self._dragging: tuple[str, int] | None = None
        self._hover: tuple[str, int] | None = None
        self._cursor = QPointF(-1, -1)
        self._inside = False

    # ---------------- 图像 ----------------
    def set_image(self, pil_image) -> None:
        self._source = pil_image
        self._rebuild()

    def set_adjust(self, brightness: int, contrast: int, invert: bool) -> None:
        self.brightness, self.contrast, self.invert = brightness, contrast, invert
        self._rebuild()

    def _rebuild(self) -> None:
        if self._source is None:
            self.image = None
            self.update()
            return
        img = self._source
        lut = build_lut(self.brightness, self.contrast, self.invert)
        if lut is not None:
            img = img.point(lut * 3)
        self.img_w, self.img_h = img.size
        data = img.tobytes("raw", "RGB")
        self.image = QImage(data, self.img_w, self.img_h, self.img_w * 3,
                            QImage.Format_RGB888).copy()
        self.update()

    # ---------------- 视图 ----------------
    def fit(self) -> None:
        if not self.image:
            return
        cw = max(120, self.width() - 32)
        ch = max(120, self.height() - 32)
        self.scale = max(MIN_SCALE, min(cw / self.img_w, ch / self.img_h))
        self._center()
        self.update()
        self.viewChanged.emit()

    def actual_size(self) -> None:
        if not self.image:
            return
        self.set_zoom(1.0)

    def _center(self) -> None:
        self.offset = QPointF((self.width() - self.img_w * self.scale) / 2,
                              (self.height() - self.img_h * self.scale) / 2)

    def set_zoom(self, new_scale: float, center: QPointF | None = None) -> None:
        if not self.image:
            return
        new_scale = max(MIN_SCALE, min(MAX_SCALE, new_scale))
        if center is None:
            center = QPointF(self.width() / 2, self.height() / 2)
        ix, iy = self.widget_to_image(center)
        self.scale = new_scale
        self.offset = QPointF(center.x() - ix * self.scale, center.y() - iy * self.scale)
        self.update()
        self.viewChanged.emit()

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self.scale * factor)

    def image_to_widget(self, x: float, y: float) -> QPointF:
        return QPointF(x * self.scale + self.offset.x(), y * self.scale + self.offset.y())

    def widget_to_image(self, pt: QPointF) -> tuple[float, float]:
        return ((pt.x() - self.offset.x()) / self.scale,
                (pt.y() - self.offset.y()) / self.scale)

    # ---------------- 命中测试 ----------------
    def _label(self) -> dict:
        return self.overlay_getter() if self.overlay_getter else {}

    def hit_test(self, pos: QPointF) -> tuple[str, int] | None:
        """找到屏幕上离光标最近的已有点；当前步骤的点优先。"""
        label = self._label()
        current = self.mode_key_getter() if self.mode_key_getter else None
        best = None
        best_d = HIT_RADIUS
        for key in POINT_KEYS:
            for i, pt in enumerate(label.get(key, [])):
                w = self.image_to_widget(float(pt[0]), float(pt[1]))
                d = math.hypot(w.x() - pos.x(), w.y() - pos.y())
                if key == current:
                    d -= 3.0        # 同一步骤的点更容易抓到
                if d < best_d:
                    best_d = d
                    best = (key, i)
        return best

    # ---------------- 鼠标 ----------------
    def mousePressEvent(self, e):
        if not self.image:
            return
        pos = QPointF(e.position())
        if e.button() == Qt.LeftButton:
            hit = self.hit_test(pos)
            if hit and (e.modifiers() & Qt.AltModifier):
                self.pointDeleteRequested.emit(hit[0], hit[1])
                return
            if hit:
                self._dragging = hit
                self.selected = hit
                self.setCursor(Qt.ClosedHandCursor)
                self.pointGrabbed.emit(hit[0], hit[1])
                self.update()
                return
            x, y = self.widget_to_image(pos)
            if 0 <= x < self.img_w and 0 <= y < self.img_h:
                self.pointClicked.emit(x, y)
        elif e.button() in (Qt.RightButton, Qt.MiddleButton):
            self._panning = True
            self._pan_start = e.position().toPoint()
            self._offset_start = QPointF(self.offset)
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        pos = QPointF(e.position())
        self._cursor = pos
        self._inside = True
        if not self.image:
            return
        if self._panning:
            delta = e.position().toPoint() - self._pan_start
            self.offset = QPointF(self._offset_start.x() + delta.x(),
                                  self._offset_start.y() + delta.y())
            self.update()
            self.viewChanged.emit()
            return
        x, y = self.widget_to_image(pos)
        if self._dragging:
            x = max(0.0, min(self.img_w - 1.0, x))
            y = max(0.0, min(self.img_h - 1.0, y))
            self.pointMoved.emit(self._dragging[0], self._dragging[1], x, y)
            self.update()
        else:
            hover = self.hit_test(pos)
            changed = hover != self._hover
            if changed:
                self._hover = hover
                self.setCursor(Qt.OpenHandCursor if hover else Qt.CrossCursor)
            # 大图上别每次移动都全量重绘，只有放大镜/准星/悬停变化时才刷新
            if changed or self.show_loupe or self.show_crosshair:
                self.update()
        self.cursorMoved.emit(x, y)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._dragging:
            self._dragging = None
            self.setCursor(Qt.OpenHandCursor)
            self.pointReleased.emit()
        elif e.button() in (Qt.RightButton, Qt.MiddleButton):
            self._panning = False
            self.setCursor(Qt.CrossCursor)

    def leaveEvent(self, e):
        self._inside = False
        self._hover = None
        self.update()
        super().leaveEvent(e)

    def wheelEvent(self, e):
        if not self.image:
            return
        dy = e.angleDelta().y()
        if dy == 0:
            return
        self.set_zoom(self.scale * (1.12 if dy > 0 else 1 / 1.12), QPointF(e.position()))

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and not self.hit_test(QPointF(e.position())):
            self.fit()

    # ---------------- 绘制 ----------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#07080c"))
        if not self.image:
            p.setPen(QColor("#6b7280"))
            p.setFont(QFont(self.font().family(), 12))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "把图片或文件夹拖进来，或按 ⌘O 打开\n\n左键取点 · 拖动已有点微调 · ⌥点删除\n右键平移 · 滚轮缩放 · 双击适配")
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.scale < 3.0)
        target = QRectF(self.offset.x(), self.offset.y(),
                        self.img_w * self.scale, self.img_h * self.scale)
        p.drawImage(target, self.image)
        self._draw_overlays(p, self.scale, self.offset)
        if self.show_crosshair and self._inside and not self._panning:
            self._draw_crosshair(p)
        if self.show_loupe and self._inside and not self._panning:
            self._draw_loupe(p)

    # ---- 覆盖层（画布与放大镜共用） ----
    def _pt(self, x: float, y: float, scale: float, off: QPointF) -> QPointF:
        return QPointF(x * scale + off.x(), y * scale + off.y())

    def _line(self, p: QPainter, pts, color: str, width: float, scale, off):
        if len(pts) < 2:
            return
        pen = QPen(QColor(color))
        pen.setWidthF(width)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(self._pt(pts[0][0], pts[0][1], scale, off))
        for q in pts[1:]:
            path.lineTo(self._pt(q[0], q[1], scale, off))
        p.drawPath(path)

    def _marker(self, p: QPainter, x, y, color: str, scale, off,
                r: float = 4.5, text: str | None = None,
                selected: bool = False, hovered: bool = False):
        w = self._pt(x, y, scale, off)
        col = QColor(color)
        if selected or hovered:
            halo = QColor(color)
            halo.setAlpha(70)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(w, r + 5, r + 5)
        pen = QPen(col)
        pen.setWidthF(2.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawEllipse(w, r, r)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(w, 1.4, 1.4)
        if text:
            f = QFont(self.font().family(), 9)
            f.setBold(True)
            p.setFont(f)
            fm = QFontMetrics(f)
            tw = fm.horizontalAdvance(text)
            box = QRectF(w.x() + r + 3, w.y() - r - 11, tw + 8, 15)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 155))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(col)
            p.drawText(box, Qt.AlignCenter, text)

    def _draw_overlays(self, p: QPainter, scale: float, off: QPointF):
        if not self.overlay_getter:
            return
        label = self._label()
        guide = as_points(label.get("guide", []))
        pupil = as_points(label.get("pupil_plane", []))
        anterior = as_points(label.get("anterior", []))
        posterior = as_points(label.get("posterior", []))
        manual = as_points(label.get("manual_iol_axis", []))

        self._line(p, guide, ANN["guide"], 1.6, scale, off)
        self._line(p, pupil, ANN["pupil"], 2.0, scale, off)
        self._line(p, manual, ANN["manual"], 2.0, scale, off)

        # 自动轴：前后表面各 3 点以上时实时拟合
        if len(anterior) >= 3 and len(posterior) >= 3:
            try:
                front = core.fit_circle(anterior)
                back = core.fit_circle(posterior)
                iol_l, iol_r = core.circle_intersections(front, back)
                y_front = sum(q[1] for q in anterior) / len(anterior)
                y_back = sum(q[1] for q in posterior) / len(posterior)
                allp = anterior + posterior + [iol_l, iol_r]
                x_min = min(q[0] for q in allp) - 40
                x_max = max(q[0] for q in allp) + 40
                self._line(p, core.arc_points(front, x_min, x_max, y_front, y_front - 70, y_front + 70),
                           ANN["anterior"], 1.5, scale, off)
                self._line(p, core.arc_points(back, x_min, x_max, y_back, y_back - 70, y_back + 70),
                           ANN["posterior"], 1.5, scale, off)
                self._line(p, [iol_l, iol_r], ANN["iol"], 2.2, scale, off)
                self._marker(p, iol_l[0], iol_l[1], ANN["intersection"], scale, off, 4)
                self._marker(p, iol_r[0], iol_r[1], ANN["intersection"], scale, off, 4)
            except Exception:
                pass

        for key in POINT_KEYS:
            color = ANN[KEY_COLOR[key]]
            pts = as_points(label.get(key, []))
            for i, q in enumerate(pts):
                if key == "pupil_plane":
                    text = "A" if i == 0 else "B"
                elif key == "guide":
                    text = "C" if i == 0 else ("D" if i == len(pts) - 1 else None)
                else:
                    text = f"{KEY_PREFIX[key]}{i + 1}"
                self._marker(p, q[0], q[1], color, scale, off,
                             5.0 if key in ("pupil_plane", "manual_iol_axis") else 4.2, text,
                             selected=(self.selected == (key, i)),
                             hovered=(self._hover == (key, i)))

    def _draw_crosshair(self, p: QPainter):
        pen = QPen(QColor(255, 255, 255, 60))
        pen.setWidth(1)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawLine(QPointF(0, self._cursor.y()), QPointF(self.width(), self._cursor.y()))
        p.drawLine(QPointF(self._cursor.x(), 0), QPointF(self._cursor.x(), self.height()))

    def _draw_loupe(self, p: QPainter):
        if not self.image:
            return
        size = 128.0
        zoom = max(4.0, self.scale * 4)
        margin = 18.0
        cx = self._cursor.x() + margin + size / 2
        cy = self._cursor.y() - margin - size / 2
        if cx + size / 2 > self.width() - 6:
            cx = self._cursor.x() - margin - size / 2
        if cy - size / 2 < 6:
            cy = self._cursor.y() + margin + size / 2
        cx = max(size / 2 + 6, min(self.width() - size / 2 - 6, cx))
        cy = max(size / 2 + 6, min(self.height() - size / 2 - 6, cy))
        center = QPointF(cx, cy)

        ix, iy = self.widget_to_image(self._cursor)
        off = QPointF(cx - ix * zoom, cy - iy * zoom)

        p.save()
        clip = QPainterPath()
        clip.addEllipse(center, size / 2, size / 2)
        p.setClipPath(clip)
        p.fillRect(QRectF(cx - size / 2, cy - size / 2, size, size), QColor("#07080c"))
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.drawImage(QRectF(off.x(), off.y(), self.img_w * zoom, self.img_h * zoom), self.image)
        self._draw_overlays(p, zoom, off)
        p.restore()

        pen = QPen(QColor(255, 255, 255, 190))
        pen.setWidthF(1.4)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(center, size / 2, size / 2)
        pen = QPen(QColor(255, 60, 50, 220))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawLine(QPointF(cx - 9, cy), QPointF(cx - 3, cy))
        p.drawLine(QPointF(cx + 3, cy), QPointF(cx + 9, cy))
        p.drawLine(QPointF(cx, cy - 9), QPointF(cx, cy - 3))
        p.drawLine(QPointF(cx, cy + 3), QPointF(cx, cy + 9))
