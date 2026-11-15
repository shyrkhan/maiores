"""Choosing how to share the tree as a web page, and the window that shows the address
while it is shared live on this network."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

import webshare
from strings import t
import theme


class WebPageDialog(QDialog):
    """Options for a page: hide living people, photos, and (for a file) a password."""

    def __init__(self, parent, name, with_password=True):
        super().__init__(parent)
        self.setWindowTitle(t("webpage_title") if with_password else t("liveshare_title"))
        self.setMinimumWidth(460)
        intro = QLabel(t("webpage_intro", name=name) if with_password else t("liveshare_intro", name=name))
        intro.setWordWrap(True)
        self.hide_living = QCheckBox(t("webpage_hide_living"))
        self.hide_living.setChecked(True)
        self.photos = QCheckBox(t("webpage_photos"))
        self.photos.setChecked(True)
        form = QFormLayout()
        form.addRow("", self.hide_living)
        form.addRow("", self.photos)
        self.password = QLineEdit()
        self.repeat = QLineEdit()
        for box in (self.password, self.repeat):
            box.setEchoMode(QLineEdit.EchoMode.Password)
        self.problem = QLabel()
        self.problem.setStyleSheet(f"color: {theme.hex('error')};")
        self.problem.setWordWrap(True)
        if with_password:
            available = webshare.encryption_available()
            self.password.setPlaceholderText(t("webpage_password_hint") if available else t("webpage_no_encryption"))
            self.password.setEnabled(available)
            self.repeat.setEnabled(available)
            form.addRow(t("webpage_password"), self.password)
            form.addRow(t("webpage_repeat"), self.repeat)
        self.with_password = with_password
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            t("webpage_save") if with_password else t("liveshare_start"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for box in (self.password, self.repeat):
            box.textChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        problem = ""
        if self.password.text() != self.repeat.text():
            problem = t("webpage_passwords_differ")
        elif self.password.text() and len(self.password.text()) < 8:
            problem = t("webpage_password_short")
        self.problem.setText(problem)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not problem)

    def values(self):
        return {"hide_living": self.hide_living.isChecked(), "photos": self.photos.isChecked(),
                "password": self.password.text() if self.with_password else ""}


class LiveShareDialog(QDialog):
    """Shows where the page can be opened, with a QR code to scan; closing it stops sharing."""

    def __init__(self, parent, share):
        super().__init__(parent)
        self.share = share
        self.setWindowTitle(t("liveshare_title"))
        self.setMinimumWidth(520)
        addresses = share.addresses()
        layout = QVBoxLayout(self)
        if not addresses:
            note = QLabel(t("liveshare_no_network"))
            note.setWordWrap(True)
            layout.addWidget(note)
        else:
            hint = QLabel(t("liveshare_scan"))
            hint.setWordWrap(True)
            layout.addWidget(hint)
            png = webshare.qr_png(addresses[0])
            if png:
                picture = QPixmap()
                picture.loadFromData(png)
                code = QLabel()
                code.setPixmap(picture)
                layout.addWidget(code, 0, Qt.AlignmentFlag.AlignHCenter)
            for address in addresses:
                row = QHBoxLayout()
                field = QLineEdit(address)
                field.setReadOnly(True)
                copy = QPushButton(t("liveshare_copy"))
                copy.clicked.connect(lambda _checked=False, text=address: QGuiApplication.clipboard().setText(text))
                row.addWidget(field, 1)
                row.addWidget(copy)
                layout.addLayout(row)
        privacy = QLabel(t("liveshare_privacy"))
        privacy.setWordWrap(True)
        privacy.setStyleSheet(f"color: {theme.hex('soft')};")
        layout.addWidget(privacy)
        self.views = QLabel()
        layout.addWidget(self.views)
        stop = QDialogButtonBox()
        stop.addButton(t("liveshare_stop"), QDialogButtonBox.ButtonRole.RejectRole)
        stop.rejected.connect(self.reject)
        layout.addWidget(stop)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._count)
        self.timer.start(1000)
        self._count()

    def _count(self):
        self.views.setText(t("liveshare_views", count=self.share.views))

    def done(self, result):
        self.timer.stop()
        self.share.stop()  # Closing the window, however it closes, ends sharing.
        super().done(result)
