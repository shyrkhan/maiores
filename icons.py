"""Toolbar icons, drawn here as simple line pictures in the current theme's colours, so
they stay sharp at any size and need no image files."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QPixmap

import theme

NAMES = ("back", "home", "undo", "redo", "zoom_out", "zoom_in", "fit", "centre")


def _draw(painter, name, s):
    """One icon on a square of side `s`, in the painter's current pen."""
    m = s * 0.18  # Margin.
    path = QPainterPath()
    if name == "back":
        path.moveTo(s - m, s / 2)
        path.lineTo(m, s / 2)
        path.moveTo(s * 0.45, m * 1.4)
        path.lineTo(m, s / 2)
        path.lineTo(s * 0.45, s - m * 1.4)
    elif name == "home":
        path.moveTo(m, s * 0.5)
        path.lineTo(s / 2, m)
        path.lineTo(s - m, s * 0.5)
        path.moveTo(m * 1.6, s * 0.42)
        path.lineTo(m * 1.6, s - m)
        path.lineTo(s - m * 1.6, s - m)
        path.lineTo(s - m * 1.6, s * 0.42)
    elif name in ("undo", "redo"):
        flip = name == "redo"
        arc = QRectF(m, s * 0.3, s - 2 * m, s * 0.56)
        path.arcMoveTo(arc, 0 if flip else 180)
        path.arcTo(arc, 0 if flip else 180, 180 if flip else -180)
        tip = QPointF(s - m if flip else m, s * 0.58)
        path.moveTo(tip + QPointF(-s * 0.16 if flip else s * 0.16, -s * 0.14))
        path.lineTo(tip)
        path.lineTo(tip + QPointF(s * 0.14 if flip else -s * 0.14, -s * 0.16))
    elif name in ("zoom_in", "zoom_out"):
        radius = s * 0.26
        centre = QPointF(s * 0.42, s * 0.42)
        path.addEllipse(centre, radius, radius)
        handle = centre + QPointF(radius * math.cos(math.pi / 4), radius * math.sin(math.pi / 4))
        path.moveTo(handle)
        path.lineTo(s - m, s - m)
        path.moveTo(centre - QPointF(radius * 0.5, 0))
        path.lineTo(centre + QPointF(radius * 0.5, 0))
        if name == "zoom_in":
            path.moveTo(centre - QPointF(0, radius * 0.5))
            path.lineTo(centre + QPointF(0, radius * 0.5))
    elif name == "fit":
        corner = s * 0.22
        for x, y, dx, dy in ((m, m, 1, 1), (s - m, m, -1, 1), (m, s - m, 1, -1), (s - m, s - m, -1, -1)):
            path.moveTo(x + dx * corner, y)
            path.lineTo(x, y)
            path.lineTo(x, y + dy * corner)
    elif name == "centre":
        path.addEllipse(QPointF(s / 2, s / 2), s * 0.2, s * 0.2)
        for x1, y1, x2, y2 in ((s / 2, m * 0.6, s / 2, s * 0.3), (s / 2, s * 0.7, s / 2, s - m * 0.6),
                               (m * 0.6, s / 2, s * 0.3, s / 2), (s * 0.7, s / 2, s - m * 0.6, s / 2)):
            path.moveTo(x1, y1)
            path.lineTo(x2, y2)
    painter.drawPath(path)


def icon(name):
    """A QIcon for a toolbar action, drawn for normal and disabled states."""
    result = QIcon()
    for size in (24, 48):
        for mode, key in ((QIcon.Mode.Normal, "text"), (QIcon.Mode.Disabled, "disabled")):
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(theme.colour(key), max(1.6, size / 13), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                       Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            _draw(painter, name, size)
            painter.end()
            result.addPixmap(pixmap, mode)
    return result


def draw_app_icon(size=1024):
    """The program's icon: three portraits with initials joined by rounded lines, on a deep
    blue square. Written to assets/icon.png by tools (kept here so it can be redrawn)."""
    from PySide6.QtGui import QColor, QImage, QLinearGradient
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 1024
    back = QLinearGradient(0, 0, 0, size)
    back.setColorAt(0, QColor("#2f4f7a"))
    back.setColorAt(1, QColor("#1c2b45"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(back)
    painter.drawRoundedRect(QRectF(32 * s, 32 * s, 960 * s, 960 * s), 200 * s, 200 * s)
    line = QPen(QColor("#d9e3f0"), 26 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(line)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    joints = QPainterPath()
    joints.moveTo(330 * s, 330 * s)
    joints.lineTo(694 * s, 330 * s)
    joints.moveTo(512 * s, 330 * s)
    joints.lineTo(512 * s, 520 * s)
    joints.quadTo(512 * s, 560 * s, 512 * s, 600 * s)
    painter.drawPath(joints)
    for (cx, cy), colour in (((300, 330), "#e7a35b"), ((724, 330), "#c46a8a"), ((512, 720), "#6fb3a6")):
        circle = QRectF((cx - 150) * s, (cy - 150) * s, 300 * s, 300 * s)
        painter.setPen(QPen(QColor("#f4f6fa"), 22 * s))
        painter.setBrush(QColor(colour))
        painter.drawEllipse(circle)
        figure = QPainterPath()  # Head and shoulders, cut to the circle.
        figure.addEllipse(QPointF(cx * s, (cy - 38) * s), 52 * s, 60 * s)
        figure.addEllipse(QPointF(cx * s, (cy + 120) * s), 108 * s, 96 * s)
        clip = QPainterPath()
        clip.addEllipse(circle.adjusted(11 * s, 11 * s, -11 * s, -11 * s))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawPath(figure.intersected(clip))
    painter.end()
    return image
