#!/usr/bin/env python3
"""Gather what the Android build needs into one folder: the program's modules,
fonts and icon, and the main.py that pyside6-android-deploy insists on.

Usage: android_stage.py OUTPUT_DIR
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Everything the program imports; the developer tools, tests and build scripts stay out.
MODULES = ["app", "canvas", "dialogs", "edits", "exports", "gedcom", "house_layout", "kinship",
           "model", "panel", "photos", "sample", "storage", "strings", "tour", "version", "combine", "combine_dialog",
           "documents", "documents_dialog", "privacy", "facts_dialogs",
           "duplicates", "duplicates_dialog", "reports", "reports_dialog", "poster",
           "faces_dialog", "places_dialog", "research_dialogs", "webshare", "webshare_dialog", "theme", "views_dialogs", "icons", "start_cards", "dna", "dna_dialog", "branding",
           "map_view", "map_dialog", "screen"]
FOLDERS = ["fonts", "assets", "translations"]

MAIN = '''"""Entry point for the Android build. The phone version is the same program."""
import sys

from app import main

sys.exit(main([]))
'''


def stage(target):
    target = Path(target)
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for module in MODULES:
        shutil.copy2(ROOT / f"{module}.py", target / f"{module}.py")
    for folder in FOLDERS:
        shutil.copytree(ROOT / folder, target / folder, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "THIRD_PARTY.txt", target / "THIRD_PARTY.txt")
    (target / "main.py").write_text(MAIN, encoding="utf-8")
    return target


if __name__ == "__main__":
    print(f"Staged {stage(sys.argv[1])}")
