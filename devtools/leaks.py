"""Looks for memory that is never given back: each scenario runs many times, and what is
left afterwards is measured three ways: Python memory (tracemalloc), live Qt widgets,
and the whole process (resident memory). A leak shows as steady growth per round.

    python devtools/leaks.py                 every scenario, 60 rounds after 10 warm-up
    python devtools/leaks.py --rounds 200 --only dialogs
"""
import argparse
import datetime
import gc
import os
import sys
import tempfile
import tracemalloc
from pathlib import Path

os.environ.setdefault("FT_STILL", "1")  # No gliding: checks look right after each move.

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

# Allowed growth per round before a scenario counts as leaking.
PYTHON_BYTES = 4096
WIDGETS = 0


def resident_kb():
    try:
        return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE") // 1024
    except (OSError, ValueError):
        return 0


def settle(app):
    from PySide6.QtCore import QCoreApplication, QEvent
    for _ in range(3):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def measure(app, name, step, rounds, warmup):
    from PySide6.QtWidgets import QApplication
    for _ in range(warmup):
        step()
    settle(app)
    tracemalloc.start()
    python_before = tracemalloc.get_traced_memory()[0]
    widgets_before = len(QApplication.allWidgets())
    resident_before = resident_kb()
    for _ in range(rounds):
        step()
        settle(app)
    python_growth = (tracemalloc.get_traced_memory()[0] - python_before) / rounds
    widget_growth = (len(QApplication.allWidgets()) - widgets_before) / rounds
    resident_growth = (resident_kb() - resident_before) / rounds
    tracemalloc.stop()
    leaking = python_growth > PYTHON_BYTES or widget_growth > WIDGETS
    print(f"{'LEAK ' if leaking else 'ok   '}{name:34} python {python_growth:8.0f} B/round   "
          f"widgets {widget_growth:+.2f}/round   process {resident_growth:+7.1f} KB/round")
    return leaking


def scenarios(window, folder):
    """(name, one round) for the main window's everyday actions and every window it opens."""
    from PySide6.QtGui import QImage
    import dialogs
    import combine
    from combine_dialog import CombineDialog
    from documents_dialog import DocumentsDialog
    from duplicates import find_duplicates
    from duplicates_dialog import DuplicatesDialog
    from faces_dialog import FacesDialog
    from facts_dialogs import (CitationDialog, FactContext, NamesDialog, PeopleDialog, SourcesDialog,
                               UnsourcedDialog)
    from map_dialog import MapDialog
    from model import all_facts, fact_year
    from reports_dialog import PosterDialog, ReportDialog
    from research_dialogs import ResearchDialog, StoryDialog, TasksDialog
    from test_sources import parish_tree

    tree_folder = folder / "P.tree"

    def charts():
        for chart in ("family", "pyramid", "pedigree", "bowtie", "fan"):
            window.show_chart(chart)

    def panels():
        for person in list(window.tree.people):
            window.select(person)

    def edit_undo():
        window.apply_edit(lambda: window.tree.people["ivan"].extra.update(story="x" * 200))
        window.undo()

    def reopen():
        window.close_tree()
        window.open_path(tree_folder)

    def opened(make):
        def run():
            dialog = make()
            dialog.show()
            dialog.close()
            dialog.deleteLater()
        return run

    image = QImage(400, 300, QImage.Format.Format_RGB32)
    tree = lambda: window.tree  # noqa: E731
    context = lambda: FactContext(tree(), find_person=lambda title: None)  # noqa: E731
    windows = [
        ("person window", lambda: dialogs.PersonDialog(window, "x", dialogs.person_to_values(tree().people["davor"]),
                                                         context=context())),
        ("event window", lambda: dialogs.EventDialog(window, {"type": "residence"}, context())),
        ("documents window", lambda: DocumentsDialog(window, tree().people["ivan"], folder, None, {}, context())),
        ("faces window", lambda: FacesDialog(window, image, [{"rect": [0.1, 0.1, 0.2, 0.2]}], context())),
        ("map window (offline)", lambda: MapDialog(window, tree(), "davor")),
        ("places window", lambda: dialogs.PlacesDialog(window, tree(), all_facts(tree()))),
        ("timeline window", lambda: dialogs.TimelineDialog(window, tree(), all_facts(tree()), fact_year)),
        ("find window", lambda: dialogs.FindDialog(window, tree(), datetime.date(2026, 11, 13))),
        ("preferences window", lambda: dialogs.PreferencesDialog(window, {"card_style": "portrait", "detail": "age",
                                                                          "generations_up": 3, "reopen_last": True,
                                                                          "language": "system"})),
        ("sources window", lambda: SourcesDialog(window, tree())),
        ("facts without a source", lambda: UnsourcedDialog(window, tree())),
        ("citation window", lambda: CitationDialog(window, context())),
        ("people present window", lambda: PeopleDialog(window, context(), [], "x")),
        ("other names window", lambda: NamesDialog(window, context(), [])),
        ("duplicates window", lambda: DuplicatesDialog(window, tree(), find_duplicates(tree()))),
        ("combine window", lambda: CombineDialog(window, tree(), parish_tree(),
                                                 combine.suggest_matches(tree(), parish_tree()), "x")),
        ("report window", lambda: ReportDialog(window, "x")),
        ("poster window", lambda: PosterDialog(window, window._poster_scene(tree())[1])),
        ("to-do window", lambda: TasksDialog(window, tree().people["ivan"])),
        ("life story window", lambda: StoryDialog(window, tree().people["ivan"])),
        ("research window", lambda: ResearchDialog(window, tree())),
    ]
    return ([("charts", charts), ("panels", panels), ("edit and undo", edit_undo), ("close and reopen", reopen)],
            [(name, opened(make)) for name, make in windows])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, default=60)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--only", choices=["actions", "dialogs"])
    args = parser.parse_args()
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import app as app_module
    from storage import create_tree
    from test_sources import parish_tree
    leaks = 0
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        create_tree(folder / "P.tree", parish_tree())
        window = app_module.MainWindow(QSettings(str(folder / "s.ini"), QSettings.Format.IniFormat),
                                       today=datetime.date(2026, 11, 13))
        window.alert = window.inform = lambda *a: None
        window.resize(1200, 800)
        window.show()
        window.open_path(folder / "P.tree")
        actions, windows = scenarios(window, folder)
        chosen = {"actions": actions, "dialogs": windows}.get(args.only, actions + windows)
        for name, step in chosen:
            leaks += measure(app, name, step, args.rounds, args.warmup)
        window.close()
    print("no leaks found" if not leaks else f"leaking: {leaks}")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
