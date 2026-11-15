#!/usr/bin/env python3
"""A robot that uses the program like a person would, and stops at the first bug.

It clicks cards and add buttons with the real mouse, presses keys, uses the
toolbar, menus and panel, answers dialogs at random, and after every step checks
the rules in checks.py plus what that step should have done (an added person is
on screen and selected, undo really restores the previous tree, and so on).

    python -m devtools.explorer --seed 3 --steps 300
    python -m devtools.explorer --seed 3 --until 57      replay up to a failing step

It runs on a private virtual screen (Xvfb), never on yours, and always on a
throwaway tree; your own family trees are never opened. The report, with
screenshots, goes to dev-output/explore-SEED/report.html.
"""
import argparse
import datetime
import html
import os
import random
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("FT_STILL", "1")  # No gliding: checks look right after each move.

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TODAY = datetime.date(2026, 11, 8)
GIVEN = ["Ana", "Ivo", "Mara", "Ante", "Jela", "Luka", "Kata", "Stipe", "Iva", "Đuro", "Žana", "Mile"]
SURNAMES = ["Šimić", "Bilić", "Kovač", "Perić", "Čulić", "Đurić"]
DATES = ["", "", "1950", "14.5.1921.", "abt 1900", "bef 1880", "1880-1885", "2001-03-04", "aft 1960"]


def ensure_private_screen():
    """Re-run under xvfb-run so no window ever appears on the user's own screen."""
    if os.environ.get("FT_PRIVATE_SCREEN") or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        return
    env = dict(os.environ, FT_PRIVATE_SCREEN="1", QT_QPA_PLATFORM="xcb", PYTHONHASHSEED="0")
    command = [sys.executable, "-m", "devtools.explorer", *sys.argv[1:]]
    if shutil.which("xvfb-run"):
        command = ["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24", *command]
    else:
        env["QT_QPA_PLATFORM"] = "offscreen"  # Not as thorough, but never visible.
    sys.exit(subprocess.call(command, cwd=ROOT, env=env))


class Failure(Exception):
    pass


class Robot:
    def __init__(self, seed, steps, out, shot_every=25, until=None):
        from PySide6.QtCore import QSettings
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        from app import MainWindow, apply_theme

        import itertools

        import edits
        import gedcom
        import model

        counter = itertools.count(1)
        repeatable = lambda prefix: f"{prefix}-{next(counter):08d}"  # Same seed, same IDs, same run.
        model.new_id = edits.new_id = gedcom.new_id = repeatable
        self.app = QApplication.instance() or QApplication([])
        apply_theme(self.app)
        self.rng = random.Random(seed)
        self.seed, self.steps, self.until = seed, steps, until
        self.out = Path(out)
        shutil.rmtree(self.out, ignore_errors=True)
        (self.out / "shots").mkdir(parents=True)
        self.shot_every = shot_every
        self.work = Path(tempfile.mkdtemp(prefix="ft-explore-"))
        # Private settings: the explorer must never change which tree the owner reopens.
        self.settings = QSettings(str(self.work / "settings.ini"), QSettings.Format.IniFormat)
        self.window = MainWindow(self.settings, today=TODAY)
        self.log = []
        self.slot_errors = []
        self.alerts = []
        self.my_undo, self.my_redo = [], []
        self.warnings = {}  # Kind of warning: how many steps showed it.
        self._install_seams()
        sys.excepthook = lambda kind, error, trace: self.slot_errors.append(
            "".join(traceback.format_exception(kind, error, trace))
        )
        self.window.resize(1400, 900)
        self.window.show()
        QTest.qWaitForWindowExposed(self.window)
        self.window.activateWindow()
        QTest.qWaitForWindowActive(self.window, 2000)
        self.folder = self.work / "Explore.tree"

    # Answers to every question the program asks.
    def _install_seams(self):
        from photos import default_crop

        w, rng = self.window, self.rng

        def ask_person(title, initial=None, link=None, relationships=(), another=False):
            if rng.random() < 0.1:
                return None
            initial = initial or {}
            values = {
                "given": rng.choice(GIVEN),
                "surname": initial.get("surname") or rng.choice(SURNAMES),
                "birth_surname": rng.choice(["", "", rng.choice(SURNAMES)]),
                "sex": initial.get("sex") or rng.choice(["M", "F", ""]),
                "birth_date": rng.choice(DATES),
                "birth_place": rng.choice(["", "Split", "Trogir"]),
                "living": rng.choice(["yes", "yes", "no", "unknown"]),
                "death_date": "",
                "death_place": "",
                "notes": rng.choice(["", "", "Note <b>with</b> markup & stuff"]),
                "photo_source": None,
                "relationships": {key: "married" for key, *_ in relationships},
            }
            if "given" in initial:  # Editing: keep it recognisable.
                values["given"] = initial["given"]
            if link is not None:
                values["link"] = rng.choice(["birth", "birth", "adopted"])
            if another and rng.random() < 0.15:
                values["add_another"] = True
            return values

        def choose(title, label, options):
            return None if rng.random() < 0.1 else rng.randrange(len(options))

        def ask_existing_person(title, exclude):
            people = [p for p in w.tree.people if p not in exclude]
            return rng.choice(people) if people and rng.random() < 0.9 else None

        def show_menu(menu, position):
            actions = [a for a in menu.actions() if a.isEnabled() and not a.isSeparator()]
            if actions and rng.random() < 0.9:
                action = rng.choice(actions)
                self.note(f"menu: {action.text()}")
                action.trigger()
            menu.deleteLater()  # As the real show_menu does.

        w.ask_person = ask_person
        w.choose = choose
        w.confirm = lambda title, text: rng.random() < 0.7
        w.ask_existing_person = ask_existing_person
        w.ask_photo = lambda: None
        w.ask_crop = default_crop
        w.alert = lambda title, text: self.alerts.append(text) or self.note(f"alert: {text}")
        w.show_menu = show_menu
        w.inform = lambda title, text: self.note(f"info: {text}")
        w.ask_duplicate = lambda title, label, options: (
            None if rng.random() < 0.1 else rng.randrange(len(options))
        )
        w.ask_open_file = lambda *a: None
        w.ask_save_file = lambda *a: None
        # The documents window: cancelled, or the last document taken off.
        from model import person_documents
        w.ask_documents = lambda person: None if rng.random() < 0.4 else (person_documents(person)[:-1], None)
        w.ask_combine = lambda *a: None
        # The Sources window: cancelled, or every source kept as it is.
        from model import tree_sources
        w.ask_sources = lambda: None if rng.random() < 0.5 else (tree_sources(w.tree), {}, set())
        w.ask_unsourced = lambda: None
        # Duplicates: close, merge the first pair keeping either, or call them different.
        w.ask_duplicates = lambda candidates, selected: None if rng.random() < 0.4 else (
            rng.choice(["merge", "different"]), *rng.sample([candidates[0].a, candidates[0].b], 2), 0)
        w.ask_places = lambda rows: None
        w.ask_timeline = lambda rows: None
        w.ask_preferences = lambda values: None
        w.ask_print = lambda printer: False
        w.ask_report = lambda name: None
        w.ask_tasks = lambda person: None if rng.random() < 0.5 else [{"text": "Look in the parish books"}]
        w.ask_story = lambda person: None if rng.random() < 0.5 else ("Wrote letters home.", rng.random() < 0.3)
        w.ask_research = lambda: None
        w.ask_map = lambda: None  # Never the network from the robot.
        w.ask_web_page = lambda with_password=True: None
        w.ask_statistics = lambda summary: None
        w.ask_lifelines = lambda: None
        w.ask_gallery = lambda: None
        w.ask_dna = lambda person_id: None
        w.ask_poster = lambda area: None

        # Keep an independent record of every change, to check undo and redo against.
        from edits import copy_tree
        real_apply = w.apply_edit

        def apply_edit(change, focus=None):
            before = copy_tree(w.tree)
            result = real_apply(change, focus)
            if w.tree != before:
                self.my_undo.append(before)
                del self.my_undo[:-200]
                self.my_redo.clear()
            return result

        w.apply_edit = apply_edit

    # Real input.
    def settle(self):
        from PySide6.QtWidgets import QApplication

        for _ in range(3):
            QApplication.processEvents()

    def point_of(self, scene_point):
        view = self.window.view
        view.ensureVisible(scene_point.x() - 1, scene_point.y() - 1, 2, 2, 60, 60)
        self.settle()
        return view.mapFromScene(scene_point)

    def mouse(self, kind, scene_point, button=None):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        button = button or Qt.MouseButton.LeftButton
        point = self.point_of(scene_point)
        viewport = self.window.view.viewport()
        if kind == "click":
            QTest.mouseClick(viewport, button, pos=point)
        elif kind == "double":
            QTest.mouseDClick(viewport, button, pos=point)
        self.settle()

    def key(self, key, modifiers=None, widget=None):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        target = widget or self.window.view
        if not target.isVisible():
            target = self.window  # The tree is not showing, e.g. after deleting everyone.
        target.setFocus()
        QTest.keyClick(target, key, modifiers or Qt.KeyboardModifier.NoModifier)
        self.settle()

    def card_centre(self, person_id):
        item = self.window.person_items[person_id]
        return item.click_point()

    def random_card(self):
        people = [p for p in self.window.person_items if p in self.window.tree.people]
        return self.rng.choice(people) if people else None

    # The things a person might do.
    def act(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QPushButton

        w, rng = self.window, self.rng
        choices = [
            ("click card", 18), ("click add button", 16), ("panel button", 10),
            ("arrow key", 10), ("context menu", 7), ("toolbar", 10), ("undo", 6),
            ("redo", 3), ("double-click card", 4), ("click empty space", 3),
            ("enter", 2), ("search", 3), ("delete key", 2), ("back", 2), ("zoom", 2),
            ("drag card onto card", 6), ("fold button", 6), ("card style", 3), ("chart", 4),
            ("redraw mid-press", 4),
        ]
        names, weights = zip(*choices)
        name = rng.choices(names, weights)[0]
        if not w.tree.people:
            # Everyone was deleted: start again from the empty page, or undo.
            if rng.random() < 0.5:
                button = next(b for b in w.pages.currentWidget().findChildren(QPushButton) if b.isVisible())
                self.note(f"empty page: {button.text()}")
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                self.settle()
                return "add"
            name = "undo"

        if name == "click card":
            pid = self.random_card()
            self.note(f"click card {self._name(pid)}")
            self.mouse("click", self.card_centre(pid))
        elif name == "double-click card":
            pid = self.random_card()
            self.note(f"double-click {self._name(pid)}")
            self.mouse("double", self.card_centre(pid))
        elif name == "click add button":
            if not w.add_button_items:
                return self.act()
            button = rng.choice(w.add_button_items)
            self.note(f"click {button.label} on {self._name(button.person_id)}")
            self.mouse("click", button.sceneBoundingRect().center())
            name = "add"
        elif name == "panel button":
            buttons = [b for b in w.panel.findChildren(QPushButton) if b.isVisible() and b.isEnabled()]
            if not buttons:
                return self.act()
            button = rng.choice(buttons)
            self.note(f"panel: {button.text()}")
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            self.settle()
        elif name == "arrow key":
            key = rng.choice([Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down])
            self.note(f"key {key.name}")
            self.key(key)
        elif name == "enter":
            self.note("key Enter (edit)")
            self.key(Qt.Key.Key_Return)
        elif name == "delete key":
            self.note("key Delete")
            self.key(Qt.Key.Key_Delete)
        elif name == "context menu":
            pid = self.random_card()
            self.note(f"right-click {self._name(pid)}")
            point = self.point_of(self.card_centre(pid))
            from PySide6.QtGui import QContextMenuEvent
            viewport = w.view.viewport()
            event = QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse, point, viewport.mapToGlobal(point)
            )
            from PySide6.QtWidgets import QApplication
            QApplication.sendEvent(viewport, event)
            self.settle()
        elif name == "toolbar":
            actions = [a for a in w.toolbar.actions() if a.isEnabled() and a.text()]
            action = rng.choice(actions)
            self.note(f"toolbar: {action.text()}")
            widget = w.toolbar.widgetForAction(action)
            QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
            self.settle()
            # By the program's own texts, so it works in every language.
            from strings import t
            if action.text() == t("toolbar_fit"):
                name = "fit"
            elif action is getattr(w, "undo_tool", None):
                name = "undo"
            elif action is getattr(w, "redo_tool", None):
                name = "redo"
        elif name in ("undo", "redo"):
            self.note(f"shortcut {name}")
            key = Qt.Key.Key_Z
            mods = Qt.KeyboardModifier.ControlModifier
            if name == "redo":
                mods |= Qt.KeyboardModifier.ShiftModifier
            self.key(key, mods)
        elif name == "back":
            self.note("shortcut Alt+Left")
            self.key(Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
        elif name == "zoom":
            self.note("wheel zoom")
            from PySide6.QtGui import QWheelEvent
            from PySide6.QtWidgets import QApplication
            viewport = w.view.viewport()
            centre = QPointF(viewport.rect().center())
            delta = rng.choice([120, -120, 240])
            event = QWheelEvent(
                centre, QPointF(viewport.mapToGlobal(centre.toPoint())), QPoint(0, 0),
                QPoint(0, delta), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            )
            QApplication.sendEvent(viewport, event)
            self.settle()
        elif name == "drag card onto card":
            if len(w.person_items) < 2:
                return self.act()
            source, target = rng.sample(list(w.person_items), 2)
            self.note(f"drag {self._name(source)} onto {self._name(target)}")
            start = self.point_of(self.card_centre(source))
            end = w.view.mapFromScene(self.card_centre(target))
            viewport = w.view.viewport()
            QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
            for step in range(1, 9):
                QTest.mouseMove(viewport, start + (end - start) * step / 8)
            QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
            self.settle()
        elif name == "redraw mid-press":
            # The button goes down on a card, the tree is redrawn (an undo, a style change),
            # and only then does the mouse move and let go: the old cards are gone by then.
            pid = self.random_card()
            self.note(f"press on {self._name(pid)}, redraw, then move and let go")
            viewport = w.view.viewport()
            start = self.point_of(self.card_centre(pid))
            QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
            redraw = rng.choice(["refresh", "style", "undo"])
            if redraw == "undo":
                w.undo()
            elif redraw == "style":
                w.set_card_style(rng.choice(["portrait", "compact"]))
            else:
                w.refresh()
            self.settle()
            for step in range(1, 6):
                QTest.mouseMove(viewport, start + QPoint(step * 17, step * 9))
            QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=start + QPoint(85, 45))
            self.settle()
            name = "undo" if redraw == "undo" else "redraw"
        elif name == "chart":
            number = rng.randint(1, 5)
            self.note(f"key Ctrl+{number} (chart)")
            self.key(getattr(Qt.Key, f"Key_{number}"), Qt.KeyboardModifier.ControlModifier, widget=self.window)
        elif name == "card style":
            number = rng.randint(1, 4)
            self.note(f"key Ctrl+Shift+{number} (card style)")
            key = getattr(Qt.Key, f"Key_{number}")
            mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
            self.key(key, mods, widget=self.window)
        elif name == "fold button":
            from canvas import FoldItem
            folds = [i for i in w.view.scene().items() if isinstance(i, FoldItem)]
            if not folds:
                return self.act()
            fold = rng.choice(folds)
            self.note(f"fold {fold.direction} {fold.text} at {self._name(fold.person_id)}")
            self.mouse("click", fold.sceneBoundingRect().center())
        elif name == "click empty space":
            self.note("click empty space")
            from PySide6.QtTest import QTest
            QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
            self.settle()
        elif name == "search":
            people = list(w.tree.people.values())
            target = rng.choice(people)
            text = target.given[:3]
            self.note(f"search {text!r}")
            box = w.search_box
            box.setFocus()
            box.clear()
            from PySide6.QtCore import QEvent
            from PySide6.QtGui import QKeyEvent
            from PySide6.QtWidgets import QApplication
            for letter in text:  # Like a keyboard, so letters such as Đ and Ž work.
                for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                    QApplication.sendEvent(box, QKeyEvent(kind, 0, Qt.KeyboardModifier.NoModifier, letter))
            QTest.keyClick(box, Qt.Key.Key_Return)
            self.settle()
            w.view.setFocus()
        return name

    def _name(self, person_id):
        person = self.window.tree.people.get(person_id)
        return f"{person.display_name} ({person_id[-4:]})" if person else str(person_id)

    def note(self, text):
        self.current.append(text)

    # One step and everything it must leave true.
    def step(self, number):
        from devtools.checks import failures, fit_problems, run_checks
        from edits import copy_tree

        w = self.window
        before = copy_tree(w.tree)
        people_before = set(w.tree.people)
        alerts_before = len(self.alerts)
        self.current = []
        kind = self.act()
        found = run_checks(w)
        for warning in {p.kind for p in found if p.severity != "fail"}:
            self.warnings[warning] = self.warnings.get(warning, 0) + 1
        problems = list(failures(found))
        if self.slot_errors:
            problems.append(f"error inside the program:\n{self.slot_errors[-1]}")
        if kind == "fit":
            problems += fit_problems(w)
        added = set(w.tree.people) - people_before
        if kind == "undo":
            expected = self.my_undo[-1] if self.my_undo else before
            if w.tree != expected:
                problems.append("undo did not restore the previous tree")
            if self.my_undo:
                self.my_redo.append(before)
                self.my_undo.pop()
        elif kind == "redo":
            expected = self.my_redo[-1] if self.my_redo else before
            if w.tree != expected:
                problems.append("redo did not bring back the undone change")
            if self.my_redo:
                self.my_undo.append(before)
                self.my_redo.pop()
        if added and kind not in ("undo", "redo") and len(self.alerts) == alerts_before:
            linked = {p for p in w.tree.people if p in before.people and (
                w.tree.parent_families(p) != before.parent_families(p)
                or w.tree.families_of(p) != before.families_of(p))}
            if w.selected not in added | linked:
                problems.append(f"a person was added but {self._name(w.selected)} is selected instead")
            if not (added & set(w.person_items)):
                problems.append("a person was added but is not on screen")
        entry = {"step": number, "did": "; ".join(self.current), "problems": [str(p) for p in problems],
                 "people": len(w.tree.people), "shot": None}
        if problems or number % self.shot_every == 0 or (self.until and number >= self.until - 3):
            entry["shot"] = self.shot(number)
        self.log.append(entry)
        if problems:
            raise Failure(f"step {number}: " + " | ".join(str(p) for p in problems))

    def shot(self, number):
        path = self.out / "shots" / f"step-{number:04d}.png"
        self.window.grab().save(str(path))
        return path.name

    def run(self):
        from storage import open_tree

        w = self.window
        failure = None
        try:
            w.new_tree(self.folder)
            w.ask_person, real_ask = (lambda *a, **k: {"given": "Start", "surname": "Šimić",
                                                       "living": "yes"}), w.ask_person
            w.add_first_person()
            w.ask_person = real_ask
            import house_layout as hl
            w.set_card_style(self.rng.choice(sorted(hl.STYLES)))  # Each run starts in some style.
            last = self.until or self.steps
            for number in range(1, last + 1):
                self.step(number)
            # Everything shown must be exactly what a fresh start would read back.
            if open_tree(self.folder).tree != w.tree:
                raise Failure("reopening the tree from disk gives a different tree")
        except Failure as error:
            failure = str(error)
        except Exception:
            failure = "the explorer itself crashed:\n" + traceback.format_exc()
        self.report(failure)
        shutil.rmtree(self.work, ignore_errors=True)
        return failure

    def report(self, failure):
        rows = []
        for entry in self.log:
            bad = bool(entry["problems"])
            shot = (f'<a href="shots/{entry["shot"]}"><img src="shots/{entry["shot"]}"></a>'
                    if entry["shot"] else "")
            rows.append(
                f'<tr class="{"bad" if bad else ""}"><td>{entry["step"]}</td>'
                f'<td>{html.escape(entry["did"])}</td><td>{entry["people"]}</td>'
                f'<td><pre>{html.escape(chr(10).join(entry["problems"]))}</pre></td><td>{shot}</td></tr>'
            )
        verdict = (f'<p class="bad">FAILED: {html.escape(failure)}</p>'
                   f'<p>Replay: <code>python -m devtools.explorer --seed {self.seed} '
                   f'--until {len(self.log)}</code></p>' if failure else '<p class="good">Passed</p>')
        page = f"""<!doctype html><meta charset="utf-8"><title>Explorer seed {self.seed}</title>
<style>body{{font:14px sans-serif;background:#2b2d31;color:#e8e8e8;margin:16px}}
table{{border-collapse:collapse;width:100%}}td{{border-top:1px solid #44474d;padding:4px;vertical-align:top}}
img{{width:320px}}.bad{{color:#ff9c8f}}tr.bad{{background:#3a2a2a}}.good{{color:#8fd18f}}pre{{white-space:pre-wrap;margin:0}}</style>
<h1>Explorer, seed {self.seed}</h1>{verdict}
<table><tr><th>Step</th><th>What it did</th><th>People</th><th>Problems</th><th>Screen</th></tr>
{''.join(rows)}</table>"""
        (self.out / "report.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--until", type=int, help="stop after this step, with screenshots near the end")
    parser.add_argument("--shot-every", type=int, default=25)
    parser.add_argument("--out", help="report folder (default dev-output/explore-SEED)")
    parser.add_argument("--language", default="en", help="interface language, e.g. de, ar, ja")
    args = parser.parse_args()
    import strings
    strings.set_language(args.language)
    ensure_private_screen()
    out = args.out or ROOT / "dev-output" / f"explore-{args.seed}"
    robot = Robot(args.seed, args.steps, out, args.shot_every, args.until)
    failure = robot.run()
    if failure:
        print(failure, file=sys.stderr)
        summary = failure.splitlines()[0] + (" ..." if "\n" in failure else "")
        if "error inside the program" in failure:
            summary += " " + failure.strip().splitlines()[-1]  # The error's own name.
    verdict = f"FAILED {summary}" if failure else "passed"
    if robot.warnings:
        verdict += " | warnings: " + ", ".join(f"{k} x{n}" for k, n in sorted(robot.warnings.items()))
    print(f"seed {args.seed}: {verdict} - report {Path(out) / 'report.html'}")
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())
