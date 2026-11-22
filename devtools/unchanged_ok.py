#!/usr/bin/env python3
"""Real trees through every editing window, accepted unchanged: nothing may change.

    devtools/unchanged_ok.py PATH [PATH ...] [--people N]

PATH is a .tree folder or a GEDCOM file. A .tree folder is copied first and the original
is never written to; a GEDCOM file is imported into a throwaway tree. For each tree, the
N people with the most details (default 40) and every tree-wide window are opened and
accepted untouched, and tree.json must stay byte for byte the same. Prints one line per
tree and each difference found. Exit code 1 if any.
"""
import argparse
import contextlib
import datetime
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("FT_STILL", "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402


@contextlib.contextmanager
def every_dialog_accepts():
    def accept(dialog):
        dialog.accept()
        return QDialog.DialogCode.Accepted.value

    original = QDialog.exec
    QDialog.exec = accept
    try:
        yield
    finally:
        QDialog.exec = original


def differences(old, new, path=""):
    if isinstance(old, dict) and isinstance(new, dict):
        found = []
        for key in sorted(set(old) | set(new), key=str):
            if old.get(key) != new.get(key):
                found += differences(old.get(key), new.get(key), f"{path}/{key}")
        return found
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        return [line for i, (a, b) in enumerate(zip(old, new)) for line in differences(a, b, f"{path}[{i}]")]
    return [f"{path}: {str(old)[:120]!r} -> {str(new)[:120]!r}"]


def check(window, folder, people_limit):
    tree_file = Path(folder) / "tree.json"
    problems = []

    def unchanged(label, action, *args):
        before = tree_file.read_bytes()
        try:
            with every_dialog_accepts():
                action(*args)
        except Exception as error:  # noqa: BLE001 - reported, the run goes on.
            problems.append(f"{label}: raised {error!r}")
            return
        if window.save_error is not None:
            problems.append(f"{label}: save failed: {window.save_error}")
            window.save_error = None
        after = tree_file.read_bytes()
        if after != before:
            found = differences(json.loads(before), json.loads(after))
            problems.extend(f"{label}: {line}" for line in found[:10])
            tree_file.write_bytes(before)  # Back to the original for the next window.
            window.close_tree()
            window.open_path(folder)

    tree = window.tree
    people = sorted(tree.people, key=lambda pid: -len(json.dumps(tree.people[pid].to_dict(), ensure_ascii=False)))
    for person_id in people[:people_limit]:
        name = tree.people[person_id].display_name
        for action in ("edit", "documents", "tasks", "story"):
            unchanged(f"{name} / {action}", window.run_action, action, person_id)
        unchanged(f"{name} / dna", window.show_dna, person_id)
    for method in ("show_sources", "show_places", "show_duplicates"):
        unchanged(method, getattr(window, method))
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--people", type=int, default=40)
    args = parser.parse_args()
    QApplication.instance() or QApplication([])
    from app import MainWindow
    failed = False
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        settings = QSettings(str(temp / "settings.ini"), QSettings.Format.IniFormat)
        window = MainWindow(settings, today=datetime.date.today())
        window.trees_folder = temp / "trees"
        window.alert = window.inform = lambda *a, **k: None
        window.confirm = lambda *a, **k: True
        for number, source in enumerate(map(Path, args.paths)):
            folder = temp / f"t{number}.tree"
            if source.is_dir():
                shutil.copytree(source, folder, ignore=shutil.ignore_patterns(".lock", "backups"))
            elif not window.import_gedcom(source, folder):
                print(f"SKIP  {source.name}: could not be imported")
                continue
            if not window.open_path(folder):
                print(f"SKIP  {source.name}: could not be opened")
                continue
            window._save()  # Written once by this version: later differences are the windows'.
            problems = check(window, folder, args.people)
            people = len(window.tree.people)
            window.close_tree()
            print(f"{'FAIL' if problems else 'PASS'}  {source.name} ({people} people)")
            for line in problems:
                print(f"      {line}")
            failed = failed or bool(problems)
        window.close()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
