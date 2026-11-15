"""Maiores: the name, the mark and the pictures made from them. No window code here.

The mark is an M drawn as a family: its two peaks are a couple, the ancestors (in Latin,
maiores); their lines meet in the middle at their child; the outer strokes run down to
the descendants. Drawn in code so it is sharp at every size, in the program and in the
files made from it (tools/make_graphics.py)."""
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPainterPath, QPen

NAME = "Maiores"
ROOT = Path(__file__).resolve().parent

TERRACOTTA = QColor("#9b3a24")
DEEP = QColor("#5e1f15")
CREAM = QColor("#f4e9d4")
GOLD = QColor("#e0ad4f")
INK = QColor("#3b2520")
PARCHMENT = QColor("#f6efe2")

# The mark in a unit square: the M's corners are people.
_PEOPLE = {"left_foot": (0.20, 0.80), "left_peak": (0.27, 0.24), "child": (0.50, 0.58),
           "right_peak": (0.73, 0.24), "right_foot": (0.80, 0.80)}
_STROKE = ("left_foot", "left_peak", "child", "right_peak", "right_foot")


SMALL_ICON = ROOT / "assets" / "icon-64.png"  # Made by tools/make_graphics.py.


def small_icon_uri():
    """The icon as a data: address, for web pages and reports (no Qt needed)."""
    import base64
    try:
        return "data:image/png;base64," + base64.b64encode(SMALL_ICON.read_bytes()).decode()
    except OSError:
        return ""


def _font(size, weight=QFont.Weight.Normal):
    families = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(
        str(ROOT / "fonts" / "NotoSerif-Regular.ttf")))
    font = QFont(families[0] if families else "serif")
    font.setPixelSize(max(1, int(size)))
    font.setWeight(weight)
    return font


def draw_mark(painter, rect, line=CREAM, people=GOLD, centre=CREAM):
    """The M of people inside `rect` (kept square, centred)."""
    side = min(rect.width(), rect.height())
    left, top = rect.center().x() - side / 2, rect.center().y() - side / 2

    def at(name):
        x, y = _PEOPLE[name]
        return QPointF(left + x * side, top + y * side)

    path = QPainterPath(at(_STROKE[0]))
    for name in _STROKE[1:]:
        path.lineTo(at(name))
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(line, side * 0.075, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.setPen(QPen(line, side * 0.03))
    for name, radius, colour in (("left_peak", 0.11, people), ("right_peak", 0.11, people),
                                 ("child", 0.095, centre), ("left_foot", 0.075, people),
                                 ("right_foot", 0.075, people)):
        painter.setBrush(colour)
        painter.drawEllipse(at(name), side * radius, side * radius)
    painter.restore()


def app_icon(size=1024):
    """The program's icon: the mark on a deep terracotta tile."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    tile = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    fill = QLinearGradient(tile.topLeft(), tile.bottomRight())
    fill.setColorAt(0, TERRACOTTA)
    fill.setColorAt(1, DEEP)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawRoundedRect(tile, size * 0.2, size * 0.2)
    draw_mark(painter, tile.adjusted(size * 0.1, size * 0.1, -size * 0.1, -size * 0.1))
    painter.end()
    return image


def draw_wordmark(painter, rect, tagline="", dark=False):
    """The tile, then MAIORES in inscription capitals, and a small line under it."""
    height = rect.height()
    tile = QRectF(rect.left(), rect.top(), height, height)
    icon = app_icon(max(64, int(height * 2)))
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(tile, icon)
    text_left = tile.right() + height * 0.28
    title = _font(height * (0.52 if tagline else 0.62))
    title.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
    painter.setFont(title)
    painter.setPen(CREAM if dark else INK)
    name_box = QRectF(text_left, rect.top(), rect.right() - text_left, height * (0.66 if tagline else 1))
    painter.drawText(name_box, Qt.AlignmentFlag.AlignLeft | (Qt.AlignmentFlag.AlignBottom if tagline
                                                              else Qt.AlignmentFlag.AlignVCenter), NAME.upper())
    if tagline:
        small = _font(height * 0.2)
        small.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
        painter.setFont(small)
        painter.setPen(GOLD if dark else TERRACOTTA)
        painter.drawText(QRectF(text_left + height * 0.03, rect.top() + height * 0.7, rect.right() - text_left,
                                height * 0.3), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, tagline)
    painter.restore()


def wordmark_width(height, tagline=""):
    """How wide draw_wordmark is at this height (for laying it out)."""
    from PySide6.QtGui import QFontMetricsF
    title = _font(height * (0.52 if tagline else 0.62))
    title.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
    width = QFontMetricsF(title).horizontalAdvance(NAME.upper())
    if tagline:
        small = _font(height * 0.2)
        small.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
        width = max(width, QFontMetricsF(small).horizontalAdvance(tagline))
    return height * 1.28 + width + height * 0.1


def picture(width, height, draw, background=PARCHMENT):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(background)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(painter)
    painter.end()
    return image


def social_preview(tagline="Free family tree program · Windows, Mac, Linux"):
    """The 1280x640 picture shown when the GitHub page is shared."""
    def draw(painter):
        fill = QLinearGradient(0, 0, 1280, 640)
        fill.setColorAt(0, DEEP)
        fill.setColorAt(1, TERRACOTTA)
        painter.fillRect(QRectF(0, 0, 1280, 640), fill)
        height = 190
        width = wordmark_width(height, tagline)
        draw_wordmark(painter, QRectF((1280 - width) / 2, (640 - height) / 2, width, height), tagline, dark=True)
    return picture(1280, 640, draw)


def banner(tagline="family tree"):
    """The top of the README: the wordmark on parchment."""
    height = 140
    width = int(wordmark_width(height, tagline)) + 80
    return picture(width, height + 60, lambda p: draw_wordmark(p, QRectF(40, 30, width - 80, height), tagline),
                   QColor(0, 0, 0, 0))


def installer_side(width=164, height=314):
    """Inno Setup's tall picture at the left of the first and last pages."""
    def draw(painter):
        fill = QLinearGradient(0, 0, 0, height)
        fill.setColorAt(0, TERRACOTTA)
        fill.setColorAt(1, DEEP)
        painter.fillRect(QRectF(0, 0, width, height), fill)
        draw_mark(painter, QRectF(width * 0.15, height * 0.18, width * 0.7, width * 0.7))
        painter.setFont(_font(width * 0.16))
        painter.setPen(CREAM)
        painter.drawText(QRectF(0, height * 0.62, width, height * 0.1), Qt.AlignmentFlag.AlignCenter, NAME.upper())
    return picture(width, height, draw)


def dmg_background(width=660, height=400, hint="Drag Maiores to Applications"):
    """The Mac disk image window: the two icons sit at (180, 200) and (480, 200)."""
    def draw(painter):
        painter.setPen(QPen(QColor(TERRACOTTA.red(), TERRACOTTA.green(), TERRACOTTA.blue(), 150), 6,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(270, 200), QPointF(380, 200))
        painter.drawLine(QPointF(380, 200), QPointF(360, 186))
        painter.drawLine(QPointF(380, 200), QPointF(360, 214))
        painter.setFont(_font(18))
        painter.setPen(INK)
        painter.drawText(QRectF(0, 310, width, 40), Qt.AlignmentFlag.AlignCenter, hint)
        draw_wordmark(painter, QRectF(24, 20, 220, 44))
    return picture(width, height, draw)
