"""Marking faces in a picture: draw a box around a face, say who it is (someone in the
tree, or a name as written on the back of the photo), and optionally make that face
their portrait. Boxes are stored as fractions of the upright picture."""
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from photos import STORED_H, STORED_W
from strings import t
import theme


def portrait_crop(image, rect):
    """A portrait-shaped part of the picture around a face box (fractions): the face with
    some hair and shoulders, kept inside the picture."""
    width, height = image.width(), image.height()
    x, y, w, h = rect[0] * width, rect[1] * height, rect[2] * width, rect[3] * height
    ratio = STORED_W / STORED_H
    crop_h = max(h * 1.9, w * 1.9 / ratio)
    crop_w = crop_h * ratio
    crop_w, crop_h = min(crop_w, width), min(crop_h, height)
    if crop_w / crop_h > ratio:
        crop_w = crop_h * ratio
    else:
        crop_h = crop_w / ratio
    left = min(max(0.0, x + w / 2 - crop_w / 2), width - crop_w)
    top = min(max(0.0, y + h * 0.45 - crop_h * 0.4), height - crop_h)
    return QRect(round(left), round(top), max(1, round(crop_w)), max(1, round(crop_h)))


class FaceCanvas(QWidget):
    """The picture with its face boxes. Dragging draws a new box; clicking one selects it."""

    drawn = Signal(list)
    picked = Signal(int)

    def __init__(self, image):
        super().__init__()
        self.image, self.faces, self.selected = image, [], -1
        self.start = self.current = None
        self.setMinimumSize(420, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def picture_rect(self):
        size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                      size.width(), size.height())

    def to_screen(self, rect):
        area = self.picture_rect()
        return QRectF(area.left() + rect[0] * area.width(), area.top() + rect[1] * area.height(),
                      rect[2] * area.width(), rect[3] * area.height())

    def to_fraction(self, box):
        area = self.picture_rect()
        box = box.normalized().intersected(area)
        return [(box.left() - area.left()) / area.width(), (box.top() - area.top()) / area.height(),
                box.width() / area.width(), box.height() / area.height()]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.picture_rect(), self.image)
        for number, face in enumerate(self.faces):
            chosen = number == self.selected
            painter.setPen(QPen(theme.colour("mark" if chosen else "highlight"), 3 if chosen else 2))
            box = self.to_screen(face["rect"])
            painter.drawRect(box)
            painter.drawText(box.bottomLeft() + QPointF(2, 14), str(number + 1))
        if self.start is not None and self.current is not None:
            painter.setPen(QPen(theme.colour("mark"), 2, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(self.start, self.current).normalized())

    def mousePressEvent(self, event):
        point = event.position()
        for number, face in reversed(list(enumerate(self.faces))):
            if self.to_screen(face["rect"]).contains(point):
                self.picked.emit(number)
                return
        self.start = self.current = point

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.current = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start is None:
            return
        box = QRectF(self.start, event.position()).normalized()
        self.start = self.current = None
        self.update()
        if box.width() >= 8 and box.height() >= 8:
            self.drawn.emit(self.to_fraction(box))


class FacesDialog(QDialog):
    """values(): the faces of this picture; portraits: [(person id, face box)] to cut."""

    def __init__(self, parent, image, faces, context):
        super().__init__(parent)
        self.context = context
        self.faces = [dict(face) for face in faces]
        self.portraits = []
        self.setWindowTitle(t("faces_title"))
        self.resize(980, 640)
        self.canvas = FaceCanvas(image)
        self.canvas.drawn.connect(self.add_face)
        self.canvas.picked.connect(lambda number: self.list.setCurrentRow(number))
        hint = QLabel(t("faces_hint"))
        hint.setWordWrap(True)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        self.choose = QPushButton(t("role_choose_person"))
        self.choose.clicked.connect(self.choose_person)
        self.choose.setEnabled(context.find_person is not None)
        self.name = QLineEdit()
        self.name.setPlaceholderText(t("faces_name_hint"))
        self.name.textEdited.connect(self._name_typed)
        self.portrait = QPushButton(t("faces_portrait"))
        self.portrait.clicked.connect(self.use_as_portrait)
        self.remove = QPushButton(t("list_remove"))
        self.remove.clicked.connect(self.remove_face)
        side = QVBoxLayout()
        side.addWidget(hint)
        side.addWidget(self.list, 1)
        side.addWidget(self.choose)
        side.addWidget(self.name)
        side.addWidget(self.portrait)
        side.addWidget(self.remove)
        body = QHBoxLayout()
        body.addWidget(self.canvas, 3)
        body.addLayout(side, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)
        self._fill()

    def label(self, face):
        if face.get("person") and self.context.tree is not None and face["person"] in self.context.tree.people:
            return self.context.tree.people[face["person"]].display_name
        return face.get("name") or t("faces_unknown")

    def _fill(self, select=None):
        self.list.blockSignals(True)
        self.list.clear()
        for number, face in enumerate(self.faces, 1):
            self.list.addItem(f"{number}. {self.label(face)}")
        self.list.blockSignals(False)
        self.canvas.faces = self.faces
        row = select if select is not None else min(self.list.count() - 1, max(0, self.list.currentRow()))
        self.list.setCurrentRow(row)
        self._select(row)

    def _select(self, row):
        self.canvas.selected = row
        self.canvas.update()
        face = self.faces[row] if 0 <= row < len(self.faces) else None
        for widget in (self.choose, self.name, self.remove):
            widget.setEnabled(face is not None and (widget is not self.choose or self.context.find_person is not None))
        self.name.setText((face or {}).get("name", ""))
        self.portrait.setEnabled(bool(face and face.get("person")))

    def add_face(self, rect):
        self.faces.append({"rect": rect})
        self._fill(len(self.faces) - 1)

    def current(self):
        row = self.list.currentRow()
        return self.faces[row] if 0 <= row < len(self.faces) else None

    def choose_person(self):
        face = self.current()
        if face is None:
            return
        chosen = self.context.find_person(t("faces_who"))
        if chosen:
            face["person"] = chosen
            self._fill(self.list.currentRow())

    def _name_typed(self, text):
        face = self.current()
        if face is not None:
            if text.strip():
                face["name"] = text.strip()
            else:
                face.pop("name", None)
            self.list.currentItem().setText(f"{self.list.currentRow() + 1}. {self.label(face)}")

    def use_as_portrait(self):
        face = self.current()
        if face and face.get("person"):
            self.portraits = [p for p in self.portraits if p[0] != face["person"]] + [(face["person"], face["rect"])]
            self.portrait.setText(t("faces_portrait_chosen"))

    def remove_face(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.faces):
            del self.faces[row]
            self._fill(max(0, row - 1))

    def values(self):
        return [face for face in self.faces if face.get("rect")]
