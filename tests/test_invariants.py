"""Two rules every change must keep, checked across the whole program rather than case by case.

1. Opening a window and pressing OK without changing anything changes nothing. Windows
   show only some of what a record holds; whatever they don't show must survive. One rich
   tree (imported from a file full of other programs' details, plus everything Maiores
   itself stores) goes through every editing window, and the saved tree must stay
   byte for byte the same. Nested editors (a citation, a name, an event, a witness, a DNA
   test or match) must give back exactly what they were given.

2. A file operation that fails part way leaves the person's files as they were. Export,
   share, import, combine, restore, attaching documents and saving are run again and again,
   with the Nth write on disk failing (N = 1, 2, 3, ... until the operation gets through).
   After every failure: what was there before is intact and consistent (every file a tree
   or GEDCOM refers to exists), nothing unrelated was touched, nothing half-made is left
   behind, and trying again works.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QDialog  # noqa: E402

import app as app_module  # noqa: E402
from model import person_documents, place_records, stored_facts  # noqa: E402
from storage import open_tree  # noqa: E402
from test_window import WindowCase  # noqa: E402

RICH_GEDCOM = """0 HEAD
1 SOUR OtherProgram
2 VERS 9.1
1 GEDC
2 VERS 5.5.1
1 CHAR UTF-8
0 @S1@ SOUR
1 TITL Parish register of Trogir
1 AUTH Parish office
1 PUBL Town Press 1901
1 ABBR PR1901
1 REPO @R1@
1 _CUSTOM kept as written
0 @R1@ REPO
1 NAME Diocesan archive
0 @N1@ NOTE A shared note
1 CONT on two lines
0 @I1@ INDI
1 NAME Ivan /Case/
2 NPFX Dr.
2 NSFX Sr.
1 NAME Elena /Case/ Jr.
2 TYPE aka
1 NAME Elena /Case/ III
2 TYPE aka
1 NAME Johannes /Casius/
2 TYPE religious
1 SEX M
1 BIRT
2 DATE 12 MAR 1890
2 PLAC Trau
2 ADDR Harbour Street 12
2 SOUR @S1@
3 PAGE 17
3 QUAY 3
3 DATA
4 TEXT Transcribed birth entry
2 _MYTAG something else
1 BAPM
2 DATE 14 MAR 1890
2 PLAC Trogir
1 OCCU Fisherman
2 DATE FROM 1910 TO 1930
1 RESI
2 ADDR Old Quay 4
2 PLAC Split
1 DEAT
2 DATE ABT 1960
2 PLAC Split
2 CAUS Old age
2 AGE 70y
1 TITL Captain
1 NOTE @N1@
1 NOTE A note of his own
1 RESN confidential
1 _UID 1234-ABCD
1 FAMS @F1@
1 FAMS @F2@
0 @I2@ INDI
1 NAME Ana /Marin/
1 SEX F
1 BIRT
2 ADDR Only an address
1 DEAT Y
1 FAMS @F1@
0 @I3@ INDI
1 NAME Mia /Case/
1 SEX F
1 BIRT
2 DATE BET 1915 AND 1920
1 FAMC @F1@
2 _FREL Natural
2 _MREL Adopted
0 @I4@ INDI
1 NAME Ruth /Other/
1 SEX F
1 DEAT Y
1 FAMS @F2@
0 @I5@ INDI
1 NAME Witness /Person/
1 DEAT Y
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 CHIL @I3@
1 MARR
2 DATE 1912
2 PLAC Trogir
2 SOUR @S1@
3 PAGE 22
1 _FAMTAG kept for the couple
0 @F2@ FAM
1 HUSB @I1@
1 WIFE @I4@
1 DIV Y
0 TRLR
"""


@contextlib.contextmanager
def every_dialog_accepts():
    """Every window opens and is accepted at once, untouched: the real code path of OK."""
    def accept(dialog):
        dialog.accept()
        return QDialog.DialogCode.Accepted.value

    with mock.patch.object(QDialog, "exec", accept):
        yield


def tree_bytes(folder):
    return (Path(folder) / "tree.json").read_bytes()


class Faults:
    """Makes the Nth write under `root` fail as a full disk would. Counts every way the
    program writes: opening a file for writing, copying, renaming, replacing, making a
    folder and syncing."""

    def __init__(self, root, fail_at):
        self.root, self.fail_at, self.count = str(Path(root).resolve()), fail_at, 0

    def hit(self, path=None):
        if path is not None:
            try:
                if not str(Path(os.fspath(path)).resolve()).startswith(self.root):
                    return
            except (TypeError, ValueError):
                return
        self.count += 1
        if self.count == self.fail_at:
            raise OSError(28, "No space left on device (injected)")

    @contextlib.contextmanager
    def active(self):
        real_open, real_replace, real_rename = os.open, os.replace, os.rename
        real_mkdir, real_fsync, real_copyfile = os.mkdir, os.fsync, shutil.copyfile
        real_io_open = io.open
        writing = os.O_WRONLY | os.O_RDWR | os.O_CREAT

        def os_open(path, flags, *args, **kwargs):
            if flags & writing:
                self.hit(path)
            return real_open(path, flags, *args, **kwargs)

        def io_open(file, mode="r", *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in "wax+"):
                self.hit(file)
            return real_io_open(file, mode, *args, **kwargs)

        def replace(src, dst, *args, **kwargs):
            self.hit(dst)
            return real_replace(src, dst, *args, **kwargs)

        def rename(src, dst, *args, **kwargs):
            self.hit(dst)
            return real_rename(src, dst, *args, **kwargs)

        def mkdir(path, *args, **kwargs):
            if not os.path.exists(path):  # An existing folder answers "exists", whatever the disk.
                self.hit(path)
            return real_mkdir(path, *args, **kwargs)

        def fsync(fd):
            import stat
            if not stat.S_ISDIR(os.fstat(fd).st_mode):  # Syncing a folder is best effort by design.
                self.hit()
            return real_fsync(fd)

        def copyfile(src, dst, *args, **kwargs):
            self.hit(dst)
            return real_copyfile(src, dst, *args, **kwargs)

        with mock.patch.object(os, "open", os_open), mock.patch.object(os, "replace", replace), \
                mock.patch.object(os, "rename", rename), mock.patch.object(os, "mkdir", mkdir), \
                mock.patch.object(os, "fsync", fsync), mock.patch.object(shutil, "copyfile", copyfile), \
                mock.patch("builtins.open", io_open), mock.patch.object(io, "open", io_open):
            yield self


def listing(folder):
    """Every path under a folder, with the bytes of each file."""
    folder = Path(folder)
    return {str(p.relative_to(folder)): (p.read_bytes() if p.is_file() else None)
            for p in sorted(folder.rglob("*"))}


class RichTreeCase(WindowCase):
    def rich_tree(self):
        """The rich GEDCOM imported, with a document, a portrait, DNA, tasks, a story,
        faces, place details and private marks added the way the program stores them."""
        source = self.temp / "rich"
        source.mkdir()
        (source / "rich.ged").write_text(RICH_GEDCOM, encoding="utf-8")
        self.assertTrue(self.window.import_gedcom(source / "rich.ged", self.folder))
        self.assertTrue(self.window.open_path(self.folder))
        tree = self.window.tree
        ivan = next(p for p in tree.people.values() if p.given == "Ivan")
        letter = self.temp / "letter.pdf"
        letter.write_bytes(b"%PDF-1.4 a letter")
        from PySide6.QtGui import QColor, QImage
        picture = QImage(120, 90, QImage.Format.Format_RGB32)
        picture.fill(QColor("#336699"))
        group = self.temp / "group.png"
        picture.save(str(group))
        self.window.attach_documents(ivan.id, [str(letter), str(group)])
        data = json.loads(tree_bytes(self.folder))
        person = data["people"][ivan.id]
        person["documents"][0].update({"kind": "letter", "date": "1910-03-15", "private": True})
        person["dna"] = {"tests": [{
            "id": "t1", "company": "MyHeritage", "kind": "autosomal", "kit": "K1", "haplogroup": "", "notes": "kit note",
            "matches": [{"id": "m1", "name": "Cousin", "kit": "A1", "cm": 120.5, "segments": 6, "longest": 40.0,
                         "guess": "2nd cousin", "person": "", "notes": "met in 2020", "source": "list.csv"}],
            "segments": [{"match": "m1", "chr": "1", "start": 1000000, "end": 9000000, "cm": 8.5, "snps": 900}]}]}
        person["tasks"] = [{"text": "Find the will", "done": False, "note": "Ask the archive"}]
        person["story"] = "He sailed."
        person["notes_private"] = True
        places = data.setdefault("places", {})
        places["Trogir"] = {"parent": "Dalmatia", "kind": "town", "lat": 43.52, "lon": 16.25,
                            "old_names": [{"name": "Tragurium", "until": "1420"}], "note": "on an island"}
        places["Dalmatia"] = {"kind": "region"}
        data["faces"] = {person["documents"][1]["file"]: [{"rect": [0.1, 0.1, 0.2, 0.2], "person": ivan.id},
                                                          {"rect": [0.5, 0.1, 0.2, 0.2], "name": "Unknown sailor"}]}
        (self.folder / "tree.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.window.close_tree()
        self.assertTrue(self.window.open_path(self.folder))
        self.window._save()  # Written once by this version, so a later difference is an edit's.
        self.window.refresh()
        # The real windows, not the test stand-ins: these tests are about what they give back.
        self.window.ask_person = app_module.MainWindow.ask_person.__get__(self.window)
        return ivan.id


class UnchangedOkTests(RichTreeCase):
    def assert_unchanged(self, action, *args):
        before = tree_bytes(self.folder)
        with every_dialog_accepts():
            action(*args)
        self.assertIsNone(self.window.save_error)
        after = tree_bytes(self.folder)
        if before != after:
            old, new = json.loads(before), json.loads(after)
            self.fail(f"{getattr(action, '__name__', action)}{args} changed the tree:\n"
                      + "\n".join(_differences(old, new)[:20]))

    def test_every_person_window_given_ok(self):
        self.rich_tree()
        for person_id in list(self.window.tree.people):
            for action in ("edit", "documents", "tasks", "story"):
                with self.subTest(person=self.window.tree.people[person_id].display_name, action=action):
                    self.assert_unchanged(self.window.run_action, action, person_id)
            with self.subTest(person=person_id, action="dna"):
                self.assert_unchanged(self.window.show_dna, person_id)

    def test_every_tree_window_given_ok(self):
        self.rich_tree()
        for name in ("show_sources", "show_places"):
            with self.subTest(window=name):
                self.assert_unchanged(getattr(self.window, name))

    def test_every_place_saved_unchanged_in_the_places_window(self):
        from dialogs import PlacesDialog
        self.rich_tree()
        before = tree_bytes(self.folder)
        dialog = PlacesDialog(self.window, self.window.tree)
        for name in list(place_records(self.window.tree)):
            if name in dialog.shown:
                dialog.places.setCurrentRow(dialog.shown.index(name))
                dialog.editor.save.click()
        operations = dialog.operations
        dialog.deleteLater()
        self.window.apply_edit(lambda: self.window._replay_places(operations))
        self.assertEqual(json.loads(tree_bytes(self.folder)), json.loads(before))

    def test_nested_editors_give_back_what_they_were_given(self):
        from dialogs import EventDialog
        from dna_dialog import MatchDialog, TestDialog
        from facts_dialogs import CitationDialog, FactContext, NameDialog, RoleDialog
        import dna
        from model import clean_citations, clean_role_people, person_events, person_names
        self.rich_tree()
        tree = self.window.tree
        context = FactContext(tree)
        checked = 0
        for _owner, _kind, fact in stored_facts(tree):
            for citation in clean_citations(fact.get("citations")):
                with self.subTest(citation=citation):
                    dialog = CitationDialog(self.window, context, citation)
                    self.assertEqual(dialog.values(), citation)
                    dialog.deleteLater()
                    checked += 1
            for role in clean_role_people(fact.get("people")):
                with self.subTest(role=role):
                    dialog = RoleDialog(self.window, context, role)
                    self.assertEqual(dialog.values(), role)
                    dialog.deleteLater()
        for person in tree.people.values():
            for name in person_names(person):
                with self.subTest(name=name):
                    dialog = NameDialog(self.window, context, name)
                    self.assertEqual({k: v for k, v in dialog.values().items() if v not in ("", None, [])},
                                     {k: v for k, v in name.items() if v not in ("", None, [])})
                    dialog.deleteLater()
                    checked += 1
            for event in person_events(person):
                with self.subTest(event=event):
                    dialog = EventDialog(self.window, event, context)
                    self.assertEqual({k: v for k, v in dialog.values().items() if v not in ("", None, [])},
                                     {k: v for k, v in event.items() if v not in ("", None, [])})
                    dialog.deleteLater()
                    checked += 1
            for test in dna.tests_of(person):
                with self.subTest(test=test["id"]):
                    dialog = TestDialog(self.window, test)
                    values = dialog.values()
                    self.assertEqual({k: v for k, v in values.items() if k in test}, {k: test[k] for k in values if k in test})
                    dialog.deleteLater()
                for match in test["matches"]:
                    with self.subTest(match=match["name"]):
                        dialog = MatchDialog(self.window, match, tree, None)
                        values = dialog.values()
                        self.assertEqual({k: v for k, v in values.items() if k in match},
                                         {k: match[k] for k in values if k in match})
                        dialog.deleteLater()
        self.assertGreater(checked, 5)  # The rich tree really has things to check.


def _differences(old, new, path=""):
    if isinstance(old, dict) and isinstance(new, dict):
        found = []
        for key in sorted(set(old) | set(new), key=str):
            if old.get(key) != new.get(key):
                found += _differences(old.get(key), new.get(key), f"{path}/{key}")
        return found
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        found = []
        for index, (a, b) in enumerate(zip(old, new)):
            found += _differences(a, b, f"{path}[{index}]")
        return found
    return [f"{path}: {old!r} -> {new!r}"]


class FailingWriteTests(RichTreeCase):
    """Rule 2. `operation()` returns whether it reports success; `check(succeeded)` asserts
    the state on disk after each attempt."""

    def every_failure(self, operation, check, reset=None, limit=400, strict=True):
        """`strict`: a failed write may never come with success. Not strict: success may
        follow a failed best-effort write (a routine backup), and `check` must then find the
        result complete."""
        fail_at = 0
        while True:
            fail_at += 1
            self.assertLess(fail_at, limit, "the operation never got through")
            faults = Faults(self.temp, fail_at)
            failed = False
            with faults.active():
                try:
                    succeeded = bool(operation())
                except OSError as error:  # Escaping the program's own handling is a bug too,
                    self.fail(f"write {fail_at}: {error!r} was not handled")  # but say where.
            failed = faults.count >= fail_at
            with self.subTest(failing_write=fail_at):
                if failed and strict:
                    self.assertFalse(succeeded, f"write {fail_at} failed, yet success was reported")
                check(succeeded)
            if reset is not None:
                reset()
            if not failed:
                return fail_at - 1

    def outside_files(self):
        """Files of the person's that no operation should ever touch."""
        mine = self.temp / "out"
        mine.mkdir(exist_ok=True)
        (mine / "my notes.txt").write_text("mine")
        (mine / ".hidden folder").mkdir(exist_ok=True)
        (mine / ".hidden folder" / "keep.txt").write_text("mine")
        (mine / "family_media-old").mkdir(exist_ok=True)
        (mine / "family_media-old" / "keep.jpg").write_bytes(b"mine")
        return mine

    def assert_untouched(self, mine):
        self.assertEqual((mine / "my notes.txt").read_text(), "mine")
        self.assertEqual((mine / ".hidden folder" / "keep.txt").read_text(), "mine")
        self.assertEqual((mine / "family_media-old" / "keep.jpg").read_bytes(), b"mine")

    def assert_gedcom_consistent(self, path):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if " FILE " in line:
                self.assertTrue((path.parent / line.split(" FILE ", 1)[1]).is_file(), line)

    def assert_tree_consistent(self, folder):
        tree = open_tree(folder).tree  # Opens: not damaged.
        for person in tree.people.values():
            for stored in [person.photo] + [d["file"] for d in person_documents(person)]:
                if stored:
                    self.assertTrue((Path(folder) / stored).is_file(), stored)
        return tree

    def test_gedcom_export(self):
        self.rich_tree()
        mine = self.outside_files()
        target = mine / "family.ged"
        self.assertTrue(self.window.export_gedcom(target))
        previous = listing(mine)

        def check(succeeded):
            self.assert_untouched(mine)
            self.assert_gedcom_consistent(target)
            if not succeeded:
                self.assertEqual(listing(mine), previous)  # Nothing changed, nothing left behind.
            self.assertFalse([p for p in mine.iterdir() if "-export-" in p.name])

        writes = self.every_failure(lambda: self.window.export_gedcom(target), check)
        self.assertGreater(writes, 3)

    def test_share_copy(self):
        self.rich_tree()
        mine = self.outside_files()
        target = mine / "Shared.tree"
        before = listing(mine)

        def check(succeeded):
            self.assert_untouched(mine)
            if succeeded:
                self.assert_tree_consistent(target)
            else:
                self.assertEqual(listing(mine), before)

        def reset():
            if target.exists():
                shutil.rmtree(target)

        self.every_failure(lambda: self.window.make_share_copy(target, hide=False), check, reset)

    def test_gedcom_import(self):
        source = self.temp / "rich"
        source.mkdir()
        (source / "rich.ged").write_text(RICH_GEDCOM + "", encoding="utf-8")
        letter = source / "letter.pdf"
        letter.write_bytes(b"%PDF-1.4 a letter")
        text = RICH_GEDCOM.replace("1 RESN confidential\n", "1 OBJE\n2 FILE letter.pdf\n2 TITL Letter\n2 _FT_DOC Y\n")
        (source / "rich.ged").write_text(text, encoding="utf-8")
        mine = self.outside_files()
        target = mine / "Imported.tree"
        before = listing(mine)

        def check(succeeded):
            self.assert_untouched(mine)
            if succeeded or target.exists():  # Made, even if opening it afterwards failed: complete.
                self.assert_tree_consistent(target)
            else:
                self.assertEqual(listing(mine), before)
            self.assertFalse([p for p in mine.iterdir() if "-import-" in p.name])

        def reset():
            self.window.close_tree()
            if target.exists():
                shutil.rmtree(target)

        # Opening the new tree afterwards takes a routine backup, which may fail without harm.
        self.every_failure(lambda: self.window.import_gedcom(source / "rich.ged", target), check, reset, strict=False)

    def test_saving_an_edit(self):
        ivan = self.rich_tree()
        good = tree_bytes(self.folder)

        def operation():
            with every_dialog_accepts():
                self.window.ask_person = lambda *a, **k: {**app_module.person_to_values(self.window.tree.people[ivan]),
                                                          "notes": "changed"}
                self.window.run_action("edit", ivan)
            return self.window.save_error is None

        def check(succeeded):
            on_disk = self.assert_tree_consistent(self.folder)
            if succeeded:
                self.assertEqual(on_disk.people[ivan].notes, "changed")
            else:
                self.assertEqual(tree_bytes(self.folder), good)

        def reset():
            self.window.save_error = None
            (self.folder / "tree.json").write_bytes(good)
            self.window.close_tree()
            self.window.open_path(self.folder)

        self.every_failure(operation, check, reset)

    def test_restoring_a_backup(self):
        ivan = self.rich_tree()
        from storage import list_backups, make_backup
        make_backup(self.folder)
        self.window.apply_edit(lambda: setattr(self.window.tree.people[ivan], "notes", "after the backup"))
        good = tree_bytes(self.folder)
        backup = list_backups(self.folder)[0][0]

        def check(succeeded):
            self.assert_tree_consistent(self.folder)
            if succeeded:
                self.assertNotEqual(tree_bytes(self.folder), good)
            else:
                self.assertEqual(tree_bytes(self.folder), good)

        def reset():
            self.window.save_error = None
            (self.folder / "tree.json").write_bytes(good)
            self.window.close_tree()
            self.window.open_path(self.folder)

        self.every_failure(lambda: self.window.restore_backup(backup, "then"), check, reset)

    def test_attaching_documents(self):
        ivan = self.rich_tree()
        good = tree_bytes(self.folder)
        letters = []
        for number in (1, 2):
            path = self.temp / f"new{number}.pdf"
            path.write_bytes(b"%PDF-1.4 new " + bytes([48 + number]))
            letters.append(str(path))

        def operation():
            alerts = len(self.answers.alerts)
            self.window.attach_documents(ivan, letters)
            return self.window.save_error is None and len(self.answers.alerts) == alerts

        def check(succeeded):
            # A file that couldn't be copied is named in an alert and the rest are attached;
            # either way the tree on disk refers only to files that are there.
            self.assert_tree_consistent(self.folder)
            if succeeded:
                self.assertEqual(len(person_documents(open_tree(self.folder).tree.people[ivan])), 4)

        def reset():
            self.window.save_error = None
            (self.folder / "tree.json").write_bytes(good)
            self.window.close_tree()
            self.window.open_path(self.folder)

        self.every_failure(operation, check, reset)

    def test_combining_a_relatives_tree(self):
        self.rich_tree()
        relative = self.temp / "Relative.tree"
        shutil.copytree(self.folder, relative, ignore=shutil.ignore_patterns(".lock", "backups"))
        data = json.loads(tree_bytes(relative))
        for person in data["people"].values():
            person["given"] = person["given"] + "x"  # Nobody matches: everyone comes across, with files.
        (relative / "tree.json").write_text(json.dumps(data), encoding="utf-8")
        good = tree_bytes(self.folder)

        def ask(theirs, suggestions, name, initial):
            return {"matches": {}, "take_theirs": {}}

        self.window.ask_combine = ask

        def check(succeeded):
            on_disk = self.assert_tree_consistent(self.folder)
            if succeeded:
                self.assertEqual(len(on_disk.people), 10)
            else:
                self.assertEqual(tree_bytes(self.folder), good)
            self.assertEqual(json.loads(tree_bytes(relative)), data)  # Theirs only read.

        def reset():
            self.window.save_error = None
            (self.folder / "tree.json").write_bytes(good)
            self.window.close_tree()
            self.window.open_path(self.folder)

        self.every_failure(lambda: self.window.combine_with(str(relative)) and self.window.save_error is None,
                           check, reset)


class MoreUnchangedOkTests(UnchangedOkTests):
    """Windows added to rule 1 after the first version of these checks."""

    def test_every_person_window_given_ok(self):  # Already run above; not again here.
        pass

    def test_every_tree_window_given_ok(self):
        pass

    def test_every_place_saved_unchanged_in_the_places_window(self):
        pass

    def test_nested_editors_give_back_what_they_were_given(self):
        pass

    def test_the_faces_duplicates_and_map_windows_given_ok(self):
        ivan = self.rich_tree()
        self.answers.confirms = [False] * 5  # The map may not fetch tiles in a test.
        self.answers.choices = [None] * 5
        for name in ("show_duplicates", "show_map"):
            with self.subTest(window=name):
                self.assert_unchanged(getattr(self.window, name))
        from model import face_links
        for path in list(face_links(self.window.tree)):
            with self.subTest(faces=path):
                def faces_ok(path=path):
                    from faces_dialog import FacesDialog
                    import documents
                    source = documents.resolve_document(self.folder, path)
                    from photos import read_image
                    from facts_dialogs import FactContext
                    dialog = FacesDialog(self.window, read_image(source), face_links(self.window.tree)[path],
                                         FactContext(self.window.tree))
                    values = dialog.values()
                    dialog.deleteLater()
                    self.assertEqual(values, face_links(self.window.tree)[path])
                faces_ok()
        self.assertTrue(ivan)


class MoreFailingWriteTests(FailingWriteTests):
    """File operations added to rule 2 after the first version of these checks."""

    for _name in ("test_gedcom_export", "test_share_copy", "test_gedcom_import", "test_saving_an_edit",
                  "test_restoring_a_backup", "test_attaching_documents", "test_combining_a_relatives_tree"):
        locals()[_name] = lambda self: None  # Already run above.

    def one_file(self, name, write):
        """A file written over a previous version, beside the person's own files, including
        one called like a temporary file would be."""
        mine = self.outside_files()
        target = mine / name
        target.write_bytes(b"previous version")
        (mine / f".{name}.tmp").write_text("mine")
        before = listing(mine)

        def check(succeeded):
            self.assert_untouched(mine)
            self.assertEqual((mine / f".{name}.tmp").read_text(), "mine")
            self.assertEqual(set(listing(mine)), set(before))  # Nothing left behind.
            if succeeded:
                self.assertNotEqual(target.read_bytes(), b"previous version")
            else:
                self.assertEqual(target.read_bytes(), b"previous version")

        self.every_failure(lambda: write(target), check)

    def test_web_page(self):
        self.rich_tree()
        self.one_file("family.html", lambda path: self.window.write_web_page(
            path, {"hide_living": False, "photos": True, "password": "secret"}))

    def test_picture_pdf_and_png(self):
        self.rich_tree()
        self.one_file("family.pdf", lambda path: self.window.export_picture(path, hide=False))
        self.one_file("family.png", lambda path: self.window.export_picture(path, hide=False))

    def test_poster(self):
        self.rich_tree()
        self.one_file("poster.pdf", lambda path: self.window.export_poster(path, {"paper": "A4", "across": 2},
                                                                          hide=False))

    def test_book(self):
        import reports
        self.rich_tree()

        def write(path):
            try:
                reports.write_document("<html><body><h1>Book</h1></body></html>", path)
            except OSError:
                return False
            return True

        self.one_file("book.pdf", write)

    def test_dna_raw_file(self):
        ivan = self.rich_tree()
        from dna_dialog import DnaDialog
        raw = "# build 37\nrsid\tchromosome\tposition\tgenotype\n" + "".join(
            f"rs{n}\t1\t{1000 + n}\tAG\n" for n in range(50))
        source = self.temp / "raw.txt"
        source.write_text(raw, encoding="utf-8")
        before = listing(self.folder / "media")

        def operation():
            dialog = DnaDialog(self.window, self.window.tree, ivan, self.folder)
            report = dialog.import_path(source)
            files = list(dialog.new_raw_files)
            dialog.reject()
            dialog.deleteLater()
            return bool(files) and "50" in report

        def check(succeeded):
            raw_dir = self.folder / "dna"
            left = [p.name for p in raw_dir.iterdir()] if raw_dir.exists() else []
            self.assertEqual(left, [])  # Cancelled each time: nothing stays, whole or half.
            self.assertEqual(listing(self.folder / "media"), before)

        self.every_failure(operation, check)

if __name__ == "__main__":
    unittest.main()
