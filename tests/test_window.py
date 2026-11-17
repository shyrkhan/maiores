"""The real window driven headlessly, from an empty tree to a family with photos."""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QPointF, QRect, QSettings, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QPushButton

import app as app_module
from edits import copy_tree
from devtools.checks import failures, run_checks
import house_layout as hl
from app import PAGE_EMPTY, PAGE_START, PAGE_TREE, MainWindow, apply_theme
from dialogs import CropDialog, FindDialog, PersonDialog, matching_people, person_to_values
from model import date_input_text, validate
from photos import default_crop, import_photo, resolve_photo, store_photo
from sample import sample_tree
from storage import create_tree, list_backups, open_tree

TODAY = datetime.date(2026, 11, 4)
qt_app = QApplication.instance() or QApplication([])
apply_theme(qt_app)


def wait_until(condition, timeout_ms=3000):
    """Slow test machines need more than a fixed pause, so wait for the result itself."""
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(20)
        waited += 20
    return condition()


class Answers:
    """Stands in for the dialogs: each ask gets the next prepared answer."""

    def __init__(self, window):
        self.people = []
        self.choices = []
        self.confirms = []
        self.photos = []
        self.alerts = []
        self.asked = []
        window.ask_person = self.ask_person
        window.choose = lambda title, label, options: self.choices.pop(0)
        window.confirm = lambda title, text: self.confirms.pop(0)
        window.ask_photo = lambda: self.photos.pop(0)
        window.ask_crop = lambda image: default_crop(image)
        self.existing = []
        window.ask_existing_person = lambda title, exclude: self.existing.pop(0)
        window.alert = lambda title, text: self.alerts.append(text)
        self.informed = []
        window.inform = lambda title, text: self.informed.append(text)
        # Unless a test says otherwise, a look-alike is a new person.
        self.duplicates = []
        self.duplicate_questions = []

        def ask_duplicate(title, label, options):
            self.duplicate_questions.append(options)
            return self.duplicates.pop(0) if self.duplicates else len(options) - 1

        window.ask_duplicate = ask_duplicate

    def ask_person(self, title, initial=None, link=None, relationships=(), another=False):
        self.asked.append({"title": title, "initial": initial, "link": link, "relationships": relationships})
        answer = self.people.pop(0)
        return answer if answer is None else {"living": "yes", **answer}


class WindowCase(unittest.TestCase):
    def setUp(self):
        # An error inside a button or signal handler only prints; make it fail the test.
        self.slot_errors = []
        previous = sys.excepthook
        sys.excepthook = lambda kind, error, trace: self.slot_errors.append(error)
        self.addCleanup(setattr, sys, "excepthook", previous)
        self.addCleanup(lambda: self.assertEqual(self.slot_errors, []))
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.settings = QSettings(str(self.temp / "settings.ini"), QSettings.Format.IniFormat)
        self.window = self.make_window()
        self.answers = Answers(self.window)
        self.folder = self.temp / "Test.tree"
        # Registered last so it runs first, while the window and files still exist:
        # the rules the running program must always obey (devtools/checks.py).
        self.addCleanup(lambda: self.assertEqual([str(p) for p in failures(run_checks(self.window))], []))

    def make_window(self):
        window = MainWindow(self.settings, today=TODAY)
        window.trees_folder = self.temp / "Family Trees"  # Never the real Documents folder.
        window.resize(1280, 860)  # The size these tests were written for; the test screen is smaller.
        window.show()
        QTest.qWaitForWindowExposed(window)
        self.addCleanup(window.close)
        return window

    def line_view(self):
        """Switch to the descendant chart, which these older tests were written for."""
        self.window.chart = "pyramid"
        self.window.house = None
        self.window.refresh(keep_view=False)

    def saved(self):
        return json.loads((self.folder / "tree.json").read_text(encoding="utf-8"))

    def person_named(self, given):
        return next(p for p in self.window.tree.people.values() if p.given == given)

    def make_photo(self, name="photo.png", size=(800, 600), colour="#336699"):
        image = QImage(*size, QImage.Format.Format_RGB32)
        image.fill(QColor(colour))
        path = self.temp / name
        self.assertTrue(image.save(str(path)))
        return path

    def start_family(self):
        """Ana, her partner Ivo and their child Mia."""
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Ana", "surname": "Šimić"}]
        self.window.add_first_person()
        ana = self.person_named("Ana").id
        self.answers.people = [{"given": "Ivo", "relationships": {None: "married"}}]
        self.window.run_action("add_partner", ana)
        self.answers.people = [{"given": "Mia", "link": "birth"}]
        self.window.run_action("add_child", ana)
        return ana


class ResourceTests(WindowCase):
    def test_bundled_font_is_loaded_with_croatian_letters(self):
        self.assertIn("Noto Serif", QFontDatabase.families())
        for letter in "čćšžđČĆŠŽĐ":
            self.assertTrue(QFontMetrics(QFont("Noto Serif")).inFontUcs4(ord(letter)), letter)

    def test_licence_notices_are_present(self):
        root = Path(app_module.__file__).parent
        self.assertIn("LGPL", (root / "THIRD_PARTY.txt").read_text(encoding="utf-8"))
        self.assertTrue((root / "fonts" / "OFL.txt").is_file())
        self.assertFalse(qt_app.windowIcon().isNull())


class StartPageTests(WindowCase):
    def test_starts_on_the_start_page(self):
        self.assertEqual(self.window.pages.currentIndex(), PAGE_START)

    def test_new_tree_gets_suffix_and_empty_page(self):
        self.assertTrue(self.window.new_tree(self.temp / "Mine"))
        self.assertTrue((self.temp / "Mine.tree" / "tree.json").is_file())
        self.assertEqual(self.window.pages.currentIndex(), PAGE_EMPTY)

    def test_new_tree_will_not_replace_an_existing_one(self):
        create_tree(self.folder, sample_tree())
        original = (self.folder / "tree.json").read_bytes()
        self.answers.confirms = [False]  # "Open it instead?" No.
        self.assertFalse(self.window.new_tree(self.folder))
        self.assertEqual((self.folder / "tree.json").read_bytes(), original)

    def test_open_accepts_the_folder_or_its_tree_json(self):
        create_tree(self.folder, sample_tree())
        self.assertTrue(self.window.open_path(self.folder / "tree.json"))
        self.assertEqual(self.window.folder, self.folder)
        self.assertEqual(self.window.pages.currentIndex(), PAGE_TREE)

    def test_failed_open_keeps_current_tree(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        broken = self.temp / "Broken.tree"
        broken.mkdir()
        (broken / "tree.json").write_text("{bad")
        self.assertFalse(self.window.open_path(broken))
        self.assertEqual(self.window.folder, self.folder)
        self.assertEqual((broken / "tree.json").read_text(), "{bad")

    def test_second_window_cannot_open_the_same_tree(self):
        create_tree(self.folder, sample_tree())
        self.assertTrue(self.window.open_path(self.folder))
        second = self.make_window()
        answers = Answers(second)
        self.assertFalse(second.open_path(self.folder))
        self.assertIn("already open", answers.alerts[0])

    def test_opening_the_tree_already_open_here_is_quiet(self):
        """Found by the MCP sweep: Open recent on the tree in this window said it was open elsewhere."""
        create_tree(self.folder, sample_tree())
        self.assertTrue(self.window.open_path(self.folder))
        self.window.select("luka")
        self.assertTrue(self.window.open_path(self.folder / "tree.json"))
        self.assertEqual(self.answers.alerts, [])
        self.assertEqual(self.window.selected, "luka")  # Not reloaded.

    def test_lock_from_a_crashed_program_does_not_block_opening(self):
        create_tree(self.folder, sample_tree())
        script = (
            "import os\n"
            "from PySide6.QtCore import QLockFile\n"
            f"lock = QLockFile({str(self.folder / '.lock')!r})\n"
            "assert lock.tryLock(0)\n"
            "os._exit(0)\n"
        )
        subprocess.run([sys.executable, "-c", script], check=True)
        self.assertTrue((self.folder / ".lock").exists())
        self.assertTrue(self.window.open_path(self.folder))

    def write_foreign_lock(self):
        create_tree(self.folder, sample_tree())
        lock = self.folder / ".lock"
        lock.write_text(
            "4242\nfamily-tree\nother-computer\n" + "0" * 32 + "\n00000000-0000-0000-0000-000000000000\n"
        )

    def test_lock_from_another_computer_asks_and_can_open(self):
        self.write_foreign_lock()
        self.answers.confirms = [True]
        self.assertTrue(self.window.open_path(self.folder))
        self.window.close()
        self.assertFalse((self.folder / ".lock").exists())

    def test_lock_from_another_computer_can_be_declined(self):
        self.write_foreign_lock()
        self.answers.confirms = [False]
        self.assertFalse(self.window.open_path(self.folder))
        self.assertIn("other-computer", (self.folder / ".lock").read_text())

    @unittest.skipIf(
        sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        "needs Unix folder permissions",
    )
    def test_folder_that_cannot_be_written_is_refused_cleanly(self):
        create_tree(self.folder, sample_tree())
        self.folder.chmod(0o500)
        self.addCleanup(self.folder.chmod, 0o700)
        self.assertFalse(self.window.open_path(self.folder))
        self.assertIn("cannot be written", self.answers.alerts[0])

    def test_tree_can_reopen_after_closing(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.close()
        second = self.make_window()
        Answers(second)
        self.assertTrue(second.open_path(self.folder))

    def test_last_tree_is_remembered(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.assertEqual(self.settings.value(app_module.LAST_TREE_KEY), str(self.folder))

    def test_sample_is_read_only(self):
        self.window.load_sample()
        keys = [a[0] for a in self.window.person_actions("ante")]
        self.assertEqual(keys, ["collapse", "dna", "family_line"])  # Only ways of looking, no editing.
        self.assertIn("centre", [a[0] for a in self.window.person_actions("mara")])


class EditingTests(WindowCase):
    def test_first_person_is_saved_immediately(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Ana", "surname": "Šimić", "birth_date": "14.5.1980."}]
        self.window.add_first_person()
        self.assertEqual(self.window.pages.currentIndex(), PAGE_TREE)
        people = self.saved()["people"]
        self.assertEqual(len(people), 1)
        person = next(iter(people.values()))
        self.assertEqual(person["surname"], "Šimić")
        self.assertEqual(person["birth"]["date"], "1980-05-14")

    def test_cancelling_changes_nothing(self):
        self.window.new_tree(self.folder)
        self.answers.people = [None]
        self.window.add_first_person()
        self.assertEqual(self.saved()["people"], {})

    def test_building_a_family_saves_and_reopens(self):
        ana = self.start_family()
        tree = open_tree(self.folder).tree
        self.assertEqual(len(tree.people), 3)
        self.assertEqual(validate(tree), [])
        self.assertEqual(self.window.tree, tree)
        self.assertEqual(len(self.window.person_items), 3)
        self.assertEqual(self.window.house, ana)

    def test_child_surname_is_suggested(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Ana", "surname": "Šimić"}]
        self.window.add_first_person()
        self.answers.people = [None]
        self.window.run_action("add_child", self.person_named("Ana").id)
        self.assertEqual(self.answers.asked[-1]["initial"]["surname"], "Šimić")

    def test_adding_parent_to_head_shows_the_new_parent(self):
        ana = self.start_family()
        self.line_view()
        self.answers.people = [{"given": "Baka", "link": "birth"}]
        self.window.run_action("add_parent", ana)
        baka = self.person_named("Baka").id
        self.assertEqual(self.window.house, baka)
        self.assertIn(baka, self.window.person_items)
        self.assertIn(ana, self.window.person_items)

    def test_parent_of_partner_switches_to_their_line(self):
        self.start_family()
        ivo = self.person_named("Ivo").id
        self.answers.people = [{"given": "Djed", "link": "birth"}]
        self.window.run_action("add_parent", ivo)
        self.assertIn(self.person_named("Djed").id, self.window.person_items)
        self.assertIn(ivo, self.window.person_items)
        self.assertIn("Back returns", self.window.statusBar().currentMessage())

    def test_second_partner_child_asks_which_parent(self):
        ana = self.start_family()
        self.answers.people = [{"given": "Pero", "relationships": {None: "partners"}}]
        self.window.run_action("add_partner", ana)
        self.answers.choices = [1]
        self.answers.people = [{"given": "Leo", "link": "adopted"}]
        self.window.run_action("add_child", ana)
        family = self.window.tree.birth_family_of(self.person_named("Leo").id)
        self.assertIn(self.person_named("Pero").id, family.partners)
        self.assertEqual(family.children[0]["link"], "adopted")
        self.assertEqual(family.relationship, "partners")

    def test_undo_and_redo_also_change_the_saved_file(self):
        self.start_family()
        self.assertEqual(len(self.saved()["people"]), 3)
        self.window.undo()
        self.assertEqual(len(self.saved()["people"]), 2)
        self.assertEqual(len(self.window.person_items), 2)
        self.window.redo()
        self.assertEqual(len(self.saved()["people"]), 3)

    def test_undo_back_to_empty_shows_empty_page(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Ana"}]
        self.window.add_first_person()
        self.window.undo()
        self.assertEqual(self.window.pages.currentIndex(), PAGE_EMPTY)
        self.assertEqual(self.saved()["people"], {})

    def test_delete_asks_and_can_be_declined(self):
        ana = self.start_family()
        self.answers.confirms = [False]
        self.window.run_action("delete", ana)
        self.assertIn(ana, self.window.tree.people)

    def test_deleting_the_head_keeps_a_working_view(self):
        ana = self.start_family()
        self.answers.confirms = [True]
        self.window.run_action("delete", ana)
        self.assertNotIn(ana, self.window.tree.people)
        self.assertIn(self.window.house, self.window.tree.people)
        self.assertEqual(self.window.pages.currentIndex(), PAGE_TREE)
        self.assertEqual(validate(self.window.tree), [])

    def test_deleting_everyone_then_undo(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Ana"}]
        self.window.add_first_person()
        self.answers.confirms = [True]
        self.window.run_action("delete", self.person_named("Ana").id)
        self.assertEqual(self.window.pages.currentIndex(), PAGE_EMPTY)
        self.window.undo()
        self.assertEqual(self.window.pages.currentIndex(), PAGE_TREE)

    def test_edit_updates_card_and_file(self):
        ana = self.start_family()
        values = person_to_values(self.window.tree.people[ana])
        values.update(given="Anica", living="no", death_date="2020", relationships={})
        self.answers.people = [values]
        self.window.run_action("edit", ana)
        self.assertEqual(self.window.person_items[ana].name, "Anica Šimić")
        saved = self.saved()["people"][ana]
        self.assertEqual(saved["living"], "no")
        self.assertEqual(saved["death"]["date"], "2020")

    def test_save_failure_is_reported_and_close_asks(self):
        ana = self.start_family()
        real_save = app_module.save_tree

        def failing(folder, tree):
            raise OSError("disk is full")

        app_module.save_tree = failing
        self.addCleanup(setattr, app_module, "save_tree", real_save)
        self.answers.people = [{"given": "Late", "link": "birth"}]
        self.window.run_action("add_child", ana)
        self.assertIn("disk is full", self.window.statusBar().currentMessage())

        self.answers.confirms = [False]
        self.assertFalse(self.window.close())
        self.assertTrue(self.window.isVisible())

        app_module.save_tree = real_save
        self.assertTrue(self.window.close())
        self.assertIn("Late", [p["given"] for p in self.saved()["people"].values()])

    def test_make_head_changes_view_and_persists(self):
        ana = self.start_family()
        self.line_view()
        ivo = self.person_named("Ivo").id
        self.assertIn("make_head", [a[0] for a in self.window.person_actions(ivo)])
        self.window.run_action("make_head", ivo)
        self.assertEqual(self.window.house, ivo)
        self.assertEqual(open_tree(self.folder).tree.default_house_root(), ivo)
        self.assertNotIn("make_head", [a[0] for a in self.window.person_actions(ivo)])
        self.assertIn(ana, self.window.person_items)


class MouseTests(WindowCase):
    def click(self, person_id, double=False):
        view, item = self.window.view, self.window.person_items[person_id]
        middle = item.scenePos() + QPointF(hl.PORTRAIT_W / 2, hl.PORTRAIT_H / 2)
        point = view.mapFromScene(middle)
        action = QTest.mouseDClick if double else QTest.mouseClick
        action(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QApplication.processEvents()

    def test_click_selects_and_panel_opens_after_a_moment(self):
        ana = self.start_family()
        self.click(ana)
        self.assertEqual(self.window.selected, ana)
        self.assertTrue(self.window.person_items[ana].highlighted)
        self.assertTrue(wait_until(self.window.panel.isVisible))
        self.assertIn("Ana", self.window.panel.name.text())

    def test_panel_buttons_run_actions(self):
        ana = self.start_family()
        self.window.go_to_person(ana)
        self.window._show_panel_now()
        button = self.window.panel.findChild(QPushButton, "action_add_child")
        self.answers.people = [{"given": "Rea", "link": "birth"}]
        button.click()
        self.assertTrue(self.person_named("Rea"))

    def test_clicking_empty_space_keeps_the_selection(self):
        ana = self.start_family()
        self.click(ana)
        QTest.mouseClick(self.window.view.viewport(), Qt.MouseButton.LeftButton, pos=self.window.view.viewport().rect().topLeft() + QPointF(3, 3).toPoint())
        QApplication.processEvents()
        self.assertEqual(self.window.selected, ana)
        self.assertTrue(self.window.panel.isVisible())

    def test_double_click_on_blood_relative_edits(self):
        ana = self.start_family()
        self.answers.people = [None]
        self.click(ana, double=True)
        self.assertIn("Edit", self.answers.asked[-1]["title"])

    def test_edit_keeps_zoom_and_position(self):
        ana = self.start_family()
        view = self.window.view
        view.scale(1.5, 1.5)
        before = (view.zoom_level(), view.mapToScene(view.viewport().rect().center()))
        values = person_to_values(self.window.tree.people[ana])
        values["relationships"] = {}
        self.answers.people = [values]
        self.window.run_action("edit", ana)
        self.assertEqual(view.zoom_level(), before[0])
        after = view.mapToScene(view.viewport().rect().center())
        self.assertLess((after - before[1]).manhattanLength(), 2)

    def test_panel_shows_names_as_text_not_markup(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "<img src=x>", "notes": "<b>note</b>"}]
        self.window.add_first_person()
        person = next(iter(self.window.tree.people))
        self.window.select(person)
        self.window._show_panel_now()
        self.assertIn("&lt;b&gt;note", self.window.panel.details.text())
        self.assertEqual(self.window.panel.name.text(), "<img src=x>")

    def test_context_menu_lists_actions(self):
        ana = self.start_family()
        captured = []
        self.window.show_menu = lambda menu, pos: captured.extend(a.text() for a in menu.actions())
        self.window._context_menu(ana, self.window.view.mapToGlobal(self.window.view.rect().center()))
        self.assertIn("Add child...", captured)
        self.assertIn("Delete...", captured)


class BranchTests(WindowCase):
    def open_sample(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)

    def test_hide_and_show_descendants(self):
        self.open_sample()
        self.window.run_action("collapse", "luka")
        self.assertNotIn("ivana", self.window.person_items)
        from canvas import FoldItem
        folds = [i.text for i in self.window.view.scene().items()
                 if isinstance(i, FoldItem) and i.person_id == "luka"]
        self.assertEqual(folds, ["+3"])  # On screen the count is on the fold button.
        self.assertIn("Show descendants", [a[1] for a in self.window.person_actions("luka")])
        self.window.run_action("collapse", "luka")
        self.assertIn("ivana", self.window.person_items)

    def test_finding_a_hidden_person_reveals_them(self):
        self.open_sample()
        self.window.run_action("collapse", "luka")
        self.window.go_to_person("ivana")
        self.assertIn("ivana", self.window.person_items)
        self.assertEqual(self.window.selected, "ivana")

    def test_adding_a_child_to_a_hidden_branch_reveals_it(self):
        self.open_sample()
        self.window.run_action("collapse", "luka")
        self.answers.people = [{"given": "Nova", "link": "birth"}]
        self.window.run_action("add_child", "luka")
        self.assertIn(self.person_named("Nova").id, self.window.person_items)

    def test_choose_family_line(self):
        self.open_sample()
        heads = [head for head, _ in self.window.tree.family_line_heads()]
        self.answers.choices = [heads.index("stipe")]
        self.window.choose_family_line()
        self.assertEqual(self.window.house, "stipe")
        self.window.go_back()
        self.assertEqual(self.window.house, "ante")


class AncestorViewTests(WindowCase):
    def open_sample(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)

    def test_show_and_leave_ancestors(self):
        self.open_sample()
        self.assertIn("ancestors", [a[0] for a in self.window.person_actions("ivana")])
        self.assertNotIn("ancestors", [a[0] for a in self.window.person_actions("ante")])
        self.window.run_action("ancestors", "ivana")
        self.assertIn("stipe", self.window.person_items)
        self.assertIn("ante", self.window.person_items)
        self.assertNotIn("josip", self.window.person_items)
        self.assertIn("ivana", self.window.statusBar().currentMessage().lower())
        self.window.run_action("family_view", "stipe")
        self.assertEqual(self.window.house, "stipe")
        self.assertNotEqual(self.window.chart, "pedigree")
        self.assertIn("zvonko", self.window.person_items)

    def test_back_returns_to_where_you_were(self):
        self.open_sample()
        self.window.run_action("ancestors", "ivana")
        self.window.go_back()
        self.assertNotEqual(self.window.chart, "pedigree")
        self.assertIn("josip", self.window.person_items)

    def test_editing_stays_in_ancestor_view(self):
        self.open_sample()
        self.window.run_action("ancestors", "ivana")
        self.answers.people = [{"given": "Pradjed", "link": "birth"}]
        self.window.run_action("add_parent", "ante")
        self.assertEqual((self.window.chart, self.window.house), ("pedigree", "ivana"))
        self.assertIn(self.person_named("Pradjed").id, self.window.person_items)

    def test_deleting_the_view_person_returns_to_family_view(self):
        self.open_sample()
        self.window.run_action("ancestors", "ivana")
        self.answers.confirms = [True]
        self.window.run_action("delete", "ivana")
        self.assertNotEqual(self.window.chart, "pedigree")
        self.assertEqual(validate(self.window.tree), [])

    def test_export_uses_the_ancestor_view(self):
        self.open_sample()
        self.window.run_action("ancestors", "ivana")
        path = self.temp / "a.pdf"
        self.assertTrue(self.window.export_picture(path))
        if shutil.which("pdftotext"):
            text = subprocess.run(
                ["pdftotext", "-enc", "UTF-8", str(path), "-"], capture_output=True
            ).stdout.decode("utf-8")
            self.assertIn("Jela", text)
            self.assertNotIn("Josip", text)

    def test_find_leaves_ancestor_view_when_needed(self):
        self.open_sample()
        self.window.run_action("ancestors", "ivana")
        self.window.go_to_person("tomo")
        self.assertNotEqual(self.window.chart, "pedigree")
        self.assertEqual(self.window.selected, "tomo")


class MergeAndRestoreTests(WindowCase):
    def open_sample(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)

    def test_merge_of_people_with_different_parents_is_explained(self):
        self.open_sample()
        self.answers.existing = ["zvonko"]
        self.answers.confirms = [True]
        self.window.run_action("merge", "tomo")
        self.assertIn("zvonko", self.window.tree.people)
        self.assertIn("different parents", self.answers.alerts[0])
        self.assertFalse(self.window.history.can_undo())

    def test_merge_of_people_with_no_parents(self):
        self.open_sample()
        self.answers.existing = ["ana"]
        self.answers.confirms = [True]
        self.window.run_action("merge", "katica")
        self.assertNotIn("ana", self.window.tree.people)
        self.assertEqual(validate(self.window.tree), [])
        self.window.undo()
        self.assertIn("ana", self.window.tree.people)
        self.assertIn("ana", self.saved()["people"])

    def test_declined_merge_changes_nothing(self):
        self.open_sample()
        self.answers.existing = ["ana"]
        self.answers.confirms = [False]
        self.window.run_action("merge", "katica")
        self.assertIn("ana", self.window.tree.people)

    def test_restore_brings_back_old_data_and_can_be_undone(self):
        self.open_sample()
        self.answers.confirms = [True]
        self.window.run_action("delete", "tomo")
        self.assertNotIn("tomo", self.saved()["people"])
        backups = list_backups(self.folder)
        self.assertEqual(backups[-1][2], 16)
        self.assertTrue(self.window.restore_backup(backups[-1][0], "then"))
        self.assertIn("tomo", self.window.tree.people)
        self.assertIn("tomo", self.saved()["people"])
        self.window.undo()
        self.assertNotIn("tomo", self.window.tree.people)

    def test_restore_keeps_the_current_version_as_a_backup(self):
        self.open_sample()
        self.answers.confirms = [True]
        self.window.run_action("delete", "tomo")
        current = (self.folder / "tree.json").read_bytes()
        backup = list_backups(self.folder)[-1][0]
        self.window.restore_backup(backup, "then")
        self.assertTrue(
            any((b / "tree.json").read_bytes() == current for b, _, _ in list_backups(self.folder))
        )

    def test_choose_restore_lists_backups(self):
        self.open_sample()
        self.answers.choices = [None]
        self.window.choose_restore()
        self.assertEqual(len(self.window.tree.people), 16)

    def test_damaged_backup_is_not_offered(self):
        self.open_sample()
        backups = list_backups(self.folder)
        (backups[0][0] / "tree.json").write_text("{broken")
        self.assertEqual(list_backups(self.folder), [])
        self.window.choose_restore()
        self.assertIn("no backups", self.answers.alerts[0])


class FindTests(WindowCase):
    def test_search_ignores_case_and_accents(self):
        tree = sample_tree()
        self.assertEqual({p.id for p in matching_people(tree, "culic")}, {"jela"})
        self.assertIn("ana", {p.id for p in matching_people(tree, "SIMIC ana")})
        self.assertEqual({p.id for p in matching_people(tree, "duric")}, {"katica"})

    def test_find_dialog_returns_first_match(self):
        dialog = FindDialog(self.window, sample_tree(), TODAY)
        dialog.search.setText("zvonko")
        dialog._choose_current()
        self.assertEqual(dialog.chosen, "zvonko")

    def test_going_to_someone_elsewhere_switches_view(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.line_view()
        self.assertEqual(self.window.house, "ante")
        self.window.go_to_person("zvonko")
        self.assertEqual(self.window.house, "stipe")
        self.assertEqual(self.window.selected, "zvonko")
        self.window.go_back()
        self.assertEqual(self.window.house, "ante")

    def test_finding_someone_who_married_in_shows_them_with_their_partner(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.line_view()
        self.window.go_to_person("zvonko")
        self.assertEqual(self.window.house, "stipe")
        self.window.go_to_person("ana")
        self.assertEqual(self.window.house, "ante")
        self.assertEqual(self.window.selected, "ana")
        self.assertIn("josip", self.window.person_items)

    def test_finding_the_second_partner_of_a_head_keeps_the_family_together(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.line_view()
        self.window.go_to_person("jela")
        self.assertEqual(self.window.house, "stipe")

    def test_view_is_remembered_on_reopen(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.line_view()
        self.window.go_to_person("zvonko")
        self.assertEqual(open_tree(self.folder).house, "stipe")


class DialogTests(WindowCase):
    def save_button(self, dialog):
        return dialog.buttons.button(QDialogButtonBox.StandardButton.Save)

    def test_bad_date_blocks_saving(self):
        dialog = PersonDialog(self.window, "Add")
        self.assertTrue(self.save_button(dialog).isEnabled())
        dialog.birth_date.setText("sometime")
        self.assertFalse(self.save_button(dialog).isEnabled())
        self.assertTrue(dialog.problem.text())
        dialog.birth_date.setText("14.5.1921.")
        self.assertTrue(self.save_button(dialog).isEnabled())

    def test_death_before_birth_blocks_saving(self):
        dialog = PersonDialog(self.window, "Add")
        dialog.status.setCurrentIndex(dialog.status.findData("no"))
        dialog.birth_date.setText("2000")
        dialog.death_date.setText("1990")
        self.assertFalse(self.save_button(dialog).isEnabled())

    def test_existing_person_round_trips_unchanged(self):
        import edits

        for person in sample_tree().people.values():
            values = person_to_values(person)
            dialog = PersonDialog(self.window, "Edit", values)
            tree = sample_tree()
            edits.update_person(tree, person.id, dialog.values())
            self.assertEqual(tree.people[person.id].to_dict(), person.to_dict(), person.id)

    def test_living_status_disables_death_fields(self):
        dialog = PersonDialog(self.window, "Add", {"living": "yes"})
        self.assertFalse(dialog.death_place.isEnabled())
        dialog.status.setCurrentIndex(dialog.status.findData("no"))
        self.assertTrue(dialog.death_place.isEnabled())


class PhotoTests(WindowCase):
    def test_photo_is_copied_cropped_and_shown(self):
        ana = self.start_family()
        source = self.make_photo(size=(1600, 900))
        original = source.read_bytes()
        self.answers.photos = [source]
        self.window.run_action("photo", ana)
        stored = self.window.tree.people[ana].photo
        self.assertTrue(stored.startswith("media/"))
        saved = QImage(str(self.folder / stored))
        self.assertAlmostEqual(saved.width() / saved.height(), hl.PORTRAIT_W / hl.PORTRAIT_H, places=2)
        self.assertLessEqual(saved.width(), 480)
        self.assertEqual(source.read_bytes(), original)
        self.assertIsNotNone(self.window.person_items[ana].pixmap)
        self.assertEqual(validate(self.window.tree), [])

    def test_undo_restores_previous_photo(self):
        ana = self.start_family()
        self.answers.photos = [self.make_photo("one.png", colour="#ff0000")]
        self.window.run_action("photo", ana)
        first = self.window.tree.people[ana].photo
        self.answers.photos = [self.make_photo("two.png", colour="#00ff00")]
        self.window.run_action("photo", ana)
        self.assertNotEqual(self.window.tree.people[ana].photo, first)
        self.window.undo()
        self.assertEqual(self.window.tree.people[ana].photo, first)
        self.assertTrue((self.folder / first).is_file())

    def test_remove_photo_can_be_undone(self):
        ana = self.start_family()
        self.answers.photos = [self.make_photo()]
        self.window.run_action("photo", ana)
        self.window.run_action("remove_photo", ana)
        self.assertEqual(self.window.tree.people[ana].photo, "")
        self.assertIsNone(self.window.person_items[ana].pixmap)
        self.window.undo()
        self.assertIsNotNone(self.window.person_items[ana].pixmap)

    def test_unreadable_photo_is_reported_and_person_kept(self):
        ana = self.start_family()
        bad = self.temp / "broken.jpg"
        bad.write_bytes(b"this is not a picture")
        self.answers.photos = [bad]
        self.window.run_action("photo", ana)
        self.assertTrue(self.answers.alerts)
        self.assertEqual(self.window.tree.people[ana].photo, "")
        undo_steps = len(self.window.history.undo_stack)
        self.answers.photos = [bad]
        self.window.run_action("photo", ana)
        self.assertEqual(len(self.window.history.undo_stack), undo_steps)

    def test_new_person_with_photo(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Ana", "photo_source": self.make_photo()}]
        self.window.add_first_person()
        self.assertTrue(self.person_named("Ana").photo)

    def test_tall_photo_keeps_more_of_the_top(self):
        image = QImage(400, 2000, QImage.Format.Format_RGB32)
        image.fill(QColor("#000000"))
        for y in range(600):
            for x in range(400):
                image.setPixelColor(x, y, QColor("#ffffff"))
        source = self.temp / "tall.png"
        image.save(str(source))
        self.folder.mkdir()
        stored = import_photo(source, self.folder)
        saved = QImage(str(self.folder / stored))
        self.assertGreater(saved.pixelColor(saved.width() // 2, 5).red(), 200)

    def test_unsafe_paths_are_not_loaded(self):
        self.folder.mkdir()
        (self.folder / "media").mkdir()
        outside = self.make_photo("secret.png")
        for stored in (str(outside), f"media/../../{outside.name}", "../secret.png"):
            self.assertIsNone(resolve_photo(self.folder, stored), stored)
        link = self.folder / "media" / "link.png"
        try:
            link.symlink_to(outside)
        except OSError:
            return  # Windows only allows links with special permission.
        self.assertIsNone(resolve_photo(self.folder, "media/link.png"))

    def test_missing_photo_shows_placeholder_without_failing(self):
        tree = sample_tree()
        tree.people["ante"].photo = "media/gone.jpg"
        create_tree(self.folder, tree)
        self.assertTrue(self.window.open_path(self.folder))
        self.assertIsNone(self.window.person_items["ante"].pixmap)


class CropTests(WindowCase):
    def image(self, width, height):
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor("#336699"))
        return image

    def assert_good_crop(self, area):
        crop = area.crop
        self.assertTrue(area.image.rect().contains(crop), crop)
        self.assertAlmostEqual(crop.width() / crop.height(), hl.PORTRAIT_W / hl.PORTRAIT_H, places=1)

    def test_starts_on_the_automatic_crop(self):
        dialog = CropDialog(self.window, self.image(1600, 900))
        self.assertEqual(dialog.area.crop, default_crop(dialog.area.image))
        self.assert_good_crop(dialog.area)

    def test_slider_and_dragging_stay_inside_the_picture(self):
        dialog = CropDialog(self.window, self.image(1600, 900))
        area = dialog.area
        dialog.slider.setValue(dialog.slider.minimum())
        self.assert_good_crop(area)
        self.assertEqual(area.crop.width(), area.smallest_width())
        dialog.slider.setValue(dialog.slider.maximum())
        self.assert_good_crop(area)
        for delta in ((-99999, -99999), (99999, 99999), (5000, -5000)):
            area.move_crop(*delta)
            self.assert_good_crop(area)

    def test_real_mouse_drag_moves_the_crop(self):
        dialog = CropDialog(self.window, self.image(1600, 900))
        dialog.show()
        QTest.qWaitForWindowExposed(dialog)
        area = dialog.area
        before = area.crop.left()
        start = area.rect().center()
        QTest.mousePress(area, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(area, start + QPoint(40, 0))
        QTest.mouseRelease(area, Qt.MouseButton.LeftButton, pos=start + QPoint(40, 0))
        self.assertGreater(area.crop.left(), before)
        dialog.close()

    def test_tiny_and_odd_shaped_pictures(self):
        for size in ((1, 1), (10, 300), (300, 10), (5000, 40)):
            dialog = CropDialog(self.window, self.image(*size))
            dialog.slider.setValue(dialog.slider.minimum())
            dialog.slider.setValue(dialog.slider.maximum())
            self.assertTrue(dialog.area.image.rect().contains(dialog.area.crop), size)

    def test_chosen_crop_decides_what_is_saved(self):
        image = self.image(1000, 1000)
        for y in range(1000):
            for x in range(500):
                image.setPixelColor(x, y, QColor("#ff0000"))
        self.folder.mkdir()
        stored = store_photo(image, self.folder, QRect(0, 0, 400, 400))
        saved = QImage(str(self.folder / stored))
        self.assertGreater(saved.pixelColor(saved.width() // 2, saved.height() // 2).red(), 200)

    def test_cancelling_the_crop_keeps_the_old_photo(self):
        ana = self.start_family()
        self.window.ask_crop = lambda image: None
        self.answers.photos = [self.make_photo()]
        self.window.run_action("photo", ana)
        self.assertEqual(self.window.tree.people[ana].photo, "")


class ConnectTests(WindowCase):
    def open_sample(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)

    def test_connect_partners_who_exist(self):
        self.open_sample()
        self.answers.choices = [0]
        self.answers.existing = ["zvonko"]
        self.window.run_action("connect", "ivana")
        family = self.window.tree.families_of("ivana")[0]
        self.assertEqual(set(family.partners), {"ivana", "zvonko"})
        self.assertEqual(validate(self.window.tree), [])
        self.window.undo()
        self.assertEqual(self.window.tree.families_of("ivana"), [])

    def test_loop_is_refused_with_a_message(self):
        self.open_sample()
        self.answers.choices = [2]
        self.answers.existing = ["ivana"]
        self.window.run_action("connect", "ante")
        self.assertIn("is already an ancestor of", self.answers.alerts[0])
        self.assertFalse(self.window.history.can_undo())

    def test_parent_for_head_moves_the_view_up(self):
        self.open_sample()
        self.line_view()
        self.answers.choices = [2]
        self.answers.existing = ["zvonko"]
        self.window.run_action("connect", "ante")
        self.assertEqual(self.window.house, "stipe")
        self.assertIn("ante", self.window.person_items)
        self.assertEqual(validate(self.window.tree), [])

    def test_cousin_marriage_can_be_built_and_shown(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Top"}]
        self.window.add_first_person()
        top = self.person_named("Top").id
        for given in ("One", "Two"):
            self.answers.people = [{"given": given, "link": "birth"}]
            self.window.run_action("add_child", top)
        self.answers.people = [{"given": "X", "link": "birth"}]
        self.window.run_action("add_child", self.person_named("One").id)
        self.answers.people = [{"given": "Y", "link": "birth"}]
        self.window.run_action("add_child", self.person_named("Two").id)
        self.answers.choices = [0]
        self.answers.existing = [self.person_named("Y").id]
        self.window.run_action("connect", self.person_named("X").id)
        self.answers.people = [{"given": "Kid", "link": "birth"}]
        self.window.run_action("add_child", self.person_named("X").id)
        self.assertEqual(validate(self.window.tree), [])
        kid = self.person_named("Kid").id
        layout = hl.layout_house(self.window.tree, top)
        self.assertEqual([c.person_id for c in layout.cards].count(kid), 1)
        self.assertIn(self.person_named("Y").id, self.window.person_items)


class ExchangeTests(WindowCase):
    def open_sample(self):
        tree = sample_tree()
        create_tree(self.folder, tree)
        self.window.open_path(self.folder)

    def test_export_then_import_gives_the_same_family(self):
        self.open_sample()
        self.answers.photos = [self.make_photo()]
        self.window.run_action("photo", "ante")
        ged = self.temp / "out" / "family.ged"
        ged.parent.mkdir()
        self.assertTrue(self.window.export_gedcom(ged))
        self.assertTrue((ged.parent / "family_media").is_dir())
        target = self.temp / "Copy"
        self.answers.alerts.clear()
        self.assertTrue(self.window.import_gedcom(ged, target))
        self.assertEqual(self.window.folder, self.temp / "Copy.tree")
        self.assertIn("Imported 16 people", self.answers.alerts[0])
        tree = self.window.tree
        self.assertEqual(len(tree.people), 16)
        self.assertEqual(validate(tree), [])
        ante = next(p for p in tree.people.values() if p.given == "Ante")
        self.assertTrue(ante.photo)
        self.assertTrue((self.window.folder / ante.photo).is_file())
        self.assertEqual(self.person_named("Mara").birth_surname, "Bilić")

    def test_import_refuses_to_replace_a_tree(self):
        self.open_sample()
        ged = self.temp / "family.ged"
        self.window.export_gedcom(ged)
        original = (self.folder / "tree.json").read_bytes()
        self.assertFalse(self.window.import_gedcom(ged, self.folder))
        self.assertEqual((self.folder / "tree.json").read_bytes(), original)

    def test_import_of_rubbish_is_refused(self):
        bad = self.temp / "bad.ged"
        bad.write_text("not a gedcom")
        self.assertFalse(self.window.import_gedcom(bad, self.temp / "Bad"))
        self.assertIn("does not look like", self.answers.alerts[0])
        self.assertFalse((self.temp / "Bad.tree").exists())

    def test_hiding_living_people_leaves_nothing_behind(self):
        self.open_sample()
        self.answers.photos = [self.make_photo()]
        self.window.run_action("photo", "mara")
        ged = self.temp / "share.ged"
        self.assertTrue(self.window.export_gedcom(ged, hide=True))
        text = ged.read_text(encoding="utf-8")
        self.assertIn("Ante", text)
        for private in ("Mara", "Marko", "1951", "Bili"):
            if private == "Bili":
                self.assertNotIn("Zvonko", text)
            else:
                self.assertNotIn(private, text, private)
        self.assertFalse((self.temp / "share_media").exists())
        self.assertEqual(self.window.tree.people["mara"].given, "Mara")

    def test_png_export(self):
        self.open_sample()
        path = self.temp / "tree.png"
        self.assertTrue(self.window.export_picture(path))
        image = QImage(str(path))
        self.assertFalse(image.isNull())
        self.assertGreater(image.width(), 2000)

    def test_pdf_export(self):
        self.open_sample()
        path = self.temp / "tree.pdf"
        self.assertTrue(self.window.export_picture(path))
        data = path.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 2000)
        self.assertEqual(list(self.temp.glob(".*.tmp")), [])

    @unittest.skipUnless(shutil.which("pdftotext"), "needs pdftotext")
    def test_pdf_names_are_complete_not_cut_off(self):
        self.open_sample()
        path = self.temp / "tree.pdf"
        self.window.export_picture(path)
        text = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8")
        for name in ("Ante Šimić", "Ružica Šimić", "Nikola Šimić", "1925 - 2004"):
            self.assertIn(name, text)

    def test_picture_without_a_known_ending_becomes_pdf(self):
        self.open_sample()
        self.assertTrue(self.window.export_picture(self.temp / "tree"))
        self.assertTrue((self.temp / "tree.pdf").is_file())

    def test_export_failure_is_reported(self):
        self.open_sample()
        self.assertFalse(self.window.export_gedcom(self.temp / "missing" / "x.ged"))
        self.assertTrue(self.answers.alerts)

    def test_screen_is_unchanged_by_export(self):
        self.open_sample()
        self.window.select("luka")
        self.window.export_picture(self.temp / "x.png", hide=True)
        self.assertEqual(self.window.person_items["mara"].name, "Mara Šimić")
        self.assertEqual(self.window.selected, "luka")


if __name__ == "__main__":
    unittest.main()


class AddButtonTests(WindowCase):
    """The labelled buttons around the selected card, and the always-open panel."""

    def keys_shown(self):
        return sorted(item.key for item in self.window.add_button_items)

    def click_button(self, key):
        item = next(i for i in self.window.add_button_items if i.key == key)
        view = self.window.view
        view.ensureVisible(item, 10, 10)
        QApplication.processEvents()
        point = view.mapFromScene(item.sceneBoundingRect().center())
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QApplication.processEvents()

    def test_one_person_tree_is_selected_with_panel_and_buttons(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Tomo", "surname": "Šimić"}]
        self.window.add_first_person()
        tomo = self.person_named("Tomo").id
        self.assertEqual(self.window.selected, tomo)
        self.assertTrue(self.window.panel.isVisible())
        self.assertEqual(self.keys_shown(), ["add_child", "add_father", "add_mother", "add_partner", "add_sibling"])
        self.assertIsNotNone(self.window.panel.findChild(QPushButton, "action_add_father"))

    def test_reopened_tree_starts_with_someone_selected(self):
        self.start_family()
        self.window.open_path(self.folder)
        self.assertIsNotNone(self.window.selected)
        self.assertTrue(self.window.panel.isVisible())
        self.assertTrue(self.window.add_button_items)

    def test_father_button_adds_a_father_with_the_surname(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Tomo", "surname": "Šimić"}]
        self.window.add_first_person()
        tomo = self.person_named("Tomo").id
        self.answers.people = [{"given": "Ante", "surname": "Šimić", "sex": "M", "link": "birth"}]
        self.click_button("add_father")
        asked = self.answers.asked[-1]
        self.assertEqual(asked["initial"]["sex"], "M")
        self.assertEqual(asked["initial"]["surname"], "Šimić")
        family = self.window.tree.birth_family_of(tomo)
        self.assertIn(self.person_named("Ante").id, family.partners)
        self.window.select(tomo)
        self.assertNotIn("add_father", self.keys_shown())
        self.assertIn("add_mother", self.keys_shown())
        self.assertIn("add_sibling", self.keys_shown())

    def test_mother_gets_no_guessed_surname(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Tomo", "surname": "Šimić"}]
        self.window.add_first_person()
        tomo = self.person_named("Tomo").id
        self.answers.people = [None]
        self.window.run_action("add_mother", tomo)
        initial = self.answers.asked[-1]["initial"]
        self.assertEqual(initial["sex"], "F")
        self.assertNotIn("surname", initial)

    def test_child_button_and_add_another(self):
        ana = self.start_family()
        self.window.select(ana)
        self.answers.people = [
            {"given": "Rea", "link": "birth", "add_another": True},
            {"given": "Lea", "link": "birth"},
        ]
        self.click_button("add_child")
        self.assertTrue(self.person_named("Rea"))
        self.assertTrue(self.person_named("Lea"))

    def test_no_add_buttons_when_read_only(self):
        self.window.load_sample()
        self.assertIsNotNone(self.window.selected)
        self.assertEqual(self.window.add_button_items, [])

    def test_add_buttons_are_not_in_exported_pictures(self):
        from exports import _prepared_scene
        from canvas import AddButtonItem, INK_SCREEN
        ana = self.start_family()
        self.window.select(ana)
        layout = self.window._layout_for(self.window.tree)
        scene, _ = _prepared_scene(self.window.tree, layout, TODAY, self.window._photo_for, INK_SCREEN)
        self.assertFalse(any(isinstance(i, AddButtonItem) for i in scene.items()))

    def test_arrow_keys_move_between_people(self):
        ana = self.start_family()
        mia = self.person_named("Mia").id
        ivo = self.person_named("Ivo").id
        self.window.select(ana)
        self.window.view.setFocus()
        QTest.keyClick(self.window.view, Qt.Key.Key_Down)
        self.assertEqual(self.window.selected, mia)
        QTest.keyClick(self.window.view, Qt.Key.Key_Up)
        self.assertIn(self.window.selected, (ana, ivo))
        self.window.select(ana)
        QTest.keyClick(self.window.view, Qt.Key.Key_Right)
        self.assertEqual(self.window.selected, ivo)

    def test_search_box_jumps_to_a_person(self):
        ana = self.start_family()
        self.window.select(ana)
        box = self.window.search_box
        box.setText("mia")
        box.textEdited.emit("mia")
        box.returnPressed.emit()
        self.assertEqual(self.window.selected, self.person_named("Mia").id)

    def test_recent_trees_are_remembered(self):
        self.start_family()
        other = self.temp / "Other.tree"
        self.window.new_tree(other)
        self.assertEqual(Path(self.window._recent_trees()[0]), other)
        self.assertEqual(Path(self.window._recent_trees()[1]), self.folder)
        self.window._fill_recent_menu()
        names = [a.text() for a in self.window.recent_menu.actions()]
        self.assertIn("Test", names)

    def test_people_count_in_status_bar(self):
        self.start_family()
        self.assertIn("3", self.window.count_label.text())


class StartupFocusTests(WindowCase):
    def test_arrow_keys_work_right_after_opening(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.activateWindow()
        QTest.qWaitForWindowActive(self.window)
        before = self.window.selected
        self.assertIs(QApplication.focusWidget(), self.window.view)
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Down)
        self.assertNotEqual(self.window.selected, before)


class StrayWindowTests(WindowCase):
    def test_rebuilding_the_panel_leaves_no_loose_windows(self):
        # Old panel buttons once lost their parent and flashed up as separate windows.
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Tomo", "surname": "Šimić"}]
        self.window.add_first_person()
        tomo = self.person_named("Tomo").id
        self.answers.people = [{"given": "Ante", "sex": "M", "link": "birth"}]
        self.window.run_action("add_father", tomo)
        loose = [w for w in QApplication.topLevelWidgets() if isinstance(w, QPushButton)]
        self.assertEqual(loose, [])


class NewPersonVisibleTests(WindowCase):
    def test_parent_of_a_married_in_partner_is_shown(self):
        # Adding a grandfather on the mother's side once left him off screen.
        ana = self.start_family()  # Ana heads the line; Ivo married in.
        ivo = self.person_named("Ivo").id
        self.answers.people = [{"given": "Stari", "sex": "M", "link": "birth"}]
        self.window.run_action("add_father", ivo)
        stari = self.person_named("Stari").id
        self.assertIn(stari, self.window.visible_ids)
        self.assertEqual(self.window.selected, stari)
        self.window.go_back()
        self.assertIn(ana, self.window.visible_ids)

    def test_fit_centres_on_people_not_add_buttons(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Tomo"}]
        self.window.add_first_person()
        view = self.window.view
        view.fit_tree()
        card = self.window.person_items[self.window.selected]
        centre = view.mapToScene(view.viewport().rect().center())
        self.assertLess(abs(centre.x() - card.sceneBoundingRect().center().x()), 3)


class DuplicateTests(WindowCase):
    """Adding someone who is already in the tree offers to link them instead."""

    def family_with_two_lines(self):
        # Davor's parents Ivan and Đurđa; Dragan is Davor's brother.
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Davor", "surname": "Radić", "sex": "M"}]
        self.window.add_first_person()
        davor = self.person_named("Davor").id
        self.answers.people = [{"given": "Ivan", "surname": "Radić", "sex": "M", "link": "birth"}]
        self.window.run_action("add_father", davor)
        self.answers.people = [{"given": "Dragan", "surname": "Radić", "link": "birth"}]
        self.window.run_action("add_sibling", davor)
        return davor, self.person_named("Dragan").id

    def test_adding_an_existing_brother_links_him(self):
        davor, dragan = self.family_with_two_lines()
        count = len(self.window.tree.people)
        self.answers.people = [{"given": "Davor", "surname": "Radic", "link": "birth"}]
        self.answers.duplicates = [0]
        self.window.run_action("add_sibling", dragan)
        self.assertEqual(len(self.window.tree.people), count)  # No second Davor.
        self.assertIn("Ivan", self.answers.duplicate_questions[-1][0])
        self.assertIn(davor, self.window.tree.birth_family_of(dragan).child_ids)

    def test_someone_with_other_parents_cannot_be_linked_as_sibling(self):
        davor, dragan = self.family_with_two_lines()
        self.answers.people = [{"given": "Mila", "surname": "Kovač", "relationships": {None: "married"}}]
        self.window.run_action("add_partner", davor)
        mila = self.person_named("Mila").id
        self.answers.people = [{"given": "Pero", "surname": "Kovač", "link": "birth"}]
        self.window.run_action("add_father", mila)
        count = len(self.window.tree.people)
        self.answers.people = [{"given": "Mila", "surname": "Kovač", "link": "birth"}]
        self.answers.duplicates = [0]
        self.window.run_action("add_sibling", dragan)
        self.assertEqual(len(self.window.tree.people), count)
        self.assertTrue(self.answers.alerts)  # Refused: Mila already has her own parents.
        self.assertNotIn(mila, self.window.tree.birth_family_of(dragan).child_ids)

    def test_choosing_new_still_adds_a_person(self):
        davor, dragan = self.family_with_two_lines()
        count = len(self.window.tree.people)
        self.answers.people = [{"given": "Davor", "surname": "Radić", "link": "birth"}]
        self.window.run_action("add_sibling", dragan)  # Default answer: a new person.
        self.assertEqual(len(self.window.tree.people), count + 1)

    def test_cancelling_the_question_adds_nobody(self):
        davor, dragan = self.family_with_two_lines()
        count = len(self.window.tree.people)
        self.answers.people = [{"given": "Davor", "surname": "Radić", "link": "birth"}]
        self.answers.duplicates = [None]
        self.window.run_action("add_sibling", dragan)
        self.assertEqual(len(self.window.tree.people), count)

    def test_different_birth_years_are_not_offered(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Ante", "surname": "Šimić", "birth_date": "1921"}]
        self.window.add_first_person()
        ante = self.person_named("Ante").id
        self.answers.people = [{"given": "Ante", "surname": "Šimić", "birth_date": "1950", "link": "birth"}]
        self.window.run_action("add_child", ante)
        self.assertEqual(self.answers.duplicate_questions, [])


class DragConnectTests(WindowCase):
    def drag(self, source, target):
        view = self.window.view
        start = view.mapFromScene(self.window.person_items[source].sceneBoundingRect().center())
        end = view.mapFromScene(self.window.person_items[target].sceneBoundingRect().center())
        viewport = view.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        for step in range(1, 9):
            QTest.mouseMove(viewport, start + (end - start) * step / 8)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        QApplication.processEvents()

    def test_drag_one_card_onto_another_to_make_siblings(self):
        self.start_family()
        mia = self.person_named("Mia").id
        self.answers.people = [{"given": "Teo", "relationships": {None: "married"}}]
        self.window.run_action("add_partner", mia)
        teo = self.person_named("Teo").id
        # Lone is Teo's earlier partner, unrelated to Ana's family.
        self.answers.choices = [1]
        self.answers.people = [{"given": "Lone", "relationships": {None: "married"}}]
        self.window.run_action("add_partner", teo)
        lone = self.person_named("Lone").id
        self.window.centre_on(teo)
        menus = []

        def pick(menu, position):
            menus.append([a.text() for a in menu.actions() if a.text()])
            next(a for a in menu.actions() if "brother or sister" in a.text()).trigger()

        self.window.show_menu = pick
        self.drag(mia, lone)
        self.assertEqual(len(menus), 1)
        self.assertEqual(len(menus[0]), 7)
        self.assertIn("Lone is a brother or sister of Mia", menus[0])
        self.assertIn(lone, self.window.tree.birth_family_of(mia).child_ids)
        self.assertEqual(self.answers.alerts, [])

    def test_making_a_partner_into_a_sibling_is_refused(self):
        self.start_family()
        mia = self.person_named("Mia").id
        self.answers.people = [{"given": "Teo", "relationships": {None: "married"}}]
        self.window.run_action("add_partner", mia)
        teo = self.person_named("Teo").id
        before = copy_tree(self.window.tree)
        self.window._link("sibling", mia, teo)
        self.assertTrue(self.answers.alerts)
        self.assertEqual(self.window.tree, before)

    def test_drag_onto_a_duplicate_merges_them(self):
        ana = self.start_family()
        self.answers.people = [{"given": "Mia", "link": "birth"}]
        self.window.run_action("add_child", ana)  # A second Mia, by mistake.
        mias = [p.id for p in self.window.tree.people.values() if p.given == "Mia"]
        self.window.refresh()
        self.window.show_menu = lambda menu, position: next(
            a for a in menu.actions() if "same person" in a.text()).trigger()
        self.answers.confirms = [True]
        self.drag(mias[1], mias[0])
        self.assertEqual([p.given for p in self.window.tree.people.values()].count("Mia"), 1)
        self.assertIn(mias[0], self.window.tree.people)

    def test_dragging_empty_space_still_pans(self):
        self.start_family()
        view = self.window.view
        before = view.mapToScene(view.viewport().rect().center())
        viewport = view.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
        for step in range(1, 9):
            QTest.mouseMove(viewport, QPoint(5 + step * 20, 5 + step * 10))
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=QPoint(165, 85))
        after = view.mapToScene(view.viewport().rect().center())
        self.assertGreater((after - before).manhattanLength(), 50)


class UndoLabelTests(WindowCase):
    def test_undo_says_what_it_will_undo(self):
        self.start_family()
        self.assertIn("add Mia", self.window.undo_action.text())
        self.window.undo()
        self.assertIn("add Mia", self.window.redo_action.text())
        self.assertIn("add Ivo", self.window.undo_action.text())

    def test_undo_several_steps_at_once(self):
        self.start_family()
        self.window._fill_undo_menu()
        labels = [a.text() for a in self.window.undo_menu.actions()]
        self.assertIn("add Mia", labels[0])
        self.assertEqual(len(self.window.tree.people), 3)
        self.window.undo_steps(2)
        self.assertEqual(len(self.window.tree.people), 1)
        self.assertEqual(self.saved()["people"].keys(), self.window.tree.to_dict()["people"].keys())


class NewTreeSafetyTests(WindowCase):
    def test_new_on_an_existing_tree_offers_to_open_it(self):
        create_tree(self.folder, sample_tree())
        self.answers.confirms = [True]
        self.assertTrue(self.window.new_tree(self.folder / "tree.json"))
        self.assertEqual(self.window.folder, self.folder)
        self.assertFalse((self.folder / "tree.json.tree").exists())

    def test_no_tree_inside_another_tree(self):
        create_tree(self.folder, sample_tree())
        self.assertFalse(self.window.new_tree(self.folder / "Inner"))
        self.assertFalse((self.folder / "Inner.tree").exists())
        self.assertIn("inside the family tree", self.answers.alerts[-1])


class FamilyViewTests(WindowCase):
    """The main view: one person in the middle, both parents' sides above."""

    def open_sample(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)

    def test_both_sides_are_shown_around_one_person(self):
        self.open_sample()
        self.window.centre_on("ivana")  # Luka's daughter; her mother Mara is a Bilić.
        shown = set(self.window.person_items)
        for person in ("ivana", "luka", "mara", "ante", "ruzica", "stipe", "jela", "marko", "petar"):
            self.assertIn(person, shown)
        items = self.window.person_items
        self.assertLess(items["ante"].y(), items["luka"].y())
        self.assertLess(items["luka"].y(), items["ivana"].y())
        self.assertLess(items["ante"].x(), items["stipe"].x())  # Father's side on the left.

    def test_double_click_opens_details_and_keeps_the_view(self):
        self.open_sample()
        self.window.centre_on("luka")
        view = self.window.view
        item = self.window.person_items["mara"]
        point = view.mapFromScene(item.sceneBoundingRect().center())
        self.answers.people = [None]
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QApplication.processEvents()
        self.assertIn("Edit", self.answers.asked[-1]["title"])
        self.assertEqual(self.window.house, "luka")  # The view did not move.

    def test_centre_on_keeps_the_person_in_place_and_says_so(self):
        self.open_sample()
        self.window.centre_on("luka")
        view = self.window.view
        before = view.mapFromScene(self.window.person_items["mara"].sceneBoundingRect().center())
        self.window.run_action("centre", "mara")
        self.assertEqual(self.window.house, "mara")
        self.assertIn("stipe", self.window.person_items)  # Her own parents are above her now.
        after = view.mapFromScene(self.window.person_items["mara"].sceneBoundingRect().center())
        self.assertLess((after - before).manhattanLength(), 3)
        self.assertIn("Centred on: Mara", self.window.where_label.text())
        self.window.go_back()
        self.assertEqual(self.window.house, "luka")
        self.assertIn("Centred on: Luka", self.window.where_label.text())

    def test_home_returns_to_the_first_person(self):
        self.open_sample()
        self.window.centre_on("mara")
        self.window.go_home()
        self.assertEqual(self.window.house, "ante")  # First in the sample family.

    def test_mothers_parents_can_be_added_in_place(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Tomo", "surname": "Radić", "sex": "M"}]
        self.window.add_first_person()
        tomo = self.person_named("Tomo").id
        self.answers.people = [{"given": "Vesna", "surname": "Lukach", "sex": "F", "link": "birth"}]
        self.window.run_action("add_mother", tomo)
        mother = self.person_named("Vesna").id
        self.assertEqual(self.window.house, tomo)  # Still centred on Tomo.
        self.answers.people = [{"given": "Stjepan", "surname": "Lukach", "sex": "M", "link": "birth"}]
        self.window.run_action("add_father", mother)
        stjepan = self.person_named("Stjepan").id
        self.assertEqual(self.window.house, tomo)
        self.assertIn(stjepan, self.window.person_items)
        self.assertEqual(self.window.selected, stjepan)

    def test_more_and_fewer_generations(self):
        self.open_sample()
        self.window.centre_on("ivana")
        self.window.change_generations(-2)  # Parents only.
        self.assertNotIn("ante", self.window.person_items)
        self.assertIn("luka", self.window.person_items)
        self.window.change_generations(1)
        self.assertIn("ante", self.window.person_items)

    def test_mode_is_remembered_on_reopen(self):
        self.open_sample()
        self.window.centre_on("mara")
        self.assertEqual(open_tree(self.folder).house, "mara")
        self.assertEqual(open_tree(self.folder).mode, "family")
        self.answers.choices = [0]
        self.window.choose_family_line()
        self.assertEqual(open_tree(self.folder).mode, "pyramid")
        self.window.go_back()
        self.assertEqual(self.window.chart, "family")


class FoldTests(WindowCase):
    """The round - / +N buttons on the lines fold whole branches away."""

    def open_sample(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.centre_on("ivana")

    def fold_button(self, person_id, direction):
        from canvas import FoldItem
        return next(i for i in self.window.view.scene().items()
                    if isinstance(i, FoldItem) and i.person_id == person_id and i.direction == direction)

    def click(self, item):
        view = self.window.view
        view.ensureVisible(item, 20, 20)
        QApplication.processEvents()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         pos=view.mapFromScene(item.sceneBoundingRect().center()))
        QApplication.processEvents()

    def test_fold_and_unfold_the_mothers_side(self):
        self.open_sample()
        self.assertIn("stipe", self.window.person_items)
        self.click(self.fold_button("mara", "up"))  # Mara is Ivana's mother.
        self.assertNotIn("stipe", self.window.person_items)
        self.assertNotIn("jela", self.window.person_items)
        self.assertIn("ante", self.window.person_items)  # The father's side stays.
        folded = self.fold_button("mara", "up")
        self.assertEqual(folded.text, "+3")  # Stipe, Jela and her brother Zvonko.
        self.click(folded)
        self.assertIn("stipe", self.window.person_items)

    def test_fold_descendants(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.centre_on("ante")
        self.click(self.fold_button("luka", "down"))
        self.assertNotIn("ivana", self.window.person_items)
        self.assertEqual(self.fold_button("luka", "down").text, "+3")
        self.click(self.fold_button("luka", "down"))
        self.assertIn("ivana", self.window.person_items)

    def test_folding_everything_above_the_centre(self):
        self.open_sample()
        self.click(self.fold_button("ivana", "up"))
        self.assertNotIn("luka", self.window.person_items)
        self.assertNotIn("marko", self.window.person_items)  # Brothers fold with the parents.
        self.window.expand_all()
        self.assertIn("luka", self.window.person_items)

    def test_fold_buttons_never_appear_in_pictures(self):
        from canvas import FoldItem
        from exports import _prepared_scene
        from canvas import INK_SCREEN
        self.open_sample()
        layout = self.window._layout_for(self.window.tree)
        scene, _ = _prepared_scene(self.window.tree, layout, TODAY, self.window._photo_for, INK_SCREEN)
        self.assertFalse(any(isinstance(i, FoldItem) for i in scene.items()))


class OpeningTests(WindowCase):
    """Finding and opening a tree without knowing that a tree is a folder."""

    def test_start_page_lists_trees_by_name(self):
        folder = self.temp / "Family Trees"
        create_tree(folder / "Radic.tree", sample_tree())
        create_tree(folder / "Other.tree", sample_tree())
        self.window._fill_start_page()
        names = [b.text() for b in self.window.start_page.findChildren(QPushButton) if b.isVisibleTo(self.window)]
        self.assertIn("Open Radic", names)
        self.assertIn("Open Other", names)
        button = next(b for b in self.window.start_page.findChildren(QPushButton)
                      if b.text() == "Open Radic" and b.isVisibleTo(self.window))
        button.click()
        self.assertEqual(self.window.folder, folder / "Radic.tree")

    def test_open_dialog_takes_the_tree_json_file(self):
        create_tree(self.folder, sample_tree())
        asked = []
        self.window.ask_open_file = lambda title, file_filter, start=None: asked.append(file_filter) or str(self.folder / "tree.json")
        self.window.choose_open_tree()
        self.assertEqual(self.window.folder, self.folder)
        self.assertIn("tree.json", asked[0])

    def test_reopens_the_most_recent_tree_when_the_last_one_has_gone(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        gone = self.temp / "Gone.tree"
        self.settings.setValue("last_tree", str(gone))
        self.assertEqual(Path(self.window.tree_to_reopen()), self.folder)


class AuntUncleTests(WindowCase):
    def test_parents_brothers_and_sisters_are_shown(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.centre_on("tomo")  # Josip's son; Josip's brothers are Luka and Ivan.
        items = self.window.person_items
        for uncle in ("luka", "ivan"):
            self.assertIn(uncle, items)
            self.assertEqual(items[uncle].y(), items["josip"].y())
        self.assertLess(items["luka"].x(), items["josip"].x())  # Father's side: on the left.
        self.assertIn("ivana", items)  # Cousins too, with their parents.
        self.assertIn("mara", items)  # Luka's wife.

    def test_folding_a_parents_side_hides_the_uncles_too(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.centre_on("tomo")
        self.window.toggle_fold("josip", "up")
        self.assertNotIn("luka", self.window.person_items)
        self.assertNotIn("ante", self.window.person_items)


class EveryoneTests(WindowCase):
    """The combined-tree shape: father's brother with wife and sons beside the centre."""

    def build(self):
        self.window.new_tree(self.folder)
        ask = lambda **v: setattr(self.answers, "people", [dict(v)])
        ask(given="Marin", surname="Radić", sex="M")
        self.window.add_first_person()
        tom = self.person_named("Marin").id
        ask(given="Davor", surname="Radić", sex="M", link="birth"); self.window.run_action("add_father", tom)
        davor = self.person_named("Davor").id
        ask(given="Vesna", surname="Lukach", sex="F", link="birth"); self.window.run_action("add_mother", tom)
        ask(given="Filip", surname="Radić", link="birth"); self.window.run_action("add_sibling", tom)
        ask(given="Ivan", surname="Radić", sex="M", link="birth"); self.window.run_action("add_father", davor)
        ask(given="Đurđa", surname="Radić", sex="F", link="birth"); self.window.run_action("add_mother", davor)
        ask(given="Dragan", surname="Radić", sex="M", link="birth"); self.window.run_action("add_sibling", davor)
        dragan = self.person_named("Dragan").id
        ask(given="Nada", surname="Radić", sex="F", relationships={None: "married"})
        self.window.run_action("add_partner", dragan)
        ask(given="Robert", surname="Radić", link="birth"); self.window.run_action("add_child", dragan)
        self.window.centre_on(tom)
        return tom, davor, dragan

    def test_uncle_with_his_family_is_shown_without_overlaps(self):
        tom, davor, dragan = self.build()
        items = self.window.person_items
        for name in ("Dragan", "Nada", "Robert", "Ivan", "Đurđa", "Vesna", "Filip"):
            self.assertIn(self.person_named(name).id, items, name)
        from devtools.checks import failures, run_checks
        self.assertEqual([str(p) for p in failures(run_checks(self.window))], [])

    def test_folding_the_uncle_hides_his_children(self):
        tom, davor, dragan = self.build()
        robert = self.person_named("Robert").id
        self.window.toggle_fold(dragan, "down")
        self.assertNotIn(robert, self.window.person_items)
        self.assertIn(dragan, self.window.person_items)

    def test_folding_the_fathers_side_hides_everyone_there(self):
        tom, davor, dragan = self.build()
        self.window.toggle_fold(davor, "up")
        for name in ("Ivan", "Đurđa", "Dragan", "Nada", "Robert"):
            self.assertNotIn(self.person_named(name).id, self.window.person_items, name)
        from canvas import FoldItem
        texts = [i.text for i in self.window.view.scene().items()
                 if isinstance(i, FoldItem) and i.person_id == davor]
        self.assertEqual(texts, ["+5"])  # Ivan, Đurđa, Dragan, Nada, Robert.


class ClearMessageTests(WindowCase):
    """Refusals name the people and the real reason; links can be removed."""

    def test_mother_as_child_of_fathers_mother_is_explained(self):
        # The owner's case: making the mother a daughter of the father's mother.
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        before = copy_tree(self.window.tree)
        self.window._link("child", "ruzica", "mara")  # Mara is Luka's wife, Ružica Luka's mother.
        self.assertEqual(self.window.tree, before)
        message = self.answers.alerts[-1]
        self.assertIn("Mara Šimić already has parents: Stipe Bilić and Jela Bilić", message)

    def test_an_existing_link_says_already(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window._link("child", "ante", "luka")
        self.assertIn("already", self.answers.alerts[-1])
        self.assertIn("Luka Šimić", self.answers.alerts[-1])

    def test_remove_from_parents_and_undo(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.answers.confirms = [True]
        self.window.run_action("remove_parents", "mara")
        self.assertIsNone(self.window.tree.birth_family_of("mara"))
        self.assertIn("mara", self.window.tree.people)  # Nobody is deleted.
        self.window.undo()
        self.assertIsNotNone(self.window.tree.birth_family_of("mara"))

    def test_remove_partnership_keeps_children(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.answers.confirms = [True]
        self.window.run_action("remove_partner", "luka")
        family = self.window.tree.birth_family_of("ivana")
        self.assertEqual(family.partners, ["luka"])
        self.assertIn("mara", self.window.tree.people)


class AdoptionTests(WindowCase):
    def test_adoptive_parents_come_in_addition_to_birth_parents(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        # Zvonko has birth parents Stipe and Jela; Ivan (no relation) adopts him too.
        self.window._link_dragged("adopted_child", "ivan", "zvonko")
        self.assertEqual(self.answers.alerts, [])
        kinds = [(f.partners, k) for f, k in self.window.tree.parent_families("zvonko")]
        self.assertEqual(kinds[0], (["stipe", "jela"], "birth"))
        self.assertIn("adopted", [k for _p, k in kinds])
        from model import validate
        self.assertEqual(validate(self.window.tree), [])
        self.window.go_to_person("zvonko")
        self.assertIn("Adoptive parents", self.window.panel.details.text())

    def test_add_adoptive_parent_action_makes_a_separate_family(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.answers.people = [{"given": "Kuma", "surname": "Test", "sex": "F", "link": "adopted"}]
        self.window.run_action("add_extra_parent", "ivana")  # Ivana already has both birth parents.
        kuma = self.person_named("Kuma").id
        families = self.window.tree.parent_families("ivana")
        self.assertEqual(len(families), 2)
        self.assertEqual(families[1], (families[1][0], "adopted"))
        self.assertEqual(families[1][0].partners, [kuma])
        self.assertEqual(self.answers.asked[-1]["link"], "adopted")

    def test_second_birth_parents_are_still_refused(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window._link_dragged("child", "ante", "mara")
        self.assertIn("already has parents", self.answers.alerts[-1])
        self.assertIn("adoptive", self.answers.alerts[-1])


class DateWarningTests(WindowCase):
    def make(self, child_born, parent_born="1950", parent_died="", parent_sex="M"):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Kid", "birth_date": child_born}]
        self.window.add_first_person()
        kid = self.person_named("Kid").id
        self.answers.people = [{"given": "Dad", "sex": parent_sex, "birth_date": parent_born,
                                "death_date": parent_died, "living": "no" if parent_died else "yes",
                                "link": "birth"}]
        self.window.run_action("add_father" if parent_sex == "M" else "add_mother", kid)
        return kid

    def warnings(self, person_id):
        from model import date_warnings
        return date_warnings(self.window.tree, person_id, TODAY)

    def test_parent_born_after_child(self):
        kid = self.make("1950", parent_born="1960")
        self.assertTrue(any("under 12" in w for w in self.warnings(kid)))

    def test_uncertain_dates_do_not_warn(self):
        kid = self.make("abt 1960", parent_born="abt 1950")  # Could be 14 years apart.
        self.assertEqual(self.warnings(kid), [])

    def test_born_after_mother_died(self):
        kid = self.make("1990", parent_born="1950", parent_died="1985", parent_sex="F")
        self.assertTrue(any("after" in w for w in self.warnings(kid)))

    def test_father_may_die_shortly_before_birth(self):
        kid = self.make("1986", parent_born="1950", parent_died="1985")
        self.assertEqual(self.warnings(kid), [])

    def test_dates_after_today_are_flagged(self):
        """Found by the MCP sweep: a birth in 2090 was accepted without a word."""
        kid = self.make(str(TODAY.year + 64), parent_born="1950")
        self.assertTrue(any("after today" in w for w in self.warnings(kid)), self.warnings(kid))

    def test_a_birth_this_year_is_fine(self):
        self.assertEqual(self.warnings(self.make(str(TODAY.year), parent_born="1950")), [])

    def test_check_dates_lists_and_goes_to_the_person(self):
        kid = self.make("1950", parent_born="1960")
        self.answers.choices = [0]
        self.window.check_dates()
        self.assertEqual(self.window.selected, kid)
        self.assertIn("Check these dates", self.window.panel.details.text())

    def test_check_dates_says_when_all_is_well(self):
        self.make("1980", parent_born="1950")
        self.window.check_dates()
        self.assertEqual(self.answers.informed, ["No impossible dates found."])


class CardStyleTests(WindowCase):
    def open_sample(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)

    def test_every_style_draws_the_family_cleanly(self):
        import house_layout as hl
        from devtools.checks import failures, run_checks
        self.open_sample()
        for style in hl.STYLES:
            self.window.set_card_style(style)
            for focus in ("ivana", "luka", "ante"):
                self.window.centre_on(focus)
                self.window.select(focus)
                self.assertEqual([str(p) for p in failures(run_checks(self.window))], [], f"{style} {focus}")
            item = self.window.person_items["luka"]
            self.assertEqual(item.metrics.style, style)

    def test_style_is_a_personal_setting_that_persists(self):
        self.open_sample()
        self.window.set_card_style("compact")
        self.assertEqual(self.settings.value("card_style"), "compact")
        again = self.make_window()
        self.assertEqual(again.card_style, "compact")
        self.assertNotIn("card_style", (self.folder / "tree.json").read_text(encoding="utf-8"))

    def test_compact_style_is_much_smaller(self):
        self.open_sample()
        self.window.centre_on("ivana")
        tall = self.window.view.scene().itemsBoundingRect()
        self.window.set_card_style("compact")
        self.window.centre_on("ivana")
        small = self.window.view.scene().itemsBoundingRect()
        self.assertLess(small.height(), tall.height() * 0.6)

    def test_exports_use_the_chosen_style(self):
        from exports import _prepared_scene
        from canvas import INK_SCREEN
        self.open_sample()
        self.window.set_card_style("round")
        layout = self.window._layout_for(self.window.tree)
        from canvas import PersonItem
        scene, _area = _prepared_scene(self.window.tree, layout, TODAY, self.window._photo_for, INK_SCREEN)
        cards = [i for i in scene.items() if isinstance(i, PersonItem)]
        self.assertTrue(cards)
        self.assertTrue(all(i.metrics.style == "round" for i in cards))


class ProfessionalMenuTests(WindowCase):
    def open_sample(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)

    def menu_titles(self):
        return [a.text().replace("&", "") for a in self.window.menuBar().actions()]

    def test_menu_bar_has_the_usual_menus(self):
        self.assertEqual(self.menu_titles(), ["File", "Edit", "View", "Person", "Tools", "Help"])

    def test_mac_roles_are_set(self):
        from PySide6.QtGui import QAction
        roles = {a.text().replace("&", ""): a.menuRole() for m in self.window.menuBar().actions()
                 for a in m.menu().actions()}
        self.assertEqual(roles["Preferences..."], QAction.MenuRole.PreferencesRole)
        self.assertEqual(roles["Quit"], QAction.MenuRole.QuitRole)
        self.assertEqual(roles["About Maiores"], QAction.MenuRole.AboutRole)

    def test_person_menu_follows_the_selection(self):
        self.open_sample()
        self.window.select("luka")
        self.window._fill_person_menu()
        texts = [a.text() for a in self.window.person_menu.actions()]
        self.assertEqual(texts[0], "Luka Šimić")
        self.assertIn("Edit...", texts)

    def test_preferences_apply_and_persist(self):
        self.open_sample()
        self.window.ask_preferences = lambda values: {**values, "card_style": "round", "detail": "years",
                                                      "generations_up": 2, "reopen_last": False}
        self.window.show_preferences()
        self.assertEqual(self.window.card_style, "round")
        self.assertEqual(self.window.generations_up, 2)
        self.assertEqual(self.window.person_items["ante"].detail, "c. 1921 - 1988")
        again = self.make_window()
        self.assertEqual((again.card_style, again.detail_mode, again.generations_up, again.reopen_last),
                         ("round", "years", 2, False))

    def test_close_tree_releases_it(self):
        self.open_sample()
        self.window.close_tree()
        self.assertIsNone(self.window.tree)
        self.assertEqual(self.window.pages.currentIndex(), PAGE_START)
        other = self.make_window()
        self.assertTrue(other.open_path(self.folder))  # The lock was given up.

    def test_statistics(self):
        self.open_sample()
        shown = []
        self.window.ask_statistics = shown.append
        self.window.show_statistics()
        text = shown[-1]
        self.assertIn("People: 16", text)
        self.assertIn("Šimić", text)

    def test_hiding_the_side_panel(self):
        self.open_sample()
        self.window.panel_action.setChecked(False)
        self.window._toggle_panel()
        self.window.select("luka")
        self.assertFalse(self.window.panel.isVisible())


class ChartTests(WindowCase):
    def open_sample(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)

    def clean(self):
        from devtools.checks import failures, run_checks
        return [str(p) for p in failures(run_checks(self.window))]

    def test_every_chart_shows_and_survives_reopening(self):
        self.open_sample()
        for chart in ("pyramid", "pedigree", "bowtie", "fan", "family"):
            self.window.select("ivana")
            self.window.show_chart(chart)
            self.assertEqual(self.window.chart, chart)
            self.assertIn("ivana" if chart != "pyramid" else "ante", self.window.person_items)
            self.assertEqual(self.clean(), [], chart)
            self.assertEqual(open_tree(self.folder).mode, chart)
            self.assertEqual(self.window.chart_box.currentData(), chart)

    def test_bowtie_puts_fathers_side_left_and_mothers_right(self):
        self.open_sample()
        self.window.show_chart("bowtie", "ivana")
        items = self.window.person_items
        self.assertLess(items["ante"].x(), items["luka"].x())
        self.assertLess(items["luka"].x(), items["ivana"].x())
        self.assertGreater(items["stipe"].x(), items["mara"].x())
        self.assertGreater(items["mara"].x(), items["ivana"].x())
        self.assertEqual(self.window.add_button_items, [])  # Browse-only chart.

    def test_fan_wedges_are_clickable_and_selectable(self):
        from canvas import FanItem
        self.open_sample()
        self.window.show_chart("fan", "ivana")
        item = self.window.person_items["stipe"]
        self.assertIsInstance(item, FanItem)
        view = self.window.view
        view.ensureVisible(item.boundingRect().translated(item.scenePos()), 20, 20)
        QApplication.processEvents()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(item.click_point()))
        QApplication.processEvents()
        self.assertEqual(self.window.selected, "stipe")

    def test_keyboard_switches_charts_and_back_returns(self):
        self.open_sample()
        self.window.select("ivana")
        self.window.chart_actions["fan"].trigger()
        self.assertEqual(self.window.chart, "fan")
        self.window.go_back()
        self.assertEqual(self.window.chart, "family")

    def test_fan_export(self):
        self.open_sample()
        self.window.show_chart("fan", "ivana")
        path = self.temp / "fan.png"
        self.assertTrue(self.window.export_picture(path))
        self.assertTrue(path.stat().st_size > 1000)

    def test_old_line_view_files_open_as_pyramid(self):
        create_tree(self.folder, sample_tree())
        (self.folder / "view.json").write_text('{"format_version": 1, "house": "ante", "mode": "line"}',
                                               encoding="utf-8")
        self.assertEqual(open_tree(self.folder).mode, "pyramid")


class PhotoDropTests(WindowCase):
    def open_sample(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.centre_on("luka")

    def drop(self, mime, person_id):
        from PySide6.QtGui import QDropEvent
        view = self.window.view
        point = view.mapFromScene(self.window.person_items[person_id].click_point())
        event = QDropEvent(QPointF(point), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        view.dropEvent(event)
        QApplication.processEvents()

    def test_dropping_a_picture_file_sets_that_persons_photo(self):
        from PySide6.QtCore import QMimeData, QUrl
        self.open_sample()
        picture = self.make_photo("dropped.png", (300, 400))
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(picture))])
        self.drop(mime, "mara")
        photo = self.window.tree.people["mara"].photo
        self.assertTrue(photo.startswith("media/"))
        self.assertTrue((self.folder / photo).is_file())
        self.assertEqual(self.window.selected, "mara")
        self.window.undo()
        self.assertEqual(self.window.tree.people["mara"].photo, "")

    def test_non_pictures_are_ignored(self):
        from PySide6.QtCore import QMimeData, QUrl
        self.open_sample()
        text = self.temp / "notes.txt"
        text.write_text("hello")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(text))])
        self.drop(mime, "mara")
        self.assertEqual(self.window.tree.people["mara"].photo, "")

    def test_paste_a_copied_image(self):
        from PySide6.QtGui import QColor, QImage
        self.open_sample()
        self.window.select("ante")
        image = QImage(200, 260, QImage.Format.Format_RGB32)
        image.fill(QColor("#884422"))
        QApplication.clipboard().setImage(image)
        self.window.paste_photo()
        self.assertTrue(self.window.tree.people["ante"].photo)

    def test_compact_boxes_show_the_photo(self):
        self.open_sample()
        picture = self.make_photo("p.png", (300, 400))
        self.window.photo_dropped("mara", str(picture))
        self.window.set_card_style("compact")
        self.window.centre_on("luka")
        self.assertIsNotNone(self.window.person_items["mara"].pixmap)
        self.window.view.grab()  # Paints every card, including the photo path, without errors.


class PrintTests(WindowCase):
    def test_print_goes_to_the_chosen_printer_with_everyone_on_the_page(self):
        from PySide6.QtPrintSupport import QPrinter
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.centre_on("ivana")
        out = self.temp / "printed.pdf"

        def ask_print(printer):
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(out))
            return True

        self.window.ask_print = ask_print
        self.window.print_tree()
        self.assertTrue(out.is_file() and out.stat().st_size > 1000)
        if shutil.which("pdftotext"):
            text = subprocess.run(["pdftotext", "-enc", "UTF-8", str(out), "-"],
                                  capture_output=True).stdout.decode("utf-8")
            for name in ("Ivana", "Luka", "Stipe", "Jela"):
                self.assertIn(name, text)

    def test_wide_charts_print_landscape(self):
        from PySide6.QtGui import QPageLayout
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.show_chart("bowtie", "ivana")
        self.assertEqual(self.window._printer().pageLayout().orientation(), QPageLayout.Orientation.Landscape)

    def test_print_preview_paints_without_errors(self):
        from PySide6.QtCore import QTimer
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)

        def close_it():
            dialog = QApplication.activeModalWidget()
            if dialog is None:
                QTimer.singleShot(20, close_it)
            else:
                dialog.reject()

        QTimer.singleShot(50, close_it)
        self.window.print_preview()  # Builds and paints the preview pages, then closes.


class LanguageTests(WindowCase):
    def test_a_window_made_in_croatian_speaks_croatian(self):
        import strings
        strings.set_language("hr")
        try:
            window = self.make_window()
            titles = [a.text().replace("&", "") for a in window.menuBar().actions()]
            self.assertEqual(titles, ["Datoteka", "Uredi", "Prikaz", "Osoba", "Alati", "Pomoć"])
        finally:
            strings.set_language("en")

    def test_language_choice_is_saved_for_next_start(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.ask_preferences = lambda values: {**values, "language": "hr"}
        self.window.show_preferences()
        self.assertEqual(self.settings.value("language"), "hr")
        self.assertTrue(self.answers.informed)  # Says it takes effect after a restart.


    def test_every_language_builds_the_window_and_its_dialogs(self):
        import strings
        from dialogs import PreferencesDialog
        create_tree(self.folder, sample_tree())
        try:
            for code in strings.LANGUAGES:
                strings.set_language(code)
                window = self.make_window()
                window.alert = window.inform = lambda title, text, code=code: self.fail(f"{code}: {title}: {text}")
                self.assertTrue(window.open_path(self.folder), code)
                window.select("ivana")
                window._fill_person_menu()
                window._relation_to_home("ana")
                dialog = PreferencesDialog(window, {"card_style": "portrait", "detail": "years", "generations_up": 3,
                                                    "reopen_last": True, "language": "system"})
                self.assertEqual(dialog.language.count(), len(strings.LANGUAGES) + 1, code)
                dialog.deleteLater()
                window.close()  # Lets go of the tree, so the next language can open it.
        finally:
            strings.set_language("en")

    def test_a_stored_language_in_any_spelling_is_kept(self):
        self.settings.setValue("language", "pt_br")
        self.assertEqual(self.window.language_setting(), "pt_BR")
        self.settings.setValue("language", "xx")
        self.assertEqual(self.window.language_setting(), "system")


class CombineTests(WindowCase):
    def relative_tree(self):
        """A relative's copy of the sample family with one more person, saved as their own tree."""
        from edits import add_child, make_person
        theirs = sample_tree()
        add_child(theirs, "ivana", make_person({"given": "Lucija", "surname": "Šimić"}))
        folder = self.temp / "Relative.tree"
        create_tree(folder, theirs)
        return folder

    def test_a_relative_tree_is_combined_in_one_undoable_step(self):
        from combine_dialog import CombineDialog
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        relative = self.relative_tree()
        shown = []

        def ask(theirs, suggestions, name, initial):
            dialog = CombineDialog(self.window, self.window.tree, theirs, suggestions, name, initial)
            shown.append(dialog.summary.text())
            for row in range(dialog.table.rowCount()):  # Every row's differences can be shown.
                dialog._show_differences(row)
            values = dialog.values()
            dialog.deleteLater()
            return values

        self.window.ask_combine = ask
        before = len(self.window.tree.people)
        self.assertTrue(self.window.combine_with(str(relative / "tree.json")))
        self.assertEqual(len(self.window.tree.people), before + 1)
        lucija = next(p for p in self.window.tree.people.values() if p.given == "Lucija")
        self.assertEqual([f.partners for f, _l in self.window.tree.parent_families(lucija.id)][0][0], "ivana")
        self.assertIn("1", shown[0])
        self.assertEqual(validate(self.window.tree), [])
        self.assertEqual(len(open_tree(self.folder).tree.people), before + 1)  # Saved.
        self.assertFalse((relative / "backups").exists() and any((relative / "backups").iterdir()))
        self.window.undo()
        self.assertEqual(len(self.window.tree.people), before)

    def test_combining_with_the_open_tree_itself_is_refused(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.ask_combine = lambda *args: self.fail("no dialog expected")
        self.assertFalse(self.window.combine_with(str(self.folder)))
        self.assertTrue(self.answers.alerts)


class DocumentsAndSharingTests(WindowCase):
    def opened(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)

    def scan(self, name, content=b"%PDF-1.4 scan"):
        path = self.temp / name
        path.write_bytes(content)
        return str(path)

    def test_a_file_dropped_on_someone_is_attached_and_undoable(self):
        from model import person_documents
        self.opened()
        self.window.photo_dropped("ivana", self.scan("birth.pdf"))
        attached = person_documents(self.window.tree.people["ivana"])
        self.assertEqual([d["title"] for d in attached], ["birth"])
        self.assertTrue((self.folder / attached[0]["file"]).is_file())
        self.assertIn(("documents", True), [(k, e) for k, _l, e in self.window.person_actions("ivana")])
        self.window.undo()
        self.assertEqual(person_documents(self.window.tree.people["ivana"]), [])
        self.assertTrue((self.folder / attached[0]["file"]).is_file())  # Undo can bring it back.

    def test_programs_dropped_on_someone_are_refused(self):
        self.opened()
        self.assertFalse(self.window.attach_documents("ivana", [self.scan("setup.exe", b"MZ")]))
        self.assertTrue(self.answers.alerts)

    def test_the_documents_window_edits_the_list(self):
        from documents_dialog import DocumentsDialog
        from model import person_documents
        self.opened()
        dialog = DocumentsDialog(self.window, self.window.tree.people["ivana"], self.folder)
        self.assertEqual(dialog.add_files([self.scan("a.pdf"), self.scan("b.txt", b"letter"), self.scan("x.sh")]),
                         ["x.sh"])
        dialog.list.setCurrentRow(0)
        dialog.title.setText("Birth certificate")
        dialog.title.textEdited.emit("Birth certificate")
        dialog.private.setChecked(True)
        dialog.list.setCurrentRow(1)
        dialog.remove_current()
        self.window.ask_documents = lambda person: (dialog.values(), None)
        self.window._edit_documents("ivana")
        [kept] = person_documents(self.window.tree.people["ivana"])
        self.assertEqual((kept["title"], kept["private"]), ("Birth certificate", True))
        dialog.deleteLater()

    def test_private_marks_are_saved_from_the_person_window(self):
        self.opened()
        values = person_to_values(self.window.tree.people["ivana"])
        self.answers.people.append({**values, "private": True, "notes_private": True})
        self.window._edit_person("ivana")
        extra = self.window.tree.people["ivana"].extra
        self.assertTrue(extra.get("private") and extra.get("notes_private"))
        self.answers.people.append({**values, "private": False, "notes_private": False})
        self.window._edit_person("ivana")
        self.assertNotIn("private", self.window.tree.people["ivana"].extra)

    def test_a_copy_to_share_leaves_out_private_things_and_backups(self):
        from model import person_documents
        self.opened()
        self.window.photo_dropped("ante", self.scan("will.pdf", b"will"))
        self.window.photo_dropped("ante", self.scan("medical.pdf", b"medical"))
        items = person_documents(self.window.tree.people["ante"])
        items[1]["private"] = True
        self.window.apply_edit(lambda: self.window.tree.people["ante"].extra.update(documents=items))
        self.assertTrue(any((self.folder / "backups").iterdir()))  # Your own tree has backups...
        target = self.temp / "Shared.tree"
        self.assertTrue(self.window.make_share_copy(target, hide=True))
        self.assertEqual(list((target / "backups").iterdir()), [])  # ...the shared copy gets none of them.
        shared = open_tree(target).tree
        self.assertEqual([d["title"] for d in person_documents(shared.people["ante"])], ["will"])
        self.assertTrue((target / items[0]["file"]).is_file())
        self.assertFalse((target / items[1]["file"]).exists())
        living = [p for p in shared.people.values() if p.extra.get("hidden")]
        self.assertTrue(living and all(not p.given and not p.photo for p in living))
        self.assertEqual(validate(shared), [])


class SourcesNamesRolesWindowTests(WindowCase):
    def opened(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_sources import parish_tree
        create_tree(self.folder, parish_tree())
        self.window.open_path(self.folder)

    def test_the_person_window_saved_unchanged_keeps_everything(self):
        import json
        from dialogs import EventDialog
        from facts_dialogs import FactContext
        self.opened()
        before = json.dumps(self.window.tree.to_dict(), sort_keys=True)
        for person_id in list(self.window.tree.people):
            person = self.window.tree.people[person_id]
            rows = []
            for own in self.window.tree.families_of(person_id):
                marriage = app_module.family_marriage(own)
                rows.append((own.id, "", own.relationship, {**marriage, "date": date_input_text(marriage["date"])}))
            dialog = PersonDialog(self.window, "x", person_to_values(person), None, rows,
                                  context=FactContext(self.window.tree))
            values = dialog.values()
            for event in values["events"]:  # Each life event through its own window too.
                event.update(EventDialog(self.window, event, FactContext(self.window.tree)).values())
            dialog.deleteLater()
            self.answers.people.append(values)
            self.window._edit_person(person_id)
        self.assertEqual(json.dumps(self.window.tree.to_dict(), sort_keys=True), before)

    def test_a_source_made_while_editing_is_stored_with_the_person(self):
        from model import tree_sources
        self.opened()
        values = person_to_values(self.window.tree.people["ivan"])
        values["death_citations"] = [{"source": "s-new", "page": "12"}]
        values["living"] = "no"
        self.window._pending_sources = {"s-new": {"title": "Death register", "author": "", "repository": "",
                                                  "note": ""}, "s-unused": {"title": "Not cited"}}
        self.answers.people.append(values)
        self.window._edit_person("ivan")
        self.assertEqual({k: v["title"] for k, v in tree_sources(self.window.tree).items() if k != "s1"},
                         {"s-new": "Death register"})
        self.window.undo()
        self.assertNotIn("s-new", tree_sources(self.window.tree))

    def test_the_sources_window_merges_two_books(self):
        from model import cited_sources
        self.opened()
        self.window.apply_edit(lambda: self.window.tree.extra["sources"].update({"s2": {"title": "Same book"}}))
        self.window.apply_edit(lambda: self.window.tree.people["ivan"].extra.update(
            names=[{"given": "Ive", "surname": "", "type": "nickname", "citations": [{"source": "s2"}]}]))
        self.window.ask_sources = lambda: ({"s1": {"title": "Parish book"}}, {"s2": "s1"}, set())
        self.window.show_sources()
        self.assertEqual(cited_sources(self.window.tree), {"s1": 2})  # Davor's birth and the nickname.
        self.assertEqual(validate(self.window.tree), [])

    def test_the_panel_shows_names_people_roles_and_sources(self):
        self.opened()
        self.window.select("davor")
        text = self.window.panel.details.text()
        for words in ("Godfather", "Dragan", "don Ante", "Matična knjiga", "str. 47"):
            self.assertIn(words, text)
        self.window.select("dragan")
        self.assertIn("Davor", self.window.panel.details.text())  # Godfather at Davor's birth.
        self.window.select("ivan")
        self.assertIn("Joannes", self.window.panel.details.text())

    def test_find_looks_at_other_names(self):
        self.opened()
        self.assertEqual([p.id for p in matching_people(self.window.tree, "joannes")], ["ivan"])

    def test_the_small_windows_open_and_answer(self):
        from facts_dialogs import (CitationDialog, FactContext, NameDialog, RoleDialog, SourcesDialog,
                                   UnsourcedDialog, unsourced_facts)
        self.opened()
        context = FactContext(self.window.tree, find_person=lambda title: "dragan")
        role = RoleDialog(self.window, context)
        role.choose_person()
        self.assertEqual(role.values(), {"role": "godfather", "person": "dragan"})
        citation = CitationDialog(self.window, context)
        citation.ask_source = lambda: {"title": "Census 1931", "author": "", "repository": "", "note": ""}
        citation.new_source()
        self.assertEqual(context.source_title(citation.values()["source"]), "Census 1931")
        name = NameDialog(self.window, context, {"given": "Ive", "type": "nickname", "date": "about 1921"})
        self.assertTrue(name.buttons.button(name.buttons.StandardButton.Ok).isEnabled())
        sources = SourcesDialog(self.window, self.window.tree)
        sources.remove()  # Still cited: refused, with a note.
        self.assertIn("s1", sources.values()[0])
        unsourced = UnsourcedDialog(self.window, self.window.tree)
        self.assertEqual(len(unsourced.rows), len(unsourced_facts(self.window.tree)))
        for dialog in (role, citation, name, sources, unsourced):
            dialog.deleteLater()


class DuplicatesWindowTests(WindowCase):
    def twice(self):
        from edits import add_child, make_person
        tree = sample_tree()
        add_child(tree, "ante", make_person({"given": "Luka", "surname": "Šimić", "sex": "M", "birth_date": "1949"}))
        create_tree(self.folder, tree)
        self.window.open_path(self.folder)
        return next(p for p in self.window.tree.people if p != "luka" and self.window.tree.people[p].given == "Luka")

    def test_a_duplicate_is_merged_and_the_list_found_again(self):
        from duplicates_dialog import DuplicatesDialog
        copy = self.twice()
        shown = []

        def ask(candidates, selected):
            dialog = DuplicatesDialog(self.window, self.window.tree, candidates, selected)
            shown.append([(c.a, c.b) for c in candidates])
            dialog.list.setCurrentRow(next(i for i, c in enumerate(candidates) if copy in (c.a, c.b)))
            dialog.keep_left.click() if not shown[1:] else dialog.reject()
            answer = dialog.answer
            dialog.deleteLater()
            return answer

        self.window.ask_duplicates = ask
        before = len(self.window.tree.people)
        self.window.show_duplicates()
        self.assertEqual(len(self.window.tree.people), before - 1)
        self.assertNotIn(tuple(sorted(("luka", copy))), [p for found in shown[1:] for p in found])
        self.assertEqual(validate(self.window.tree), [])
        self.window.undo()
        self.assertEqual(len(self.window.tree.people), before)

    def test_not_the_same_person_is_remembered(self):
        copy = self.twice()
        answers = [("different", "luka", copy, 0), None]
        self.window.ask_duplicates = lambda candidates, selected: answers.pop(0)
        self.window.show_duplicates()
        from duplicates import find_duplicates
        self.assertNotIn(tuple(sorted(("luka", copy))), [(c.a, c.b) for c in find_duplicates(self.window.tree)])
        self.assertEqual(len(open_tree(self.folder).tree.extra.get("not_duplicates", [])), 1)


class ReportWindowTests(WindowCase):
    def test_a_book_and_a_poster_are_saved_from_the_window(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.select("ante")
        book = self.temp / "book"
        self.assertTrue(self.window.write_report(book, {"kind": "descendants", "generations": 3, "notes": True,
                                                        "sources": True, "format": "pdf"}, hide=True))
        self.assertTrue((self.temp / "book.pdf").read_bytes().startswith(b"%PDF"))
        poster_path = self.temp / "poster.pdf"
        self.assertTrue(self.window.export_poster(poster_path, {"paper": "A4", "across": 2}, hide=True))
        self.assertTrue(poster_path.read_bytes().startswith(b"%PDF"))

    def test_the_report_and_poster_windows_answer(self):
        from reports_dialog import PosterDialog, ReportDialog
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        report = ReportDialog(self.window, "Ante")
        report.kind.setCurrentIndex(report.kind.findData("ancestors"))
        self.assertTrue(report.generations.isEnabled())
        self.assertEqual(report.values()["kind"], "ancestors")
        area = self.window._poster_scene(self.window.tree)[1]
        poster_window = PosterDialog(self.window, area)
        poster_window.across.setValue(1)
        self.assertIn("1 (1 × 1)", poster_window.pages.text())
        for dialog in (report, poster_window):
            dialog.deleteLater()


class FacesWindowTests(WindowCase):
    def group_photo(self):
        from PySide6.QtGui import QColor, QImage
        image = QImage(800, 600, QImage.Format.Format_RGB32)
        image.fill(QColor("#b9a37e"))
        path = self.temp / "group.jpg"
        image.save(str(path))
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.attach_documents("ante", [str(path)])
        from model import person_documents
        return person_documents(self.window.tree.people["ante"])[0]["file"]

    def test_faces_are_marked_kept_and_become_a_portrait(self):
        from model import face_links, person_documents, photos_of
        stored = self.group_photo()
        faces = [{"rect": [0.1, 0.2, 0.15, 0.2], "person": "ante"}, {"rect": [0.6, 0.2, 0.15, 0.2], "name": "Kata"}]
        self.window.ask_documents = lambda person: (person_documents(person), None, {stored: faces},
                                                    [("ante", stored, faces[0]["rect"])])
        self.window._edit_documents("ante")
        self.assertEqual(face_links(self.window.tree)[stored], faces)
        self.assertTrue(self.window.tree.people["ante"].photo)
        self.assertEqual(photos_of(self.window.tree, "ante"), [(stored, "group")])
        self.window.select("ante")
        self.assertIn("Photos with them", self.window.panel.details.text())
        # Editing the documents again without touching faces keeps them.
        self.window.ask_documents = lambda person: (person_documents(person), None)
        self.window._edit_documents("ante")
        self.assertEqual(face_links(self.window.tree)[stored], faces)
        self.window.undo()
        self.window.undo()
        self.assertEqual(face_links(self.window.tree), {})

    def test_the_faces_window_draws_names_and_picks_a_portrait(self):
        from documents_dialog import DocumentsDialog
        from facts_dialogs import FactContext
        from faces_dialog import FacesDialog
        from PySide6.QtCore import QPoint
        stored = self.group_photo()
        context = FactContext(self.window.tree, find_person=lambda title: "luka")
        documents_window = DocumentsDialog(self.window, self.window.tree.people["ante"], self.folder, None, {},
                                           context)
        self.assertTrue(documents_window.faces_button.isEnabled())
        image = __import__("photos").read_image(self.temp / "group.jpg")
        window = FacesDialog(self.window, image, [], context)
        window.resize(900, 600)
        window.show()
        canvas = window.canvas
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
        QTest.mouseMove(canvas, QPoint(180, 190))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(180, 190))
        self.assertEqual(len(window.values()), 1)
        window.choose_person()
        window.use_as_portrait()
        self.assertEqual([p for p, _r in window.portraits], ["luka"])
        documents_window.ask_faces = lambda image, faces: (window.values(), window.portraits)
        documents_window.mark_faces()
        self.assertEqual(documents_window.face_changes[stored][0]["person"], "luka")
        self.assertEqual(documents_window.portraits[0][:2], ("luka", stored))
        for dialog in (window, documents_window):
            dialog.deleteLater()

    def test_a_portrait_box_stays_inside_the_picture_and_has_portrait_shape(self):
        from faces_dialog import portrait_crop
        from photos import STORED_H, STORED_W
        from PySide6.QtGui import QImage
        image = QImage(800, 600, QImage.Format.Format_RGB32)
        for rect in ([0.0, 0.0, 0.1, 0.1], [0.9, 0.85, 0.1, 0.15], [0.4, 0.3, 0.2, 0.3], [0.0, 0.0, 1.0, 1.0]):
            crop = portrait_crop(image, rect)
            self.assertTrue(image.rect().contains(crop), (rect, crop))
            self.assertAlmostEqual(crop.width() / crop.height(), STORED_W / STORED_H, delta=0.02)


class PlacesAndResearchWindowTests(WindowCase):
    def opened(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_sources import parish_tree
        create_tree(self.folder, parish_tree())
        self.window.open_path(self.folder)

    def test_the_places_window_edits_renames_and_is_one_undo_step(self):
        from dialogs import PlacesDialog
        from model import all_facts, place_records
        self.opened()
        dialog = PlacesDialog(self.window, self.window.tree, all_facts(self.window.tree))
        row = dialog.shown.index("Trogir")
        dialog.places.setCurrentRow(row)
        editor = dialog.editor
        self.assertEqual(editor.lat.text(), "43.5167")
        editor.name.setText("Trogir (town)")
        editor.lon.setText("16,2511")
        editor.save.click()
        self.assertIn("Trogir (town)", dialog.shown)
        editor.parent_place.setCurrentText("Trogir (town)")  # Inside itself: refused, with the reason.
        editor.save.click()
        self.assertTrue(editor.problem.text())
        operations = dialog.operations
        dialog.deleteLater()
        self.window.ask_places = lambda rows: (None, operations)
        self.window.show_places()
        self.assertEqual(self.window.tree.people["davor"].birth["place"], "Trogir (town)")
        self.assertEqual(place_records(self.window.tree)["Trogir (town)"]["lon"], 16.2511)
        self.assertEqual(validate(self.window.tree), [])
        self.window.undo()
        self.assertEqual(self.window.tree.people["davor"].birth["place"], "Trogir")

    def test_bad_coordinates_are_explained(self):
        from places_dialog import PlaceEditor
        editor = PlaceEditor()
        editor.show_place("X", {}, [])
        editor.lat.setText("95")
        editor.lon.setText("10")
        self.assertIsNone(editor.record())
        self.assertTrue(editor.problem.text())
        editor.deleteLater()

    def test_to_do_and_life_story_from_the_panel(self):
        from model import person_story, person_tasks
        from research_dialogs import ResearchDialog, StoryDialog, TasksDialog
        self.opened()
        tasks = TasksDialog(self.window, self.window.tree.people["ivan"])
        tasks.ask_text = lambda current="": "Ask aunt Kata"
        tasks.add()
        tasks.list.item(0).setCheckState(Qt.CheckState.Checked)
        self.window.ask_tasks = lambda person: tasks.values()
        self.window.run_action("tasks", "ivan")
        self.assertEqual([(x["text"], x["done"]) for x in person_tasks(self.window.tree.people["ivan"])],
                         [("Find Ivan's death in the Trogir books", True), ("Ask aunt Kata", False)])
        story = StoryDialog(self.window, self.window.tree.people["ivan"])
        story.text.setPlainText("New story.")
        story.private.setChecked(True)
        self.window.ask_story = lambda person: story.values()
        self.window.run_action("story", "ivan")
        self.assertEqual(person_story(self.window.tree.people["ivan"]), "New story.")
        self.window.select("ivan")
        text = self.window.panel.details.text()
        self.assertIn("New story.", text)
        self.assertIn("Ask aunt Kata", text)
        research = ResearchDialog(self.window, self.window.tree)
        self.assertEqual(research.list.count(), 1)  # The done one hides until asked.
        research.show_done.setChecked(True)
        self.assertEqual(research.list.count(), 2)
        for dialog in (tasks, story, research):
            dialog.deleteLater()


class MapWindowTests(WindowCase):
    def test_nothing_goes_online_without_a_yes_and_the_answer_is_kept(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.answers.confirms = [False]
        factory, reason = self.window._tile_source_factory()
        self.assertIsNone(factory)
        self.assertTrue(reason)
        self.assertEqual(self.settings.value("map_tiles_allowed"), "no")
        factory, _reason = self.window._tile_source_factory()  # Asked once only.
        self.assertIsNone(factory)
        self.answers.confirms = [False]
        self.assertIsNone(self.window._place_search())
        self.assertEqual(self.settings.value("map_search_allowed"), "no")

    def test_preferences_can_give_and_take_back_the_permission(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.ask_preferences = lambda values: {**values, "map_tiles": True}
        self.window.show_preferences()
        self.assertEqual(self.settings.value("map_tiles_allowed"), "yes")
        self.window.ask_preferences = lambda values: {**values, "map_tiles": False}
        self.window.show_preferences()
        self.assertEqual(self.settings.value("map_tiles_allowed"), "no")
        self.assertIsNone(self.settings.value("map_search_allowed"))  # Never asked, never set.

    def test_positions_set_on_the_map_are_one_undo_step(self):
        from model import place_records
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.ask_map = lambda: (None, [("set", "Split", {"lat": 43.508, "lon": 16.44})])
        self.window.show_map()
        self.assertEqual(place_records(self.window.tree)["Split"]["lat"], 43.508)
        self.window.undo()
        self.assertNotIn("Split", place_records(self.window.tree))

    def test_the_real_map_window_opens_offline_in_a_test(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.answers.confirms = [False]
        from map_dialog import MapDialog
        factory, reason = self.window._tile_source_factory()
        dialog = MapDialog(self.window, self.window.tree, "ante", factory, None, reason)
        self.assertIsNone(dialog.view.source)
        dialog.deleteLater()


class SiblingsWithoutParentsTests(WindowCase):
    def build(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Marin", "surname": "Radić", "sex": "M"}]
        self.window.add_first_person()
        tom = self.person_named("Marin").id
        self.answers.people = [{"given": "Davor", "surname": "Radić", "sex": "M", "link": "birth"}]
        self.window.run_action("add_father", tom)
        davor = self.person_named("Davor").id
        self.answers.people = [{"given": "Đurđa", "surname": "Radić", "sex": "F", "link": "birth"}]
        self.window.run_action("add_mother", davor)
        return tom, davor, self.person_named("Đurđa").id

    def clean(self):
        from devtools.checks import failures, run_checks
        return [str(p) for p in failures(run_checks(self.window))]

    def test_grandmother_without_parents_can_get_a_sister(self):
        tom, davor, durda = self.build()
        self.assertIn("add_sibling", [k for k, _l, on in self.window.person_actions(durda) if on])
        self.answers.people = [{"given": "Mara", "surname": "Kovač", "sex": "F", "link": "birth"}]
        self.window.run_action("add_sibling", durda)
        mara = self.person_named("Mara").id
        family = self.window.tree.birth_family_of(durda)
        self.assertEqual(family.partners, [])
        self.assertEqual(set(family.child_ids), {durda, mara})
        self.window.centre_on(tom)
        self.assertIn(mara, self.window.person_items)  # Shown beside her sister.
        self.assertEqual(self.clean(), [])

    def test_adding_a_parent_later_joins_both_sisters(self):
        tom, davor, durda = self.build()
        self.answers.people = [{"given": "Mara", "sex": "F", "link": "birth"}]
        self.window.run_action("add_sibling", durda)
        mara = self.person_named("Mara").id
        self.answers.people = [{"given": "Josip", "sex": "M", "link": "birth"}]
        self.window.run_action("add_father", durda)
        josip = self.person_named("Josip").id
        self.assertIn(josip, self.window.tree.birth_family_of(mara).partners)

    def test_your_own_brother_without_known_parents(self):
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Ana"}]
        self.window.add_first_person()
        ana = self.person_named("Ana").id
        self.answers.people = [{"given": "Brat", "link": "birth"}]
        self.window.run_action("add_sibling", ana)
        self.window.centre_on(ana)
        self.assertIn(self.person_named("Brat").id, self.window.person_items)
        self.assertEqual(self.clean(), [])

    def test_uncle_without_known_grandparents(self):
        # A father's brother, with the grandparents not known.
        self.window.new_tree(self.folder)
        self.answers.people = [{"given": "Kid"}]
        self.window.add_first_person()
        kid = self.person_named("Kid").id
        self.answers.people = [{"given": "Dad", "sex": "M", "link": "birth"}]
        self.window.run_action("add_father", kid)
        dad = self.person_named("Dad").id
        self.answers.people = [{"given": "Uncle", "link": "birth"}]
        self.window.run_action("add_sibling", dad)
        self.window.centre_on(kid)
        self.assertIn(self.person_named("Uncle").id, self.window.person_items)
        self.assertEqual(self.clean(), [])


class RelationshipFinderTests(WindowCase):
    def test_panel_says_how_the_selected_person_is_related_to_you(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)  # Ante is the first person: the home person.
        self.window.centre_on("ivana")
        self.window.select("ivana")
        self.assertIn("Relationship to Ante: granddaughter", self.window.panel.details.text())

    def test_how_are_they_related_lights_up_the_path(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.window.centre_on("ivana")
        self.window.select("ivana")
        self.answers.existing = ["zvonko"]
        self.window.find_relationship()
        self.assertIn("Zvonko Bilić is Ivana Šimić's uncle (mother's side).", self.answers.informed[-1])
        lit = {pid for pid, item in self.window.person_items.items() if item.on_path}
        self.assertEqual(lit, {"ivana", "mara", "stipe", "zvonko"} & set(self.window.person_items))
        self.window.select("luka")
        self.assertFalse(any(item.on_path for item in self.window.person_items.values()))


class LifeEventWindowTests(WindowCase):
    def test_editing_saves_events_marriage_and_sources(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        values = person_to_values(self.window.tree.people["luka"])
        values.update({"relationships": {}, "birth_citations": [{"source": "s-book", "page": "47"}],
                       "events": [{"type": "occupation", "date": "1975", "text": "stolar", "place": "Split"}],
                       "marriages": {"f-luka": {"date": "14.6.1975.", "place": "Split"}}})
        self.answers.people = [values]
        self.window._pending_sources = {"s-book": {"title": "matična knjiga"}}
        self.window.run_action("edit", "luka")
        luka = self.window.tree.people["luka"]
        self.assertEqual(luka.extra["events"][0]["text"], "stolar")
        self.assertEqual(luka.birth["citations"], [{"source": "s-book", "page": "47"}])
        self.assertEqual(self.window.tree.families["f-luka"].extra["marriage"],
                         {"date": "1975-06-14", "place": "Split"})
        self.window.select("luka")
        text = self.window.panel.details.text()
        self.assertIn("Occupation: stolar, 1975, Split", text)
        self.assertIn("married 14.6.1975, Split", text)
        self.assertEqual(self.saved()["people"]["luka"]["events"][0]["type"], "occupation")

    def test_a_bad_event_date_is_refused_with_its_name(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        values = person_to_values(self.window.tree.people["luka"])
        values.update({"relationships": {}, "events": [{"type": "burial", "date": "sometime"}]})
        self.answers.people = [values]
        before = copy_tree(self.window.tree)
        self.window.run_action("edit", "luka")
        self.assertEqual(self.window.tree, before)
        self.assertIn("Burial", self.answers.alerts[-1])

    def test_person_dialog_shows_and_returns_events(self):
        values = {"given": "Luka", "events": [{"type": "occupation", "date": "1975", "text": "stolar"}]}
        dialog = PersonDialog(self.window, "x", values, relationships=[("f1", "Mara", "married",
                                                                      {"date": "1975", "place": "Split"})])
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.events_list.count(), 1)
        self.assertIn("stolar", dialog.events_list.item(0).text())
        out = dialog.values()
        self.assertEqual(out["events"][0]["text"], "stolar")
        self.assertEqual(out["marriages"]["f1"]["place"], "Split")


class PlacesTimelineMapTests(WindowCase):
    def open_with_places(self):
        tree = sample_tree()
        tree.people["luka"].birth["place"] = "Split"
        tree.people["mara"].birth["place"] = "Trogir"
        tree.people["ivana"].birth["place"] = "Split"
        tree.people["luka"].extra["events"] = [{"type": "occupation", "date": "1975", "place": "Split", "text": "stolar"}]
        tree.families["f-luka"].extra["marriage"] = {"date": "1975-06-14", "place": "Trogir"}
        create_tree(self.folder, tree)
        self.window.open_path(self.folder)

    def test_places_lists_what_happened_where_and_goes_to_the_person(self):
        from dialogs import PlacesDialog
        from model import all_facts
        self.open_with_places()
        dialog = PlacesDialog(self.window, self.window.tree, all_facts(self.window.tree))
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.shown[0], "Split")  # Most events first.
        texts = [dialog.events.item(i).text() for i in range(dialog.events.count())]
        self.assertTrue(any("Born: Luka Šimić" in x for x in texts))
        self.assertTrue(any("Occupation: Luka Šimić (stolar)" in x for x in texts))
        dialog.filter.setText("trog")
        self.assertEqual(dialog.shown, ["Trogir"])
        marriage = [dialog.events.item(i).text() for i in range(dialog.events.count())]
        self.assertTrue(any("Married: Luka Šimić and Mara Šimić" in x for x in marriage))
        self.window.ask_places = lambda rows: "mara"
        self.window.show_places()
        self.assertEqual(self.window.selected, "mara")

    def test_timeline_is_in_date_order(self):
        from dialogs import TimelineDialog
        from model import all_facts, fact_year
        self.open_with_places()
        dialog = TimelineDialog(self.window, self.window.tree, all_facts(self.window.tree), fact_year)
        self.addCleanup(dialog.deleteLater)
        import re
        years = [int(re.findall(r"\d{4}", dialog.list.item(i).text())[0]) for i in range(dialog.list.count())]
        self.assertEqual(years, sorted(years))  # Including "about 1921", which once sorted last.
        self.assertIn("Stipe", dialog.list.item(0).text())  # Born about 1920: the earliest.
        self.assertGreater(dialog.list.count(), 10)

    def test_map_pins_csv_for_google_my_maps(self):
        import csv
        self.open_with_places()
        out = self.temp / "pins.csv"
        self.assertTrue(self.window.export_map(out, births_only=True))
        rows = list(csv.reader(out.read_text(encoding="utf-8-sig").splitlines()))
        self.assertEqual(rows[0], ["Name", "Event", "Date", "Place"])
        self.assertEqual(sorted(r[3] for r in rows[1:]), ["Split", "Split", "Trogir"])
        self.assertIn("google.com/mymaps", self.answers.informed[-1])
        self.window.export_map(out, births_only=False)
        everything = list(csv.reader(out.read_text(encoding="utf-8-sig").splitlines()))
        self.assertEqual(len(everything) - 1, 5)  # 3 births, the occupation and the marriage.

    def test_map_pins_can_hide_the_living(self):
        import csv
        self.open_with_places()
        out = self.temp / "pins.csv"
        self.window.export_map(out, births_only=True, hide=True)
        rows = list(csv.reader(out.read_text(encoding="utf-8-sig").splitlines()))
        self.assertNotIn("Ivana Šimić", [r[0] for r in rows])  # Ivana is living; her details are hidden.


class StaleCardTests(WindowCase):
    def test_moving_the_mouse_after_the_tree_is_redrawn_mid_press(self):
        """A press on a card, then a redraw (say Edit from a double-click), then the mouse moves."""
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        view = self.window.view
        start = view.mapFromScene(self.window.person_items["luka"].click_point())
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        self.window.refresh()  # The old cards are deleted while the button is still down.
        QApplication.processEvents()
        for step in range(1, 6):
            QTest.mouseMove(view.viewport(), start + QPoint(step * 15, step * 10))
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(75, 50))
        QApplication.processEvents()
        # The slot-error guard in setUp fails this test if anything touched a deleted card.

    def test_dragging_a_picture_across_a_redraw(self):
        from PySide6.QtCore import QMimeData, QUrl
        from PySide6.QtGui import QDragMoveEvent, QDragLeaveEvent
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        view = self.window.view
        picture = self.make_photo("x.png", (100, 120))
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(picture))])
        point = view.mapFromScene(self.window.person_items["luka"].click_point())
        view.dragMoveEvent(QDragMoveEvent(point, Qt.DropAction.CopyAction, mime,
                                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        self.window.refresh()
        view.dragLeaveEvent(QDragLeaveEvent())


class HelpTests(WindowCase):
    def open_sample(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)

    def test_tour_walks_through_every_step_and_is_remembered(self):
        self.open_sample()
        self.window.start_tour()
        tour = self.window.tour
        self.assertEqual(tour.counter.text(), "1 / 7")
        for _ in range(6):
            tour.next_button.click()
        self.assertEqual(tour.counter.text(), "7 / 7")
        self.assertEqual(tour.next_button.text(), "Done")
        tour.next_button.click()
        self.assertIsNone(self.window.tour)
        self.assertEqual(self.settings.value("first_tour"), "done")

    def test_every_tour_step_points_at_something_on_screen(self):
        self.open_sample()
        self.window.resize(1280, 860)
        QApplication.processEvents()
        for find, key in self.window._tour_steps():
            rect = find()
            self.assertTrue(rect is not None and self.window.rect().contains(rect.center()), key)
            if key in ("tour_cards", "tour_folds"):  # Things on the chart lie inside the chart's view.
                view = QRect(self.window.view.viewport().mapTo(self.window, QPoint(0, 0)),
                             self.window.view.viewport().size())
                self.assertTrue(view.contains(rect), key)

    def test_tour_buttons_are_whole_and_the_bubble_leaves_its_card_visible(self):
        """Found by the MCP sweep: "Don't show again" was cut short, and on the fan and
        pedigree charts the bubble sat on top of the big card it was explaining."""
        import strings
        self.open_sample()
        self.window.resize(1500, 950)
        for chart in ("family", "fan", "pedigree"):
            self.window.chart_actions[chart].trigger()
            QApplication.processEvents()
            for code in ("en", "de", "hr"):
                strings.set_language(code, [])
                try:
                    self.window.start_tour()
                    tour = self.window.tour
                    QApplication.processEvents()
                    for button in (tour.never_button, tour.skip_button, tour.back_button, tour.next_button):
                        self.assertGreaterEqual(button.width(), button.sizeHint().width(), (chart, code, button.text()))
                    card = tour.target()
                    bubble = tour.bubble.geometry()
                    overlap = bubble.intersected(card)
                    covered = overlap.width() * overlap.height() if overlap.isValid() else 0
                    self.assertLess(covered, 0.5 * card.width() * card.height(), (chart, code))
                    tour.next_button.click()  # Step 2 points elsewhere; the bubble must still be whole.
                    tour.finish()
                    QApplication.processEvents()
                    QApplication.processEvents()
                finally:
                    strings.set_language("en", [])
        # The tour left open while the chart changes underneath: the bubble must follow its card.
        self.window.chart_actions["family"].trigger()
        self.window.start_tour()
        QApplication.processEvents()
        for chart in ("fan", "pedigree"):
            self.window.chart_actions[chart].trigger()
            self.window.tour.update()
            QApplication.processEvents()
            tour = self.window.tour
            self.assertEqual(tour.placed_for, tour.target(), chart)  # Placed for the card as it is now.
            overlap = tour.bubble.geometry().intersected(tour.target())
            covered = overlap.width() * overlap.height() if overlap.isValid() else 0
            self.assertLess(covered, 0.5 * tour.target().width() * tour.target().height(), chart)
        self.window.tour.finish()

    def test_skip_closes_for_now_and_dont_show_again_is_kept(self):
        self.open_sample()
        self.window.start_tour()
        self.window.tour.skip_button.click()
        self.assertIsNone(self.settings.value("first_tour"))  # Skipped: offered again next start.
        self.window.start_tour()
        self.window.tour.never_button.click()
        self.assertIsNone(self.window.tour)
        self.assertEqual(self.settings.value("first_tour"), "done")

    def test_preferences_turn_the_tour_back_on_and_off(self):
        self.open_sample()
        self.settings.setValue("first_tour", "done")
        seen = []
        self.window.ask_preferences = lambda values: seen.append(values["show_tour"]) or {**values, "show_tour": True}
        self.window.show_preferences()
        self.assertEqual(seen, [False])
        self.assertIsNone(self.settings.value("first_tour"))
        self.window.ask_preferences = lambda values: {**values, "show_tour": False}
        self.window.show_preferences()
        self.assertEqual(self.settings.value("first_tour"), "done")

    def test_tour_never_starts_by_itself_in_tests(self):
        self.open_sample()
        QApplication.processEvents()
        self.assertIsNone(self.window.tour)

    def test_first_real_start_offers_the_tour_once(self):
        from PySide6.QtCore import QTimer
        self.window.auto_tour = True
        calls = []
        self.window.start_tour = lambda: calls.append(1)
        original = QTimer.singleShot
        QTimer.singleShot = staticmethod(lambda ms, fn: fn())
        try:
            self.open_sample()
            self.window.refresh()
        finally:
            QTimer.singleShot = original
        self.assertEqual(calls, [1])

    def test_user_guide_opens(self):
        self.open_sample()
        self.window.show_guide()
        self.addCleanup(self.window.guide_dialog.close)
        from PySide6.QtWidgets import QTextBrowser
        text = self.window.guide_dialog.findChild(QTextBrowser).toPlainText()
        self.assertIn("Adding relatives", text)
