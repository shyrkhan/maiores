"""Themes, card styles and line shapes."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import canvas  # noqa: E402
import theme  # noqa: E402
from model import Family, Person, Tree  # noqa: E402


class ThemeTests(unittest.TestCase):
    def tearDown(self):
        theme.apply("dark", app)

    def test_every_theme_has_every_colour(self):
        for name, palette in theme.PALETTES.items():
            self.assertEqual(sorted(palette), sorted(theme.KEYS), name)
            for key, value in palette.items():
                self.assertRegex(value, r"^#[0-9a-f]{6}$", (name, key))

    def test_a_theme_repaints_the_chart_colours_in_place(self):
        background = canvas.BACKGROUND  # The very object other modules imported.
        theme.apply("paper", app)
        self.assertEqual(background.name(), theme.PALETTES["paper"]["background"])
        self.assertEqual(canvas.INK_SCREEN["text"].name(), theme.PALETTES["paper"]["text"])
        self.assertEqual(app.palette().window().color().name(), theme.PALETTES["paper"]["panel"])
        theme.apply("nonsense", app)
        self.assertEqual(theme.current, "dark")

    def test_text_stays_readable_on_every_theme(self):
        for name in theme.PALETTES:
            theme.apply(name, app)
            text, background = theme.colour("text"), theme.colour("background")
            self.assertGreater(abs(text.lightness() - background.lightness()), 120, name)


class LineTests(unittest.TestCase):
    def test_segments_join_into_runs_at_corners_and_split_at_junctions(self):
        # A parent's drop onto the middle of the bar, and the bar turning down to two children:
        # the bar and both drops are one run with two corners; the parent's drop stands alone.
        lines = [(50, 0, 50, 10), (0, 10, 100, 10), (0, 10, 0, 20), (100, 10, 100, 20)]
        runs = canvas._runs(lines)
        self.assertEqual(sorted(len(r) for r in runs), [2, 4])
        # Three segments meeting at one point (a T made of segments) end the runs there.
        tee = [(0, 0, 10, 0), (10, 0, 20, 0), (10, 0, 10, 10)]
        self.assertEqual(sorted(len(r) for r in canvas._runs(tee)), [2, 2, 2])
        self.assertEqual(sum(len(r) - 1 for r in runs), len(lines))  # Every segment used once.

    def test_rounded_lines_stay_inside_the_square_ones(self):
        lines = [(0, 0, 0, 50), (0, 50, 80, 50), (80, 50, 80, 120)]
        square = canvas.lines_path(lines, 0).boundingRect()
        for radius in (14, 60, 500):
            rounded = canvas.lines_path(lines, radius)
            self.assertTrue(square.adjusted(-0.01, -0.01, 0.01, 0.01).contains(rounded.boundingRect()), radius)
            self.assertAlmostEqual(rounded.pointAtPercent(0).y(), 0)
            self.assertAlmostEqual(rounded.pointAtPercent(1).y(), 120)


class SideTests(unittest.TestCase):
    def test_each_side_of_the_family_gets_its_own_tint(self):
        from app import family_sides
        names = ("me", "dad", "mum", "granddad", "aunt", "cousin", "uncle", "brother", "son")
        people = {k: Person(k, given=k, sex="F" if k in ("mum", "aunt") else "M") for k in names}
        tree = Tree(people, {
            "f0": Family("f0", ["granddad"], "unknown", [{"person": "dad", "link": "birth"},
                                                         {"person": "aunt", "link": "birth"}]),
            "f1": Family("f1", ["dad", "mum"], "married", [{"person": "me", "link": "birth"},
                                                           {"person": "brother", "link": "birth"}]),
            "f2": Family("f2", ["aunt"], "unknown", [{"person": "cousin", "link": "birth"}]),
            "f3": Family("f3", ["uncle"], "unknown", [{"person": "mum", "link": "birth"}]),
            "f4": Family("f4", ["me"], "unknown", [{"person": "son", "link": "birth"}]),
        })
        sides = family_sides(tree, "me")
        father, mother = theme.colour("father_side"), theme.colour("mother_side")
        for person in ("dad", "granddad", "aunt", "cousin"):
            self.assertEqual(sides[person], father, person)
        for person in ("mum", "uncle"):
            self.assertEqual(sides[person], mother, person)
        for person in ("me", "brother", "son"):  # Both sides, or your own line: plain.
            self.assertNotIn(person, sides)


class PreferencesTests(unittest.TestCase):
    def test_card_choices_are_saved_and_used(self):
        import datetime
        import tempfile
        from PySide6.QtCore import QSettings
        import app as app_module
        from sample import sample_tree
        from storage import create_tree
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            create_tree(folder / "S.tree", sample_tree())
            settings = QSettings(str(folder / "s.ini"), QSettings.Format.IniFormat)
            window = app_module.MainWindow(settings, today=datetime.date(2026, 11, 14))
            window.open_path(folder / "S.tree")
            window.ask_preferences = lambda values: {**values, "lines": "curved", "colours": "surname",
                                                     "mark_deceased": True, "theme": "light"}
            window.show_preferences()
            self.assertEqual((canvas.DECOR.lines, canvas.DECOR.colours, canvas.DECOR.mark_deceased),
                             ("curved", "surname", True))
            self.assertTrue(canvas.DECOR.tints)
            self.assertEqual(theme.current, "light")
            luka = window.person_items["luka"]
            self.assertTrue(luka.detail_text().endswith("†"))
            window.close()
            theme.apply("dark", app)
            canvas.DECOR = canvas.Decor()


class PolishTests(unittest.TestCase):
    def window(self, folder):
        import datetime
        from PySide6.QtCore import QSettings
        import app as app_module
        from sample import sample_tree
        from storage import create_tree
        create_tree(folder / "S.tree", sample_tree())
        settings = QSettings(str(folder / "s.ini"), QSettings.Format.IniFormat)
        window = app_module.MainWindow(settings, today=datetime.date(2026, 11, 14))
        window.trees_folder = folder / "Family Trees"  # Never the real one.
        window.alert = window.inform = lambda title, text: self.fail(text)
        return window, settings

    def test_every_icon_draws_something_in_every_theme(self):
        import icons
        for name in theme.PALETTES:
            theme.apply(name, app)
            for icon_name in icons.NAMES:
                image = icons.icon(icon_name).pixmap(24, 24).toImage()
                inked = sum(image.pixelColor(x, y).alpha() > 0 for x in range(24) for y in range(24))
                self.assertGreater(inked, 20, (name, icon_name))
        theme.apply("dark", app)
        self.assertFalse(icons.draw_app_icon(64).isNull())

    def test_toolbar_style_and_motion_are_saved(self):
        import tempfile
        from PySide6.QtCore import Qt
        with tempfile.TemporaryDirectory() as folder:
            window, settings = self.window(Path(folder))
            self.assertEqual(window.toolbar.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.assertFalse(window.back_tool.icon().isNull())
            window.ask_preferences = lambda values: {**values, "toolbar": "both", "motion": False}
            window.show_preferences()
            self.assertEqual(window.toolbar.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.assertFalse(window.view.smooth)
            self.assertEqual(settings.value("toolbar_style"), "both")
            window.close()

    def test_the_overview_map_shows_the_tree_and_moves_the_view(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            window, settings = self.window(Path(folder))
            window.resize(1200, 800)
            window.show()
            window.open_path(Path(folder) / "S.tree")
            before = len(window.view.scene().items())
            window.minimap_action.trigger()
            minimap = window.view.minimap
            self.assertEqual(len(window.view.scene().items()), before)  # Drawing it once lost the lines.
            self.assertTrue(minimap.isVisible())
            self.assertEqual(settings.value("show_minimap"), "yes")
            self.assertIsNotNone(minimap.picture)
            corner = minimap.target().topLeft()
            minimap._go(corner)
            seen = window.view.mapToScene(window.view.viewport().rect().center())
            self.assertLess((seen - minimap.area.topLeft()).manhattanLength(), 60)
            minimap.grab()  # Paints without errors.
            window.minimap_action.trigger()
            self.assertFalse(minimap.isVisible())
            window.close()

    def test_without_gliding_the_view_jumps_at_once(self):
        import tempfile
        from PySide6.QtCore import QPointF
        with tempfile.TemporaryDirectory() as folder:
            window, _settings = self.window(Path(folder))
            window.open_path(Path(folder) / "S.tree")
            window.view.glide_to(QPointF(123, 45))
            centre = window.view.mapToScene(window.view.viewport().rect().center())
            self.assertLess((centre - QPointF(123, 45)).manhattanLength(), 10)  # Scroll steps round.
            window.close()

    def test_start_page_shows_trees_as_cards(self):
        import tempfile
        import start_cards
        with tempfile.TemporaryDirectory() as folder:
            window, _settings = self.window(Path(folder))
            window.open_path(Path(folder) / "S.tree")
            window.close_tree()
            cards = [c for c in window.start_page.findChildren(start_cards.TreeCard) if c.isVisibleTo(window)]
            self.assertEqual(len(cards), 1)
            card = cards[0]
            self.assertEqual(card.objectName(), "start_tree_0")
            self.assertGreater(card.summary.people, 3)
            self.assertTrue(card.summary.first_name)
            self.assertIn("S", card.text())
            card.grab()
            broken = Path(folder) / "Broken.tree"
            broken.mkdir()
            (broken / "tree.json").write_text("{nonsense", encoding="utf-8")
            self.assertEqual(start_cards.summarise(broken, "tree.json").people, 0)
            card.click()
            self.assertIn("S.tree", str(window.folder))
            window.close()


class FoldArrowTests(unittest.TestCase):
    def test_fold_buttons_say_which_way_they_fold(self):
        import house_layout as hl
        up = canvas.FoldItem(hl.Fold("p", "up", 0, 0))
        down = canvas.FoldItem(hl.Fold("p", "down", 0, 0))
        folded = canvas.FoldItem(hl.Fold("p", "up", 0, 0, True, 10))
        self.assertEqual(up.toolTip(), "Fold up: hide the ancestors above")
        self.assertEqual(down.toolTip(), "Fold down: hide the descendants below")
        self.assertEqual(folded.toolTip(), "Show the 10 hidden ancestors")
        self.assertEqual(folded.text, "+10")
        self.assertGreater(folded.width, up.width)
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtWidgets import QStyleOptionGraphicsItem
        for item in (up, down, folded):
            image = QImage(80, 30, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            item.paint(painter, QStyleOptionGraphicsItem())
            painter.end()
        # The chevron's tip: above the middle for up, below it for down.
        def tip_row(item):
            image = QImage(80, 30, QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            item.paint(painter, QStyleOptionGraphicsItem())
            painter.end()
            x = round(item.width / 2)
            text = canvas.TEXT
            rows = [y for y in range(30) if image.pixelColor(x, y).name() == text.name()]
            return sum(rows) / len(rows)
        self.assertLess(tip_row(up), up.RADIUS)
        self.assertGreater(tip_row(down), down.RADIUS)


class SideFoldTests(unittest.TestCase):
    """Folding a level's side branches onto the direct line, from Ivana: her brothers,
    her father's brothers (with their families) and her mother's brother."""

    def setUp(self):
        from sample import sample_tree
        self.tree = sample_tree()
        self.id = {p.given: k for k, p in self.tree.people.items()}

    def shown(self, side_folded):
        import house_layout as hl
        layout = hl.layout_family(self.tree, self.id["Ivana"], side_folded=frozenset(side_folded))
        return {self.tree.people[c.person_id].given for c in layout.cards}, layout.folds

    def test_every_line_with_siblings_offers_both_ways(self):
        _cards, folds = self.shown(())
        for name in ("Ivana", "Luka", "Mara"):
            kinds = sorted(f.direction for f in folds if f.person_id == self.id[name])
            self.assertEqual(kinds, ["side", "up"], name)

    def test_folding_sideways_keeps_the_direct_line(self):
        everyone, _folds = self.shown(())
        cards, folds = self.shown([self.id[n] for n in ("Ivana", "Luka", "Mara")])
        self.assertEqual(cards, {"Ivana", "Luka", "Mara", "Ante", "Ružica", "Stipe", "Jela"})
        counts = {self.tree.people[f.person_id].given: f.count for f in folds if f.direction == "side" and f.folded}
        self.assertEqual(sum(counts.values()), len(everyone) - len(cards))  # Every hidden person counted.
        self.assertEqual(counts["Mara"], 1)  # Zvonko.

    def test_one_level_at_a_time(self):
        cards, _folds = self.shown([self.id["Luka"]])
        self.assertNotIn("Josip", cards)
        self.assertNotIn("Tomo", cards)
        self.assertIn("Marko", cards)  # Her own brothers stay.
        self.assertIn("Zvonko", cards)  # The mother's side stays.

    def test_the_window_toggles_and_unfolds_everything(self):
        import datetime
        import tempfile
        from PySide6.QtCore import QSettings
        import app as app_module
        from storage import create_tree
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            create_tree(folder / "S.tree", self.tree)
            window = app_module.MainWindow(QSettings(str(folder / "s.ini"), QSettings.Format.IniFormat),
                                           today=datetime.date(2026, 11, 14))
            window.trees_folder = folder / "none"
            window.open_path(folder / "S.tree")
            window.centre_on(self.id["Ivana"])
            before = len(window.person_items)
            window.toggle_fold(self.id["Luka"], "side")
            self.assertLess(len(window.person_items), before)
            self.assertTrue(window.expand_action.isEnabled())
            window.expand_all()
            self.assertEqual(len(window.person_items), before)
            window.toggle_fold(self.id["Luka"], "side")
            window.toggle_fold(self.id["Luka"], "side")
            self.assertEqual(len(window.person_items), before)
            window.close()


class SurnameTests(unittest.TestCase):
    def tearDown(self):
        import model
        model.SURNAMES = "both"

    def test_cards_show_the_birth_surname_as_chosen(self):
        import datetime
        import model
        from house_layout import PlacedCard
        vesna = Person("e", given="Vesna", surname="Radić", birth_surname="Lukač", sex="F")
        marija = Person("m", given="Marija", surname="Lukač", birth_surname="Matić", sex="F")
        ivan = Person("i", given="Ivan", surname="Radić", birth_surname="Radić", sex="M")
        self.assertEqual(vesna.display_name, "Vesna Radić")
        self.assertEqual(vesna.born_as, "née Lukač")
        self.assertEqual(marija.full_name, "Marija Lukač, née Matić")
        self.assertEqual(ivan.born_as, "")  # The same surname: nothing to add.
        card = canvas.PersonItem(vesna, PlacedCard("e", 0, 0, True), datetime.date(2026, 11, 14))
        self.assertTrue(card.detail.startswith("née Lukač"))
        model.SURNAMES = "birth"
        self.assertEqual(vesna.display_name, "Vesna Lukač")
        self.assertEqual(vesna.born_as, "")
        model.SURNAMES = "current"
        self.assertEqual(vesna.display_name, "Vesna Radić")
        self.assertEqual(vesna.full_name, "Vesna Radić")
        self.assertEqual(vesna.line_surname, "Lukač")


class FamilyLineTests(unittest.TestCase):
    def setUp(self):
        import datetime
        import tempfile
        from PySide6.QtCore import QSettings
        import app as app_module
        from sample import sample_tree
        from storage import create_tree
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        create_tree(folder / "S.tree", sample_tree())
        self.window = app_module.MainWindow(QSettings(str(folder / "s.ini"), QSettings.Format.IniFormat),
                                            today=datetime.date(2026, 11, 14))
        self.window.trees_folder = folder / "none"
        self.window.open_path(folder / "S.tree")
        self.id = {p.given: k for k, p in self.window.tree.people.items()}

    def tearDown(self):
        self.window.close()
        self.temp.cleanup()
        canvas.DECOR = canvas.Decor()

    def test_lines_are_counted_by_birth_surname(self):
        lines = dict(self.window.family_lines())
        self.assertEqual(lines["Šimić"], 9)  # Wives who married in are counted with their own families.
        self.assertIn("Mara", {self.window.tree.people[p].given for p in self.window.line_members("Bilić")})

    def test_highlight_fades_everyone_else_and_joins_the_line(self):
        window = self.window
        window.centre_on(self.id["Ivana"])
        window.highlight_family_line("Šimić")
        self.assertFalse(window.line_bar.isHidden())
        members = window.line_members()
        for person_id, item in window.person_items.items():
            self.assertEqual(item.opacity() == 1.0, person_id in members, person_id)
        gold = [i for i in window.view.scene().items() if isinstance(i, canvas.LinesItem) and i.colour is not None]
        self.assertEqual(len(gold), 1)
        window.line_fade.setValue(40)
        self.assertAlmostEqual(window.person_items[self.id["Mara"]].opacity(), 0.4)
        window.stop_family_line()
        self.assertTrue(all(i.opacity() == 1.0 for i in window.person_items.values()))
        self.assertTrue(window.line_bar.isHidden())

    def test_only_this_line_and_back(self):
        window = self.window
        window.centre_on(self.id["Ivana"])
        window.highlight_family_line("Šimić")
        window.line_only.setChecked(True)
        self.assertEqual((window.chart, window.house), ("pyramid", self.id["Ante"]))
        self.assertNotIn(self.id["Zvonko"], window.person_items)  # The Bilić side is gone.
        window.line_only.setChecked(False)
        self.assertEqual((window.chart, window.house), ("family", self.id["Ivana"]))

    def test_the_line_joins_a_child_to_their_parent(self):
        import house_layout as hl
        tree = self.window.tree
        layout = hl.layout_family(tree, self.id["Ivana"])
        members = {self.id[n] for n in ("Luka", "Ivana")}
        joined = canvas.line_segments(layout, members)
        self.assertTrue(joined)
        nobody = canvas.line_segments(layout, {self.id["Ivana"]})
        self.assertEqual(nobody, [])  # One person alone has nothing to join.


if __name__ == "__main__":
    unittest.main()


class RenameTests(unittest.TestCase):
    def test_settings_from_before_the_name_maiores_come_along(self):
        import tempfile
        from PySide6.QtCore import QCoreApplication, QSettings
        import app as app_module
        with tempfile.TemporaryDirectory() as folder:
            QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, folder)
            QSettings.setDefaultFormat(QSettings.Format.IniFormat)
            old_names = QCoreApplication.organizationName(), QCoreApplication.applicationName()
            try:
                old = QSettings("FamilyTree", "FamilyTree")
                old.setValue("theme", "paper")
                old.sync()
                QCoreApplication.setOrganizationName("Maiores")
                QCoreApplication.setApplicationName("Maiores")
                app_module._bring_old_settings()
                self.assertEqual(QSettings().value("theme"), "paper")
                QSettings().setValue("theme", "dark")
                app_module._bring_old_settings()  # Only once: later changes stay.
                self.assertEqual(QSettings().value("theme"), "dark")
            finally:
                QCoreApplication.setOrganizationName(old_names[0])
                QCoreApplication.setApplicationName(old_names[1])
                QSettings.setDefaultFormat(QSettings.Format.NativeFormat)

    def test_the_web_page_and_reports_carry_the_mark(self):
        import branding
        import reports
        from sample import sample_tree
        self.assertTrue(branding.small_icon_uri().startswith("data:image/png;base64,"))
        page = reports.descendant_book(sample_tree(), "ante", 3)
        self.assertIn(branding.small_icon_uri()[:60], page)


class SupportLinkTests(unittest.TestCase):
    def test_help_menu_opens_the_report_form_and_the_support_page(self):
        import datetime
        import tempfile
        from unittest import mock
        from PySide6.QtCore import QSettings
        import app as app_module
        with tempfile.TemporaryDirectory() as folder:
            window = app_module.MainWindow(QSettings(str(Path(folder) / "s.ini"), QSettings.Format.IniFormat),
                                           today=datetime.date(2026, 11, 15))
            opened = []
            actions = {a.text(): a for menu in window.menuBar().actions() if menu.menu()
                       for a in menu.menu().actions()}
            with mock.patch.object(app_module.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())):
                actions["&Report a problem or idea..."].trigger()
                actions["Su&pport Maiores..."].trigger()
            self.assertEqual(opened, ["https://github.com/shyrkhan/maiores/issues/new/choose",
                                      "https://paypal.me/shyrkhan"])
            window.close()


class MenuLabelTests(unittest.TestCase):
    def test_no_two_menu_entries_share_a_label(self):
        """1.4.1 found this: the Help menu's new "Report a problem" reused the key of
        File > Export > "Report or book", so both menus showed the same words."""
        import datetime
        import tempfile
        from PySide6.QtCore import QSettings
        import app as app_module
        import strings

        def labels(menu, trail, out):
            for action in menu.actions():
                if action.menu() is not None:
                    labels(action.menu(), trail + [action.text()], out)
                elif action.text() and not action.isSeparator():
                    out.setdefault(action.text().replace("&", ""), []).append(" / ".join(trail))
            return out

        codes = ["en"] + sorted(p.stem for p in (Path(__file__).resolve().parent.parent / "translations").glob("*.py")
                                if p.stem != "__init__")
        try:
            for code in codes:
                strings.set_language(code, [])
                with tempfile.TemporaryDirectory() as folder:
                    window = app_module.MainWindow(QSettings(str(Path(folder) / "s.ini"), QSettings.Format.IniFormat),
                                                   today=datetime.date(2026, 11, 17))
                    found = {}
                    for top in window.menuBar().actions():
                        if top.menu() is not None and top.menu() is not window.person_menu:
                            labels(top.menu(), [top.text()], found)
                    window.close()
                    window.deleteLater()
                twice = {text: where for text, where in found.items() if len(where) > 1}
                self.assertEqual(twice, {}, code)
        finally:
            strings.set_language("en", [])
