"""Small windows for the details of a fact: where it was found (citations of sources),
who else was there (godparents, witnesses), and a person's other names. Plus the
Sources window for the whole tree and the list of facts nobody has a source for yet.

They work on a FactContext: the tree, and a working copy of its sources, so a source
added while editing someone is only stored when that person is saved.
"""
import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from model import (
    CITATION_QUALITIES, NAME_TYPES, ROLES, SOURCE_FIELDS, cited_sources, clean_citations, clean_role_people,
    date_input_text, fold_text, new_id, normalize_date_input, person_events, person_names, stored_facts,
    tree_sources,
)
from screen import fit_hint, fit_to_screen
from strings import t


class FactContext:
    def __init__(self, tree=None, today=None, documents=(), find_person=None):
        self.tree, self.today = tree, today
        self.sources = tree_sources(tree) if tree is not None else {}
        self.documents = list(documents)  # The person's documents a citation can point at.
        self.find_person = find_person  # (title) -> person id or None: the Find window.
        self.sources_changed = False

    def source_title(self, source_id):
        source = self.sources.get(source_id)
        return (source or {}).get("title") or t("source_untitled")

    def person_name(self, entry):
        person = self.tree.people.get(entry.get("person")) if self.tree is not None and entry.get("person") else None
        return person.display_name if person is not None else entry.get("name", "?")

    def add_source(self, values):
        source_id = new_id("s")
        self.sources[source_id] = {key: values.get(key, "").strip() for key in SOURCE_FIELDS}
        self.sources_changed = True
        return source_id


def citation_text(context, citation):
    """'Matična knjiga krštenih, p. 47 (original)'."""
    text = context.source_title(citation["source"])
    if citation.get("page"):
        text += f", {citation['page']}"
    if citation.get("quality") and citation["quality"] != "unknown":
        text += f" ({t('quality_' + citation['quality'])})"
    return text


def role_text(context, entry):
    """'Godfather: Dragan Radić'."""
    return f"{t('role_' + entry['role'])}: {context.person_name(entry)}"


def name_text(item):
    name = " ".join(part for part in (item["given"], item["surname"]) if part)
    when = date_input_text(item.get("date", ""))
    return f"{name} ({t('name_type_' + item['type'])}{', ' + when if when else ''})"


def _ok_cancel(dialog, layout):
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return buttons


class _ListDialog(QDialog):
    """A list with Add, Edit and Remove; subclasses say how one item is shown and edited."""

    def __init__(self, parent, title, items, empty_key):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self.items = [copy.deepcopy(item) for item in items]
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self.edit())
        self.empty = QLabel(t(empty_key))
        self.empty.setWordWrap(True)
        row = QHBoxLayout()
        for key, handler in (("list_add", self.add), ("list_edit", self.edit), ("list_remove", self.remove)):
            button = QPushButton(t(key))
            button.setObjectName(key)
            button.clicked.connect(lambda _checked=False, h=handler: h())
            row.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addWidget(self.empty)
        layout.addLayout(row)
        _ok_cancel(self, layout)
        self._fill()

    def _fill(self, select=0):
        self.list.clear()
        for item in self.items:
            self.list.addItem(self.describe(item))
        self.empty.setVisible(not self.items)
        if self.items:
            self.list.setCurrentRow(max(0, min(select, len(self.items) - 1)))

    def add(self):
        item = self.ask(None)
        if item is not None:
            self.items.append(item)
            self._fill(len(self.items) - 1)

    def edit(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.items):
            item = self.ask(self.items[row])
            if item is not None:
                self.items[row] = item
                self._fill(row)

    def remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.items):
            del self.items[row]
            self._fill(row)

    def values(self):
        return self.items


# Sources and citations.

class SourceDialog(QDialog):
    """One source: a parish book, a census, a letter collection, an aunt's memory."""

    def __init__(self, parent, source=None):
        super().__init__(parent)
        self.setWindowTitle(t("source_title_window"))
        self.setMinimumWidth(460)
        source = source or {}
        self.fields = {key: QLineEdit(source.get(key, "")) for key in ("title", "author", "repository")}
        self.fields["title"].setPlaceholderText(t("source_title_hint"))
        self.fields["repository"].setPlaceholderText(t("source_repository_hint"))
        self.note = QPlainTextEdit(source.get("note", ""))
        self.note.setFixedHeight(70)
        form = QFormLayout()
        for key in ("title", "author", "repository"):
            form.addRow(t(f"source_field_{key}"), self.fields[key])
        form.addRow(t("source_field_note"), self.note)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.buttons = _ok_cancel(self, layout)
        self.fields["title"].textChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.fields["title"].text().strip()))

    def values(self):
        return {**{key: box.text().strip() for key, box in self.fields.items()}, "note": self.note.toPlainText().strip()}


class CitationDialog(QDialog):
    """Which source, where in it, how trustworthy, and the scan of that page."""

    def __init__(self, parent, context, citation=None):
        super().__init__(parent)
        self.context = context
        self.setWindowTitle(t("citation_title"))
        self.setMinimumWidth(480)
        citation = citation or {}
        self.source = QComboBox()
        self._fill_sources(citation.get("source"))
        new_source = QPushButton(t("citation_new_source"))
        new_source.clicked.connect(self.new_source)
        source_row = QWidget()
        row = QHBoxLayout(source_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.source, 1)
        row.addWidget(new_source)
        self.page = QLineEdit(citation.get("page", ""))
        self.page.setPlaceholderText(t("citation_page_hint"))
        self.quality = QComboBox()
        for quality in CITATION_QUALITIES:
            self.quality.addItem(t(f"quality_{quality}"), quality)
        self.quality.setCurrentIndex(max(0, self.quality.findData(citation.get("quality", "unknown"))))
        self.document = QComboBox()
        self.document.addItem(t("citation_no_document"), "")
        for document in context.documents:
            self.document.addItem(document.get("title") or document["file"], document["file"])
        self.document.setCurrentIndex(max(0, self.document.findData(citation.get("document", ""))))
        self.document.setEnabled(bool(context.documents))
        form = QFormLayout()
        form.addRow(t("citation_source"), source_row)
        form.addRow(t("citation_page"), self.page)
        form.addRow(t("citation_quality"), self.quality)
        form.addRow(t("citation_document"), self.document)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.buttons = _ok_cancel(self, layout)
        self.source.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def _fill_sources(self, selected=None):
        self.source.blockSignals(True)
        self.source.clear()
        for source_id in sorted(self.context.sources, key=lambda s: fold_text(self.context.source_title(s))):
            self.source.addItem(self.context.source_title(source_id), source_id)
        self.source.setCurrentIndex(max(0, self.source.findData(selected)) if self.source.count() else -1)
        self.source.blockSignals(False)

    def ask_source(self):
        dialog = SourceDialog(self)
        return dialog.values() if dialog.exec() else None

    def new_source(self):
        values = self.ask_source()
        if values:
            self._fill_sources(self.context.add_source(values))
            self._refresh()

    def _refresh(self):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.source.currentData() is not None)

    def values(self):
        entry = {"source": self.source.currentData()}
        if self.page.text().strip():
            entry["page"] = self.page.text().strip()
        if self.quality.currentData() != "unknown":
            entry["quality"] = self.quality.currentData()
        if self.document.currentData():
            entry["document"] = self.document.currentData()
        return entry


class CitationsDialog(_ListDialog):
    def __init__(self, parent, context, citations, what):
        self.context = context
        super().__init__(parent, t("citations_title", what=what), clean_citations(citations), "citations_empty")

    def describe(self, item):
        return citation_text(self.context, item)

    def ask(self, item):
        dialog = CitationDialog(self, self.context, item)
        return dialog.values() if dialog.exec() else None


# The people at an event.

class RoleDialog(QDialog):
    """Someone at an event: a person in the tree, or a name as written in the record."""

    def __init__(self, parent, context, entry=None):
        super().__init__(parent)
        self.context = context
        self.setWindowTitle(t("role_window_title"))
        self.setMinimumWidth(440)
        entry = entry or {"role": "godfather"}
        self.person_id = entry.get("person", "")
        self.role = QComboBox()
        for role in ROLES:
            self.role.addItem(t(f"role_{role}"), role)
        self.role.setCurrentIndex(max(0, self.role.findData(entry.get("role"))))
        self.chosen = QLabel()
        choose = QPushButton(t("role_choose_person"))
        choose.clicked.connect(self.choose_person)
        choose.setEnabled(context.find_person is not None)
        clear = QPushButton(t("role_clear_person"))
        clear.clicked.connect(lambda: self.set_person(""))
        person_row = QWidget()
        row = QHBoxLayout(person_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.chosen, 1)
        row.addWidget(choose)
        row.addWidget(clear)
        self.name = QLineEdit(entry.get("name", ""))
        self.name.setPlaceholderText(t("role_name_hint"))
        form = QFormLayout()
        form.addRow(t("role_field_role"), self.role)
        form.addRow(t("role_field_person"), person_row)
        form.addRow(t("role_field_name"), self.name)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.buttons = _ok_cancel(self, layout)
        self.name.textChanged.connect(self._refresh)
        self.set_person(self.person_id)

    def choose_person(self):
        chosen = self.context.find_person(t("role_choose_person"))
        if chosen:
            self.set_person(chosen)

    def set_person(self, person_id):
        self.person_id = person_id or ""
        self.chosen.setText(self.context.person_name({"person": self.person_id}) if self.person_id
                            else t("role_no_person"))
        self._refresh()

    def _refresh(self):
        ok = bool(self.person_id or self.name.text().strip())
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def values(self):
        entry = {"role": self.role.currentData()}
        if self.person_id:
            entry["person"] = self.person_id
        if self.name.text().strip():
            entry["name"] = self.name.text().strip()
        return entry


class PeopleDialog(_ListDialog):
    def __init__(self, parent, context, people, what):
        self.context = context
        super().__init__(parent, t("people_title", what=what), clean_role_people(people), "people_empty")

    def describe(self, item):
        return role_text(self.context, item)

    def ask(self, item):
        dialog = RoleDialog(self, self.context, item)
        return dialog.values() if dialog.exec() else None


# Other names.

class NameDialog(QDialog):
    def __init__(self, parent, context, item=None):
        super().__init__(parent)
        self.context = context
        self.setWindowTitle(t("other_name_title"))
        self.setMinimumWidth(440)
        item = item or {"type": "other"}
        self.given = QLineEdit(item.get("given", ""))
        self.surname = QLineEdit(item.get("surname", ""))
        self.kind = QComboBox()
        for kind in NAME_TYPES:
            self.kind.addItem(t(f"name_type_{kind}"), kind)
        self.kind.setCurrentIndex(max(0, self.kind.findData(item.get("type"))))
        self.date = QLineEdit(item.get("date", ""))
        fit_hint(self.date, t("date_hint"))
        self.citations = clean_citations(item.get("citations"))
        self.cite = QPushButton()
        self.cite.clicked.connect(self.edit_citations)
        self._label_citations()
        form = QFormLayout()
        form.addRow(t("field_given"), self.given)
        form.addRow(t("field_surname"), self.surname)
        form.addRow(t("other_name_type"), self.kind)
        form.addRow(t("other_name_date"), self.date)
        form.addRow(t("field_sources"), self.cite)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.buttons = _ok_cancel(self, layout)
        for box in (self.given, self.surname, self.date):
            box.textChanged.connect(self._refresh)
        self._refresh()

    def _label_citations(self):
        self.cite.setText(t("button_sources", count=len(self.citations)))

    def edit_citations(self):
        dialog = CitationsDialog(self, self.context, self.citations, t("other_name_title"))
        if dialog.exec():
            self.citations = dialog.values()
            self._label_citations()

    def _refresh(self):
        ok = bool(self.given.text().strip() or self.surname.text().strip()) \
            and normalize_date_input(self.date.text()) is not None
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def values(self):
        item = {"given": self.given.text().strip(), "surname": self.surname.text().strip(),
                "type": self.kind.currentData(), "date": self.date.text().strip()}
        if self.citations:
            item["citations"] = self.citations
        return item


class NamesDialog(_ListDialog):
    def __init__(self, parent, context, names):
        self.context = context
        super().__init__(parent, t("other_names_title"), names, "other_names_empty")

    def describe(self, item):
        return name_text({**item, "date": normalize_date_input(item.get("date", "")) or ""})

    def ask(self, item):
        dialog = NameDialog(self, self.context, item)
        return dialog.values() if dialog.exec() else None


class FactDetails(QWidget):
    """Two buttons under a fact: "Sources (2)..." and "People (1)..."; keeps what they edit."""

    def __init__(self, context, fact, what, people=True):
        super().__init__()
        self.context, self.what = context, what
        self.citations = clean_citations((fact or {}).get("citations"))
        self.people = clean_role_people((fact or {}).get("people"))
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.sources_button = QPushButton()
        self.sources_button.clicked.connect(self.edit_citations)
        row.addWidget(self.sources_button)
        self.people_button = QPushButton()
        self.people_button.clicked.connect(self.edit_people)
        self.people_button.setVisible(people)
        row.addWidget(self.people_button)
        row.addStretch(1)
        self._label()

    def _label(self):
        self.sources_button.setText(t("button_sources", count=len(self.citations)))
        self.people_button.setText(t("button_people", count=len(self.people)))

    def ask_citations(self):
        dialog = CitationsDialog(self, self.context, self.citations, self.what)
        return dialog.values() if dialog.exec() else None

    def ask_people(self):
        dialog = PeopleDialog(self, self.context, self.people, self.what)
        return dialog.values() if dialog.exec() else None

    def edit_citations(self):
        chosen = self.ask_citations()
        if chosen is not None:
            self.citations = chosen
            self._label()

    def edit_people(self):
        chosen = self.ask_people()
        if chosen is not None:
            self.people = chosen
            self._label()

    def values(self):
        found = {}
        if self.citations:
            found["citations"] = self.citations
        if self.people:
            found["people"] = self.people
        return found


# The whole tree's sources.

class SourcesDialog(QDialog):
    """Every source with how often it is cited: edit, add, remove, or merge two that are
    the same book. values() gives (sources, {merged id: kept id}, removed ids)."""

    def __init__(self, parent, tree):
        super().__init__(parent)
        self.setWindowTitle(t("sources_title"))
        fit_to_screen(self, 640, 460)
        self.sources = tree_sources(tree)
        self.uses = cited_sources(tree)
        self.merged, self.removed = {}, set()
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self.edit())
        self.empty = QLabel(t("sources_empty"))
        self.empty.setWordWrap(True)
        row = QHBoxLayout()
        for key, handler in (("list_add", self.add), ("list_edit", self.edit), ("sources_merge", self.merge),
                             ("list_remove", self.remove)):
            button = QPushButton(t(key))
            button.setObjectName(key)
            button.clicked.connect(lambda _checked=False, h=handler: h())
            row.addWidget(button)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addWidget(self.empty)
        layout.addLayout(row)
        layout.addWidget(self.note)
        _ok_cancel(self, layout)
        self._fill()

    def order(self):
        return sorted(self.sources, key=lambda s: fold_text(self.sources[s]["title"]))

    def _fill(self, select=None):
        self.list.clear()
        for source_id in self.order():
            source = self.sources[source_id]
            item = QListWidgetItem(t("sources_row", title=source["title"] or t("source_untitled"),
                                     count=self.uses.get(source_id, 0)))
            item.setData(Qt.ItemDataRole.UserRole, source_id)
            self.list.addItem(item)
            if source_id == select:
                self.list.setCurrentItem(item)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)
        self.empty.setVisible(not self.sources)

    def current(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def ask_source(self, source):
        dialog = SourceDialog(self, source)
        return dialog.values() if dialog.exec() else None

    def ask_merge_target(self, source_id):
        """Which other source this one is the same as, or None."""
        others = [s for s in self.order() if s != source_id]
        if not others:
            return None
        from PySide6.QtWidgets import QInputDialog
        labels = [self.sources[s]["title"] or t("source_untitled") for s in others]
        chosen, ok = QInputDialog.getItem(self, t("sources_merge"), t("sources_merge_into",
                                                                     title=self.sources[source_id]["title"]),
                                          labels, 0, False)
        return others[labels.index(chosen)] if ok else None

    def add(self):
        values = self.ask_source(None)
        if values:
            source_id = new_id("s")
            self.sources[source_id] = values
            self._fill(source_id)

    def edit(self):
        source_id = self.current()
        if source_id is not None:
            values = self.ask_source(self.sources[source_id])
            if values:
                self.sources[source_id] = values
                self._fill(source_id)

    def merge(self):
        source_id = self.current()
        target = self.ask_merge_target(source_id) if source_id is not None else None
        if target is not None:
            self.merged[source_id] = target
            for old, new in list(self.merged.items()):  # A source merged earlier into this one follows it.
                if new == source_id:
                    self.merged[old] = target
            self.uses[target] = self.uses.get(target, 0) + self.uses.pop(source_id, 0)
            del self.sources[source_id]
            self._fill(target)

    def remove(self):
        """A source still cited can't simply go: its citations would point at nothing."""
        source_id = self.current()
        if source_id is None:
            return
        if self.uses.get(source_id):
            self.note.setText(t("sources_in_use", count=self.uses[source_id]))
            return
        self.removed.add(source_id)
        del self.sources[source_id]
        self._fill()

    def values(self):
        return self.sources, self.merged, self.removed


class UnsourcedDialog(QDialog):
    """Facts with no source yet, to know what still needs proof. Double-click goes there."""

    def __init__(self, parent, tree):
        super().__init__(parent)
        self.setWindowTitle(t("unsourced_title"))
        fit_to_screen(self, 560, 480)
        self.chosen = None
        self.rows = unsourced_facts(tree)
        intro = QLabel(t("unsourced_intro", count=len(self.rows)))
        intro.setWordWrap(True)
        self.list = QListWidget()
        for person_id, label in self.rows:
            self.list.addItem(label)
        self.list.itemDoubleClicked.connect(self._chosen)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _chosen(self, item):
        self.chosen = self.rows[self.list.row(item)][0]
        self.accept()


def unsourced_facts(tree):
    """[(person id, 'Born: Ivan Radić, 1921')] for recorded facts without any citation."""
    found = []
    for person in sorted(tree.people.values(), key=lambda p: (fold_text(p.surname), fold_text(p.given), p.id)):
        if person.extra.get("hidden"):
            continue
        facts = [("fact_birth", person.birth), ("fact_death", person.death)]
        facts += [(f"event_{e['type']}", e) for e in person_events(person)]
        for label, fact in facts:
            if fact and (fact.get("date") or fact.get("place") or fact.get("text")) \
                    and not clean_citations(fact.get("citations")):
                when = date_input_text(fact.get("date", ""))
                found.append((person.id, f"{t(label)}: {person.display_name}{', ' + when if when else ''}"))
        for item in person_names(person):
            if not item.get("citations"):
                found.append((person.id, f"{t('other_name_title')}: {person.display_name} - {name_text(item)}"))
    seen = set()
    for owner, kind, fact in stored_facts(tree):
        if kind == "marriage" and owner not in seen and (fact.get("date") or fact.get("place")) \
                and not clean_citations(fact.get("citations")):
            seen.add(owner)
            family = tree.families[owner]
            names = [tree.people[p].display_name for p in family.partners if p in tree.people]
            if names:
                found.append((family.partners[0], f"{t('fact_marriage')}: {t('names_and', a=names[0], b=names[-1])}"
                              if len(names) > 1 else f"{t('fact_marriage')}: {names[0]}"))
    return found
