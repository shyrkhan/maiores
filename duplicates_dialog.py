"""The window for possible duplicates: pick a pair, see both side by side, then merge
(keeping either one) or say they are different people. One answer at a time: the main
window applies it and opens the list again from the tree as it now is."""
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QListWidget, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from model import date_input_text, fold_text, person_names
from screen import fit_to_screen
from strings import t
import theme


def _label(person):
    years = person.years_label()
    return f"{person.display_name} ({years})" if years else person.display_name


def _rows(tree, person):
    """(label key, text) for the comparison table."""
    def names(ids):
        return ", ".join(tree.people[p].display_name for p in ids if p in tree.people)

    parents = [p for f, link in tree.parent_families(person.id) if link == "birth" for p in f.partners]
    partners, children = [], []
    for family in tree.families_of(person.id):
        partners += [p for p in family.partners if p != person.id]
        children += family.child_ids
    birth, death = person.birth or {}, person.death or {}
    return [
        ("field_given", person.given), ("field_surname", person.surname),
        ("field_birth_surname", person.birth_surname),
        ("field_other_names", ", ".join(f"{n['given']} {n['surname']}".strip() for n in person_names(person))),
        ("field_sex", t({"M": "sex_male", "F": "sex_female", "X": "sex_other"}[person.sex]) if person.sex else ""),
        ("panel_born", date_input_text(birth.get("date", ""))), ("field_birth_place", birth.get("place", "")),
        ("panel_died", date_input_text(death.get("date", ""))), ("field_death_place", death.get("place", "")),
        ("panel_parents", names(parents)), ("panel_partners", names(partners)), ("panel_children", names(children)),
    ]


class DuplicatesDialog(QDialog):
    def __init__(self, parent, tree, candidates, selected=0):
        super().__init__(parent)
        self.tree, self.candidates = tree, candidates
        self.answer = None
        self.setWindowTitle(t("duplicates_title"))
        fit_to_screen(self, 940, 600)
        intro = QLabel(t("duplicates_intro", count=len(candidates)))
        intro.setWordWrap(True)
        self.list = QListWidget()
        self.list.setMinimumWidth(320)
        self.list.setSpacing(3)
        self.list.setAlternatingRowColors(True)  # Each entry is two lines: keep pairs apart.
        for candidate in candidates:
            a, b = tree.people[candidate.a], tree.people[candidate.b]
            self.list.addItem(f"{_label(a)}\n{_label(b)}")
        self.table = QTableWidget(0, 3)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.reasons = QLabel()
        self.reasons.setWordWrap(True)
        self.keep_left = QPushButton(t("duplicates_keep_left"))
        self.keep_right = QPushButton(t("duplicates_keep_right"))
        self.different = QPushButton(t("duplicates_different"))
        self.keep_left.clicked.connect(lambda: self._answer("merge", left=True))
        self.keep_right.clicked.connect(lambda: self._answer("merge", left=False))
        self.different.clicked.connect(lambda: self._answer("different"))
        actions = QHBoxLayout()
        for button in (self.keep_left, self.keep_right, self.different):
            actions.addWidget(button)
        right = QVBoxLayout()
        right.addWidget(self.table, 1)
        right.addWidget(self.reasons)
        right.addLayout(actions)
        body = QHBoxLayout()
        body.addWidget(self.list)
        body.addLayout(right, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(body, 1)
        layout.addWidget(close)
        self.list.currentRowChanged.connect(self._show)
        if candidates:
            self.list.setCurrentRow(max(0, min(selected, len(candidates) - 1)))

    def _show(self, row):
        if not 0 <= row < len(self.candidates):
            return
        candidate = self.candidates[row]
        a, b = self.tree.people[candidate.a], self.tree.people[candidate.b]
        self.table.setHorizontalHeaderLabels(["", t("duplicates_first"), t("duplicates_second")])
        left, right = _rows(self.tree, a), _rows(self.tree, b)
        shown = [(key, x, y) for (key, x), (_k, y) in zip(left, right) if x or y]
        self.table.setRowCount(len(shown))
        for line, (key, x, y) in enumerate(shown):
            self.table.setItem(line, 0, QTableWidgetItem(t(key)))
            for column, text in ((1, x), (2, y)):
                item = QTableWidgetItem(text)
                if x and y and fold_text(x) != fold_text(y):
                    item.setForeground(theme.colour("warn"))  # The two records disagree here.
                self.table.setItem(line, column, item)
        lines = [t(reason) for reason in candidate.reasons]
        if candidate.blocked:
            lines.append(t(candidate.blocked))
        self.reasons.setText(" · ".join(lines))
        for button in (self.keep_left, self.keep_right):
            button.setEnabled(not candidate.blocked)

    def _answer(self, action, left=True):
        row = self.list.currentRow()
        if not 0 <= row < len(self.candidates):
            return
        candidate = self.candidates[row]
        keep, other = (candidate.a, candidate.b) if left else (candidate.b, candidate.a)
        self.answer = (action, keep, other, row)
        self.accept()
