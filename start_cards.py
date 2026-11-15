"""The start page's trees as cards: the first person's portrait (or initials), the tree's
name, how many people it holds and when it last changed. Each card is a button, so it
works with the keyboard and screen readers like any other."""
import datetime
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QLocale, QRectF, QSize, Qt
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton, QWidget

import theme
from strings import t

CARD_W, CARD_H, PORTRAIT = 340, 104, 64


@dataclass
class TreeSummary:
    path: Path
    people: int = 0
    first_name: str = ""
    initials: str = ""
    portrait: object = None  # QImage, or None.
    changed: datetime.date | None = None


def summarise(path, tree_file):
    """What a card shows about a tree. A tree that cannot be read still gets a card (with
    just its name): opening it gives the real reason."""
    from model import TreeFormatError
    from photos import read_image, resolve_photo
    from storage import TreeLoadError, read_tree
    summary = TreeSummary(Path(path))
    try:
        summary.changed = datetime.date.fromtimestamp((Path(path) / tree_file).stat().st_mtime)
        tree = read_tree(path)
    except (OSError, ValueError, TreeLoadError, TreeFormatError):
        return summary
    summary.people = len(tree.people)
    first = next(iter(tree.people.values()), None)
    if first is not None:
        summary.first_name = first.display_name
        summary.initials = "".join(part[:1] for part in (first.given, first.surname) if part).upper()
        source = resolve_photo(path, first.photo) if first.photo else None
        if source is not None:
            image = read_image(source)
            if image is not None and not image.isNull():
                summary.portrait = image.scaled(PORTRAIT * 2, PORTRAIT * 2, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                Qt.TransformationMode.SmoothTransformation)
    return summary


class BrandHeader(QWidget):
    """The Maiores mark and name, with a short line under it, for the start page and About."""

    def __init__(self, tagline="", height=96):
        super().__init__()
        import branding
        self.tagline, self.mark_height = tagline, height
        self.setFixedSize(int(branding.wordmark_width(height, tagline)) + 8, height + 8)

    def paintEvent(self, event):
        import branding
        painter = QPainter(self)
        branding.draw_wordmark(painter, QRectF(4, 4, self.width() - 8, self.mark_height), self.tagline,
                               dark=theme.current == "dark")


class TreeCard(QPushButton):
    """A tree on the start page. The button's text (read by screen readers and tests) is
    the usual "Open <tree>"; the card draws its own picture of the tree instead."""

    def __init__(self, summary):
        super().__init__(t("start_tree_button", name=summary.path.stem))
        self.summary = summary
        self.setToolTip(str(summary.path))
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)

    def sizeHint(self):
        return QSize(CARD_W, CARD_H)

    def details(self):
        lines = [t("start_card_people", count=self.summary.people)]
        if self.summary.changed is not None:
            when = QLocale().toString(self.summary.changed, QLocale.FormatType.ShortFormat)
            lines.append(t("start_card_changed", date=when))
        return "  ·  ".join(lines)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        lit = self.underMouse() or self.hasFocus()
        painter.setPen(QPen(theme.colour("highlight" if lit else "divider"), 2 if lit else 1))
        painter.setBrush(theme.colour("card"))
        painter.drawRoundedRect(box, 12, 12)
        picture = QRectF(box.left() + 14, box.center().y() - PORTRAIT / 2, PORTRAIT, PORTRAIT)
        circle = QPainterPath()
        circle.addEllipse(picture)
        if self.summary.portrait is not None:
            painter.save()
            painter.setClipPath(circle)
            image = self.summary.portrait
            source = QRectF(0, 0, image.width(), image.height())
            side = min(source.width(), source.height())
            source = QRectF((source.width() - side) / 2, (source.height() - side) * 0.25, side, side)
            painter.drawImage(picture, image, source)
            painter.restore()
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.soft_colour(sum(map(ord, self.summary.path.stem)) * 47))
            painter.drawPath(circle)
            font = QFont(self.font())
            font.setPointSizeF(font.pointSizeF() * 1.5)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(theme.colour("text"))
            painter.drawText(picture, Qt.AlignmentFlag.AlignCenter,
                             self.summary.initials or self.summary.path.stem[:1].upper())
        text = QRectF(picture.right() + 14, box.top() + 12, box.right() - picture.right() - 26, box.height() - 24)
        title = QFont(self.font())
        title.setPointSizeF(title.pointSizeF() * 1.25)
        title.setBold(True)
        painter.setFont(title)
        painter.setPen(theme.colour("text"))
        painter.drawText(text, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                         painter.fontMetrics().elidedText(self.summary.path.stem, Qt.TextElideMode.ElideRight,
                                                          int(text.width())))
        painter.setFont(self.font())
        painter.setPen(theme.colour("soft"))
        for row, line in enumerate((self.summary.first_name, self.details())):
            if line:
                painter.drawText(QRectF(text.left(), text.bottom() - (2 - row) * painter.fontMetrics().height(),
                                        text.width(), painter.fontMetrics().height()),
                                 Qt.AlignmentFlag.AlignLeft,
                                 painter.fontMetrics().elidedText(line, Qt.TextElideMode.ElideRight, int(text.width())))
