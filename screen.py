"""Windows that fit the screen they open on, down to a 1366 x 768 laptop."""
import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QGuiApplication

# The window frame and title bar, and a little air, around a window's own size.
FRAME_W, FRAME_H = 24, 64


def room(widget=None):
    """(width, height) a window can use on the screen it opens on."""
    screen = None
    if widget is not None:
        parent = widget.parentWidget()
        screen = (parent or widget).screen()
    screen = screen or QGuiApplication.primaryScreen()
    if screen is None:
        return 10_000, 10_000
    area = screen.availableGeometry()
    return area.width() - FRAME_W, area.height() - FRAME_H


def fit_to_screen(widget, width, height):
    """resize(width, height), but never larger than the screen leaves room for."""
    most_w, most_h = room(widget)
    widget.resize(min(width, most_w), min(height, most_h))


class _HintFitter(QObject):
    """Keeps a field's hint to the examples that fit its width, whole ones only."""

    def __init__(self, edit, text):
        super().__init__(edit)
        self.edit, self.text = edit, text
        self.items = [part for part in re.split(r"\s*[,،、，]\s*", text) if part]
        self.joiner = "، " if "،" in text else ("、" if "、" in text else ", ")
        edit.installEventFilter(self)
        self.fit()

    def fit(self):
        room = self.edit.width() - 14
        metrics = self.edit.fontMetrics()
        shown = self.items[:1]
        for count in range(len(self.items), 0, -1):
            candidate = self.joiner.join(self.items[:count])
            if metrics.horizontalAdvance(candidate) <= room:
                shown = self.items[:count]
                break
        self.edit.setPlaceholderText(self.joiner.join(shown))

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.FontChange):
            self.fit()
        return False


def fit_hint(edit, text):
    """A hint of examples ("1921, about 1921, ...") that shows as many whole examples as
    the field has room for; all of them are in the tooltip."""
    edit.setToolTip(text)
    _HintFitter(edit, text)
