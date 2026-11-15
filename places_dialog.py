"""Editing one place in the Places window: its name (renaming changes every fact), the
place it lies in, what kind of place it is, coordinates, older names and a note."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from model import PLACE_KINDS
from strings import t
import theme


def parse_old_names(text):
    """'Traù | 1918' lines into [{"name", "until"}]."""
    found = []
    for line in text.splitlines():
        name, _bar, until = line.partition("|")
        if name.strip():
            entry = {"name": name.strip()}
            if until.strip():
                entry["until"] = until.strip()
            found.append(entry)
    return found


def old_names_text(old_names):
    return "\n".join(f"{o['name']} | {o['until']}" if o.get("until") else o["name"] for o in old_names)


def parse_coordinate(text, limit):
    """'43.5167', '43,5167' or empty; None when not a number within ±limit."""
    text = text.strip().replace(",", ".")
    if not text:
        return ""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if -limit <= value <= limit else None


class PlaceEditor(QWidget):
    """Emits saved(old name, new name, record) and forgotten(name)."""

    saved = Signal(str, str, dict)
    forgotten = Signal(str)

    def __init__(self):
        super().__init__()
        self.current = None
        self.name = QLineEdit()
        self.parent_place = QComboBox()
        self.parent_place.setEditable(True)
        self.kind = QComboBox()
        self.kind.addItem("", "")
        for kind in PLACE_KINDS:
            self.kind.addItem(t(f"place_kind_{kind}"), kind)
        self.lat, self.lon = QLineEdit(), QLineEdit()
        self.lat.setPlaceholderText(t("place_lat_hint"))
        self.lon.setPlaceholderText(t("place_lon_hint"))
        where = QWidget()
        row = QHBoxLayout(where)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.lat)
        row.addWidget(self.lon)
        self.old_names = QPlainTextEdit()
        self.old_names.setFixedHeight(56)
        self.old_names.setPlaceholderText(t("place_old_names_hint"))
        self.note = QLineEdit()
        self.problem = QLabel()
        self.problem.setStyleSheet(f"color: {theme.hex('error')};")
        self.problem.setWordWrap(True)
        self.save = QPushButton(t("place_save"))
        self.save.clicked.connect(self._save)
        self.forget = QPushButton(t("place_forget"))
        self.forget.setToolTip(t("place_forget_tip"))
        self.forget.clicked.connect(lambda: self.current is not None and self.forgotten.emit(self.current))
        form = QFormLayout()
        form.addRow(t("place_name"), self.name)
        form.addRow(t("place_parent"), self.parent_place)
        form.addRow(t("place_kind"), self.kind)
        form.addRow(t("place_coordinates"), where)
        form.addRow(t("place_old_names"), self.old_names)
        form.addRow(t("place_note"), self.note)
        buttons = QHBoxLayout()
        buttons.addWidget(self.save)
        buttons.addWidget(self.forget)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        layout.addLayout(buttons)
        self.setEnabled(False)

    def show_place(self, name, record, all_places):
        self.current = name
        self.setEnabled(name is not None)
        record = record or {}
        self.name.setText(name or "")
        self.parent_place.clear()
        self.parent_place.addItem("")
        self.parent_place.addItems(sorted(p for p in all_places if p != name))
        self.parent_place.setCurrentText(record.get("parent", ""))
        self.kind.setCurrentIndex(max(0, self.kind.findData(record.get("kind", ""))))
        self.lat.setText(f"{record['lat']:.5f}".rstrip("0").rstrip(".") if "lat" in record else "")
        self.lon.setText(f"{record['lon']:.5f}".rstrip("0").rstrip(".") if "lon" in record else "")
        self.old_names.setPlainText(old_names_text(record.get("old_names", [])))
        self.note.setText(record.get("note", ""))
        self.problem.clear()

    def record(self):
        """The edited details, or None (with the reason shown) when something is not valid."""
        lat, lon = parse_coordinate(self.lat.text(), 90), parse_coordinate(self.lon.text(), 180)
        if lat is None or lon is None or (lat == "") != (lon == ""):
            self.problem.setText(t("place_bad_coordinates"))
            return None
        record = {"parent": self.parent_place.currentText().strip(), "kind": self.kind.currentData(),
                  "old_names": parse_old_names(self.old_names.toPlainText()), "note": self.note.text().strip()}
        if lat != "":
            record["lat"], record["lon"] = lat, lon
        return record

    def _save(self):
        record = self.record()
        if record is None or self.current is None:
            return
        if not self.name.text().strip():
            self.problem.setText(t("place_needs_name"))
            return
        if record["parent"] == self.name.text().strip():
            self.problem.setText(t("error_place_loop", place=self.name.text().strip(), parent=record["parent"]))
            return
        self.problem.clear()
        self.saved.emit(self.current, self.name.text().strip(), record)
