"""The window for combining a relative's tree with yours: who is already in your tree,
and which version wins where the two records of a person disagree."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QHeaderView,
    QLabel, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import combine
from canvas import clear_layout
from model import fold_text
from strings import t

NEW = ""  # The combo box value for "add as a new person".


def _label(person):
    years = person.years_label()
    return f"{person.display_name} ({years})" if years else person.display_name


class CombineDialog(QDialog):
    def __init__(self, parent, mine, theirs, suggestions, source_name, initial=None):
        super().__init__(parent)
        self.mine, self.theirs = mine, theirs
        self.suggestions = {s.theirs: s for s in suggestions}
        self.order = [s.theirs for s in suggestions]
        initial = initial or {}
        self.take_theirs = {k: set(v) for k, v in initial.get("take_theirs", {}).items()}
        self.setWindowTitle(t("combine_title", name=source_name))
        self.resize(900, 640)

        intro = QLabel(t("combine_intro"))
        intro.setWordWrap(True)
        self.table = QTableWidget(len(self.order), 3)
        self.table.setHorizontalHeaderLabels([t("combine_col_theirs"), t("combine_col_yours"), t("combine_col_match")])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        everyone = sorted(mine.people, key=lambda pid: fold_text(mine.people[pid].display_name))
        self.boxes = {}
        start = initial.get("matches")
        for row, their_id in enumerate(self.order):
            suggestion = self.suggestions[their_id]
            self.table.setItem(row, 0, QTableWidgetItem(_label(theirs.people[their_id])))
            box = QComboBox()
            box.addItem(t("combine_new"), NEW)
            offered = [m for m in [suggestion.mine, *suggestion.alternatives] if m]
            for my_id in offered + [p for p in everyone if p not in offered]:
                box.addItem(_label(mine.people[my_id]), my_id)
            chosen = start.get(their_id, NEW) if start is not None else (suggestion.mine if suggestion.accepted else NEW)
            box.setCurrentIndex(max(0, box.findData(chosen or NEW)))
            box.currentIndexChanged.connect(lambda _i, r=row: self._changed(r))
            self.table.setCellWidget(row, 1, box)
            self.table.setItem(row, 2, QTableWidgetItem(""))
            self.boxes[their_id] = box
        self.table.currentCellChanged.connect(lambda row, *_rest: self._show_differences(row))

        self.details = QGroupBox()
        self.details_layout = QVBoxLayout(self.details)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("combine_ok"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.table, 3)
        layout.addWidget(self.details, 2)
        layout.addWidget(self.summary)
        layout.addWidget(self.buttons)
        for row in range(len(self.order)):
            self._update_row(row)
        self._update_summary()
        if self.order:
            self.table.selectRow(0)
            self._show_differences(0)

    def chosen(self, their_id):
        return self.boxes[their_id].currentData() or None

    def _changed(self, row):
        self._update_row(row)
        self._update_summary()
        self.table.selectRow(row)
        self._show_differences(row)

    def _update_row(self, row):
        their_id = self.order[row]
        suggestion, my_id = self.suggestions[their_id], self.chosen(their_id)
        if my_id is None:
            text = ""
        elif my_id == suggestion.mine:
            text = t(f"combine_{suggestion.confidence}") if suggestion.confidence else ""
        else:
            text = t("combine_by_hand")
        self.table.item(row, 2).setText(text)

    def _update_summary(self):
        matches = self.matches()
        picked = [self.chosen(their_id) for their_id in self.order if self.chosen(their_id)]
        twice = next((m for m in picked if picked.count(m) > 1), None)
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if twice:
            self.summary.setText(t("combine_twice", name=self.mine.people[twice].display_name))
            ok.setEnabled(False)
            return
        ok.setEnabled(True)
        self.summary.setText(t("combine_summary", added=len(self.order) - len(matches), joined=len(matches)))

    def _show_differences(self, row):
        clear_layout(self.details_layout)
        if not 0 <= row < len(self.order):
            return
        their_id = self.order[row]
        their_person, my_id = self.theirs.people[their_id], self.chosen(their_id)
        self.details.setTitle(their_person.display_name)
        if my_id is None:
            self.details_layout.addWidget(QLabel(t("combine_will_add")))
            return
        found = combine.differences(self.mine.people[my_id], their_person)
        if not found:
            self.details_layout.addWidget(QLabel(t("combine_no_differences")))
            return
        self.details_layout.addWidget(QLabel(t("combine_differences")))
        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        chosen = self.take_theirs.setdefault(their_id, set())
        for line, (key, label, mine_value, their_value) in enumerate(found):
            yours = QRadioButton(t("combine_yours", value=mine_value))
            theirs = QRadioButton(t("combine_theirs", value=their_value))
            group = QButtonGroup(grid_holder)
            group.addButton(yours)
            group.addButton(theirs)
            (theirs if key in chosen else yours).setChecked(True)
            theirs.toggled.connect(lambda on, k=key: chosen.add(k) if on else chosen.discard(k))
            grid.addWidget(QLabel(t(label)), line, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(yours, line, 1)
            grid.addWidget(theirs, line, 2)
        grid.setColumnStretch(3, 1)  # The two choices stay side by side, not spread across.
        self.details_layout.addWidget(grid_holder)
        self.details_layout.addStretch(1)

    def matches(self):
        return {their_id: self.chosen(their_id) for their_id in self.order if self.chosen(their_id)}

    def values(self):
        matches = self.matches()
        take = {their_id: set(keys) for their_id, keys in self.take_theirs.items() if their_id in matches and keys}
        return {"matches": matches, "take_theirs": take}
