"""The DNA window: one person's DNA tests, their matches (imported or typed in), what each
match's shared amount could mean and how it fits the tree, and a chromosome map.

Everything is changed on a copy of the tests; the window returns them, and the main
window stores them as one edit (one undo)."""
import copy
import gzip
import re
import uuid
import zipfile
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

import dna
import kinship
import strings
import theme
from screen import fit_to_screen
from strings import t

RAW_DIR = "dna"  # Raw files live in the tree's folder; shared copies never take them.


def relation_name(up, down, half=False):
    """'first cousin once removed' (or the Croatian), else the usual shorthand: 1C1R."""
    relation = kinship.Relation("blood", up, down, half)
    language = strings.LANGUAGE
    if language == "hr":
        return kinship._hr_blood(relation)
    if language == "en":
        return kinship._en_blood(relation)
    return shorthand(up, down, half)


def pair_name(up, down, half=False):
    """Both ways round, since a match could be either: 'grandparent / grandchild'."""
    first = relation_name(up, down, half)
    if up == down:
        return first
    second = relation_name(down, up, half)
    return first if second == first else f"{first} / {second}"


def shorthand(up, down, half=False):
    prefix = "Half " if half else ""
    if min(up, down) <= 1:
        far = max(up, down)
        names = {(1, 0): "Parent/Child", (1, 1): "Sibling", (2, 0): "Grandparent", (2, 1): "Aunt/Niece"}
        if (far, min(up, down)) in names:
            return prefix + names[(far, min(up, down))]
        return prefix + ("G" * (far - 2) + "-Grandparent" if min(up, down) == 0 else "G" * (far - 2) + "-Aunt/Niece")
    degree, removed = min(up, down) - 1, abs(up - down)
    return f"{prefix}{degree}C" + (f"{removed}R" if removed else "")


_RAW_LINE = re.compile(r'^"?(rs|i)\d+"?[\t,]"?[0-9XYMT]{1,2}"?[\t,]"?\d+"?[\t,]"?[ACGTDI0-]{1,2}"?', re.IGNORECASE)


def looks_raw(data):
    """Raw genotype data rather than a match list: lines like "rs4477212  1  82154  AA"."""
    lines = [line for line in data[:40000].decode("utf-8", "replace").splitlines()
             if line.strip() and not line.startswith("#")][1:30]
    return bool(lines) and sum(1 for line in lines if _RAW_LINE.match(line.strip())) >= len(lines) * 0.8


def unpack(path):
    """The bytes of a file; for a zip (AncestryDNA, 23andMe downloads), its data file."""
    path = Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith((".txt", ".csv")) and "readme" not in n.lower()]
            if names:
                return archive.read(max(names, key=lambda n: archive.getinfo(n).file_size))
        return b""
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rb") as handle:
            return handle.read()
    return path.read_bytes()


class ChromosomeMap(QWidget):
    """The 22 chromosomes (and X), drawn to scale in cM, with shared segments on them.
    Each match has a colour; matches on the father's or mother's side, as the tree says,
    take that side's colour."""

    def __init__(self):
        super().__init__()
        self.segments, self.colours = [], {}
        self.setMinimumHeight(420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def show_segments(self, segments, colours):
        self.segments, self.colours = segments, colours
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        names = dna.AUTOSOMES + ["X"]
        longest = max(dna.chromosome_length(c) for c in names)
        label_w, gap = 34, 4
        row_h = max(10.0, (self.height() - 8) / len(names) - gap)
        width = self.width() - label_w - 12
        painter.setFont(self.font())
        for row, chromosome in enumerate(names):
            y = 4 + row * (row_h + gap)
            length = dna.chromosome_length(chromosome)
            bar = QRectF(label_w, y, width * length / longest, row_h)
            painter.setPen(theme.colour("soft"))
            painter.drawText(QRectF(0, y, label_w - 6, row_h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             chromosome)
            painter.setPen(QPen(theme.colour("divider"), 1))
            painter.setBrush(theme.colour("tile"))
            painter.drawRoundedRect(bar, row_h / 2, row_h / 2)
            own = [s for s in self.segments if s["chr"] == chromosome]
            lanes = list(dict.fromkeys(s["match"] for s in own))[:4]  # One lane per match.
            lane_h = bar.height() / max(1, len(lanes))
            for segment in own:
                if segment["match"] not in lanes:
                    continue
                lane = lanes.index(segment["match"])
                start = dna.position_cm(chromosome, segment["start"])
                end = dna.position_cm(chromosome, segment["end"])
                x0 = bar.left() + bar.width() * start / length if length else bar.left()
                x1 = bar.left() + bar.width() * end / length if length else bar.left()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self.colours.get(segment["match"], theme.colour("highlight")))
                lane_y = bar.top() + lane * lane_h
                painter.drawRect(QRectF(x0, lane_y, max(2.0, x1 - x0), lane_h))


class TestDialog(QDialog):
    def __init__(self, parent, test):
        super().__init__(parent)
        self.setWindowTitle(t("dna_test_title"))
        self.company = QComboBox()
        self.company.setEditable(True)
        self.company.addItems(list(dna.COMPANIES))
        self.company.setCurrentText(test.get("company") or "MyHeritage")
        self.kind = QComboBox()
        for kind in dna.KINDS:
            self.kind.addItem(t(f"dna_kind_{kind}"), kind)
        self.kind.setCurrentIndex(max(0, self.kind.findData(test.get("kind", "autosomal"))))
        self.kit = QLineEdit(test.get("kit", ""))
        self.haplogroup = QLineEdit(test.get("haplogroup", ""))
        self.notes = QTextEdit(test.get("notes", ""))
        self.notes.setMaximumHeight(80)
        form = QFormLayout()
        form.addRow(t("dna_company"), self.company)
        form.addRow(t("dna_kind"), self.kind)
        form.addRow(t("dna_kit"), self.kit)
        form.addRow(t("dna_haplogroup"), self.haplogroup)
        form.addRow(t("field_notes"), self.notes)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self):
        return {"company": self.company.currentText().strip() or "Other", "kind": self.kind.currentData(),
                "kit": self.kit.text().strip(), "haplogroup": self.haplogroup.text().strip(),
                "notes": self.notes.toPlainText().strip()}


class MatchDialog(QDialog):
    def __init__(self, parent, match, tree, find_person):
        super().__init__(parent)
        self.setWindowTitle(t("dna_match_title"))
        self.tree, self.find_person, self.person = tree, find_person, match.get("person", "")
        self.name = QLineEdit(match.get("name", ""))
        self.cm = QDoubleSpinBox()
        self.cm.setRange(0, 4000)
        self.cm.setDecimals(1)
        self.cm.setSuffix(" cM")
        self.cm.setValue(match.get("cm") or 0)
        self.segments = QSpinBox()
        self.segments.setRange(0, 200)
        self.segments.setValue(match.get("segments") or 0)
        self.longest = QDoubleSpinBox()
        self.longest.setRange(0, 300)
        self.longest.setDecimals(1)
        self.longest.setSuffix(" cM")
        self.longest.setValue(match.get("longest") or 0)
        self.guess = QLineEdit(match.get("guess", ""))
        self.notes = QTextEdit(match.get("notes", ""))
        self.notes.setMaximumHeight(80)
        self.linked = QLabel()
        choose = QPushButton(t("dna_link_person"))
        choose.clicked.connect(self._choose)
        unlink = QPushButton(t("dna_unlink"))
        unlink.clicked.connect(lambda: self._set_person(""))
        who = QHBoxLayout()
        who.addWidget(self.linked, 1)
        who.addWidget(choose)
        who.addWidget(unlink)
        form = QFormLayout()
        form.addRow(t("dna_match_name"), self.name)
        form.addRow(t("dna_shared"), self.cm)
        form.addRow(t("dna_segments"), self.segments)
        form.addRow(t("dna_longest"), self.longest)
        form.addRow(t("dna_company_guess"), self.guess)
        form.addRow(t("dna_in_tree"), who)
        form.addRow(t("field_notes"), self.notes)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._set_person(self.person)

    def _set_person(self, person_id):
        self.person = person_id if person_id in self.tree.people else ""
        self.linked.setText(self.tree.people[self.person].display_name if self.person else t("dna_not_linked"))

    def _choose(self):
        chosen = self.find_person(t("dna_link_person")) if self.find_person else None
        if chosen:
            self._set_person(chosen)
            if not self.name.text().strip():
                self.name.setText(self.tree.people[chosen].display_name)

    def values(self):
        return {"name": self.name.text().strip(), "cm": self.cm.value() or None,
                "segments": self.segments.value() or None, "longest": self.longest.value() or None,
                "guess": self.guess.text().strip(), "notes": self.notes.toPlainText().strip(), "person": self.person}


class DnaDialog(QDialog):
    """`tests` is a copy to change; `raw_folder` is the tree folder (raw files go in it);
    `raw_tests` gives [(person id, test)] of everyone with a raw file, to compare with."""

    COLUMNS = ("dna_match_name", "dna_shared", "dna_segments", "dna_longest", "dna_company_guess",
               "dna_could_be", "dna_in_tree", "dna_check")

    def __init__(self, parent, tree, person_id, folder, find_person=None, side_colours=None, ask_file=None):
        super().__init__(parent)
        self.tree, self.person_id, self.folder = tree, person_id, Path(folder) if folder else None
        self.find_person, self.ask_file = find_person, ask_file
        self.side_colours = side_colours or {}
        self.tests = copy.deepcopy(dna.tests_of(tree.people[person_id]))
        self.others = {}  # Other people's tests changed here (compared with), by person id.
        self.new_raw_files = []  # Written now; removed again if the window is cancelled.
        self.setWindowTitle(t("dna_title", name=tree.people[person_id].display_name))
        fit_to_screen(self, 1080, 720)

        self.test_box = QComboBox()
        self.test_box.currentIndexChanged.connect(self._show_test)
        self.read_only = False
        add_test = self.add_test_button = QPushButton(t("dna_add_test"))
        add_test.clicked.connect(self.add_test)
        self.edit_test_button = QPushButton(t("dna_edit_test"))
        self.edit_test_button.clicked.connect(self.edit_test)
        self.remove_test_button = QPushButton(t("dna_remove_test"))
        self.remove_test_button.clicked.connect(self.remove_test)
        top = QHBoxLayout()
        top.addWidget(QLabel(t("dna_test")))
        top.addWidget(self.test_box, 1)
        for button in (add_test, self.edit_test_button, self.remove_test_button):
            top.addWidget(button)
        self.test_info = QLabel()
        self.test_info.setWordWrap(True)

        self.import_button = QPushButton(t("dna_import"))
        self.import_button.setToolTip(t("dna_import_tip"))
        self.import_button.clicked.connect(self.import_file)
        self.add_match_button = QPushButton(t("dna_add_match"))
        self.add_match_button.clicked.connect(self.add_match)
        self.edit_match_button = QPushButton(t("dna_edit_match"))
        self.edit_match_button.clicked.connect(self.edit_match)
        self.remove_match_button = QPushButton(t("dna_remove_match"))
        self.remove_match_button.clicked.connect(self.remove_match)
        self.compare_button = QPushButton(t("dna_compare"))
        self.compare_button.setToolTip(t("dna_compare_tip"))
        self.compare_button.clicked.connect(self.compare_with)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(t("dna_filter"))
        self.filter.textChanged.connect(self._fill_matches)
        actions = QHBoxLayout()
        for widget in (self.import_button, self.add_match_button, self.edit_match_button, self.remove_match_button,
                       self.compare_button):
            actions.addWidget(widget)
        actions.addStretch(1)
        actions.addWidget(self.filter)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([t(key) for key in self.COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        self.table.itemDoubleClicked.connect(lambda _item: self.edit_match())
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.explain = QLabel()
        self.explain.setWordWrap(True)
        matches_page = QWidget()
        matches_layout = QVBoxLayout(matches_page)
        matches_layout.addLayout(actions)
        matches_layout.addWidget(self.table, 1)
        matches_layout.addWidget(self.explain)

        self.chromosomes = ChromosomeMap()
        self.legend = QLabel()
        self.legend.setWordWrap(True)
        map_page = QWidget()
        map_layout = QVBoxLayout(map_page)
        map_hint = QLabel(t("dna_map_hint"))
        map_hint.setWordWrap(True)
        map_layout.addWidget(map_hint)
        map_layout.addWidget(self.chromosomes, 1)
        map_layout.addWidget(self.legend)

        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 4000)
        self.amount.setDecimals(0)
        self.amount.setSuffix(" cM")
        self.amount.setValue(300)
        self.amount.valueChanged.connect(self._fill_possible)
        self.possible_list = QListWidget()
        calc_page = QWidget()
        calc_layout = QVBoxLayout(calc_page)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("dna_amount")))
        row.addWidget(self.amount)
        row.addStretch(1)
        calc_layout.addLayout(row)
        calc_layout.addWidget(self.possible_list, 1)

        self.tabs = QTabWidget()
        self.tabs.addTab(matches_page, t("dna_tab_matches"))
        self.tabs.addTab(map_page, t("dna_tab_map"))
        self.tabs.addTab(calc_page, t("dna_tab_amount"))
        credit = QLabel(f"{t('dna_private')}\n{t('dna_credit', credit=dna.CREDIT)}")
        credit.setWordWrap(True)
        credit.setStyleSheet(f"color: {theme.hex('soft')}")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.test_info)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(credit)
        layout.addWidget(buttons)
        self._fill_tests()
        self._fill_possible()

    # Tests.
    def current_test(self):
        index = self.test_box.currentIndex()
        return self.tests[index] if 0 <= index < len(self.tests) else None

    def _test_label(self, test):
        parts = [test["company"], t(f"dna_kind_{test['kind']}")]
        if test["kit"]:
            parts.append(test["kit"])
        return " · ".join(parts)

    def _fill_tests(self, select=None):
        self.test_box.blockSignals(True)
        self.test_box.clear()
        for test in self.tests:
            self.test_box.addItem(self._test_label(test))
        self.test_box.blockSignals(False)
        if self.tests:
            self.test_box.setCurrentIndex(select if select is not None else 0)
        self._show_test()

    def _show_test(self):
        test = self.current_test()
        for widget in (self.edit_test_button, self.remove_test_button, self.import_button, self.add_match_button,
                       self.compare_button):
            widget.setEnabled(test is not None and not self.read_only)
        self.filter.setEnabled(test is not None)
        self.add_test_button.setEnabled(not self.read_only)
        if test is None:
            self.test_info.setText(t("dna_no_tests"))
        else:
            parts = []
            if test["haplogroup"]:
                parts.append(t("dna_haplogroup_is", group=test["haplogroup"]))
            if test.get("raw"):
                raw = test["raw"]
                parts.append(t("dna_raw_kept", snps=f"{raw['snps']:,}".replace(",", ".")))
            parts.append(t("dna_match_count", count=len(test["matches"])))
            self.test_info.setText(" · ".join(parts))
        self._fill_matches()

    def add_test(self):
        dialog = TestDialog(self, {})
        if dialog.exec():
            self.tests.append(dna.clean_test(dialog.values()))
            self._fill_tests(len(self.tests) - 1)
        dialog.deleteLater()

    def edit_test(self):
        test = self.current_test()
        if test is None:
            return
        dialog = TestDialog(self, test)
        if dialog.exec():
            test.update(dialog.values())
            self._fill_tests(self.test_box.currentIndex())
        dialog.deleteLater()

    def remove_test(self):
        test = self.current_test()
        if test is None:
            return
        if QMessageBox.question(self, t("dna_remove_test"), t("dna_remove_test_ask", test=self._test_label(test))) \
                != QMessageBox.StandardButton.Yes:
            return
        self.tests.remove(test)
        self._fill_tests()

    # Matches.
    def _status(self, match):
        status, relation, figures = dna.check(self.tree, self.person_id, match)
        if status in ("fits", "low", "high") and relation is not None:
            name = relation_name(relation.up, relation.down, relation.half)
            return status, t(f"dna_check_{status}", relation=name, low=figures[1], high=figures[2])
        if status == "unrelated":
            return status, t("dna_check_unrelated")
        return status, ""

    def _fill_matches(self):
        test = self.current_test()
        words = self.filter.text().strip().casefold()
        matches = [m for m in (test["matches"] if test else []) if not words or words in m["name"].casefold()]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(matches))
        for row, match in enumerate(matches):
            likely = dna.possible(match["cm"], 2)
            could = " · ".join(pair_name(up, down, half) for up, down, half, _f in likely)
            status, verdict = self._status(match)
            linked = self.tree.people[match["person"]].display_name if match["person"] in self.tree.people else ""
            mark = {"fits": "✓ ", "low": "⚠ ", "high": "⚠ ", "unrelated": "⚠ "}.get(status, "")
            cells = (match["name"], match["cm"], match["segments"], match["longest"], match["guess"], could, linked,
                     mark + verdict)
            for column, value in enumerate(cells):
                item = QTableWidgetItem()
                if isinstance(value, (int, float)):
                    item.setData(Qt.ItemDataRole.DisplayRole, value)
                else:
                    item.setText(value or "")
                item.setData(Qt.ItemDataRole.UserRole, match["id"])
                if isinstance(value, str) and len(value) > 24:
                    item.setToolTip(value)
                if column == 7 and status in ("low", "high", "unrelated"):
                    item.setForeground(theme.colour("warn"))
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.table.resizeColumnsToContents()
        self._selection_changed()

    def selected_matches(self):
        test = self.current_test()
        ids = {self.table.item(i.row(), 0).data(Qt.ItemDataRole.UserRole) for i in self.table.selectedIndexes()
               if self.table.item(i.row(), 0)}
        return [m for m in (test["matches"] if test else []) if m["id"] in ids]

    def _selection_changed(self):
        chosen = self.selected_matches()
        self.edit_match_button.setEnabled(len(chosen) == 1 and not self.read_only)
        self.remove_match_button.setEnabled(bool(chosen) and not self.read_only)
        if len(chosen) == 1 and chosen[0]["cm"] is not None:
            match = chosen[0]
            lines = [t("dna_explain_head", name=match["name"], cm=match["cm"])]
            for up, down, half, (avg, low, high) in dna.possible(match["cm"], 6):
                lines.append(t("dna_explain_line", relation=pair_name(up, down, half), avg=avg, low=low, high=high))
            _status, verdict = self._status(match)
            if verdict:
                lines.append(verdict)
            self.explain.setText("\n".join(lines))
        else:
            self.explain.setText(t("dna_explain_none"))
        self._fill_map()

    def add_match(self):
        test = self.current_test()
        if test is None:
            return
        dialog = MatchDialog(self, {}, self.tree, self.find_person)
        if dialog.exec():
            match = dna.clean_match({**dialog.values(), "source": t("dna_typed_in")})
            if match:
                test["matches"].append(match)
                self._fill_matches()
        dialog.deleteLater()

    def edit_match(self):
        chosen = self.selected_matches()
        if len(chosen) != 1:
            return
        match = chosen[0]
        dialog = MatchDialog(self, match, self.tree, self.find_person)
        if dialog.exec():
            match.update({k: v for k, v in dialog.values().items()})
            self._fill_matches()
        dialog.deleteLater()

    def remove_match(self):
        test, chosen = self.current_test(), self.selected_matches()
        if not test or not chosen:
            return
        ids = {m["id"] for m in chosen}
        test["matches"] = [m for m in test["matches"] if m["id"] not in ids]
        test["segments"] = [s for s in test["segments"] if s["match"] not in ids]
        self._fill_matches()

    # The chromosome map: the chosen matches' segments, or everyone's when none is chosen.
    def _fill_map(self):
        test = self.current_test()
        if test is None:
            self.chromosomes.show_segments([], {})
            self.legend.setText("")
            return
        chosen = {m["id"] for m in self.selected_matches()} or {s["match"] for s in test["segments"]}
        segments = [s for s in test["segments"] if s["match"] in chosen]
        colours, legend = {}, []
        names = {m["id"]: m for m in test["matches"]}
        for number, match_id in enumerate(sorted({s["match"] for s in segments})):
            match = names.get(match_id, {})
            side = self.side_colours.get(match.get("person", ""))
            colour = QColor(side) if side else QColor.fromHsv((number * 67) % 360, 160, 220)
            colours[match_id] = colour
            if len(legend) < 12:
                legend.append(f'<span style="color:{colour.name()}">■</span> {match.get("name", "")}')
        self.chromosomes.show_segments(segments, colours)
        self.legend.setText("  ".join(legend) if legend else t("dna_map_empty"))

    def _fill_possible(self):
        self.possible_list.clear()
        for up, down, half, (avg, low, high) in dna.possible(self.amount.value(), 12):
            self.possible_list.addItem(t("dna_explain_line", relation=pair_name(up, down, half), avg=avg, low=low,
                                         high=high))
        if not self.possible_list.count():
            self.possible_list.addItem(t("dna_amount_none"))

    # Files.
    def import_file(self):
        test = self.current_test()
        if test is None or self.ask_file is None:
            return
        path = self.ask_file(t("dna_import"), t("dna_import_filter"))
        if path:
            self.import_path(path)

    def import_path(self, path):
        """A match list, a segment file or a raw data file, whichever this is. Returns a
        short report, also shown to the person."""
        test = self.current_test()
        try:
            data = unpack(path)
        except (OSError, zipfile.BadZipFile, EOFError) as error:
            return self._report(t("dna_import_failed", detail=str(error)))
        if looks_raw(data):
            return self._import_raw(test, data)
        kind, found = dna.read_match_file(data, Path(path).name)
        if kind == "matches":
            added, updated = dna.add_matches(test, found)
            message = t("dna_imported_matches", added=added, updated=updated)
        elif kind == "segments":
            added = dna.add_segments(test, found, Path(path).name)
            message = t("dna_imported_segments", added=added)
        else:
            message = t("dna_import_unknown")
        self._show_test()
        return self._report(message)

    def _import_raw(self, test, data):
        if self.folder is None:
            return self._report(t("dna_import_failed", detail=""))
        target = self.folder / RAW_DIR / f"{test['id']}-{uuid.uuid4().hex[:8]}.txt.gz"  # Never over an older one.
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wb") as handle:
            handle.write(data)
        self.new_raw_files.append(target)
        _calls, info = dna.read_raw(target)
        if not info["snps"]:
            target.unlink(missing_ok=True)
            return self._report(t("dna_import_unknown"))
        test["raw"] = {"file": f"{RAW_DIR}/{target.name}", **info}
        self._show_test()
        return self._report(t("dna_imported_raw", snps=f"{info['snps']:,}".replace(",", ".")))

    def _report(self, message):
        self.explain.setText(message)
        return message

    def raw_path(self, test):
        if not test.get("raw") or self.folder is None:
            return None
        path = (self.folder / test["raw"]["file"]).resolve()
        if not path.is_relative_to(self.folder.resolve()) or not path.is_file():
            return None
        return path

    def compare_with(self):
        """Another person in the tree with a raw file: shared segments worked out here,
        from both raw files, without sending them anywhere."""
        test = self.current_test()
        if test is None:
            return
        mine = self.raw_path(test)
        if mine is None:
            return self._report(t("dna_compare_need_raw"))
        candidates = []
        for person_id, person in self.tree.people.items():
            for other in (self.others.get(person_id) or dna.tests_of(person)):
                if person_id != self.person_id and self.raw_path(other):
                    candidates.append((person_id, other))
        if not candidates:
            return self._report(t("dna_compare_none"))
        from PySide6.QtWidgets import QInputDialog
        labels = [f"{self.tree.people[p].display_name} — {self._test_label(o)}" for p, o in candidates]
        label, ok = QInputDialog.getItem(self, t("dna_compare"), t("dna_compare_who"), labels, 0, False)
        if not ok:
            return None
        return self.compare_tests(*candidates[labels.index(label)])

    def compare_tests(self, other_id, other_test):
        test = self.current_test()
        calls_mine, _ = dna.read_raw(self.raw_path(test))
        calls_theirs, _ = dna.read_raw(self.raw_path(other_test))
        segments = dna.compare(calls_mine, calls_theirs)
        total, count, longest = dna.summary(segments)
        me = self.tree.people[self.person_id].display_name
        them = self.tree.people[other_id].display_name
        for owner, target, name, linked in ((self.person_id, test, them, other_id),
                                            (other_id, other_test, me, self.person_id)):
            match = next((m for m in target["matches"] if m["person"] == linked and m["source"] == "compared"), None)
            if match is None:
                match = dna.clean_match({"name": name, "person": linked, "source": "compared"})
                target["matches"].append(match)
            match.update({"cm": total, "segments": count, "longest": longest})
            target["segments"] = [s for s in target["segments"] if s["match"] != match["id"]]
            target["segments"] += [{**s, "match": match["id"]} for s in segments]
            if owner != self.person_id:
                self.others[owner] = self.others.get(owner) or [x for x in dna.tests_of(self.tree.people[owner])]
                self.others[owner] = [target if x["id"] == target["id"] else x for x in self.others[owner]]
        self._show_test()
        return self._report(t("dna_compared", name=them, cm=total, count=count))

    def reject(self):
        for path in self.new_raw_files:  # Nothing imported after all.
            Path(path).unlink(missing_ok=True)
        super().reject()

    def values(self):
        """{person id: tests} for everyone whose tests changed here."""
        return {self.person_id: self.tests, **{k: v for k, v in self.others.items() if k != self.person_id}}
