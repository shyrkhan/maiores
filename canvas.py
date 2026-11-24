"""The tree display: portrait cards, connecting lines and the pan and zoom view."""
from dataclasses import dataclass, field
import os
from pathlib import Path

import shiboken6

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import (
    QContextMenuEvent,
    QImage,
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QStyle,
    QWidget,
)

import documents
import house_layout as hl
import theme

CANVAS = QRectF(-30000, -30000, 60000, 60000)
MIN_ZOOM, MAX_ZOOM, FIT_MAX_ZOOM = 0.1, 3.0, 1.4
# Moving to someone glides there instead of jumping. Off for tests and the checking tools
# (FT_STILL), which need the view to be where it was sent the moment they look.
GLIDE = not os.environ.get("FT_STILL")
GLIDE_MS = 280
CLICK_SLOP = 5

# All colours live here, so the look can change without touching anything else.
BACKGROUND = QColor("#2b2d31")
PANEL = QColor("#232427")
CONTROL = QColor("#34363b")
TEXT = QColor("#e8e8e8")
LINE = QColor("#8f939b")
FRAME = QColor("#a8acb3")
HIGHLIGHT = QColor("#7fb2ff")
PATH_COLOUR = QColor("#e6c06a")  # A relationship path, in amber.
PORTRAIT_LIGHT = QColor("#5a5e66")
PORTRAIT_DARK = QColor("#3a3c42")
SILHOUETTE = QColor("#25262a")

# What cards and lines are drawn in: the screen look, and ink-saving for printing.
INK_SCREEN = {"text": TEXT, "line": LINE, "frame": FRAME}
INK_PRINT = {"text": QColor("#111111"), "line": QColor("#555555"), "frame": QColor("#555555")}


@dataclass
class Decor:
    """How cards and lines look, chosen in Preferences. Charts read DECOR when they draw,
    so the screen, pictures, prints and posters all look the same."""
    placeholder: str = "initials"  # "initials" or "silhouette" when someone has no photo.
    lines: str = "rounded"  # "square", "rounded" or "curved" corners where lines meet.
    colours: str = "plain"  # "plain", "side" (father's / mother's) or "surname".
    mark_deceased: bool = False  # A small cross after the years of someone who has died.
    shadows: bool = True
    tints: dict = field(default_factory=dict)  # person id -> QColor, from `colours`.
    # A highlighted family line: its people stay clear, everyone else fades to `fade`.
    line_members: frozenset | None = None
    fade: float = 0.15


DECOR = Decor()
LINE_RADIUS = {"square": 0.0, "rounded": 14.0, "curved": 60.0}


def _alive(item):
    """False once Qt has deleted an item, for example when the tree was redrawn."""
    return shiboken6.isValid(item)


PICTURE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic"}


class TreeScene(QGraphicsScene):
    def __init__(self, ink=INK_SCREEN):
        super().__init__()
        self.ink = ink


def label_font(pixel_size):
    """Sized in tree units, so text matches the cards on screens, pictures and PDFs."""
    font = QFont()
    font.setFamilies(["Noto Serif", "DejaVu Serif", "serif"])
    font.setPixelSize(pixel_size)
    return font


def _initials_colour(initials, tint):
    """A calm colour for an initials picture: the card's tint, or one picked from the letters."""
    if tint is not None:
        return QColor(tint)
    return theme.soft_colour(sum(ord(c) * (i + 3) for i, c in enumerate(initials)))


def _luminance(colour):
    def part(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    return 0.2126 * part(colour.red()) + 0.7152 * part(colour.green()) + 0.0722 * part(colour.blue())


def _contrast(a, b):
    light, dark = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _readable_ink(back):
    """White or near-black letters, whichever stands out more on `back` (WCAG contrast)."""
    white, dark = QColor("#ffffff"), QColor("#1f2328")
    return white if _contrast(white, back) >= _contrast(dark, back) else dark


def paint_portrait(painter, frame, pixmap, deceased, initials="", tint=None, rounded=0.0):
    """A photo cut to fit the frame; without one, the person's initials (or a silhouette)."""
    painter.save()
    if rounded:
        clip = QPainterPath()
        clip.addRoundedRect(frame, rounded, rounded)
        painter.setClipPath(clip)
    else:
        painter.setClipRect(frame)
    if pixmap is None and initials and DECOR.placeholder == "initials":
        back = _initials_colour(initials, tint)
        if deceased:  # Dimmed first, so the letters are chosen for the colour they end up on.
            back = QColor(back.red() * 165 // 255, back.green() * 165 // 255, back.blue() * 165 // 255)
            deceased = False
        ink = _readable_ink(back)
        if _contrast(ink, back) < 3.0:  # A middling colour: darkened until white letters read well.
            while _contrast(QColor("#ffffff"), back) < 3.0 and back.lightness() > 0:
                back = back.darker(110)
            ink = QColor("#ffffff")
        painter.fillRect(frame, back)
        painter.setPen(ink)
        painter.setFont(label_font(max(10, int(frame.height() * 0.3))))
        painter.drawText(frame, Qt.AlignmentFlag.AlignCenter, initials)
    elif pixmap is not None:
        scale = max(frame.width() / pixmap.width(), frame.height() / pixmap.height())
        width, height = frame.width() / scale, frame.height() / scale
        source = QRectF((pixmap.width() - width) / 2, (pixmap.height() - height) / 2, width, height)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(frame, pixmap, source)
    else:
        size = frame.width() / hl.PORTRAIT_W
        back = QRadialGradient(frame.center() - QPointF(0, 17 * size), 105 * size)
        back.setColorAt(0, PORTRAIT_LIGHT)
        back.setColorAt(1, PORTRAIT_DARK)
        painter.fillRect(frame, QBrush(back))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(SILHOUETTE)
        centre = frame.center().x()
        painter.drawEllipse(QPointF(centre, frame.top() + 62 * size), 25 * size, 31 * size)
        painter.drawEllipse(QPointF(centre, frame.bottom() + 22 * size), 54 * size, 58 * size)
    if deceased:
        painter.fillRect(frame, QColor(0, 0, 0, 90))
    painter.restore()


class PersonItem(QGraphicsItem):
    """A framed portrait with the name and age beneath it."""

    def __init__(self, person, placed, today, pixmap=None, hidden_count=0, metrics=hl.PORTRAIT,
                 detail="age"):
        super().__init__()
        self.metrics = metrics
        self.person_id = person.id
        self.blood = placed.blood
        self.name = person.display_name
        letters = [w[0] for w in (person.given.split()[:1] + person.surname.split()[:1]) if w]
        self.initials = "".join(letters).upper() or "?"
        # Under the name: the living's age, or everyone's birth and death years.
        self.detail = person.years_label() if detail == "years" else person.age_label(today)
        if person.born_as:  # "rođ. Lukač · 75": the birth surname shares the line under the name.
            self.detail = f"{person.born_as} \u00b7 {self.detail}" if self.detail else person.born_as
        self.deceased = person.living == "no"
        self.pixmap = pixmap
        self.hidden_count = hidden_count
        self.highlighted = False
        self.drop_target = False  # Lit while another card is dragged over it.
        self.on_path = False  # Part of a highlighted relationship path.
        self.setPos(placed.x, placed.y)
        self.setZValue(1)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(person.full_name)

    def click_point(self):
        """Where to click this card: the middle of the picture."""
        return self.scenePos() + QPointF(self.metrics.card_w / 2, self.metrics.card_h / 2)

    def label_width(self):
        m = self.metrics
        if m.style in ("compact", "names"):
            return m.card_w - 14  # The text sits inside the box.
        return m.card_w + m.couple_gap * 0.6

    def boundingRect(self):
        m = self.metrics
        if m.style in ("compact", "names"):
            return QRectF(-8, -8, m.card_w + 16, m.card_h + 16)
        overflow = (self.label_width() - m.card_w) / 2
        if m.style == "round":  # Room for the dashed ring shown while something is dragged over.
            return QRectF(-overflow - 8, -8, self.label_width() + 16, m.card_h + m.label_h + 14)
        return QRectF(-overflow - 2, -3, self.label_width() + 4, m.card_h + m.label_h + 6)

    def shape(self):
        m = self.metrics
        path = QPainterPath()
        path.addRect(QRectF(0, 0, m.card_w, m.card_h + m.label_h))
        return path

    def paint(self, painter, option, widget=None):
        m = self.metrics
        if m.style == "round":
            return self._paint_round(painter, option)
        if m.style in ("compact", "names"):
            return self._paint_box(painter, option)
        label_width = self.label_width()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(0, 0, m.card_w, m.card_h)
        ink = self.scene().ink
        radius = 8.0
        tint = DECOR.tints.get(self.person_id)
        if DECOR.shadows and ink is INK_SCREEN:
            for spread, alpha in ((6, 18), (3, 30)):  # A soft shadow under the picture.
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, alpha))
                painter.drawRoundedRect(frame.adjusted(-spread + 2, -spread + 4, spread + 2, spread + 4),
                                        radius + spread, radius + spread)
        paint_portrait(painter, frame, self.pixmap, self.deceased, self.initials, tint, radius)

        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        active = hovered or self.highlighted
        if self.drop_target:
            painter.setPen(QPen(HIGHLIGHT, 6, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(frame.adjusted(-6, -6, 6, 6), radius + 6, radius + 6)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(HIGHLIGHT if active else (tint or ink["frame"]),
                   2.5 if self.highlighted else (2.0 if active else (2.0 if tint else 1.0)))
        if self.on_path and not self.highlighted:
            pen = QPen(PATH_COLOUR, 3.0)
        painter.setPen(pen)
        painter.drawRoundedRect(frame, radius, radius)

        label_left = (m.card_w - label_width) / 2
        painter.setPen(ink["text"])
        painter.setFont(label_font(16))
        name = QFontMetricsF(painter.font()).elidedText(
            self.name, Qt.TextElideMode.ElideRight, label_width
        )
        painter.drawText(
            QRectF(label_left, m.card_h + 4, label_width, 26),
            Qt.AlignmentFlag.AlignCenter,
            name,
        )
        painter.setFont(label_font(15))
        painter.drawText(
            QRectF(label_left, m.card_h + 26, label_width, 22),
            Qt.AlignmentFlag.AlignCenter,
            self.detail_text(),
        )
        if self.hidden_count:
            self._paint_hidden_badge(painter)

    def detail_text(self):
        return f"{self.detail} \u2020" if DECOR.mark_deceased and self.deceased and self.detail else \
            ("\u2020" if DECOR.mark_deceased and self.deceased else self.detail)

    def _pen_for(self, option, ink):
        if self.on_path and not self.highlighted:
            return QPen(PATH_COLOUR, 3.0)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        active = hovered or self.highlighted
        return QPen(HIGHLIGHT if active else ink["frame"], 2.5 if self.highlighted else (2.0 if active else 1.0))

    def _paint_labels(self, painter, ink, top):
        """Name and age or years under a picture, centred on the card."""
        m = self.metrics
        width = self.label_width()
        left = (m.card_w - width) / 2
        painter.setPen(ink["text"])
        painter.setFont(label_font(m.name_px))
        name = QFontMetricsF(painter.font()).elidedText(self.name, Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRectF(left, top + 4, width, 26), Qt.AlignmentFlag.AlignCenter, name)
        painter.setFont(label_font(m.detail_px))
        painter.drawText(QRectF(left, top + 26, width, 22), Qt.AlignmentFlag.AlignCenter, self.detail_text())

    def _paint_round(self, painter, option):
        """A circular photo, or the person's initials when there is none."""
        m = self.metrics
        ink = self.scene().ink
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = QRectF(0, 0, m.card_w, m.card_h)
        if self.drop_target:
            painter.setPen(QPen(HIGHLIGHT, 6, Qt.PenStyle.DashLine))
            painter.drawEllipse(circle.adjusted(-6, -6, 6, 6))
        clip = QPainterPath()
        clip.addEllipse(circle)
        painter.save()
        painter.setClipPath(clip)
        if self.pixmap is not None:
            paint_portrait(painter, circle, self.pixmap, self.deceased)
        else:
            back = _initials_colour(self.initials, DECOR.tints.get(self.person_id))
            if self.deceased:
                back = back.darker(130)
            painter.fillRect(circle, back)
            painter.setPen(QColor("#ffffff") if back.lightness() < 150 else QColor("#1f2328"))
            painter.setFont(label_font(int(m.card_h * 0.34)))
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, self.initials)
        painter.restore()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self._pen_for(option, ink))
        painter.drawEllipse(circle)
        self._paint_labels(painter, ink, m.card_h)

    def _paint_box(self, painter, option):
        """A small rounded box with the name (and years, when there is room) inside."""
        m = self.metrics
        ink = self.scene().ink
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(0, 0, m.card_w, m.card_h)
        radius = min(10.0, m.card_h / 3)
        if self.drop_target:
            painter.setPen(QPen(HIGHLIGHT, 4, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(box.adjusted(-5, -5, 5, 5), radius + 4, radius + 4)
        printing = ink is not INK_SCREEN
        tint = DECOR.tints.get(self.person_id)
        fill = QColor(tint).lighter(150) if tint is not None and theme.colour("background").lightness() > 128 \
            else (QColor(tint).darker(220) if tint is not None else (PORTRAIT_DARK if self.deceased else CONTROL))
        painter.setBrush(Qt.BrushStyle.NoBrush if printing else fill)
        painter.setPen(self._pen_for(option, ink))
        painter.drawRoundedRect(box, radius, radius)
        painter.setPen(ink["text"])
        inner = box.adjusted(7, 0, -7, 0)
        if self.pixmap is not None and m.style == "compact":
            size = m.card_h - 12
            circle = QRectF(6, 6, size, size)
            clip = QPainterPath()
            clip.addEllipse(circle)
            painter.save()
            painter.setClipPath(clip)
            paint_portrait(painter, circle, self.pixmap, self.deceased)
            painter.restore()
            inner = box.adjusted(size + 12, 0, -7, 0)
            painter.setPen(ink["text"])
        painter.setFont(label_font(m.name_px))
        name = QFontMetricsF(painter.font()).elidedText(self.name, Qt.TextElideMode.ElideRight, inner.width())
        if m.style == "names":
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, name)
            return
        painter.drawText(QRectF(inner.left(), 6, inner.width(), m.card_h / 2 - 4),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, name)
        painter.setFont(label_font(m.detail_px))
        painter.drawText(QRectF(inner.left(), m.card_h / 2 + 2, inner.width(), m.card_h / 2 - 6),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.detail_text())

    def _paint_hidden_badge(self, painter):
        """Shows how many descendants are folded away beneath this person."""
        painter.setFont(label_font(17))
        text = f"+{self.hidden_count}"
        width = QFontMetricsF(painter.font()).horizontalAdvance(text) + 22
        badge = QRectF((self.metrics.card_w - width) / 2, self.metrics.card_h - 34, width, 28)
        painter.setPen(QPen(HIGHLIGHT, 1.5))
        painter.setBrush(PANEL)
        painter.drawRoundedRect(badge, 13, 13)
        painter.setPen(TEXT)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)


ADD_BUTTON_GAP = 6.0


class AddButtonItem(QGraphicsItem):
    """A labelled button beside the selected card, such as "+ Father".

    Labels, not a bare "+": a plus alone does not say whether it adds a parent,
    a partner or a child. Only shown on screen, never in pictures or PDFs.
    """

    def __init__(self, key, label, person_id, metrics=hl.PORTRAIT):
        super().__init__()
        self.key = key
        self.person_id = person_id
        self.label = f"+ {label}"
        self.height = metrics.button_h
        self.font = label_font(metrics.button_px)
        self.width = QFontMetricsF(self.font).horizontalAdvance(self.label) + 22
        self.setZValue(5)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(label)

    def boundingRect(self):
        return QRectF(-1, -1, self.width + 2, self.height + 2)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(QPen(HIGHLIGHT, 2.0 if hovered else 1.2, Qt.PenStyle.SolidLine if hovered else Qt.PenStyle.DashLine))
        painter.setBrush(CONTROL if hovered else PANEL)
        painter.drawRoundedRect(QRectF(0, 0, self.width, self.height), 6, 6)
        painter.setPen(TEXT)
        painter.setFont(self.font)
        painter.drawText(QRectF(0, 0, self.width, self.height), Qt.AlignmentFlag.AlignCenter, self.label)


class FoldItem(QGraphicsItem):
    """A small round button on a line, with an arrow showing which way it folds: up hides
    someone's ancestors, down their descendants. Folded, it reads "+N" beside the same
    arrow, pointing to where the hidden people belong; clicking brings them back."""

    RADIUS = 11.0

    def __init__(self, fold, metrics=hl.PORTRAIT):
        super().__init__()
        self.RADIUS = metrics.fold_r
        self.person_id = fold.person_id
        self.direction = fold.direction
        self.folded = fold.folded
        self.text = f"+{fold.count}" if fold.folded else ""
        self.font = label_font(round(13 * metrics.fold_r / 11))
        self.arrow = self.RADIUS * 0.8  # Width of the chevron.
        text_w = QFontMetricsF(self.font).horizontalAdvance(self.text) + 6 if self.text else 0
        self.width = max(self.RADIUS * 2, text_w + self.arrow + 14)
        left = {"right": fold.x - self.width, "left": fold.x}.get(fold.align, fold.x - self.width / 2)
        self.setPos(left, fold.y - self.RADIUS)
        self.setZValue(4)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        from strings import t
        kind = {"up": "up", "side": "side"}.get(fold.direction, "down")
        if fold.folded:
            self.setToolTip(t(f"fold_show_{kind}", count=fold.count))
        else:
            self.setToolTip(t(f"fold_hide_{kind}"))

    def boundingRect(self):
        return QRectF(-1, -1, self.width + 2, self.RADIUS * 2 + 2)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(QPen(HIGHLIGHT if (hovered or self.folded) else LINE, 1.5))
        painter.setBrush(CONTROL if hovered else PANEL)
        box = QRectF(0, 0, self.width, self.RADIUS * 2)
        painter.drawRoundedRect(box, self.RADIUS, self.RADIUS)
        content = self.arrow + (QFontMetricsF(self.font).horizontalAdvance(self.text) + 6 if self.text else 0)
        left = (self.width - content) / 2
        if self.text:
            painter.setPen(TEXT)
            painter.setFont(self.font)
            painter.drawText(QRectF(left, 0, content - self.arrow, box.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)
        # The chevron: ^ for up, v for down.
        cx, cy = left + content - self.arrow / 2, self.RADIUS
        half, rise = self.arrow / 2, self.arrow * 0.3 * (-1 if self.direction == "up" else 1)
        chevron = QPainterPath()
        chevron.moveTo(cx - half, cy - rise)
        chevron.lineTo(cx, cy + rise)
        chevron.lineTo(cx + half, cy - rise)
        painter.setPen(QPen(TEXT, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(chevron)


def place_add_buttons(card, entries):
    """Make add buttons around a card: parents above, partner right, sibling left, child below.

    `entries` is a list of (key, label). Returns the new items, not yet in a scene.
    """
    made = {key: AddButtonItem(key, label, card.person_id, card.metrics) for key, label in entries}
    x, y = card.pos().x(), card.pos().y()
    m = card.metrics
    w, h = m.card_w, m.card_h
    if m.style != "portrait":
        return _place_in_bands(made, card, m)
    above = [made[k] for k in ("add_father", "add_mother") if k in made]
    if above:
        total = sum(b.width for b in above) + ADD_BUTTON_GAP * (len(above) - 1)
        left = x + (w - total) / 2
        for button in above:
            button.setPos(left, y - button.height - 10)
            left += button.width + ADD_BUTTON_GAP
    # The side buttons straddle the card's own edge: neighbours sit only one gap away,
    # and a button reaching into the gap alone would cover the next person.
    if "add_partner" in made:
        button = made["add_partner"]
        button.setPos(x + w - button.width / 2, y + min(20, (h - button.height) / 2))
    if "add_sibling" in made:
        button = made["add_sibling"]
        button.setPos(x - button.width / 2, y + min(20, (h - button.height) / 2))
    if "add_child" in made:
        button = made["add_child"]
        # Beside the line down to the children and its fold button, not on top of them.
        button.setPos(x + w / 2 + 18, y + h + m.label_h + 10)
    return list(made.values())


def _place_in_bands(made, card, m):
    """For the smaller styles: buttons in the empty bands above and below the card.

    Neighbours there are only a narrow gap away on the same row, but the band
    between rows never holds a card.
    """
    x, y = card.pos().x(), card.pos().y()
    rows = (
        ([made[k] for k in ("add_father", "add_mother", "add_sibling") if k in made], y - 6, True),
        ([made[k] for k in ("add_partner", "add_child") if k in made], y + m.card_h + m.label_h + 6, False),
    )
    for buttons, edge, above in rows:
        if not buttons:
            continue
        total = sum(b.width for b in buttons) + ADD_BUTTON_GAP * (len(buttons) - 1)
        left = x + (m.card_w - total) / 2
        for button in buttons:
            button.setPos(left, edge - button.height if above else edge)
            left += button.width + ADD_BUTTON_GAP
    return list(made.values())


class FanItem(PersonItem):
    """One person in the fan chart: a segment of a ring, clickable like a card."""

    def __init__(self, person, wedge, today, ink_detail="age"):
        placed = hl.PlacedCard(person.id, 0.0, 0.0, True)
        super().__init__(person, placed, today, None, 0, hl.PORTRAIT, ink_detail)
        self.wedge = wedge
        g = wedge.generation
        self.inner = 0.0 if g == 0 else hl.FAN_CENTRE_R + (g - 1) * hl.FAN_RING
        self.outer = hl.FAN_CENTRE_R if g == 0 else self.inner + hl.FAN_RING
        self._path = self._make_path()

    def _make_path(self):
        w = self.wedge
        path = QPainterPath()
        outer = QRectF(-self.outer, -self.outer, self.outer * 2, self.outer * 2)
        if self.inner == 0:
            path.moveTo(0, 0)
            path.arcTo(outer, w.start, w.span)
            path.closeSubpath()
            return path
        inner = QRectF(-self.inner, -self.inner, self.inner * 2, self.inner * 2)
        path.arcMoveTo(outer, w.start)
        path.arcTo(outer, w.start, w.span)
        path.arcTo(inner, w.start + w.span, -w.span)
        path.closeSubpath()
        return path

    def boundingRect(self):
        return self._path.boundingRect().adjusted(-4, -4, 4, 4)

    def shape(self):
        return self._path

    def click_point(self):
        """A point inside the wedge, for clicking it."""
        import math
        angle = math.radians(self.wedge.start + self.wedge.span / 2)
        radius = (self.inner + self.outer) / 2 if self.inner else self.outer * 0.45
        return self.mapToScene(QPointF(radius * math.cos(angle), -radius * math.sin(angle)))

    def paint(self, painter, option, widget=None):
        import math
        ink = self.scene().ink
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        printing = ink is not INK_SCREEN
        side = self.wedge.start + self.wedge.span / 2 < 90  # Mother's side, on the right.
        fill = theme.colour("fan_mother" if side else "fan_father") if not printing else QColor("#ffffff")
        if self.deceased and not printing:
            fill = fill.darker(125)
        painter.setBrush(fill)
        painter.setPen(self._pen_for(option, ink))
        painter.drawPath(self._path)
        angle = self.wedge.start + self.wedge.span / 2
        radius = (self.inner + self.outer) / 2 if self.inner else self.outer * 0.42
        painter.save()
        painter.translate(radius * math.cos(math.radians(angle)), -radius * math.sin(math.radians(angle)))
        g = self.wedge.generation
        if g >= 3:  # Narrow wedges: names run along the radius.
            painter.rotate(-angle if angle <= 90 else 180 - angle)
            width, height = hl.FAN_RING - 8, max(18.0, math.radians(self.wedge.span) * radius - 4)
        else:
            width, height = (self.outer * 1.8 if g == 0 else math.radians(self.wedge.span) * radius - 8), 44.0
        painter.setPen(ink["text"])
        painter.setFont(label_font(15 if g < 3 else 13))
        box = QRectF(-width / 2, -height / 2, width, height)
        name = QFontMetricsF(painter.font()).elidedText(self.name, Qt.TextElideMode.ElideRight, width)
        if g >= 3 or height < 40:
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, name)
        else:
            painter.drawText(QRectF(box.left(), box.top(), width, height / 2), Qt.AlignmentFlag.AlignCenter, name)
            painter.setFont(label_font(13))
            painter.drawText(QRectF(box.left(), 0, width, height / 2), Qt.AlignmentFlag.AlignCenter, self.detail)
        painter.restore()


def _runs(lines):
    """Segments joined into runs wherever exactly two meet, so corners can be rounded;
    a junction of three or more ends the runs that meet there."""
    ends = {}
    for number, (x1, y1, x2, y2) in enumerate(lines):
        for point in ((round(x1, 2), round(y1, 2)), (round(x2, 2), round(y2, 2))):
            ends.setdefault(point, []).append(number)
    used, runs = set(), []

    def walk(number, start):
        points = [start]
        while True:
            used.add(number)
            x1, y1, x2, y2 = lines[number]
            a, b = (round(x1, 2), round(y1, 2)), (round(x2, 2), round(y2, 2))
            nxt = b if a == points[-1] else a
            points.append(nxt)
            following = [n for n in ends[nxt] if n not in used]
            if len(ends[nxt]) != 2 or not following:
                return points
            number = following[0]

    for point, numbers in ends.items():  # Start from ends and junctions, so runs are whole.
        if len(numbers) != 2:
            for number in numbers:
                if number not in used:
                    runs.append(walk(number, point))
    for number in range(len(lines)):  # Whatever is left forms closed loops.
        if number not in used:
            x1, y1 = round(lines[number][0], 2), round(lines[number][1], 2)
            runs.append(walk(number, (x1, y1)))
    return runs


def lines_path(lines, radius):
    """The connecting lines, with corners rounded by up to `radius` (0: square)."""
    path = QPainterPath()
    for points in _runs(lines) if radius else ([(a, b), (c, d)] for a, b, c, d in lines):
        path.moveTo(*points[0])
        for here, corner, there in zip(points, points[1:], points[2:]):
            into = QPointF(*corner) - QPointF(*here)
            out = QPointF(*there) - QPointF(*corner)
            length_in, length_out = (into.x() ** 2 + into.y() ** 2) ** 0.5, (out.x() ** 2 + out.y() ** 2) ** 0.5
            r = min(radius, length_in / 2, length_out / 2)
            if r <= 0.5 or length_in == 0 or length_out == 0:
                path.lineTo(*corner)
                continue
            path.lineTo(QPointF(*corner) - into * (r / length_in))
            path.quadTo(QPointF(*corner), QPointF(*corner) + out * (r / length_out))
        path.lineTo(*points[-1])
    return path


class LinesItem(QGraphicsItem):
    def __init__(self, lines, colour=None, width=2.0):
        super().__init__()
        self.path = lines_path(lines, LINE_RADIUS.get(DECOR.lines, 0.0))
        self.colour, self.width = colour, width  # None: the ink's line colour.
        self.setZValue(0 if colour is None else 0.5)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        return self.path.boundingRect().adjusted(-3, -3, 3, 3)

    def shape(self):
        return QPainterPath()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.colour or self.scene().ink["line"], self.width, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path)


class TreeView(QGraphicsView):
    """Drag to pan and wheel to zoom. Clicks are reported to the window."""

    def __init__(self, on_click, on_double_click, on_context, on_add=None, on_key=None):
        super().__init__(QGraphicsScene())
        self.on_click = on_click
        self.on_add = on_add
        self.on_key = on_key
        self.on_fold = None  # (person id, "up", "down" or "side") when a fold button is clicked.
        self.on_photo = None  # (person id, file path or QImage) when a picture is dropped on someone.
        self._photo_target = None
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.on_connect = None  # (from id, to id, global position) when a card is dropped on another.
        self._drag_from = None
        self._drag_line = None
        self._drop_on = None
        self.on_double_click = on_double_click
        self.on_context = on_context
        self._press_at = None
        self.setBackgroundBrush(BACKGROUND)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self._glide = None
        self.smooth = True  # The person's choice; GLIDE is the program's.
        self.minimap = Minimap(self)

    def glide_to(self, point):
        """Bring a point of the tree to the middle of the window, smoothly if the window
        is on screen (a quarter of a second, slowing down at the end)."""
        self.stop_glide()
        point = QPointF(point)
        if not (GLIDE and self.smooth) or not self.isVisible():
            self.centerOn(point)
            return
        start = self.mapToScene(self.viewport().rect().center())
        if (start - point).manhattanLength() < 1:
            return
        animation = QVariantAnimation(self)
        animation.setDuration(GLIDE_MS)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(lambda share: self.centerOn(start + (point - start) * share))
        self._glide = animation
        animation.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def stop_glide(self):
        if self._glide is not None and _alive(self._glide):
            self._glide.stop()
        self._glide = None

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.minimap.isVisible():
            self.minimap.update()  # Its frame follows every move and zoom of the view.

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.minimap.place()

    def zoom_level(self):
        return self.transform().m11()

    def wheelEvent(self, event):
        factor = 1.15 ** (event.angleDelta().y() / 120)
        target = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom_level() * factor))
        self.scale(target / self.zoom_level(), target / self.zoom_level())
        event.accept()

    def person_at(self, point):
        # Look through anything drawn on top, such as the line while dragging.
        for item in self.items(point):
            if isinstance(item, (AddButtonItem, FoldItem)):
                return None
            if isinstance(item, PersonItem):
                return item
        return None

    def mousePressEvent(self, event):
        self.stop_glide()  # Grabbing the chart stops a glide under the hand.
        self._press_at = event.position().toPoint()
        self._drag_from = None
        if event.button() == Qt.MouseButton.LeftButton and self.on_connect is not None:
            card = self.person_at(self._press_at)
            if card is not None:
                # Dragging from a card connects people; dragging empty space still pans.
                self._drag_from = card
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self._drag_from is not None and not _alive(self._drag_from):
            self._forget_cards()  # The tree was redrawn while the button was down.
        if self._drag_from is None or self._press_at is None:
            return
        point = event.position().toPoint()
        if self._drag_line is None and (point - self._press_at).manhattanLength() <= CLICK_SLOP * 2:
            return
        start = self._drag_from.sceneBoundingRect().center()
        end = self.mapToScene(point)
        if self._drag_line is None:
            self._drag_line = self.scene().addLine(
                start.x(), start.y(), end.x(), end.y(), QPen(HIGHLIGHT, 3, Qt.PenStyle.DashLine)
            )
            self._drag_line.setZValue(40)
        self._drag_line.setLine(start.x(), start.y(), end.x(), end.y())
        target = self.person_at(point)
        if target is self._drag_from or (target is not None and target.person_id == self._drag_from.person_id):
            target = None
        if target is not self._drop_on:
            for card in (self._drop_on, target):
                if card is not None:
                    card.drop_target = card is target
                    card.update()
            self._drop_on = target

    def _end_drag(self):
        if self._drag_line is not None and _alive(self._drag_line) and self._drag_line.scene() is not None:
            self._drag_line.scene().removeItem(self._drag_line)
        if self._drop_on is not None and _alive(self._drop_on):
            self._drop_on.drop_target = False
            self._drop_on.update()
        dragged = self._drag_line is not None
        source, target = self._drag_from, self._drop_on
        self._drag_line = self._drop_on = self._drag_from = None
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        return dragged, source, target

    def mouseReleaseEvent(self, event):
        dragged, source, target = self._end_drag()
        if dragged:
            self._press_at = None
            super().mouseReleaseEvent(event)
            if (target is not None and self.on_connect is not None
                    and source is not None and _alive(source) and _alive(target)):
                self.on_connect(source.person_id, target.person_id, event.globalPosition().toPoint())
            return
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton or self._press_at is None:
            return
        point = event.position().toPoint()
        moved = (point - self._press_at).manhattanLength()
        self._press_at = None
        if moved <= CLICK_SLOP:
            button = self.itemAt(point)
            if isinstance(button, AddButtonItem):
                if self.on_add is not None:
                    self.on_add(button.key, button.person_id)
                return
            if isinstance(button, FoldItem):
                if self.on_fold is not None:
                    self.on_fold(button.person_id, button.direction)
                return
            item = self.person_at(point)
            self.on_click(item.person_id if item else None)

    def keyPressEvent(self, event):
        # Shift with an arrow folds the selected person's branch, as the fold buttons do:
        # the keyboard reaches everything the mouse does.
        if event.modifiers() == Qt.KeyboardModifier.ShiftModifier and getattr(self, "on_fold_key", None) \
                and self.on_fold_key(event.key()):
            event.accept()
            return
        # Arrow keys move between people; anything else keeps its usual meaning.
        if self.on_key is not None and self.on_key(event.key()):
            event.accept()
            return
        super().keyPressEvent(event)

    def zoom_by(self, factor):
        target = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom_level() * factor))
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.scale(target / self.zoom_level(), target / self.zoom_level())
        self.setTransformationAnchor(anchor)

    @staticmethod
    def dropped_picture(mime):
        """A picture in something being dragged in: a file path or an image, or None."""
        for url in mime.urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in PICTURE_SUFFIXES:
                return path
        if mime.hasImage():
            image = mime.imageData()
            if isinstance(image, QImage) and not image.isNull():
                return image
        return None

    @staticmethod
    def dropped_file(mime):
        """A picture (it becomes the portrait) or a document file (it is attached). Several
        files at once are a list of paths: all are attached (none becomes the portrait)."""
        files = [url.toLocalFile() for url in mime.urls() if url.toLocalFile()]
        if len(files) > 1 and any(Path(f).suffix.lower() in PICTURE_SUFFIXES or documents.is_allowed(f)
                                  for f in files):
            return files
        picture = TreeView.dropped_picture(mime)
        if picture is not None:
            return picture
        for url in mime.urls():
            path = url.toLocalFile()
            if path and documents.is_allowed(path):
                return path
        return None

    def _set_photo_target(self, item):
        if item is self._photo_target:
            return
        for card in (self._photo_target, item):
            if card is not None and _alive(card):
                card.drop_target = card is item
                card.update()
        self._photo_target = item

    def dragEnterEvent(self, event):
        if self.on_photo is not None and self.dropped_file(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self.on_photo is None or self.dropped_file(event.mimeData()) is None:
            return super().dragMoveEvent(event)
        item = self.person_at(event.position().toPoint())
        self._set_photo_target(item)
        if item is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_photo_target(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        picture = self.dropped_file(event.mimeData())
        item = self.person_at(event.position().toPoint())
        self._set_photo_target(None)
        if picture is None or item is None or self.on_photo is None:
            return super().dropEvent(event)
        event.acceptProposedAction()
        self.on_photo(item.person_id, picture)

    def mouseDoubleClickEvent(self, event):
        if isinstance(self.itemAt(event.position().toPoint()), (AddButtonItem, FoldItem)):
            event.accept()
            return
        item = self.person_at(event.position().toPoint())
        if item is not None and event.button() == Qt.MouseButton.LeftButton:
            self._press_at = None
            self.on_double_click(item.person_id, item.blood)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        if event.reason() == QContextMenuEvent.Reason.Keyboard:
            # The Menu key or Shift+F10: the selected person's menu, at their card.
            self.on_context(None, None)
            event.accept()
            return
        item = self.person_at(event.pos())
        if item is not None:
            self.on_context(item.person_id, event.globalPos())
            event.accept()

    def fit_tree(self):
        scene = self.scene()
        if scene is None:
            return
        # Fit the people and lines, not the buttons, or the view drifts off-centre.
        area = QRectF()
        card_h = hl.PORTRAIT.card_h + hl.PORTRAIT.label_h
        for item in scene.items():
            if not isinstance(item, (AddButtonItem, FoldItem)):
                area = area.united(item.sceneBoundingRect())
            if isinstance(item, PersonItem):
                card_h = item.metrics.card_h + item.metrics.label_h
        if area.isNull():
            return
        area = area.adjusted(-70, -50, 70, 50)
        self.fitInView(area, Qt.AspectRatioMode.KeepAspectRatio)
        # Small cards may be shown bigger, so a small family is not lost in the window.
        limit = min(MAX_ZOOM, FIT_MAX_ZOOM * (hl.PORTRAIT.card_h + hl.PORTRAIT.label_h) / card_h)
        if self.zoom_level() > limit:
            self.resetTransform()
            self.scale(limit, limit)
            self.centerOn(area.center())

    def _forget_cards(self):
        """Drop every card held from the picture being replaced: they are about to be deleted."""
        self._drag_from = self._drop_on = self._photo_target = None
        if self._drag_line is not None and _alive(self._drag_line) and self._drag_line.scene() is not None:
            self._drag_line.scene().removeItem(self._drag_line)
        self._drag_line = None
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def replace_scene(self, scene, keep_view):
        """Show a rebuilt tree. Edits keep the zoom and position, so nothing jumps."""
        self._forget_cards()
        self.stop_glide()
        centre = self.mapToScene(self.viewport().rect().center())
        self.setScene(scene)
        if keep_view:
            self.centerOn(centre)
        else:
            self.fit_tree()
        self.minimap.redraw_later()


class Minimap(QWidget):
    """The whole tree in miniature in a corner of the chart, with a frame showing the part
    in the window. Click or drag in it to go somewhere. The miniature is drawn once per
    rebuilt tree, not on every move, so big trees stay quick."""

    WIDTH, HEIGHT, MARGIN = 220, 150, 12

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.picture = None
        self.area = QRectF()
        self.resize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def place(self):
        self.move(self.view.width() - self.width() - self.MARGIN, self.view.height() - self.height() - self.MARGIN)

    def set_shown(self, shown):
        self.setVisible(shown)
        if shown:
            self.place()
            self.redraw()

    def redraw_later(self):
        if self.isVisible():
            QTimer.singleShot(0, self.redraw)

    def tree_area(self):
        scene = self.view.scene()
        area = QRectF()
        for item in scene.items() if scene is not None else ():
            if not isinstance(item, (AddButtonItem, FoldItem)):  # (parentItem() here lost items: PySide.)
                area = area.united(item.sceneBoundingRect())
        return area.adjusted(-40, -40, 40, 40) if not area.isNull() else area

    def target(self):
        """Where the miniature sits inside the widget, keeping the tree's proportions."""
        inner = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        if self.area.isEmpty():
            return inner
        scale = min(inner.width() / self.area.width(), inner.height() / self.area.height())
        width, height = self.area.width() * scale, self.area.height() * scale
        return QRectF(inner.center().x() - width / 2, inner.center().y() - height / 2, width, height)

    def redraw(self):
        if not _alive(self) or not self.isVisible() or self.view.scene() is None:
            return
        self.area = self.tree_area()
        self.picture = None
        if not self.area.isEmpty():
            target = self.target()
            ratio = self.devicePixelRatioF()
            image = QImage(max(1, round(target.width() * ratio)), max(1, round(target.height() * ratio)),
                           QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(ratio)
            image.fill(BACKGROUND)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.view.scene().render(painter, QRectF(0, 0, target.width(), target.height()), self.area)
            painter.end()
            self.picture = image
        self.update()

    def to_scene(self, point):
        target = self.target()
        if target.isEmpty() or self.area.isEmpty():
            return None
        return QPointF(self.area.left() + (point.x() - target.left()) / target.width() * self.area.width(),
                       self.area.top() + (point.y() - target.top()) / target.height() * self.area.height())

    def to_mini(self, rect):
        target = self.target()
        sx, sy = target.width() / self.area.width(), target.height() / self.area.height()
        return QRectF(target.left() + (rect.left() - self.area.left()) * sx,
                      target.top() + (rect.top() - self.area.top()) * sy, rect.width() * sx, rect.height() * sy)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(FRAME, 1))
        painter.setBrush(PANEL)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if self.picture is None or self.area.isEmpty():
            return
        painter.drawImage(self.target(), self.picture)
        seen = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        frame = self.to_mini(seen).intersected(QRectF(self.rect()).adjusted(2, 2, -2, -2))
        painter.setPen(QPen(HIGHLIGHT, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(frame)

    def mousePressEvent(self, event):
        self._go(event.position())
        event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._go(event.position())
        event.accept()

    def _go(self, point):
        place = self.to_scene(point)
        if place is not None:
            self.view.stop_glide()
            self.view.centerOn(place)


def clear_layout(layout, keep_widgets=False):
    """Empty a layout. takeAt hands each layout item over to the caller, who must delete it
    (valgrind showed them lost, one per button per redraw). Widgets are hidden, never
    unparented (that would flash them on screen as windows), and deleted unless kept."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            if not keep_widgets:
                widget.deleteLater()
        if item.layout() is None:  # A sub-layout is its own item; it goes with its parent.
            shiboken6.delete(item)


def build_scene(tree, layout, today, photo_for, ink=INK_SCREEN, controls=False, detail="age"):
    """The picture of a layout. `controls` adds the fold buttons, for the screen only."""
    scene = TreeScene(ink)
    scene.setSceneRect(CANVAS)
    items = {}
    members = DECOR.line_members
    base_lines = LinesItem(layout.lines)
    scene.addItem(base_lines)
    if members is not None:
        base_lines.setOpacity(DECOR.fade)
        joined = line_segments(layout, members)
        if joined:
            scene.addItem(LinesItem(joined, PATH_COLOUR if ink is INK_SCREEN else ink["line"], 3.0))
    for wedge in getattr(layout, "wedges", []):
        if wedge.person_id in tree.people:
            item = FanItem(tree.people[wedge.person_id], wedge, today, detail)
            scene.addItem(item)
            items.setdefault(wedge.person_id, item)
    if controls:
        for fold in layout.folds:
            scene.addItem(FoldItem(fold, layout.metrics))
    for placed in layout.cards:
        person = tree.people[placed.person_id]
        # On screen the fold button shows the count; pictures keep the badge.
        hidden = layout.hidden.get(placed.person_id, 0) if placed.blood and not controls else 0
        item = PersonItem(person, placed, today, photo_for(person.photo), hidden, layout.metrics, detail)
        scene.addItem(item)
        items.setdefault(placed.person_id, item)
    if members is not None:
        for person_id, item in items.items():
            if person_id not in members:
                item.setOpacity(DECOR.fade)
    return scene, items


def line_segments(layout, members):
    """The connecting lines that join people of a family line to each other: from a
    child up through the bar and the parents' line to the parent, and so on.

    Lines meet each other end to end or end to middle (a drop from a couple's line),
    and stop at cards. Within each group of lines between cards, the segments on the
    way from one member's card to another's are the family line's."""
    m = layout.metrics
    boxes = {}
    for card in layout.cards:
        boxes.setdefault(card.person_id, []).append(
            QRectF(card.x - 3, card.y - 3, m.card_w + 6, m.card_h + m.label_h + 6))
    segments = [tuple(s) for s in layout.lines]

    # Lines are level or upright: index them by their y or x so each end finds its
    # neighbours quickly, even in charts with thousands of lines.
    level, upright = {}, {}
    for i, (x1, y1, x2, y2) in enumerate(segments):
        if abs(y1 - y2) < 0.5:
            level.setdefault(round(y1), []).append(i)
        elif abs(x1 - x2) < 0.5:
            upright.setdefault(round(x1), []).append(i)

    def touching(point):
        x, y = point
        for i in level.get(round(y), ()):
            x1, _y1, x2, _y2 = segments[i]
            if min(x1, x2) - 0.6 <= x <= max(x1, x2) + 0.6:
                yield i
        for i in upright.get(round(x), ()):
            _x1, y1, _x2, y2 = segments[i]
            if min(y1, y2) - 0.6 <= y <= max(y1, y2) + 0.6:
                yield i

    ends = [((s[0], s[1]), (s[2], s[3])) for s in segments]
    neighbours = {i: set() for i in range(len(segments))}
    for i, (a, b) in enumerate(ends):
        for j in list(touching(a)) + list(touching(b)):
            if i != j:
                neighbours[i].add(j)
                neighbours[j].add(i)
    # Which members' cards each segment reaches.
    columns = {}  # Member cards by 200-wide column, so each line end checks only a few.
    for person_id in members:
        for box in boxes.get(person_id, ()):
            for column in range(int(box.left() // 200), int(box.right() // 200) + 1):
                columns.setdefault(column, []).append((person_id, box))
    reaches = {}
    for i, (a, b) in enumerate(ends):
        for point in (a, b):
            for person_id, box in columns.get(int(point[0] // 200), ()):
                if box.contains(QPointF(*point)):
                    reaches.setdefault(i, set()).add(person_id)
    chosen = set()
    starts = sorted(reaches)
    for number, first in enumerate(starts):
        # Shortest ways from this segment to every other member-reaching segment.
        previous, waiting, seen = {first: None}, [first], {first}
        while waiting:
            nxt = []
            for i in waiting:
                for j in neighbours[i]:
                    if j not in seen:
                        seen.add(j)
                        previous[j] = i
                        nxt.append(j)
            waiting = nxt
        for target in starts[number + 1:]:
            # Only a way between two different members counts.
            if target in previous and len(reaches[target] | reaches[first]) > 1:
                step = target
                while step is not None:
                    chosen.add(step)
                    step = previous[step]
        if len(reaches[first]) > 1:
            chosen.add(first)  # One segment joining two members: a couple's line.
    return [list(segments[i]) for i in sorted(chosen)]
