#!/usr/bin/env python3
"""Time the everyday actions on large, realistic families.

    python -m devtools.perf                 1,000, 3,000 and 6,000 people
    python -m devtools.perf --sizes 10000

Families are generated like real ones: couples have 0-5 children, most
children marry someone from outside who sometimes brings parents along, and
dates run forward through the generations. Each action is timed on the real
window. Anything slower than its limit is reported as a problem.
"""
import argparse
import datetime
import os
import random
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("FT_STILL", "1")  # No gliding: checks look right after each move.

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

GIVEN = ["Ana", "Ivo", "Mara", "Ante", "Jela", "Luka", "Kata", "Stipe", "Iva", "Đuro", "Žana", "Mile",
         "Petar", "Marija", "Josip", "Ivana", "Tomo", "Nikola", "Ružica", "Zvonko"]
SURNAMES = ["Šimić", "Bilić", "Kovač", "Perić", "Čulić", "Đurić", "Horvat", "Babić", "Marić", "Jurić"]

# The slowest each action may be before it feels sluggish, in seconds.
LIMITS = {"open": 3.0, "centre on someone": 0.5, "select": 0.15, "add a child": 0.8, "undo": 0.8,
          "search keystroke": 0.15, "check dates": 2.0, "save": 0.5, "descendant chart": 1.5,
          "fold a branch": 0.5, "find duplicates": 3.0, "descendant book": 3.0, "map window": 2.0,
          "places list": 0.5, "overview map": 0.5, "family line": 1.5, "export GEDCOM": 1.0,
          "data check": 1.0}


def generate(size, seed=1):
    from model import Family, Person, Tree

    rng = random.Random(seed)
    people, families = {}, {}
    counter = [0]

    def person(sex, born):
        counter[0] += 1
        key = f"p{counter[0]:06d}"
        people[key] = Person(key, given=rng.choice(GIVEN), surname=rng.choice(SURNAMES), sex=sex,
                             birth={"date": str(born), "place": ""},
                             living="yes" if born > 1935 else "no")
        return key

    def family(partners, children=()):
        key = f"f{len(families) + 1:06d}"
        families[key] = Family(key, list(partners), "married",
                               [{"person": c, "link": "birth"} for c in children])
        return families[key]

    waiting = [family([person("M", 1850), person("F", 1852)])]
    while len(people) < size:
        if not waiting:  # Another unrelated line, so the tree always reaches its size.
            waiting.append(family([person("M", 1850), person("F", 1852)]))
        couple = waiting.pop(0)
        born = int(people[couple.partners[0]].birth["date"])
        # The first couples always have children, or a line could end at once.
        choices = [2, 3, 4] if len(people) < 10 else [0, 1, 2, 2, 3, 3, 4, 5]
        for _ in range(rng.choice(choices)):
            if len(people) >= size:
                break
            child_born = born + rng.randint(20, 40)
            if child_born > 2024:
                continue
            child = person(rng.choice("MF"), child_born)
            couple.children.append({"person": child, "link": "birth"})
            if rng.random() < 0.8 and len(people) < size:
                spouse = person("F" if people[child].sex == "M" else "M", child_born + rng.randint(-4, 4))
                if rng.random() < 0.3 and len(people) + 2 <= size:
                    family([person("M", child_born - 28), person("F", child_born - 26)], [spouse])
                waiting.append(family([child, spouse]))
    return Tree(people, families)


def timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def measure(size):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from app import MainWindow
    from edits import copy_tree
    from storage import create_tree

    app = QApplication.instance() or QApplication([])
    tree = generate(size)
    results = {}
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp) / "Big.tree"
        create_tree(folder, tree)
        window = MainWindow(None, today=datetime.date(2026, 11, 11))
        window.alert = window.inform = lambda *a: None
        window.choose = lambda *a: None
        window.resize(1400, 900)
        window.show()
        results["open"] = timed(lambda: (window.open_path(folder), app.processEvents()))
        people = list(window.tree.people)
        rng = random.Random(2)
        middle = people[len(people) // 3]
        results["centre on someone"] = max(timed(lambda p=p: (window.centre_on(p), app.processEvents()))
                                           for p in rng.sample(people, 8))
        window.centre_on(middle)
        visible = list(window.person_items)
        results["select"] = max(timed(lambda p=p: (window.select(p), app.processEvents()))
                                for p in rng.sample(visible, min(8, len(visible))))
        window.ask_person = lambda *a, **k: {"given": "New", "surname": "Test", "living": "yes", "link": "birth"}
        window.ask_duplicate = lambda *a: None
        results["add a child"] = timed(lambda: (window.run_action("add_child", middle), app.processEvents()))
        results["undo"] = timed(lambda: (window.undo(), app.processEvents()))
        results["search keystroke"] = max(timed(lambda txt=txt: window._search_typed(txt)) for txt in ("I", "Iv", "Iva"))
        results["check dates"] = timed(window.all_date_warnings)
        from duplicates import find_duplicates
        results["find duplicates"] = timed(lambda: find_duplicates(window.tree))
        import reports
        heads = window.tree.family_line_heads()
        results["descendant book"] = timed(lambda: reports.descendant_book(window.tree, heads[0][0], 6))
        from map_dialog import MapDialog
        results["map window"] = timed(lambda: MapDialog(window, window.tree, middle).deleteLater())
        from model import all_facts, place_records
        results["places list"] = timed(lambda: (all_facts(window.tree), place_records(window.tree)))
        results["save"] = timed(window._save)
        from gedcom import write_gedcom
        from model import validate
        results["export GEDCOM"] = timed(lambda: write_gedcom(window.tree, None))
        results["data check"] = timed(lambda: validate(window.tree))
        results["descendant chart"] = timed(lambda: (setattr(window, "chart", "pyramid"),
                                                     setattr(window, "house", window.tree.family_line_heads()[0][0]),
                                                     window.refresh(keep_view=False), app.processEvents()))
        results["_cards_in_chart"] = len(window.person_items)
        # The overview map draws the whole chart once each time the chart is rebuilt.
        results["overview map"] = timed(lambda: (window.view.minimap.set_shown(True), app.processEvents()))
        window.view.minimap.set_shown(False)
        # Highlighting the most common family line redraws the chart with its own lines.
        surname = window.family_lines()[0][0]
        results["family line"] = timed(lambda: (window.highlight_family_line(surname), app.processEvents()))
        window.stop_family_line()
        window.centre_on(middle)
        results["fold a branch"] = timed(lambda: (window.toggle_fold(middle, "up"), app.processEvents()))
        # Memory for the undo history: one full copy of the tree per step kept.
        import pickle
        results["_snapshot_kb"] = len(pickle.dumps(copy_tree(window.tree))) / 1024
        results["_people"] = len(window.tree.people)
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 3000, 6000])
    args = parser.parse_args()
    slow = []
    for size in args.sizes:
        results = measure(size)
        print(f"\n{size} people requested, {results.pop('_people')} made (descendant chart shows {results.pop('_cards_in_chart')} cards; "
              f"one undo snapshot about {results.pop('_snapshot_kb'):.0f} KB)")
        for name, seconds in results.items():
            flag = "  TOO SLOW" if seconds > LIMITS[name] else ""
            print(f"  {name:20} {seconds * 1000:8.0f} ms{flag}")
            if flag:
                slow.append(f"{size}: {name}")
    print("\nall within limits" if not slow else "\nslow: " + ", ".join(slow))
    return 1 if slow else 0


if __name__ == "__main__":
    sys.exit(main())
