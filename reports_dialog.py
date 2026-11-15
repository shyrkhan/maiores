"""Choosing what to print: a report or book about the selected person, or a wall poster."""
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox, QVBoxLayout,
)

import poster
from strings import t


def _buttons(dialog, layout):
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)


class ReportDialog(QDialog):
    KINDS = ("family", "ancestors", "descendants")

    def __init__(self, parent, name, odt=False):
        super().__init__(parent)
        self.setWindowTitle(t("report_title"))
        self.setMinimumWidth(420)
        about = QLabel(t("report_about", name=name))
        about.setWordWrap(True)
        self.kind = QComboBox()
        for kind in self.KINDS:
            self.kind.addItem(t(f"report_kind_{kind}"), kind)
        self.generations = QSpinBox()
        self.generations.setRange(1, 20)
        self.generations.setValue(5)
        self.notes = QCheckBox(t("report_include_notes"))
        self.notes.setChecked(True)
        self.sources = QCheckBox(t("report_include_sources"))
        self.sources.setChecked(True)
        self.format = QComboBox()
        self.format.addItem(t("report_format_pdf"), "pdf")
        if odt:  # Only where this Qt can write OpenDocument.
            self.format.addItem(t("report_format_odt"), "odt")
        form = QFormLayout()
        form.addRow(t("report_kind"), self.kind)
        form.addRow(t("report_generations"), self.generations)
        form.addRow("", self.notes)
        form.addRow("", self.sources)
        form.addRow(t("report_format"), self.format)
        layout = QVBoxLayout(self)
        layout.addWidget(about)
        layout.addLayout(form)
        _buttons(self, layout)
        self.kind.currentIndexChanged.connect(
            lambda _i: self.generations.setEnabled(self.kind.currentData() != "family"))
        self.generations.setEnabled(False)

    def values(self):
        return {"kind": self.kind.currentData(), "generations": self.generations.value(),
                "notes": self.notes.isChecked(), "sources": self.sources.isChecked(), "format": self.format.currentData()}


class PosterDialog(QDialog):
    def __init__(self, parent, area):
        super().__init__(parent)
        self.area = area
        self.setWindowTitle(t("poster_title"))
        self.setMinimumWidth(420)
        hint = QLabel(t("poster_hint"))
        hint.setWordWrap(True)
        self.paper = QComboBox()
        for paper in poster.PAPERS:
            self.paper.addItem(paper, paper)
        self.paper.setCurrentIndex(self.paper.findData("A4"))
        self.across = QSpinBox()
        self.across.setRange(1, 12)
        self.across.setValue(3)
        self.across.setSpecialValueText(t("poster_one_sheet"))
        self.pages = QLabel()
        form = QFormLayout()
        form.addRow(t("poster_paper"), self.paper)
        form.addRow(t("poster_across"), self.across)
        form.addRow("", self.pages)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        _buttons(self, layout)
        self.paper.currentIndexChanged.connect(self._update)
        self.across.valueChanged.connect(self._update)
        self._update()

    def _update(self, *_args):
        _orientation, rows, columns = poster.plan(self.area, self.paper.currentData(), self.across.value())
        self.pages.setText(t("poster_pages", count=rows * columns, rows=rows, columns=columns))

    def values(self):
        return {"paper": self.paper.currentData(), "across": self.across.value()}
