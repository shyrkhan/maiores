"""The window for one person's documents: add, describe, mark private, open, remove,
and cut a portrait out of a picture (a face from a group photo)."""
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

import documents
from model import DOCUMENT_KINDS, person_documents
from photos import PhotoError, read_image
from screen import fit_hint, fit_to_screen
from strings import t
import theme

THUMB = QSize(72, 72)
PREVIEW = QSize(320, 300)


def _pdf_page(path, size):
    """The first page of a PDF as a picture, when Qt's PDF module is installed."""
    try:
        from PySide6.QtPdf import QPdfDocument
    except ImportError:
        return None
    document = QPdfDocument()
    if document.load(str(path)) != QPdfDocument.Error.None_ or document.pageCount() < 1:
        return None
    page = document.pagePointSize(0).toSize().scaled(size, Qt.AspectRatioMode.KeepAspectRatio)
    image = document.render(0, page)
    document.close()
    return QPixmap.fromImage(image) if not image.isNull() else None


def _tile(text, size):
    """A plain tile with the file type, for anything that can't be previewed."""
    pixmap = QPixmap(size)
    pixmap.fill(theme.colour("tile"))
    painter = QPainter(pixmap)
    painter.setPen(theme.colour("tile_text"))
    font = QFont()
    font.setBold(True)
    font.setPointSize(max(8, size.height() // 6))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap


def upright(path):
    """A picture the right way up, or None. The same image is used for showing, marking
    faces and cutting portraits, so a rectangle means the same thing in all three."""
    try:
        return read_image(path)
    except PhotoError:
        return None


def picture_of(path, size):
    if path is None:
        return _tile("?", size)
    if documents.is_image(path):
        image = upright(path)  # Phone photos carry a rotation tag; faces must land where they are seen.
        if image is not None:
            return QPixmap.fromImage(image).scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation)
    if path.suffix.lower() == ".pdf":
        page = _pdf_page(path, size)
        if page is not None:
            return page
    return _tile(path.suffix.lstrip(".").upper() or "?", size)


def file_filter():
    patterns = " ".join(f"*{suffix}" for suffix in sorted(documents.ALLOWED_TYPES))
    return f"{t('documents_filter')} ({patterns})"


class DocumentsDialog(QDialog):
    """Works on a copy; values() gives the new list. Files are copied into the tree as
    they are added (named by content, so a cancelled dialog leaves nothing confusing)."""

    def __init__(self, parent, person, folder, start_folder=None, faces=None, context=None):
        super().__init__(parent)
        self.folder, self.start_folder = folder, start_folder or Path.home()
        self.items = [dict(d) for d in person_documents(person)]
        self.portrait_from = None  # A picture chosen to cut the portrait from.
        self.faces = {path: [dict(f) for f in items] for path, items in (faces or {}).items()}
        self.face_changes = {}  # Stored file -> its faces as now marked.
        self.portraits = []  # (person id, stored file, face box): faces made into portraits.
        self.context = context
        self.setWindowTitle(t("documents_title", name=person.display_name))
        fit_to_screen(self, 760, 520)

        self.list = QListWidget()
        self.list.setIconSize(THUMB)
        self.list.setMinimumWidth(260)
        self.list.currentRowChanged.connect(self._show)
        self.empty = QLabel(t("documents_empty"))
        self.empty.setWordWrap(True)
        add = QPushButton(t("documents_add"))
        add.clicked.connect(self.add_files)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(PREVIEW)
        self.title = QLineEdit()
        self.kind = QComboBox()
        for kind in DOCUMENT_KINDS:
            self.kind.addItem(t(f"doc_kind_{kind}"), kind)
        self.date = QLineEdit()
        fit_hint(self.date, t("date_hint"))
        self.private = QCheckBox(t("documents_private"))
        self.private.setToolTip(t("documents_private_tip"))
        for signal in (self.title.textEdited, self.date.textEdited):
            signal.connect(self._store)
        self.kind.currentIndexChanged.connect(self._store)
        self.private.toggled.connect(self._store)
        self.open_button = QPushButton(t("documents_open"))
        self.open_button.clicked.connect(self.open_current)
        self.faces_button = QPushButton(t("documents_faces"))
        self.faces_button.clicked.connect(self.mark_faces)
        self.portrait_button = QPushButton(t("documents_use_portrait"))
        self.portrait_button.clicked.connect(self._use_as_portrait)
        self.remove_button = QPushButton(t("documents_remove"))
        self.remove_button.clicked.connect(self.remove_current)

        form = QFormLayout()
        form.addRow(t("documents_field_title"), self.title)
        form.addRow(t("documents_field_kind"), self.kind)
        form.addRow(t("documents_field_date"), self.date)
        form.addRow("", self.private)
        actions = QHBoxLayout()
        for button in (self.open_button, self.faces_button, self.portrait_button, self.remove_button):
            actions.addWidget(button)
        self.editor = QWidget()
        editor = QVBoxLayout(self.editor)
        editor.addWidget(self.preview, 1)
        editor.addLayout(form)
        editor.addLayout(actions)

        left = QVBoxLayout()
        left.addWidget(self.list, 1)
        left.addWidget(self.empty)
        left.addWidget(add)
        body = QHBoxLayout()
        body.addLayout(left)
        body.addWidget(self.editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)
        self._fill()

    def path_of(self, item):
        return documents.resolve_document(self.folder, item["file"])

    def _fill(self, select=0):
        self.list.blockSignals(True)
        self.list.clear()
        for item in self.items:
            label = item["title"] or t(f"doc_kind_{item['kind']}")
            if item["date"]:
                label += f"\n{item['date']}"
            if item.get("private"):
                label += f"\n{t('documents_private_mark')}"
            self.list.addItem(QListWidgetItem(QIcon(picture_of(self.path_of(item), THUMB)), label))
        self.list.blockSignals(False)
        self.empty.setVisible(not self.items)
        self.editor.setEnabled(bool(self.items))
        if self.items:
            self.list.setCurrentRow(max(0, min(select, len(self.items) - 1)))
            self._show(self.list.currentRow())
        else:
            self.preview.setPixmap(QPixmap())

    def _show(self, row):
        if not 0 <= row < len(self.items):
            return
        item, path = self.items[row], self.path_of(self.items[row])
        for widget in (self.title, self.kind, self.date, self.private):
            widget.blockSignals(True)
        self.title.setText(item["title"])
        self.kind.setCurrentIndex(max(0, self.kind.findData(item["kind"])))
        self.date.setText(item["date"])
        self.private.setChecked(bool(item.get("private")))
        for widget in (self.title, self.kind, self.date, self.private):
            widget.blockSignals(False)
        self.preview.setPixmap(picture_of(path, PREVIEW))
        self.preview.setToolTip(t("documents_missing") if path is None else "")
        self.open_button.setEnabled(path is not None)
        self.portrait_button.setEnabled(path is not None and documents.is_image(path))
        self.faces_button.setEnabled(path is not None and documents.is_image(path) and self.context is not None)
        count = len(self.faces.get(item["file"], []))
        self.faces_button.setText(t("documents_faces_count", count=count) if count else t("documents_faces"))

    def _store(self, *_args):
        row = self.list.currentRow()
        if not 0 <= row < len(self.items):
            return
        self.items[row].update(title=self.title.text().strip(), kind=self.kind.currentData(),
                               date=self.date.text().strip(), private=self.private.isChecked())
        label = self.items[row]["title"] or t(f"doc_kind_{self.items[row]['kind']}")
        if self.items[row]["date"]:
            label += f"\n{self.items[row]['date']}"
        if self.items[row]["private"]:
            label += f"\n{t('documents_private_mark')}"
        self.list.item(row).setText(label)

    def ask_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, t("documents_add"), str(self.start_folder), file_filter())
        return paths

    def add_files(self, paths=None):
        """Copies each file into the tree; returns the names that could not be added."""
        refused = []
        for path in paths if paths is not None else self.ask_files():
            try:
                stored = documents.store_document(path, self.folder)
            except (documents.DocumentError, OSError):
                refused.append(Path(path).name)
                continue
            if all(item["file"] != stored for item in self.items):
                kind = "photo" if documents.is_image(path) else "other"
                self.items.append({"file": stored, "title": Path(path).stem, "kind": kind, "date": "",
                                   "private": False})
        self._fill(len(self.items) - 1)
        if refused:
            self.empty.setText(t("documents_refused", names=", ".join(refused)))
            self.empty.setVisible(True)
        return refused

    def open_current(self):
        row = self.list.currentRow()
        path = self.path_of(self.items[row]) if 0 <= row < len(self.items) else None
        if path is not None:  # Only allowed types inside the tree's media folder get this far.
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def ask_faces(self, image, faces):
        from faces_dialog import FacesDialog
        dialog = FacesDialog(self, image, faces, self.context)
        result = (dialog.values(), dialog.portraits) if dialog.exec() else None
        dialog.deleteLater()
        return result

    def mark_faces(self):
        row = self.list.currentRow()
        path = self.path_of(self.items[row]) if 0 <= row < len(self.items) else None
        image = upright(path) if path is not None and documents.is_image(path) else None
        if image is None:
            return
        stored = self.items[row]["file"]
        answer = self.ask_faces(image, self.faces.get(stored, []))
        if answer is None:
            return
        faces, portraits = answer
        self.faces[stored] = faces
        self.face_changes[stored] = faces
        self.portraits = [p for p in self.portraits if p[0] not in {pid for pid, _r in portraits}]
        self.portraits += [(person_id, stored, rect) for person_id, rect in portraits]
        self._show(row)

    def remove_current(self):
        """Takes the document off this person. The file stays: undo can bring it back."""
        row = self.list.currentRow()
        if 0 <= row < len(self.items):
            del self.items[row]
            self._fill(row)

    def _use_as_portrait(self):
        row = self.list.currentRow()
        path = self.path_of(self.items[row]) if 0 <= row < len(self.items) else None
        if path is not None and documents.is_image(path):
            self.portrait_from = path
            self.accept()

    def values(self):
        cleaned = []
        for item in self.items:
            entry = {"file": item["file"], "title": item["title"], "kind": item["kind"], "date": item["date"]}
            if item.get("private"):
                entry["private"] = True
            cleaned.append(entry)
        return cleaned
