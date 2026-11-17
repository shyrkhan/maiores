"""Research tools: a to-do list per person ("find the death in the Trogir books"), the
list of every open task in the tree, and a person's life story written out in full.
To-do items are your own working notes and never leave the computer."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QVBoxLayout,
)

from model import fold_text, person_story, person_tasks
from screen import fit_to_screen
from strings import t


def _ok_cancel(dialog, layout):
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)


class TasksDialog(QDialog):
    def __init__(self, parent, person):
        super().__init__(parent)
        self.setWindowTitle(t("tasks_title", name=person.display_name))
        self.setMinimumSize(460, 360)
        self.tasks = person_tasks(person)
        hint = QLabel(t("tasks_hint"))
        hint.setWordWrap(True)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self.edit())
        self.list.itemChanged.connect(self._ticked)
        row = QHBoxLayout()
        for key, handler in (("list_add", self.add), ("list_edit", self.edit), ("list_remove", self.remove)):
            button = QPushButton(t(key))
            button.clicked.connect(lambda _checked=False, h=handler: h())
            row.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.list, 1)
        layout.addLayout(row)
        _ok_cancel(self, layout)
        self._fill()

    def _fill(self, select=0):
        self.list.blockSignals(True)
        self.list.clear()
        for task in self.tasks:
            item = QListWidgetItem(task["text"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if task["done"] else Qt.CheckState.Unchecked)
            item.setToolTip(task.get("note", ""))
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self.tasks:
            self.list.setCurrentRow(max(0, min(select, len(self.tasks) - 1)))

    def _ticked(self, item):
        self.tasks[self.list.row(item)]["done"] = item.checkState() == Qt.CheckState.Checked

    def ask_text(self, current=""):
        text, ok = QInputDialog.getText(self, t("tasks_task"), t("tasks_task"), text=current)
        return text.strip() if ok and text.strip() else None

    def add(self):
        text = self.ask_text()
        if text:
            self.tasks.append({"text": text, "done": False, "note": ""})
            self._fill(len(self.tasks) - 1)

    def edit(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.tasks):
            text = self.ask_text(self.tasks[row]["text"])
            if text:
                self.tasks[row]["text"] = text
                self._fill(row)

    def remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.tasks):
            del self.tasks[row]
            self._fill(row)

    def values(self):
        return self.tasks


class StoryDialog(QDialog):
    def __init__(self, parent, person):
        super().__init__(parent)
        self.setWindowTitle(t("story_title", name=person.display_name))
        fit_to_screen(self, 640, 520)
        hint = QLabel(t("story_hint"))
        hint.setWordWrap(True)
        self.text = QPlainTextEdit(person_story(person))
        self.private = QCheckBox(t("story_private"))
        self.private.setChecked(bool(person.extra.get("story_private")))
        self.private.setToolTip(t("field_private_tip"))
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.private)
        _ok_cancel(self, layout)

    def values(self):
        return self.text.toPlainText(), self.private.isChecked()


class ResearchDialog(QDialog):
    """Every to-do item in the tree, open ones first. Double-click goes to the person."""

    def __init__(self, parent, tree):
        super().__init__(parent)
        self.setWindowTitle(t("research_title"))
        fit_to_screen(self, 620, 520)
        self.tree, self.chosen = tree, None
        self.rows = []
        for person in sorted(tree.people.values(), key=lambda p: (fold_text(p.surname), fold_text(p.given))):
            for task in person_tasks(person):
                self.rows.append((task["done"], person.id, f"{task['text']}   - {person.display_name}"))
        self.rows.sort(key=lambda row: row[0])
        self.intro = QLabel()
        self.show_done = QCheckBox(t("research_show_done"))
        self.show_done.toggled.connect(self._fill)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._go)
        layout = QVBoxLayout(self)
        layout.addWidget(self.intro)
        layout.addWidget(self.show_done)
        layout.addWidget(self.list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._fill()

    def _fill(self, *_args):
        self.list.clear()
        self.shown = [row for row in self.rows if self.show_done.isChecked() or not row[0]]
        for done, _person, text in self.shown:
            self.list.addItem(("☑ " if done else "☐ ") + text)
        self.intro.setText(t("research_intro", count=sum(1 for row in self.rows if not row[0])))

    def _go(self, item):
        self.chosen = self.shown[self.list.row(item)][1]
        self.accept()
