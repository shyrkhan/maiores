#!/usr/bin/env python3
"""Try every way of connecting every pair of people, and judge each result.

For each ordered pair (A, B) in a family and each kind of connection (B is a
child, parent, partner, brother or sister of A, or the same person), the real
window code runs it once, on a fresh copy. Each outcome must be one of:

  linked    the data changed, is still valid, and the relationship now holds
  already   refused because it is already true, and the message says so
  refused   refused for a stated reason, with the data untouched

Anything else is a bug: an error inside the program, a refusal that changed
the data, a "success" that changed nothing or broke a data rule, or a
connection that holds but was refused as if impossible.

    python -m devtools.sweep            prints a summary and writes dev-output/sweep.html
"""
import collections
import html
import os
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("FT_STILL", "1")  # No gliding: checks look right after each move.

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import itertools

_FOLDER_NUMBERS = itertools.count()
KINDS = ("child", "parent", "partner", "sibling", "same", "adopted_child", "adoptive_parent")
NO_QUESTION = {"make_head", "remove_photo"}  # Act at once (Undo reverses them); nothing to cancel.


def free_closed_windows():
    """Really delete the windows closed so far. deleteLater only happens when an event
    loop gets to it, and the sweep has none: without this, thousands of closed windows
    stayed in memory (over 3 GB) until the run was killed."""
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def holds(tree, kind, a, b):
    """Is B already the KIND of A?"""
    if kind in ("child", "adopted_child"):
        return any(b in f.child_ids for f in tree.families_of(a))
    if kind == "adoptive_parent":
        return any(b in f.partners for f, _link in tree.parent_families(a))
    if kind == "parent":
        family = tree.birth_family_of(a)
        return bool(family and b in family.partners)
    if kind == "partner":
        return any(b in f.partners for f in tree.families_of(a))
    if kind == "sibling":
        family = tree.birth_family_of(a)
        return bool(family and family is tree.birth_family_of(b) and a != b)
    return False


def families():
    """Families to sweep: the sample, and one shaped like the owner's (no real names)."""
    from model import Family, Person, Tree
    from sample import sample_tree

    def person(key, given, sex=""):
        return Person(key, given=given, surname="Test", sex=sex, living="yes")

    people = {k: person(k, g, s) for k, g, s in [
        ("me", "Me", "M"), ("dad", "Dad", "M"), ("mum", "Mum", "F"), ("bro", "Brother", ""),
        ("mgf", "MumsDad", "M"), ("mgm", "MumsMum", "F"), ("pgf", "DadsDad", "M"),
        ("pgm", "DadsMum", "F"), ("uncle", "Uncle", "M"), ("aunt", "UnclesWife", "F"),
        ("c1", "Cousin1", ""), ("c2", "Cousin2", "")]}
    def fam(key, partners, children):
        return Family(key, partners, "married", [{"person": c, "link": "birth"} for c in children])
    shaped = Tree(people, {f.id: f for f in [
        fam("f1", ["dad", "mum"], ["me", "bro"]), fam("f2", ["mgf", "mgm"], ["mum"]),
        fam("f3", ["pgf", "pgm"], ["dad", "uncle"]), fam("f4", ["uncle", "aunt"], ["c1", "c2"])]})
    return {"owner-shaped": shaped, "sample": sample_tree()}


def run():
    from PySide6.QtWidgets import QApplication

    from app import MainWindow
    from edits import copy_tree
    from model import validate
    from photos import default_crop
    from storage import create_tree

    app = QApplication.instance() or QApplication([])
    results = []
    with tempfile.TemporaryDirectory() as temp:
        for family_name, original in families().items():
            people = list(original.people)
            for a in people:
                for b in people:
                    if a == b:
                        continue
                    for kind in KINDS:
                        folder = Path(temp) / f"{family_name}-{len(results)}.tree"
                        create_tree(folder, copy_tree(original))
                        window = MainWindow(None)
                        alerts, errors = [], []
                        window.alert = lambda title, text: alerts.append(text)
                        window.inform = lambda title, text: None
                        window.confirm = lambda title, text: True
                        window.choose = lambda title, label, options: 0
                        window.ask_crop = default_crop
                        hook = sys.excepthook
                        sys.excepthook = lambda k, e, tb: errors.append("".join(traceback.format_exception(k, e, tb)))
                        try:
                            window.open_path(folder)
                            before = copy_tree(window.tree)
                            already = holds(before, kind, a, b)
                            try:
                                if kind == "same":
                                    window._merge_dragged(b, a)  # Drag B onto A: B is the duplicate.
                                else:
                                    window._link_dragged(kind, a, b)
                            except Exception:
                                errors.append(traceback.format_exc())
                            app.processEvents()
                        finally:
                            sys.excepthook = hook
                        after = window.tree
                        changed = after != before
                        message = alerts[-1] if alerts else ""
                        verdict, problem = judge(kind, a, b, before, after, changed, already, message,
                                                 errors, validate(after))
                        results.append({"family": family_name, "a": original.people[a].display_name,
                                        "b": original.people[b].display_name, "kind": kind,
                                        "verdict": verdict, "problem": problem, "message": message})
                        window.close()
                        window.deleteLater()
                        app.processEvents()
                        free_closed_windows()
    return results


def judge(kind, a, b, before, after, changed, already, message, errors, issues):
    if errors:
        return "bug", "error inside the program: " + errors[-1].strip().splitlines()[-1]
    if issues:
        return "bug", "data rule broken: " + ", ".join(i.code for i in issues)
    if kind == "same":
        if changed:
            ok = a in after.people and b not in after.people
            return ("linked", "") if ok else ("bug", "merge kept the wrong person")
        return ("refused", "") if message else ("bug", "nothing happened and nothing was said")
    if changed:
        if holds(after, kind, a, b):
            return "linked", ""
        return "bug", "data changed but the relationship does not hold"
    if not message:
        return "bug", "nothing happened and nothing was said"
    if already:
        if "already" in message.lower():
            return "already", ""
        return "bug", "it is already true, but the message gives another reason"
    if "themselves" in message:
        return "bug", "says 'themselves' about two different people"
    if not any(name in message for name in (before.people[a].display_name, before.people[b].display_name)):
        return "bug", "the message names neither person"
    return "refused", ""


def report(results):
    out = ROOT / "dev-output"
    out.mkdir(exist_ok=True)
    counts = collections.Counter(r["verdict"] for r in results)
    reasons = collections.Counter((r["kind"], r["message"]) for r in results if r["verdict"] == "refused")
    bugs = [r for r in results if r["verdict"] == "bug"]
    rows = "".join(
        f"<tr><td>{html.escape(r['family'])}</td><td>{html.escape(r['b'])} as {r['kind']} of "
        f"{html.escape(r['a'])}</td><td>{html.escape(r['problem'])}</td><td>{html.escape(r['message'])}</td></tr>"
        for r in bugs
    )
    reason_rows = "".join(
        f"<tr><td>{kind}</td><td>{n}</td><td>{html.escape(msg)}</td></tr>"
        for (kind, msg), n in reasons.most_common()
    )
    page = f"""<!doctype html><meta charset="utf-8"><title>Connection sweep</title>
<style>body{{font:14px sans-serif;background:#2b2d31;color:#e8e8e8;margin:16px}}
td,th{{border-top:1px solid #44474d;padding:4px;text-align:left;vertical-align:top}}table{{border-collapse:collapse}}</style>
<h1>Connection sweep</h1><p>{len(results)} attempts: {dict(counts)}</p>
<h2>Bugs ({len(bugs)})</h2><table><tr><th>Family</th><th>Attempt</th><th>Problem</th><th>Message</th></tr>{rows}</table>
<h2>Refusal reasons</h2><table><tr><th>Kind</th><th>Times</th><th>Message</th></tr>{reason_rows}</table>"""
    (out / "sweep.html").write_text(page, encoding="utf-8")
    return counts, reasons, bugs


def main():
    results = run()
    counts, reasons, bugs = report(results)
    print(f"{len(results)} attempts: {dict(counts)}")
    for (kind, message), n in reasons.most_common():
        print(f"  refused {kind:8} x{n:<4} {message}")
    for bug in bugs[:40]:
        print(f"BUG {bug['family']}: {bug['b']} as {bug['kind']} of {bug['a']}: {bug['problem']} [{bug['message']}]")
    print(f"report: {ROOT / 'dev-output' / 'sweep.html'}")
    return 1 if bugs else 0


if __name__ == "__main__" and "--actions" not in sys.argv:
    sys.exit(main())


def run_actions():
    """Every action on every person, in every kind of view, answered and cancelled."""
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    from app import MainWindow
    from devtools.checks import failures, run_checks
    from dialogs import person_to_values
    from edits import copy_tree
    from photos import default_crop
    from storage import create_tree

    app = QApplication.instance() or QApplication([])
    results = []
    with tempfile.TemporaryDirectory() as temp:
        photo = Path(temp) / "photo.png"
        image = QImage(300, 400, QImage.Format.Format_RGB32)
        image.fill(QColor("#556677"))
        image.save(str(photo))
        for family_name, original in families().items():
            for view in ("family", "line", "ancestors", "bowtie", "fan"):
                for person in original.people:
                    for answer in (True, False):
                        probe = MainWindow(None)
                        folder = Path(temp) / f"a{len(results)}.tree"
                        create_tree(folder, copy_tree(original))
                        probe.open_path(folder)
                        keys = _actions_in_view(probe, view, person)
                        probe.close()
                        probe.deleteLater()
                        free_closed_windows()
                        for key in keys:
                            results.append(_one_action(app, temp, original, view, person, key, answer, photo,
                                                       MainWindow, create_tree, copy_tree, default_crop,
                                                       person_to_values, run_checks, failures))
    return results


def _actions_in_view(window, view, person):
    _enter_view(window, view, person)
    if person not in window.person_items:
        return []
    return [key for key, _label, enabled in window.person_actions(person) if enabled]


def _enter_view(window, view, person):
    if view == "family":
        window.centre_on(person)
    elif view == "line":
        window.chart = "pyramid"
        window.house = window._view_head_for(person)
        window.refresh(keep_view=False)
    elif view == "ancestors":
        window.show_ancestors(person)
    else:
        window.show_chart(view, person)


def _one_action(app, temp, original, view, person, key, answer, photo, MainWindow, create_tree,
                copy_tree, default_crop, person_to_values, run_checks, failures):
    folder = Path(temp) / f"b{next(_FOLDER_NUMBERS)}-{key}.tree"  # A counter: freed objects reuse id()s.
    create_tree(folder, copy_tree(original))
    window = MainWindow(None)
    errors = []
    hook = sys.excepthook
    sys.excepthook = lambda k, e, tb: errors.append("".join(traceback.format_exception(k, e, tb)))

    def ask_person(title, initial=None, link=None, relationships=(), another=False):
        if not answer:
            return None
        if initial and initial.get("given"):
            values = dict(initial)
        else:
            values = {"given": "Newperson", "surname": "Test", "living": "yes", **(initial or {})}
        values.setdefault("relationships", {k: "married" for k, *_ in relationships})
        if link is not None:
            values.setdefault("link", "birth")
        return values

    window.ask_person = ask_person
    window.alert = lambda title, text: None
    window.inform = lambda title, text: None
    window.confirm = lambda title, text: answer
    window.choose = lambda title, label, options: 0 if answer else None
    window.ask_photo = lambda: str(photo) if answer else None
    window.ask_crop = default_crop
    window.ask_existing_person = lambda title, exclude: (
        next((p for p in window.tree.people if p not in exclude), None) if answer else None)
    window.ask_duplicate = lambda title, label, options: len(options) - 1 if answer else None
    window.show_menu = lambda menu, position: None
    window.ask_open_file = lambda *a, **k: None
    window.ask_save_file = lambda *a, **k: None
    window.ask_combine = lambda *a, **k: None
    window.ask_sources = lambda: None
    window.ask_unsourced = lambda: None
    window.ask_duplicates = lambda candidates, selected: None
    window.ask_places = lambda rows: None
    window.ask_timeline = lambda rows: None
    window.ask_preferences = lambda values: None
    window.ask_print = lambda printer: False
    window.ask_report = lambda name: None
    window.ask_tasks = lambda person: [{"text": "Check the census"}] if answer else None
    window.ask_story = lambda person: ("A short story.", False) if answer else None
    window.ask_research = lambda: None
    window.ask_map = lambda: None
    window.ask_web_page = lambda with_password=True: None
    window.ask_statistics = lambda summary: None
    window.ask_lifelines = lambda: None
    window.ask_gallery = lambda: None
    window.ask_dna = lambda person_id: None
    window.ask_poster = lambda area: None

    def ask_documents(chosen):
        """Attach the test picture as a document (stored for real), or cancel."""
        if not answer:
            return None
        import documents
        from model import person_documents
        stored = documents.store_document(photo, window.folder)
        return person_documents(chosen) + [{"file": stored, "title": "scan", "kind": "photo", "date": ""}], None

    window.ask_documents = ask_documents
    outcome, problem = "ok", ""
    try:
        window.open_path(folder)
        _enter_view(window, view, person)
        before = copy_tree(window.tree)
        if key == "edit" and answer:
            window.ask_person = lambda *a, **k: {**person_to_values(window.tree.people[person]),
                                                 "relationships": {}, "notes": "edited"}
        window.run_action(key, person)
        app.processEvents()
        found = [str(p) for p in failures(run_checks(window))]
        if errors:
            outcome, problem = "bug", errors[-1].strip().splitlines()[-1]
        elif found:
            outcome, problem = "bug", "; ".join(found)
        elif not answer and window.tree != before and key not in NO_QUESTION:
            outcome, problem = "bug", "cancelling still changed the tree"
    except Exception:
        outcome, problem = "bug", traceback.format_exc().strip().splitlines()[-1]
    finally:
        sys.excepthook = hook
        window.close()
        window.deleteLater()
        app.processEvents()
        free_closed_windows()
    return {"family": "", "view": view, "person": original.people[person].display_name, "key": key,
            "answer": "answered" if answer else "cancelled", "verdict": outcome, "problem": problem}


def main_actions():
    results = run_actions()
    bugs = [r for r in results if r["verdict"] == "bug"]
    by_key = collections.Counter(r["key"] for r in results)
    print(f"{len(results)} actions tried ({len(by_key)} kinds): {dict(collections.Counter(r['verdict'] for r in results))}")
    for bug in bugs[:40]:
        print(f"BUG {bug['view']}: {bug['key']} on {bug['person']} ({bug['answer']}): {bug['problem']}")
    return 1 if bugs else 0


if __name__ == "__main__" and "--actions" in sys.argv:
    sys.exit(main_actions())
