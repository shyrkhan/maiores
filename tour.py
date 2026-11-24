"""The first-run tour: the window dims, and a bubble points at one part at a time."""
from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from strings import t
import theme


class TourOverlay(QWidget):
    """Covers the main window. `steps` is a list of (function giving a QRect in window coordinates, text key)."""

    finished = Signal()

    def __init__(self, window, steps):
        super().__init__(window)
        self.window_, self.steps, self.index = window, steps, 0
        self.outcome = "skipped"  # "finished" after the last step, "never" for Don't show again.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setGeometry(window.rect())
        self.bubble = QWidget(self)
        self.bubble.setObjectName("tour_bubble")
        self.bubble.setStyleSheet(
            f"#tour_bubble {{ background: {theme.hex('panel')}; border: 2px solid {theme.hex('highlight')};"
            f" border-radius: 10px; }} QLabel {{ color: {theme.hex('text')}; font-size: 14px; }}")
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setFixedWidth(340)
        self.counter = QLabel()
        self.back_button = QPushButton(t("tour_back"))
        self.next_button = QPushButton(t("tour_next"))
        self.skip_button = QPushButton(t("tour_skip"))
        self.never_button = QPushButton(t("tour_never"))
        self.never_button.setToolTip(t("tour_never_tip"))
        self.never_button.clicked.connect(lambda: self.finish("never"))
        self.next_button.setDefault(True)
        self.back_button.clicked.connect(lambda: self.go(-1))
        self.next_button.clicked.connect(self._next)
        self.skip_button.clicked.connect(lambda: self.finish("skipped"))
        row = QHBoxLayout()
        row.addWidget(self.counter)
        row.addWidget(self.never_button)
        row.addStretch(1)
        row.addWidget(self.skip_button)
        row.addWidget(self.back_button)
        row.addWidget(self.next_button)
        layout = QVBoxLayout(self.bubble)
        layout.addWidget(self.text)
        layout.addLayout(row)
        self.row = row
        self.show()
        self.raise_()
        self.go(0)
        # The keys are the tour's too, as the clicks are: Escape skips it, Enter or the right
        # arrow goes on, the left arrow back. Nothing reaches the chart behind it.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # Where grabbing isn't allowed (Wayland):
        self.setFocus()  # the keys still come here first.
        self.grabKeyboard()

    def target(self):
        rect = self.steps[self.index][0]()
        return rect if rect is not None and rect.isValid() else QRect(self.width() // 2, self.height() // 2, 1, 1)

    def _next(self):
        if self.index == len(self.steps) - 1:
            self.finish("finished")
        else:
            self.go(1)

    def go(self, step):
        self.index = max(0, min(len(self.steps) - 1, self.index + step))
        last = self.index == len(self.steps) - 1
        self.text.setText(t(self.steps[self.index][1]))
        self.counter.setText(f"{self.index + 1} / {len(self.steps)}")
        self.back_button.setEnabled(self.index > 0)
        self.next_button.setText(t("tour_done") if last else t("tour_next"))
        self._place_bubble()
        self.update()

    def _place_bubble(self):
        # Wide enough for every button at full size: "Don't show again" was cut short at 340 px.
        # Measured here, after the texts are in place, and with the style applied (a button not
        # yet polished reports a smaller size).
        for button in (self.counter, self.never_button, self.skip_button, self.back_button, self.next_button):
            button.ensurePolished()
        self.row.invalidate()
        self.text.setFixedWidth(max(340, self.row.sizeHint().width()))
        self.bubble.adjustSize()
        target, size = self.target(), self.bubble.size()
        self.placed_for = target
        below = QPoint(target.center().x() - size.width() // 2, target.bottom() + 16)
        above = QPoint(target.center().x() - size.width() // 2, target.top() - size.height() - 16)
        left = QPoint(target.left() - size.width() - 16, target.center().y() - size.height() // 2)
        right = QPoint(target.right() + 16, target.center().y() - size.height() // 2)
        spots = (below, above, right, left)
        for spot in spots:
            if self.rect().contains(QRect(spot, size)):
                self.bubble.move(spot)
                return

        # Nothing fits whole (a big card, a small window): pushed inside the window, the spot
        # that covers the least of what it explains. It used to sit in the middle, on top of it.
        def inside(spot):
            return QPoint(max(8, min(self.width() - size.width() - 8, spot.x())),
                          max(8, min(self.height() - size.height() - 8, spot.y())))

        def covered(spot):
            overlap = QRect(spot, size).intersected(target.adjusted(-8, -8, 8, 8))
            return overlap.width() * overlap.height() if overlap.isValid() else 0

        self.bubble.move(min((inside(spot) for spot in spots), key=covered))

    def paintEvent(self, event):
        if self.target() != getattr(self, "placed_for", None):
            # What it points at moved (another chart, a glide, a fold): the bubble follows, as the
            # highlight already does. Found by the MCP sweep: it stayed on top of the new card.
            self._place_bubble()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hole = QRectF(self.target()).adjusted(-8, -8, 8, 8)
        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        cut = QPainterPath()
        cut.addRoundedRect(hole, 10, 10)
        painter.fillPath(dim.subtracted(cut), QColor(0, 0, 0, 150))
        painter.setPen(QPen(theme.colour("highlight"), 3))
        painter.drawRoundedRect(hole, 10, 10)

    def resizeEvent(self, event):
        self._place_bubble()

    def mousePressEvent(self, event):
        event.accept()  # The tour holds the window until it is finished or skipped.

    def focusNextPrevChild(self, _next):
        return True  # Tab stays with the tour: the window behind it waits.

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.finish("skipped")
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Right, Qt.Key.Key_Space):
            self._next()
        elif key == Qt.Key.Key_Left and self.index > 0:
            self.go(-1)
        event.accept()

    def finish(self, outcome="skipped"):
        self.releaseKeyboard()
        self.outcome = outcome
        self.hide()
        self.deleteLater()
        self.finished.emit()
