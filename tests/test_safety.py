"""What Maiores tells you must match what is on disk, and nothing private may slip out.
Each test here reproduces a finding of the November 2026 review (data loss, recovery,
privacy, leaks) and checks the fix."""
import datetime
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402

import app as app_module  # noqa: E402
import dna  # noqa: E402
import documents  # noqa: E402
import privacy  # noqa: E402
import reports  # noqa: E402
import webshare  # noqa: E402
from edits import merge_people  # noqa: E402
from gedcom import read_gedcom  # noqa: E402
from model import Family, Person, Tree, face_links, person_documents, tree_sources, place_records  # noqa: E402
from photos import PhotoCache, resolve_photo  # noqa: E402
from sample import sample_tree  # noqa: E402
from storage import create_tree, open_tree  # noqa: E402
from test_window import WindowCase  # noqa: E402

TODAY = datetime.date(2026, 11, 21)


def failing_save(test):
    """Every save fails as if the disk were full, until the test ends."""
    real = app_module.save_tree

    def failing(folder, tree):
        raise OSError("simulated disk full")

    app_module.save_tree = failing

    def disk_works_again():  # Before the window's own checks: memory and disk agree again.
        app_module.save_tree = real
        window = getattr(test, "window", None)
        if window is not None and window.tree is not None and window.folder is not None:
            window._save()

    test.addCleanup(disk_works_again)
    return real


class CombineKeepsEverythingTests(WindowCase):
    def relative_with_records(self):
        """A relative's tree whose new person cites a source and is born in a recorded place."""
        from edits import add_child, make_person
        theirs = sample_tree()
        add_child(theirs, "ivana", make_person({"given": "Lucija", "surname": "Šimić"}))
        lucija = next(p for p in theirs.people.values() if p.given == "Lucija")
        lucija.birth = {"date": "1990", "place": "Trogir", "citations": [{"source": "s-parish"}]}
        theirs.extra["sources"] = {"s-parish": {"title": "Parish book of Trogir"}}
        theirs.extra["places"] = {"Trogir": {"lat": 43.5, "lon": 16.25}, "Split": {"lat": 43.5, "lon": 16.44},
                                  "Zadar": {"note": "On the coast"}}
        folder = self.temp / "Relative.tree"
        create_tree(folder, theirs)
        return folder, lucija.id

    def accept_suggestions(self):
        from combine_dialog import CombineDialog

        def ask(theirs, suggestions, name, initial):
            dialog = CombineDialog(self.window, self.window.tree, theirs, suggestions, name, initial)
            values = dialog.values()
            dialog.deleteLater()
            return values

        self.window.ask_combine = ask

    def test_sources_and_places_are_saved_with_the_people(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        relative, _lucija = self.relative_with_records()
        self.accept_suggestions()
        self.assertTrue(self.window.combine_with(str(relative)))
        reopened = open_tree(self.folder).tree
        self.assertEqual([s["title"] for s in tree_sources(reopened).values()], ["Parish book of Trogir"])
        self.assertEqual(sorted(place_records(reopened)), ["Split", "Trogir", "Zadar"])
        self.assertNotIn("missing_source", [issue.code for issue in open_tree(self.folder).issues])

    def test_a_dna_raw_file_comes_across_or_is_not_referred_to(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        relative, lucija = self.relative_with_records()
        theirs = json.loads((relative / "tree.json").read_text(encoding="utf-8"))
        test = {"id": "t1", "company": "Other", "kind": "autosomal", "matches": [], "segments": [],
                "raw": {"file": "dna/kit.txt", "snps": 3, "build": "37", "sex": ""}}
        theirs["people"][lucija]["dna"] = {"tests": [test]}
        (relative / "tree.json").write_text(json.dumps(theirs), encoding="utf-8")
        (relative / "dna").mkdir()
        (relative / "dna" / "kit.txt").write_text("# raw\n", encoding="utf-8")
        self.accept_suggestions()
        self.assertTrue(self.window.combine_with(str(relative)))
        new = next(p for p in self.window.tree.people.values() if p.given == "Lucija")
        [kept] = dna.tests_of(new)
        self.assertNotEqual(kept["raw"]["file"], "dna/kit.txt")
        self.assertTrue((self.folder / kept["raw"]["file"]).is_file())


class UnsavedChangesTests(WindowCase):
    def edit_that_cannot_be_saved(self):
        ana = self.start_family()
        failing_save(self)
        self.answers.people = [{"given": "Late", "link": "birth"}]
        self.window.run_action("add_child", ana)
        self.assertIsNotNone(self.window.save_error)

    def test_closing_the_tree_asks_first_and_no_keeps_it_open(self):
        self.edit_that_cannot_be_saved()
        self.answers.confirms = [False]
        self.assertFalse(self.window.close_tree())
        self.assertIsNotNone(self.window.tree)
        self.assertIn("Late", [p.given for p in self.window.tree.people.values()])

    def test_opening_another_tree_asks_first(self):
        self.edit_that_cannot_be_saved()
        other = self.temp / "Other.tree"
        create_tree(other, sample_tree())
        self.answers.confirms = [False]
        self.assertFalse(self.window.open_path(other))
        self.assertEqual(Path(self.window.folder), self.folder)
        self.assertIn("Late", [p.given for p in self.window.tree.people.values()])

    def test_the_sample_asks_first(self):
        self.edit_that_cannot_be_saved()
        self.answers.confirms = [False]
        self.assertFalse(self.window.load_sample())
        self.assertEqual(Path(self.window.folder), self.folder)
        self.answers.confirms = [True]  # Now let go: the window can close at the end.
        self.assertTrue(self.window.close_tree())


class RecoveryTests(WindowCase):
    def test_restore_says_so_when_the_restored_tree_was_not_saved(self):
        ana = self.start_family()
        from storage import list_backups, make_backup
        make_backup(self.folder)
        [(backup, _when, _count)] = list_backups(self.folder)[:1]
        self.answers.people = [{"given": "After", "link": "birth"}]
        self.window.run_action("add_child", ana)  # Saved: now the backup differs.
        failing_save(self)
        self.assertFalse(self.window.restore_backup(backup, "then"))
        self.assertTrue(any("simulated disk full" in alert for alert in self.answers.alerts))
        self.assertNotIn("Restored", self.window.statusBar().currentMessage())

    def test_a_damaged_tree_offers_its_newest_backup_and_keeps_the_damaged_file(self):
        self.start_family()
        names = sorted(p.given for p in self.window.tree.people.values())
        (self.folder / "media" / "keep.txt").write_text("photo", encoding="utf-8")
        self.window.close_tree()
        from storage import make_backup
        make_backup(self.folder)
        (self.folder / "tree.json").write_text("{ broken", encoding="utf-8")
        self.answers.confirms = [True]
        self.assertTrue(self.window.open_path(self.folder))
        self.assertEqual(sorted(p.given for p in self.window.tree.people.values()), names)
        self.assertEqual([p.read_text() for p in self.folder.glob("tree-damaged-*.json")], ["{ broken"])
        self.assertTrue((self.folder / "media" / "keep.txt").exists())

    def test_saying_no_to_recovery_changes_nothing(self):
        self.start_family()
        self.window.close_tree()
        from storage import make_backup
        make_backup(self.folder)
        (self.folder / "tree.json").write_text("{ broken", encoding="utf-8")
        self.answers.confirms = [False]
        self.assertFalse(self.window.open_path(self.folder))
        self.assertEqual((self.folder / "tree.json").read_text(), "{ broken")
        self.assertEqual(list(self.folder.glob("tree-damaged-*.json")), [])


class ImportTests(WindowCase):
    def test_documents_that_cannot_be_copied_are_counted(self):
        source = self.temp / "in"
        source.mkdir()
        (source / "letter.pdf").write_bytes(b"%PDF-1.4 letter")
        (source / "family.ged").write_text("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ante /Šimić/\n"
                                           "1 OBJE\n2 FILE letter.pdf\n2 TITL Letter\n2 _FT_DOC Y\n0 TRLR\n",
                                           encoding="utf-8")
        real = documents.store_document

        def refused(*args, **kwargs):  # A file of a kind or size not taken: counted, import goes on.
            raise documents.DocumentError("size")

        documents.store_document = refused
        self.addCleanup(setattr, documents, "store_document", real)
        self.assertTrue(self.window.import_gedcom(source / "family.ged", self.temp / "Imported"))
        self.assertTrue(any("could not be copied in: 1" in text for text in self.answers.informed + self.answers.alerts),
                        self.answers.informed)

        def disk_full(*args, **kwargs):  # A disk error: the import stops and leaves nothing behind.
            raise OSError(28, "simulated disk full")

        documents.store_document = disk_full
        self.assertFalse(self.window.import_gedcom(source / "family.ged", self.temp / "Again"))
        self.assertTrue(any("simulated disk full" in text for text in self.answers.alerts))
        self.assertFalse((self.temp / "Again.tree").exists())

    def test_a_confidential_record_becomes_private(self):
        path = self.temp / "c.ged"
        path.write_text("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ante /Šimić/\n1 RESN confidential\n"
                        "1 DEAT Y\n0 @I2@ INDI\n1 NAME Mara /Šimić/\n1 RESN locked\n1 DEAT Y\n0 TRLR\n",
                        encoding="utf-8")
        people = {p.given: p for p in read_gedcom(path, TODAY).tree.people.values()}
        self.assertTrue(people["Ante"].extra.get("private"))
        self.assertFalse(people["Mara"].extra.get("private"))
        ante = people["Ante"]
        shared = privacy.shareable(Tree({ante.id: ante}, {}), TODAY, hide_living=False)
        self.assertTrue(privacy.is_hidden(shared.people[ante.id]))


class DocumentWindowTests(WindowCase):
    def test_cancelling_the_documents_window_takes_new_files_back(self):
        from documents_dialog import DocumentsDialog
        self.start_family()
        ana = self.person_named("Ana")
        letter = self.temp / "letter.pdf"
        letter.write_bytes(b"%PDF-1.4 new letter")
        dialog = DocumentsDialog(self.window, ana, self.folder)
        dialog.add_files([str(letter)])
        docs = self.folder / "media" / "docs"
        self.assertEqual(len(list(docs.iterdir())), 1)
        dialog.reject()
        dialog.deleteLater()
        self.assertEqual(list(docs.iterdir()), [])

    def test_a_file_already_in_the_tree_is_never_deleted_by_cancelling(self):
        from documents_dialog import DocumentsDialog
        self.start_family()
        ana = self.person_named("Ana")
        letter = self.temp / "letter.pdf"
        letter.write_bytes(b"%PDF-1.4 old letter")
        stored = documents.store_document(letter, self.folder)
        dialog = DocumentsDialog(self.window, ana, self.folder)
        dialog.add_files([str(letter)])
        dialog.reject()
        dialog.deleteLater()
        self.assertTrue((self.folder / stored).is_file())

    def test_the_guide_is_one_window(self):
        for _ in range(5):
            self.window.show_guide()
            self.window.guide_dialog.close()
        from PySide6.QtWidgets import QDialog
        guides = [w for w in self.window.findChildren(QDialog) if w.windowTitle() == self.window.guide_dialog.windowTitle()]
        self.assertEqual(len(guides), 1)


class MergeTests(unittest.TestCase):
    def test_a_private_document_stays_private_whoever_is_kept(self):
        for keep, remove in (("a", "b"), ("b", "a")):
            tree = Tree({
                "a": Person("a", given="Ante", extra={"documents": [{"file": "media/docs/x.pdf", "title": "X"}]}),
                "b": Person("b", given="Ante", extra={"documents": [{"file": "media/docs/x.pdf", "title": "X",
                                                                      "private": True}]}),
            }, {})
            merge_people(tree, keep, remove)
            [document] = person_documents(tree.people[keep])
            self.assertTrue(document["private"], keep)


class PrivacyRuleTests(unittest.TestCase):
    def living(self, date):
        return privacy.counts_as_living(Person("p", given="P", birth={"date": date, "place": ""}), TODAY)

    def test_protection_lasts_until_the_hundredth_birthday(self):
        self.assertTrue(self.living("1926-12-01"))  # 99 until next month.
        self.assertFalse(self.living("1926-11-20"))
        self.assertTrue(self.living("1926"))  # Could be born on 31 December.
        self.assertFalse(self.living("1925"))

    def test_a_range_counts_from_its_latest_year(self):
        self.assertTrue(self.living("1920/1930"))

    def test_a_typed_face_name_of_a_hidden_person_is_not_shared(self):
        tree = Tree({
            "dead": Person("dead", given="Ante", living="no", photo="media/group.jpg"),
            "alive": Person("alive", given="Luka", living="yes"),
        }, {})
        tree.extra["faces"] = {"media/group.jpg": [{"rect": [0, 0, 0.5, 0.5], "person": "alive", "name": "Luka"},
                                                   {"rect": [0.5, 0, 0.5, 0.5], "person": "dead"}]}
        shared = privacy.shareable(tree, TODAY)
        [luka, ante] = face_links(shared)["media/group.jpg"]
        self.assertEqual(luka, {"rect": [0.0, 0.0, 0.5, 0.5]})
        self.assertEqual(ante["person"], "dead")


class MediaPathTests(unittest.TestCase):
    def test_a_media_folder_pointing_outside_the_tree_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root / "outside"
            outside.mkdir()
            (outside / "secret.png").write_bytes(b"x")
            folder = root / "T.tree"
            folder.mkdir()
            try:
                (folder / "media").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("this system can't make links")
            self.assertIsNone(resolve_photo(folder, "media/secret.png"))
            self.assertIsNone(documents.resolve_document(folder, "media/secret.png"))


class PhotoCacheTests(unittest.TestCase):
    def test_the_cache_keeps_to_its_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "media").mkdir()
            for number in range(6):
                image = QImage(200, 200, QImage.Format.Format_RGB32)
                image.fill(QColor("#336699"))
                image.save(str(folder / "media" / f"{number}.png"))
            clock = [0.0]
            cache = PhotoCache(limit=200 * 200 * 4 * 2, clock=lambda: clock[0])
            for number in range(6):  # One drawing needs all six: none is let go meanwhile.
                self.assertIsNotNone(cache.get(folder, f"media/{number}.png"))
            self.assertEqual(len(cache._loaded), 6)
            clock[0] = 60.0  # Later, two other pictures are looked at.
            cache.get(folder, "media/0.png")
            cache.get(folder, "media/1.png")
            self.assertLessEqual(cache._bytes, cache.limit)
            self.assertEqual(sorted(cache._loaded), ["media/0.png", "media/1.png"])


class DnaTotalsTests(unittest.TestCase):
    def test_totals_are_added_up_again_after_each_segment_import(self):
        test = dna.clean_test({"id": "t", "company": "Other", "kind": "autosomal"})
        dna.add_segments(test, [("Cousin", {"chr": "1", "start": 1_000_000, "end": 9_000_000, "cm": 8.0, "snps": 900})])
        dna.add_segments(test, [("Cousin", {"chr": "2", "start": 1_000_000, "end": 9_000_000, "cm": 12.0, "snps": 900})])
        [match] = test["matches"]
        self.assertEqual((match["cm"], match["segments"]), (20.0, 2))
        stored = dna.clean_test(json.loads(json.dumps(test)))  # Saved and read back.
        dna.add_segments(stored, [("Cousin", {"chr": "3", "start": 1_000_000, "end": 9_000_000, "cm": 5.0, "snps": 900})])
        self.assertEqual(stored["matches"][0]["cm"], 25.0)

    def test_a_companys_own_total_is_not_overwritten(self):
        test = dna.clean_test({"id": "t", "company": "Other", "kind": "autosomal"})
        dna.add_matches(test, [dna.clean_match({"name": "Cousin", "cm": 100.0, "segments": 5})])
        dna.add_segments(test, [("Cousin", {"chr": "1", "start": 1_000_000, "end": 9_000_000, "cm": 8.0, "snps": 900})])
        self.assertEqual(test["matches"][0]["cm"], 100.0)

    def test_raw_files_of_different_builds_are_not_compared(self):
        self.assertTrue(dna.comparable({"build": "37"}, {"build": "37"}))
        self.assertFalse(dna.comparable({"build": "37"}, {"build": "38"}))
        self.assertFalse(dna.comparable({"build": "36"}, {"build": "36"}))


class WebPageSpeedTests(unittest.TestCase):
    def test_one_index_is_shared_while_the_page_is_built(self):
        import model
        import webshare
        built = []
        real = model.TreeIndex.__init__

        def counting(self, tree):
            built.append(1)
            real(self, tree)

        model.TreeIndex.__init__ = counting
        self.addCleanup(setattr, model.TreeIndex, "__init__", real)
        webshare.site_data(sample_tree())
        self.assertEqual(len(built), 1)



class SecondRoundTests(WindowCase):
    """The review of 1.4.2 (22 November 2026)."""

    def test_a_backup_that_cannot_be_written_never_offers_to_roll_back(self):
        self.start_family()
        self.window.close_tree()
        import storage
        real = storage.make_backup

        def failing(*args, **kwargs):
            raise OSError("simulated backup failure")

        storage.make_backup = failing
        self.addCleanup(setattr, storage, "make_backup", real)
        before = (self.folder / "tree.json").read_text(encoding="utf-8")
        self.answers.confirms = []  # Any question would fail the test.
        self.assertTrue(self.window.open_path(self.folder))  # A full disk doesn't lock you out.
        self.assertEqual((self.folder / "tree.json").read_text(encoding="utf-8"), before)
        self.assertEqual(list(self.folder.glob("tree-damaged-*.json")), [])

    def test_an_uncertain_birth_never_becomes_a_death(self):
        path = self.temp / "d.ged"
        path.write_text("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Range /A/\n1 BIRT\n2 DATE BET 1910 AND 1940\n"
                        "0 @I2@ INDI\n1 NAME After /A/\n1 BIRT\n2 DATE AFT 1910\n"
                        "0 @I3@ INDI\n1 NAME Old /A/\n1 BIRT\n2 DATE 1850\n0 TRLR\n", encoding="utf-8")
        from gedcom import write_gedcom
        tree = read_gedcom(path, TODAY).tree
        people = {p.given: p for p in tree.people.values()}
        self.assertEqual((people["Range"].living, people["After"].living, people["Old"].living),
                         ("unknown", "unknown", "no"))
        self.assertEqual(write_gedcom(tree, path).count("1 DEAT"), 1)  # Only the one born in 1850.


    def family_with_two_letters(self):
        self.start_family()
        ivo = self.person_named("Ivo")
        ivo.living = "no"  # Shown in the copy, with his documents.
        ivo.death = {"date": "2000", "place": ""}
        letters = []
        for number in (1, 2):
            path = self.temp / f"letter{number}.pdf"
            path.write_bytes(b"%PDF-1.4 letter " + bytes([48 + number]))
            letters.append(str(path))
        self.window.attach_documents(ivo.id, letters)
        return ivo

    def test_an_interrupted_share_leaves_nothing_and_a_retry_works(self):
        self.family_with_two_letters()
        target = self.temp / "Shared.tree"
        real, calls = app_module.shutil.copy2, []

        def failing(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError("simulated write failure")
            return real(source, destination)

        app_module.shutil.copy2 = failing
        self.assertFalse(self.window.make_share_copy(target, hide=False))
        app_module.shutil.copy2 = real
        self.assertEqual(sorted(p.name for p in self.temp.iterdir() if "Shared" in p.name), [])
        self.assertTrue(self.window.make_share_copy(target, hide=False))
        shared = open_tree(target).tree
        files = [d["file"] for p in shared.people.values() for d in person_documents(p)]
        self.assertEqual(len(files), 2)
        self.assertTrue(all((target / f).is_file() for f in files))

    def test_a_missing_attachment_is_reported_and_left_out(self):
        ivo = self.family_with_two_letters()
        (self.folder / person_documents(ivo)[0]["file"]).unlink()
        target = self.temp / "Shared.tree"
        self.assertTrue(self.window.make_share_copy(target, hide=False))
        self.assertIn("couldn't find", self.answers.informed[-1])
        shared = open_tree(target).tree
        files = [d["file"] for p in shared.people.values() for d in person_documents(p)]
        self.assertEqual(len(files), 1)
        self.assertTrue((target / files[0]).is_file())

class SecondRoundDataTests(unittest.TestCase):
    def test_two_people_with_one_name_stay_two_matches(self):
        test = dna.clean_test({"id": "t", "company": "Other", "kind": "autosomal"})
        _kind, rows = dna.read_match_file(b"Name,Kit,Shared cM\nJohn Smith,A1,200\nJohn Smith,B2,45\n")
        dna.add_matches(test, rows)
        self.assertEqual(sorted(m["cm"] for m in test["matches"]), [45.0, 200.0])
        _kind, rows = dna.read_match_file(b"Name,Shared cM\nAna,20\nAna,30\n")  # No ids: both kept.
        other = dna.clean_test({"id": "u", "company": "Other", "kind": "autosomal"})
        dna.add_matches(other, rows)
        self.assertEqual(len(other["matches"]), 2)

    def test_amounts_in_either_number_style(self):
        self.assertEqual(dna._cm_value("1,234.5"), 1234.5)
        self.assertEqual(dna._cm_value("1.234,5"), 1234.5)
        self.assertEqual(dna._cm_value("12,5"), 12.5)

    def test_a_windows_file_reads_whatever_its_length(self):
        for text in ("Name,Shared cM\nRen\u00e9,50\n", "Name,Shared cM\nRen\u00e9,50 \n"):
            kind, rows = dna.read_match_file(text.encode("cp1252"))
            self.assertEqual((kind, rows[0]["name"]), ("matches", "Ren\u00e9"))

    def test_the_map_fits_across_the_180th_meridian(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from map_view import MapView
        view = MapView()
        view.resize(800, 600)
        view.fit([(0, 179), (0, -179)])
        xs = [view.screen_point(0, lon).x() for lon in (179, -179)]
        self.assertTrue(all(0 <= x <= 800 for x in xs), xs)
        self.assertLess(abs(xs[0] - xs[1]), 800)

    def test_children_are_listed_in_birth_order(self):
        import reports
        tree = Tree({
            "p": Person("p", given="Parent"),
            "later": Person("later", given="Later", birth={"date": "1900", "place": ""}),
            "none": Person("none", given="Undated"),
            "earlier": Person("earlier", given="Earlier", birth={"date": "abt 1870", "place": ""}),
        }, {})
        from model import Family
        tree.families["f"] = Family("f", ["p"], "married", [{"person": c, "link": "birth"} for c in ("later", "none", "earlier")])
        self.assertEqual(reports._children(tree, "p"), ["earlier", "later", "none"])

class NotesOnlyEditTests(WindowCase):
    def test_editing_only_the_notes_changes_only_the_notes(self):
        source = self.temp / "case.ged"
        source.write_text("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ella /Case/\n1 NAME Elena /Case/ Jr.\n"
                          "2 TYPE aka\n1 BIRT\n2 ADDR Harbor Street 12\n1 DEAT Y\n0 TRLR\n", encoding="utf-8")
        target = self.temp / "Case"
        self.assertTrue(self.window.import_gedcom(source, target))
        folder = self.temp / "Case.tree"
        self.assertTrue(self.window.open_path(folder))
        person = next(iter(self.window.tree.people.values()))
        before = json.loads((folder / "tree.json").read_text(encoding="utf-8"))["people"][person.id]
        self.assertEqual(before["birth"].get("address"), "Harbor Street 12")
        self.assertTrue(any(n.get("written") for n in before.get("names", [])), before)
        from dialogs import person_to_values
        values = person_to_values(person)
        values["notes"] = "One new note"
        self.window.ask_person = lambda *args, **kwargs: dict(values)
        self.window.run_action("edit", person.id)
        self.window.close_tree()
        after = open_tree(folder).tree.to_dict()["people"][person.id]
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        self.assertEqual(changed, {"notes"}, (before, after))

    def test_notes_ending_in_spaces_stay_as_imported(self):
        from edits import update_person
        from dialogs import person_to_values
        from model import Person, Tree
        tree = Tree({"p": Person("p", given="Robert", notes="He died in 1094. \n")}, {})
        update_person(tree, "p", person_to_values(tree.people["p"]))
        self.assertEqual(tree.people["p"].notes, "He died in 1094. \n")
        values = person_to_values(tree.people["p"])
        values["notes"] = "He died in 1095.  "
        update_person(tree, "p", values)
        self.assertEqual(tree.people["p"].notes, "He died in 1095.")

class ThirdRoundTests(WindowCase):
    """The recheck of 22 November 2026."""

    def export_pair(self):
        out = self.temp / "out"
        out.mkdir()
        letter = self.temp / "Before.pdf"
        letter.write_bytes(b"%PDF-1.4 before")
        stored = documents.store_document(letter, self.temp / "T.tree")
        tree = Tree({"a": Person("a", given="Ante", living="no", death={"date": "", "place": ""},
                                 extra={"documents": [{"file": stored, "title": "Before"}]})}, {})
        return out, tree

    def test_an_export_failing_after_the_file_was_replaced_restores_the_old_file(self):
        import exports
        out, tree = self.export_pair()
        exports.export_gedcom(tree, self.temp / "T.tree", out / "family.ged")
        before = (out / "family.ged").read_text(encoding="utf-8")
        after = self.temp / "After.pdf"
        after.write_bytes(b"%PDF-1.4 after")
        tree.people["a"].extra["documents"] = [{"file": documents.store_document(after, self.temp / "T.tree"),
                                                "title": "After"}]
        real = exports.atomic_write

        def replaced_then_failed(path, text):
            real(path, text)
            raise OSError("simulated sync failure")

        exports.atomic_write = replaced_then_failed
        self.addCleanup(setattr, exports, "atomic_write", real)
        with self.assertRaises(exports.ExportError):
            exports.export_gedcom(tree, self.temp / "T.tree", out / "family.ged")
        self.assertEqual((out / "family.ged").read_text(encoding="utf-8"), before)
        self.assertEqual([f.read_bytes() for f in (out / "family_media").iterdir() if f.suffix == ".pdf"],
                         [b"%PDF-1.4 before"])
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["family.ged", "family_media"])

    def test_folders_with_names_like_the_working_folders_are_left_alone(self):
        import exports
        out, tree = self.export_pair()
        for name in (".family_media.new", ".family_media.old", ".Shared.tree.partial"):
            (out / name).mkdir()
            (out / name / "keep.txt").write_text("mine")
        exports.export_gedcom(tree, self.temp / "T.tree", out / "family.ged")
        self.start_family()
        self.assertTrue(self.window.make_share_copy(out / "Shared.tree", hide=False))
        for name in (".family_media.new", ".family_media.old", ".Shared.tree.partial"):
            self.assertEqual((out / name / "keep.txt").read_text(), "mine")
        self.assertFalse([p for p in out.iterdir() if "-export-" in p.name or "-share-" in p.name])

    def test_a_missing_tree_file_offers_the_backups(self):
        self.start_family()
        names = sorted(p.given for p in self.window.tree.people.values())
        self.window.close_tree()
        from storage import make_backup
        make_backup(self.folder)
        (self.folder / "tree.json").rename(self.temp / "moved-aside.json")
        self.answers.confirms = [True]
        self.assertTrue(self.window.open_path(self.folder))
        self.assertEqual(sorted(p.given for p in self.window.tree.people.values()), names)

    def test_two_names_alike_keep_each_suffix(self):
        source = self.temp / "case.ged"
        source.write_text("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ella /Case/\n1 NAME Elena /Case/ Jr.\n2 TYPE aka\n"
                          "1 NAME Elena /Case/ III\n2 TYPE aka\n1 DEAT Y\n0 TRLR\n", encoding="utf-8")
        self.assertTrue(self.window.import_gedcom(source, self.temp / "Case"))
        folder = self.temp / "Case.tree"
        self.assertTrue(self.window.open_path(folder))
        person = next(iter(self.window.tree.people.values()))
        from dialogs import person_to_values
        values = person_to_values(person)
        values["notes"] = "One new note"
        self.window.ask_person = lambda *args, **kwargs: dict(values)
        self.window.run_action("edit", person.id)
        from gedcom import write_gedcom
        text = write_gedcom(open_tree(folder).tree, folder / "x.ged")
        self.assertIn("Elena /Case/ Jr.", text)
        self.assertIn("Elena /Case/ III", text)


class ThirdRoundDnaTests(unittest.TestCase):
    def test_a_segment_goes_to_the_kit_it_names(self):
        test = dna.clean_test({"id": "t", "company": "Other", "kind": "autosomal"})
        dna.add_matches(test, dna.read_match_file(b"Name,Kit,Shared cM\nAlex,A1,100\nAlex,B2,40\n")[1])
        kind, found = dna.read_match_file(b"Kit,Name,Chr,Start Location,End Location,Centimorgans,SNPs\n"
                                          b"A1,Alex,1,1000000,9000000,8.5,900\n")
        self.assertEqual(kind, "segments")
        dna.add_segments(test, found)
        a1 = next(m for m in test["matches"] if m["kit"] == "A1")
        self.assertEqual([s["match"] for s in test["segments"]], [a1["id"]])

    def test_reading_the_same_list_twice_changes_nothing(self):
        test = dna.clean_test({"id": "t", "company": "Other", "kind": "autosomal"})
        data = b"Name,Shared cM\nAna,20\nAna,30\n"
        dna.add_matches(test, dna.read_match_file(data)[1])
        before = sorted(m["cm"] for m in test["matches"])
        dna.add_matches(test, dna.read_match_file(data)[1])
        self.assertEqual(sorted(m["cm"] for m in test["matches"]), before)

class RecordKeepingTests(WindowCase):
    """Editing must never lose or move what the windows don't show (review of 22 November 2026)."""

    def load(self, tree):
        create_tree(self.folder, tree)
        self.assertTrue(self.window.open_path(self.folder))

    def import_record(self):
        path = self.temp / "historical.ged"
        path.write_text("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Test /Family/\n1 BIRT\n2 DATE 1890\n2 SOUR @S1@\n"
                        "3 PAGE 17\n3 DATA\n4 TEXT Transcribed birth entry\n0 @S1@ SOUR\n1 TITL Parish register\n"
                        "1 PUBL Town Press 1901\n1 ABBR PR1901\n0 TRLR\n", encoding="utf-8")
        self.assertTrue(self.window.import_gedcom(path, self.folder))
        self.assertTrue(self.window.open_path(self.folder))

    def emitted(self):
        from gedcom import write_gedcom
        return write_gedcom(open_tree(self.folder).tree, self.temp / "out.ged")

    def test_ok_in_sources_keeps_what_it_does_not_show(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        self.import_record()
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().accept())
        self.window.show_sources()
        after = self.emitted()
        self.assertIn("1 PUBL Town Press 1901", after)
        self.assertIn("1 ABBR PR1901", after)

    def test_correcting_a_page_keeps_the_transcription(self):
        from dialogs import person_to_values
        from facts_dialogs import CitationDialog, FactContext
        self.import_record()
        person = next(iter(self.window.tree.people.values()))

        def edit(*args, **kwargs):
            fields = person_to_values(person)
            dialog = CitationDialog(self.window, FactContext(self.window.tree), fields["birth_citations"][0])
            dialog.page.setText("18")
            fields["birth_citations"] = [dialog.values()]
            dialog.deleteLater()
            return fields

        self.window.ask_person = edit
        self.window.run_action("edit", person.id)
        after = self.emitted()
        self.assertIn("3 PAGE 18", after)
        self.assertIn("4 TEXT Transcribed birth entry", after)

    def test_merging_duplicate_spouses_keeps_the_marriage(self):
        from model import Family
        people = {k: Person(k, given=v) for k, v in (("a", "Ana"), ("d", "Anna"), ("b", "Ben"), ("w", "Witness"))}
        details = {"date": "1972", "place": "Harbor", "citations": [{"source": "s", "page": "22"}],
                   "people": [{"person": "w", "role": "witness"}]}
        self.load(Tree(people, {"f1": Family("f1", ["a", "b"], "married"),
                                "f2": Family("f2", ["d", "b"], "married", extra={"marriage": details})},
                       extra={"sources": {"s": {"title": "Register"}}}))
        self.answers.existing = ["d"]
        self.answers.confirms = [True]
        self.window.run_action("merge", "a")
        after = open_tree(self.folder).tree
        [family] = after.families.values()
        self.assertEqual(family.extra.get("marriage"), details)

    def test_a_new_partner_does_not_inherit_the_old_marriage(self):
        from model import Family, family_marriage
        people = {k: Person(k, given=v) for k, v in (("a", "Ana"), ("b", "Ben"), ("c", "Child"))}
        self.load(Tree(people, {"f1": Family("f1", ["a", "b"], "married", [{"person": "c", "link": "birth"}],
                                             {"marriage": {"date": "1972", "place": "Harbor"}})}))
        self.answers.confirms = [True]
        self.window.run_action("remove_partner", "a")
        self.answers.people = [{"given": "Chris"}]
        self.window.run_action("add_partner", "a")
        after = open_tree(self.folder).tree
        chris = next(p.id for p in after.people.values() if p.given == "Chris")
        couple = next(f for f in after.families.values() if chris in f.partners)
        self.assertFalse(family_marriage(couple).get("date"))
        self.assertNotIn("Harbor", self.emitted())
        self.window.undo()
        self.window.undo()
        self.assertEqual(family_marriage(open_tree(self.folder).tree.families["f1"])["date"], "1972")

    def test_renaming_a_place_onto_another_keeps_both_details(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        self.load(Tree({"p": Person("p", given="Ana", birth={"date": "1890", "place": "Trau"})}, {},
                       extra={"places": {"Trau": {"note": "local spelling"},
                                         "Trogir": {"lat": 43.5167, "lon": 16.25, "parent": "Dalmatia",
                                                    "old_names": [{"name": "Tragurium"}]}}}))

        def fill():
            dialog = QApplication.activeModalWidget()
            dialog.places.setCurrentRow(dialog.shown.index("Trau"))
            dialog.editor.name.setText("Trogir")
            dialog.editor.save.click()
            dialog.accept()

        QTimer.singleShot(0, fill)
        self.window.show_places()
        after = open_tree(self.folder).tree
        record = place_records(after)["Trogir"]
        self.assertEqual(after.people["p"].birth["place"], "Trogir")
        self.assertEqual((record["lat"], record["parent"], record["note"]), (43.5167, "Dalmatia", "local spelling"))
        self.assertIn({"name": "Tragurium"}, record["old_names"])


class RecipientTests(WindowCase):
    """The recipient-side review of 23 November 2026: what a shared copy or report shows."""

    def couple_tree(self):
        sources = {"r1": {"title": "Register", "author": "Parish of Trogir", "repository": "State Archive Split"},
                   "r2": {"title": "Register", "author": "Parish of Kaštela", "repository": "Diocesan Archive"},
                   "m": {"title": "Marriage ledger"}, "n": {"title": "Name ledger"}}
        ana = Person("a", given="Ana", surname="Đaković", birth_surname="Petrović",
                     birth={"date": "1950", "place": "Split", "citations": [{"source": "r1", "page": "12"},
                                                                         {"source": "r2", "page": "12"}]},
                     death={"date": "2010", "place": ""}, living="no",
                     extra={"names": [{"given": "Anna", "surname": "Petrovich", "type": "aka",
                                       "citations": [{"source": "n", "page": "3"}]}]})
        ben = Person("b", given="Ben", surname="Đaković", living="no", death={"date": "2011", "place": ""})
        family = Family("f", ["a", "b"], "divorced", [],
                        {"marriage": {"date": "1972", "place": "Harbor", "citations": [{"source": "m", "page": "7"}]}})
        return Tree({"a": ana, "b": ben}, {"f": family}, extra={"sources": sources})

    def test_after_a_date_counts_as_living(self):
        person = Person("p", given="Ana", birth={"date": "aft 1910", "place": ""})
        self.assertTrue(privacy.counts_as_living(person, datetime.date(2026, 11, 23)))
        person.birth = {"date": "1880/1890", "place": ""}
        self.assertFalse(privacy.counts_as_living(person, datetime.date(2026, 11, 23)))

    def test_report_file_name_does_not_show_a_hidden_name(self):
        create_tree(self.folder, Tree({"p": Person("p", given="Ana", surname="Šimić", living="yes")}, {}))
        self.assertTrue(self.window.open_path(self.folder))
        self.window.selected = "p"
        suggested = []
        self.window.ask_report = lambda name: {"kind": "family", "format": "pdf", "notes": True, "sources": True}
        self.window._hide_living_chosen = lambda: True
        self.window.ask_save_file = lambda title, path, file_filter="": suggested.append(Path(path).name)
        self.window.choose_report()
        self.assertNotIn("Ana", suggested[0])
        self.window._hide_living_chosen = lambda: False
        self.window.choose_report()
        self.assertIn("Ana", suggested[1])

    def test_two_registers_of_one_title_are_two_notes(self):
        page = reports.family_sheet(self.couple_tree(), "a")
        self.assertIn("[1, 2]", page)
        self.assertIn("State Archive Split", page)
        self.assertIn("Diocesan Archive", page)

    def test_a_divorce_is_shown(self):
        self.assertIn("Divorced", reports.family_sheet(self.couple_tree(), "a"))

    def test_web_page_finds_married_and_birth_names_with_any_letters(self):
        data = webshare.site_data(self.couple_tree(), "a")
        index = data["people"]["a"]["search"]
        for word in ("dakovic", "petrovic"):
            self.assertIn(word, index)
        page = self.temp / "page.html"
        webshare.single_file(page, data)
        script = page.read_text(encoding="utf-8").split("const FOLD = ", 1)[1]
        table = script.split(";", 1)[0]
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        code = (f"const FOLD = {table};" + "function fold(text) {" + script.split("function fold(text) {", 1)[1]
                .split("\n}", 1)[0] + "\n}" + "console.log(fold('Đaković') + ' ' + fold('Petrović'));")
        out = subprocess.run([node, "-e", code], capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(out, ["dakovic", "petrovic"])

    def test_web_page_lists_marriage_and_name_sources(self):
        cited = webshare.site_data(self.couple_tree(), "a")["people"]["a"]["sources"]
        self.assertTrue(any("Marriage ledger" in text for text in cited), cited)
        self.assertTrue(any("Name ledger" in text for text in cited), cited)
        self.assertTrue(any("Diocesan Archive" in text for text in cited), cited)

    def test_arabic_page_reads_right_to_left(self):
        import strings
        previous = strings.LANGUAGE
        self.addCleanup(setattr, strings, "LANGUAGE", previous)
        page = self.temp / "ar.html"
        strings.LANGUAGE = "ar"
        webshare.single_file(page, webshare.site_data(self.couple_tree(), "a"))
        self.assertIn('dir="rtl"', page.read_text(encoding="utf-8")[:300])
        strings.LANGUAGE = "en"
        webshare.single_file(page, webshare.site_data(self.couple_tree(), "a"))
        self.assertIn('dir="ltr"', page.read_text(encoding="utf-8")[:300])


class MapAndKinTests(WindowCase):
    """The map and kinship review of 23 November 2026."""

    def test_dna_follows_birth_links_only(self):
        import dna
        for link, expected in (("birth", "low"), ("adopted", "unrelated"), ("foster", "unrelated")):
            tree = Tree({"me": Person("me", given="Me"), "dad": Person("dad", given="Dad", sex="M")},
                        {"f": Family("f", ["dad"], "unknown", [{"person": "me", "link": link}])})
            self.assertEqual(dna.check(tree, "me", {"person": "dad", "cm": 30})[0], expected, link)
        # The family still counts the adoptive father as a father.
        import kinship
        self.assertEqual(kinship.relationship(tree, "me", "dad").kind, "blood")

    def test_siblings_without_known_parents_are_siblings(self):
        import kinship
        from edits import add_sibling
        tree = Tree({"ivo": Person("ivo", given="Ivo", sex="M")}, {})
        add_sibling(tree, "ivo", Person("mara", given="Mara", sex="F"))
        create_tree(self.folder, tree)
        tree = open_tree(self.folder).tree
        relation = kinship.relationship(tree, "ivo", "mara")
        self.assertEqual((relation.kind, relation.up, relation.down, relation.half), ("blood", 1, 1, False))
        self.assertEqual(relation.path, ["ivo", "mara"])
        self.assertIn("sister", kinship.describe(tree, "ivo", "mara")[0])
        tree.people["kid"] = Person("kid", given="Kid")
        tree.families["k"] = Family("k", ["mara"], "unknown", [{"person": "kid", "link": "birth"}])
        self.assertIn("niece", kinship.describe(tree, "ivo", "kid")[0])

    def test_clicking_past_the_date_line_gives_a_real_longitude(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from map_view import MapView
        view = MapView(lambda ready: None)
        view.resize(600, 400)
        view.zoom, view.centre = 6, (-17.0, 179.0)
        view.picking = True
        clicked = []
        view.point_clicked.connect(lambda lat, lon: clicked.append((lat, lon)))
        point = view.screen_point(-17.0, -179.0).toPoint()
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(point))
        self.assertAlmostEqual(clicked[0][1], -179.0, delta=0.05)

    def test_the_list_beside_the_map_follows_the_filter(self):
        from map_dialog import MapDialog
        tree = Tree({"p": Person("p", given="Ana", birth={"date": "1900", "place": "Trogir"},
                                 death={"date": "1980", "place": "Trogir"}, living="no")}, {},
                    extra={"places": {"Trogir": {"lat": 43.5167, "lon": 16.25}}})
        dialog = MapDialog(None, tree, "p")
        self.addCleanup(dialog.deleteLater)
        dialog.view.selected = "Trogir"
        dialog._marker_clicked("Trogir")
        self.assertEqual(dialog.events.count(), 2)
        dialog.show_kind.setCurrentIndex(dialog.show_kind.findData("birth"))
        self.assertEqual(dialog.events.count(), 1)
        dialog.show_kind.setCurrentIndex(dialog.show_kind.findData("marriage"))
        self.assertEqual(dialog.events.count(), 0)


class DocumentResearchTests(WindowCase):
    """The documents and research review of 23 November 2026."""

    relative_with_records = CombineKeepsEverythingTests.relative_with_records
    accept_suggestions = CombineKeepsEverythingTests.accept_suggestions

    def test_combine_keeps_two_registers_of_one_title_apart(self):
        mine = sample_tree()
        mine.extra["sources"] = {"s-n": {"title": "Parish Register", "author": "North parish",
                                         "repository": "North Archive"}}
        mine.people["ivana"].birth = {**(mine.people["ivana"].birth or {}), "citations": [
            {"source": "s-n", "page": "17"}]}
        create_tree(self.folder, mine)
        self.window.open_path(self.folder)
        relative, lucija = self.relative_with_records()
        theirs = json.loads((relative / "tree.json").read_text(encoding="utf-8"))
        theirs["sources"] = {"s-s": {"title": "Parish Register", "author": "South parish",
                                              "repository": "South Archive", "publication": "Split 1901"}}
        theirs["people"][lucija]["birth"]["citations"] = [{"source": "s-s", "page": "17"}]
        (relative / "tree.json").write_text(json.dumps(theirs), encoding="utf-8")
        self.accept_suggestions()
        self.assertTrue(self.window.combine_with(str(relative)))
        reopened = open_tree(self.folder).tree
        archives = {s["repository"] for s in tree_sources(reopened).values()}
        self.assertEqual(archives, {"North Archive", "South Archive"})
        lucija_now = next(p for p in reopened.people.values() if p.given == "Lucija")
        cited = reopened.extra["sources"][lucija_now.birth["citations"][0]["source"]]
        self.assertEqual((cited["repository"], cited.get("publication")), ("South Archive", "Split 1901"))
        ivana = reopened.extra["sources"][reopened.people["ivana"].birth["citations"][0]["source"]]
        self.assertEqual(ivana["repository"], "North Archive")

    def test_no_attached_message_after_a_failed_save(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        letter = self.temp / "letter.txt"
        letter.write_text("Dear Ada", encoding="utf-8")
        original = app_module.save_tree

        def full_disk(*args, **kwargs):
            raise OSError(28, "No space left on device")

        app_module.save_tree = full_disk
        self.addCleanup(setattr, app_module, "save_tree", original)
        self.assertFalse(self.window.attach_documents("ivana", [str(letter)]))
        message = self.window.statusBar().currentMessage()
        self.assertNotIn("letter", message.lower() + "")
        self.assertIn("No space left", message)
        app_module.save_tree = original
        self.window._save()
        self.assertEqual(len(person_documents(open_tree(self.folder).tree.people["ivana"])), 1)

    def test_several_dropped_files_are_all_attached(self):
        from PySide6.QtCore import QMimeData, QUrl
        from canvas import TreeView
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        files = []
        for name in ("one", "two", "three"):
            path = self.temp / f"{name}.txt"
            path.write_text(name, encoding="utf-8")
            files.append(path)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(f)) for f in files])
        dropped = TreeView.dropped_file(mime)
        self.assertEqual(len(dropped), 3)
        self.window.photo_dropped("ivana", dropped)
        stored = person_documents(open_tree(self.folder).tree.people["ivana"])
        self.assertEqual(sorted(d["title"] for d in stored), ["one", "three", "two"])
        single = QMimeData()
        single.setUrls([QUrl.fromLocalFile(str(files[0]))])
        self.assertEqual(Path(TreeView.dropped_file(single)), files[0])

    def test_unsourced_list_counts_an_address_or_a_cause(self):
        from facts_dialogs import unsourced_facts
        tree = Tree({"a": Person("a", given="Ada", birth={"date": "", "place": "", "address": "Harbor Street 12"},
                                 death={"date": "", "place": "", "cause": "fever"}, living="no"),
                     "b": Person("b", given="Bo", birth={"date": "1900", "place": ""})}, {})
        labels = [text for _person, text in unsourced_facts(tree)]
        self.assertEqual(len(labels), 3, labels)


class TreeFolderTests(WindowCase):
    """The tree-folder and recovery review of 23 November 2026."""

    def three_people_with_backup_only(self):
        """Ana, Ivo and Mia saved and backed up, then tree.json moved aside."""
        from storage import make_backup
        self.start_family()
        self.window.close_tree()
        make_backup(self.folder)
        (self.folder / "tree.json").rename(self.temp / "aside.json")

    def test_a_backup_that_cannot_be_opened_is_never_offered(self):
        import time as time_module
        from storage import list_backups
        self.three_people_with_backup_only()
        bad = self.folder / "backups" / f"backup-{time_module.strftime('%Y%m%d-%H%M%S')}-999999999"
        bad.mkdir()
        (bad / "tree.json").write_text('{"people": {}, "families": {}}', encoding="utf-8")  # No format version.
        self.assertEqual([count for _b, _w, count in list_backups(self.folder)][0], 3)  # Newest: all three.
        self.answers.confirms = [True]
        self.assertTrue(self.window.open_path(self.folder))
        self.assertEqual(len(self.window.tree.people), 3)

    def test_recovery_refuses_a_bad_backup_before_replacing_anything(self):
        from storage import TreeLoadError, recover_from_backup
        self.start_family()
        self.window.close_tree()
        before = (self.folder / "tree.json").read_bytes()
        bad = self.temp / "bad"
        bad.mkdir()
        (bad / "tree.json").write_text('{"people": {}}', encoding="utf-8")
        with self.assertRaises(TreeLoadError):
            recover_from_backup(self.folder, bad)
        self.assertEqual((self.folder / "tree.json").read_bytes(), before)
        self.assertEqual(list(self.folder.glob("tree-damaged-*.json")), [])

    def test_new_tree_over_a_recoverable_tree_opens_it_instead(self):
        from storage import list_backups
        self.three_people_with_backup_only()
        self.answers.confirms = [False]  # "A tree is already there, open it?" No.
        self.assertFalse(self.window.new_tree(self.temp / "Test"))
        self.assertFalse((self.folder / "tree.json").exists())
        self.assertEqual([count for _b, _w, count in list_backups(self.folder)][0], 3)  # Newest: all three.
        self.answers.confirms = [True, True]  # Open it: yes. Recover from the backup: yes.
        self.assertTrue(self.window.new_tree(self.temp / "Test"))
        self.assertEqual(len(self.window.tree.people), 3)

    def test_a_recoverable_tree_stays_on_the_usual_routes(self):
        from app import tree_folder_from
        self.three_people_with_backup_only()
        self.window.trees_folder = self.temp
        self.assertIn(self.folder, self.window.known_trees())  # The start page's cards.
        self.assertEqual(self.window.tree_to_reopen(), str(self.folder))
        self.window._fill_recent_menu()
        self.assertIn("Test", " ".join(a.text() for a in self.window.recent_menu.actions()))
        backup_file = next((self.folder / "backups").iterdir()) / "tree.json"
        self.assertEqual(tree_folder_from(backup_file), self.folder)
        self.assertEqual(tree_folder_from(self.folder / "tree.json"), self.folder)

    def test_no_new_folder_when_the_switch_is_cancelled(self):
        self.start_family()
        failing_save(self)
        self.answers.people = [{"given": "Late", "link": "birth"}]
        self.window.run_action("add_child", self.person_named("Ana").id)  # Not saved.
        self.answers.confirms = [False]  # Leave the unsaved tree? No.
        self.assertFalse(self.window.new_tree(self.temp / "Other"))
        self.assertFalse((self.temp / "Other.tree").exists())
        self.assertEqual(self.window.folder, self.folder)
        source = self.temp / "other.ged"
        source.write_text("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ada /Other/\n0 TRLR\n", encoding="utf-8")
        self.answers.confirms = [False]
        self.assertFalse(self.window.import_gedcom(source, self.temp / "Imported"))
        self.assertFalse((self.temp / "Imported.tree").exists())
        self.assertEqual(self.window.folder, self.folder)


class DateTests(WindowCase):
    """The date-handling review of 23 November 2026."""

    def test_a_range_of_exact_dates_keeps_its_days(self):
        source = self.temp / "range.ged"
        source.write_text("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ana /Range/\n1 BIRT\n"
                          "2 DATE BET 12 MAY 1880 AND 19 MAY 1880\n0 TRLR\n", encoding="utf-8")
        self.assertTrue(self.window.import_gedcom(source, self.temp / "Range"))
        self.window.close_tree()
        tree = open_tree(self.temp / "Range.tree").tree
        person = next(iter(tree.people.values()))
        self.assertEqual(person.birth_date, "1880-05-12/1880-05-19")
        from gedcom import write_gedcom
        self.assertIn("2 DATE BET 12 MAY 1880 AND 19 MAY 1880", write_gedcom(tree, self.temp / "out.ged"))
        from model import date_input_text, normalize_date_input
        self.assertEqual(normalize_date_input(date_input_text(person.birth_date)), person.birth_date)
        self.assertEqual(normalize_date_input("12.5.1880 - 19.5.1880"), "1880-05-12/1880-05-19")
        self.assertIsNone(normalize_date_input("19.5.1880 - 12.5.1880"))
        self.assertEqual(normalize_date_input("1880-1885"), "1880/1885")
        self.assertEqual(normalize_date_input("1921-05-14"), "1921-05-14")

    def test_every_stored_date_reads_back_unchanged_in_every_language(self):
        import strings
        from model import date_input_text
        from edits import typed_date
        previous = strings.LANGUAGE
        self.addCleanup(setattr, strings, "LANGUAGE", previous)
        stored = ["1921", "1921-05", "1921-05-14", "abt 1921", "bef 1900", "aft 1900", "1880/1885",
                  "1880-05-12/1880-05-19", "1708/09-02-10", "1708-02-10 julian", "abt 1708 julian",
                  "from 1950", "to 1960", "from 1950 to 1960", "from 1700 julian to 1710 julian",
                  "from 1700 julian to 1710", "from 1700 to 1710 julian"]
        for language in strings.STRINGS:
            strings.LANGUAGE = language
            for date in stored:
                self.assertEqual(typed_date(date_input_text(date), [date]), date, (language, date))

    def test_a_notes_only_edit_keeps_a_period_calendar(self):
        from dialogs import person_to_values
        from edits import update_person
        tree = Tree({"p": Person("p", given="Ana", extra={"events": [
            {"type": "residence", "date": "from 1700 to 1710 julian", "place": "Trogir"}]})}, {})
        values = person_to_values(tree.people["p"])
        values["notes"] = "One new note"
        update_person(tree, "p", values)
        self.assertEqual(tree.people["p"].extra["events"][0]["date"], "from 1700 to 1710 julian")

    def test_death_before_birth_only_when_it_cannot_be_right(self):
        from edits import EditError, clean_fields
        from model import date_warnings, died_before_born
        self.assertFalse(died_before_born("bef 1900", "1880"))
        self.assertTrue(died_before_born("1900-12-31", "1900-01-01"))
        self.assertFalse(died_before_born("1900", "1900"))
        self.assertFalse(died_before_born("1880/1890", "1885"))
        self.assertTrue(died_before_born("aft 1900", "1899"))
        clean_fields({"birth_date": "before 1900", "death_date": "1880", "living": "no"})
        with self.assertRaises(EditError):
            clean_fields({"birth_date": "31.12.1900", "death_date": "1.1.1900", "living": "no"})
        tree = Tree({"p": Person("p", given="Ana", birth={"date": "1900-12-31", "place": ""},
                                 death={"date": "1900-01-01", "place": ""}, living="no")}, {})
        self.assertTrue(date_warnings(tree, "p", datetime.date(2026, 11, 23)))

    def test_lifelines_keep_one_chart(self):
        from PySide6.QtWidgets import QApplication, QGraphicsScene
        from views_dialogs import LifelinesDialog
        from sample import sample_tree
        dialog = LifelinesDialog(self.window, sample_tree(), None, datetime.date(2026, 11, 23))
        self.addCleanup(dialog.deleteLater)
        for _ in range(20):
            dialog.history.toggle()
        from PySide6.QtCore import QEvent
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        scenes = [child for child in dialog.findChildren(QGraphicsScene)]
        self.assertEqual(len(scenes), 1)


class ViewsAndStartupTests(WindowCase):
    """The views and start-up review of 23 November 2026."""

    def test_a_damaged_portrait_never_stops_the_start_page(self):
        import start_cards
        tree = Tree({"p": Person("p", given="Mia", surname="Šimić", photo="media/broken.jpg")}, {})
        create_tree(self.folder, tree)
        (self.folder / "media" / "broken.jpg").write_bytes(b"\xff\xd8 not really a picture")
        self.assertTrue(self.window.open_path(self.folder))
        self.assertTrue(self.window.close_tree())  # Builds the start page with this tree's card.
        summary = start_cards.summarise(self.folder, "tree.json")
        self.assertEqual((summary.initials, summary.portrait), ("MŠ", None))
        fresh = self.make_window()  # A new start, with this tree among the recent ones.
        self.assertIsNone(fresh.tree)

    def test_nothing_of_one_tree_carries_over_to_the_next(self):
        create_tree(self.folder, Tree({"x": Person("x", given="Mia"), "y": Person("y", given="Ivo")}, {}))
        other = self.temp / "Other.tree"
        create_tree(other, Tree({"x": Person("x", given="Taylor"), "z": Person("z", given="Sam")}, {}))
        self.assertTrue(self.window.open_path(self.folder))
        self.window.search_box.setText("Mia")
        self.window._search_typed("Mia")
        self.window.path_ids = {"x", "y"}
        self.assertTrue(self.window.close_tree())
        self.assertTrue(self.window.open_path(other))
        self.assertEqual((self.window.search_box.text(), self.window.search_hits, self.window.path_ids), ("", {}, set()))
        before = self.window.selected
        self.window._search_enter()  # Enter in the now empty box goes nowhere.
        self.assertEqual(self.window.selected, before)

    def test_close_tree_lets_go_of_the_chart(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        create_tree(self.folder, sample_tree())
        self.assertTrue(self.window.open_path(self.folder))
        self.assertTrue(self.window.person_items)
        self.assertTrue(self.window.close_tree())
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        self.assertEqual(self.window.person_items, {})
        self.assertEqual(len(self.window.view.scene().items()), 0)

    def test_gallery_reads_a_shared_photo_once(self):
        from views_dialogs import GalleryDialog
        people = {f"p{n}": Person(f"p{n}", given=f"P{n}", extra={"documents": [
            {"file": "documents/group.jpg", "title": "Group", "kind": "photo", "date": ""}]}) for n in range(40)}
        reads = []

        def picture_for(stored):
            reads.append(stored)
            image = QImage(400, 300, QImage.Format.Format_RGB32)
            image.fill(QColor("#cde"))
            from PySide6.QtGui import QPixmap
            return QPixmap.fromImage(image)

        dialog = GalleryDialog(self.window, Tree(people, {}), picture_for)
        self.addCleanup(dialog.deleteLater)
        dialog.with_documents.setChecked(False)
        dialog.with_documents.setChecked(True)
        self.assertEqual(dialog.list.count(), 40)
        self.assertEqual(len(reads), 1)

    def test_a_range_ending_less_exactly_keeps_its_days(self):
        from gedcom import date_from_gedcom, date_to_gedcom
        stored = date_from_gedcom("BET 12 MAY 1880 AND MAY 1880")
        self.assertEqual(stored, "1880-05-12/1880-05")
        self.assertEqual(date_to_gedcom(stored), "BET 12 MAY 1880 AND MAY 1880")
        # What can't be held exactly is never cut to its years: notes, and the line kept.
        for text in ("BET 19 MAY 1880 AND 12 MAY 1880", "BET @#DJULIAN@ 1700 AND @#DJULIAN@ 1710"):
            self.assertIsNone(date_from_gedcom(text), text)
        source = self.temp / "late.ged"
        source.write_text("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ana /Range/\n1 BIRT\n"
                          "2 DATE BET 19 MAY 1880 AND 12 MAY 1880\n0 TRLR\n", encoding="utf-8")
        self.assertTrue(self.window.import_gedcom(source, self.temp / "Late"))
        from gedcom import write_gedcom
        self.assertIn("BET 19 MAY 1880 AND 12 MAY 1880", write_gedcom(self.window.tree, self.temp / "out.ged"))


class RecordWorkflowTests(WindowCase):
    """The record workflows review of 23 November 2026."""

    def test_deleting_a_partner_leaves_no_marriage_for_the_next(self):
        people = {k: Person(k, given=v) for k, v in (("ana", "Ana"), ("ivo", "Ivo"), ("mia", "Mia"))}
        create_tree(self.folder, Tree(people, {"f": Family("f", ["ana", "ivo"], "married", [
            {"person": "mia", "link": "birth"}], {"marriage": {"date": "1975", "place": "Chapel"}})}))
        self.assertTrue(self.window.open_path(self.folder))
        self.answers.confirms = [True]
        self.window.run_action("delete", "ivo")
        self.answers.people = [{"given": "Toni", "relationships": {None: "married"}}]
        self.window.run_action("add_partner", "ana")
        self.window.close_tree()
        tree = open_tree(self.folder).tree
        family = next(f for f in tree.families.values() if "ana" in f.partners)
        self.assertEqual(sorted(tree.people[p].given for p in family.partners), ["Ana", "Toni"])
        self.assertFalse(family.extra.get("marriage"))
        from gedcom import write_gedcom
        self.assertNotIn("Chapel", write_gedcom(tree, self.temp / "out.ged"))

    def test_segments_of_two_kits_never_join_one_name_only_match(self):
        test = dna.clean_test({"company": "FamilyTreeDNA"})
        dna.add_matches(test, [dna.clean_match({"name": "Ana Kovač", "cm": 50})])
        segment = {"chr": "1", "start": 1_000_000, "end": 20_000_000, "cm": 12.0, "snps": 900}
        dna.add_segments(test, [("Ana Kovač", dict(segment), "K1"), ("Ana Kovač", {**segment, "chr": "2"}, "K2")])
        anas = [m for m in test["matches"] if m["name"] == "Ana Kovač"]
        self.assertEqual(sorted(m.get("kit", "") for m in anas), ["K1", "K2"])
        for match in anas:
            self.assertEqual(len([s for s in test["segments"] if s["match"] == match["id"]]), 1)

    def test_combine_names_a_document_whose_file_is_missing(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        relative, lucija = CombineKeepsEverythingTests.relative_with_records(self)
        theirs = json.loads((relative / "tree.json").read_text(encoding="utf-8"))
        (relative / "media").mkdir(exist_ok=True)
        (relative / "media" / "letter.txt").write_text("Dear Lucija", encoding="utf-8")
        theirs["people"][lucija]["documents"] = [
            {"file": "media/letter.txt", "title": "Letter", "kind": "other", "date": ""},
            {"file": "media/interview.txt", "title": "Family interview", "kind": "other", "date": ""}]
        (relative / "tree.json").write_text(json.dumps(theirs), encoding="utf-8")
        CombineKeepsEverythingTests.accept_suggestions(self)
        self.assertTrue(self.window.combine_with(str(relative)))
        self.assertIn("Family interview", self.answers.informed[-1])
        reopened = open_tree(self.folder).tree
        lucija_now = next(p for p in reopened.people.values() if p.given == "Lucija")
        self.assertEqual([d["title"] for d in person_documents(lucija_now)], ["Letter"])

    def test_a_godparent_stays_a_godparent(self):
        from gedcom import read_gedcom, write_gedcom
        source = self.temp / "baptism.ged"
        source.write_text("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Child /A/\n1 BAPM\n2 DATE 1900\n"
                          "2 ASSO @I2@\n3 RELA Godparent\n0 @I2@ INDI\n1 NAME Marko /B/\n1 SEX M\n0 TRLR\n",
                          encoding="utf-8")
        tree = read_gedcom(source).tree
        child = next(p for p in tree.people.values() if p.given == "Child")
        event = child.extra["events"][0]
        self.assertEqual(event["people"][0]["role"], "godparent")
        written = write_gedcom(tree, self.temp / "out.ged")
        self.assertIn("RELA Godparent", written)
        self.assertNotIn("Godmother", written)


class EditingAndOutputTests(WindowCase):
    """Editing integrity, faces and printed outputs (own review, 24 November 2026)."""

    def open_tree(self, people, families=(), extra=None):
        create_tree(self.folder, Tree({p.id: p for p in people}, {f.id: f for f in families}, extra or {}))
        self.assertTrue(self.window.open_path(self.folder))
        return self.window

    def test_deleting_a_nameless_person_writes_no_translated_word(self):
        import strings
        strings.set_language("hr")
        self.addCleanup(strings.set_language, "en")
        w = self.open_tree([Person("dad", "Đuro", "Čačić", birth={"date": "1901", "place": ""}), Person("anon", "")])
        w.apply_edit(lambda: w.tree.people["dad"].birth.__setitem__("people", [{"role": "witness", "person": "anon"}]))
        self.answers.confirms = [True]
        w.run_action("delete", "anon")
        text = (self.folder / "tree.json").read_text(encoding="utf-8")
        self.assertNotIn("Nepoznato", text)

    def test_removed_or_reassigned_face_gives_no_portrait(self):
        from facts_dialogs import FactContext
        from faces_dialog import FacesDialog
        w = self.open_tree([Person("mum", "Željka"), Person("kid", "Lea")])
        chosen = ["mum"]
        context = FactContext(w.tree, find_person=lambda title: chosen[0])
        image = QImage(200, 100, QImage.Format.Format_RGB32)
        image.fill(QColor("#336699"))
        dialog = FacesDialog(w, image, [], context)
        self.addCleanup(dialog.deleteLater)
        dialog.add_face([0.1, 0.1, 0.2, 0.2])
        dialog.choose_person()
        dialog.use_as_portrait()
        dialog.remove_face()
        self.assertEqual(dialog.portraits, [])
        dialog.add_face([0.5, 0.1, 0.2, 0.2])
        dialog.choose_person()
        dialog.use_as_portrait()
        chosen[0] = "kid"
        dialog.choose_person()  # It was Lea after all: Željka's portrait must not be cut from her face.
        self.assertEqual(dialog.portraits, [])

    def test_very_large_photo_is_read_smaller(self):
        from photos import MAX_PIXELS, read_image
        path = self.temp / "huge.jpg"
        image = QImage(12000, 9000, QImage.Format.Format_RGB32)
        image.fill(QColor("#336699"))
        self.assertTrue(image.save(str(path), "JPEG", 50))
        del image
        read = read_image(path)
        self.assertLessEqual(read.width() * read.height(), MAX_PIXELS)
        self.assertAlmostEqual(read.width() / read.height(), 12000 / 9000, places=2)

    def test_picture_that_cannot_be_read_is_kept_as_a_document(self):
        w = self.open_tree([Person("ana", "Ana")])
        heic = self.temp / "b.heic"
        heic.write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100)
        w.photo_dropped("ana", str(heic))
        self.assertEqual(self.answers.alerts, [])
        self.assertEqual([d["title"] for d in person_documents(w.tree.people["ana"])], ["b"])

    def test_report_index_of_a_nameless_person(self):
        tree = Tree({"a": Person("a", "Ana", "Šimić"), "b": Person("b", ""), "c": Person("c", "Ivo")},
                    {"f": Family("f", ["a"], children=[{"person": "b"}, {"person": "c"}])})
        book = reports._Book(tree)
        for pid in ("a", "b", "c"):
            book.numbers[pid] = len(book.numbers) + 1
        html = book.endings()
        self.assertNotIn("<td>, ", html)
        self.assertNotIn(", </td>", html)
        self.assertIn("<td>Ivo</td>", html)

    def test_merge_keeps_both_portraits_and_writes_no_words(self):
        import strings
        strings.set_language("hr")
        self.addCleanup(strings.set_language, "en")
        tree = Tree({"a": Person("a", "Ana", birth={"date": "1935", "place": ""}, photo="media/a.jpg"),
                     "b": Person("b", "Ana", birth={"date": "1936", "place": ""}, photo="media/b.jpg")}, {})
        merge_people(tree, "a", "b")
        ana = tree.people["a"]
        self.assertEqual(ana.photo, "media/a.jpg")
        self.assertIn("media/b.jpg", [d["file"] for d in person_documents(ana)])
        self.assertIn("1936", ana.notes)
        self.assertNotIn("Rođen", ana.notes)

    def test_places_merge_keeps_the_place_renamed_onto(self):
        from dialogs import PlacesDialog
        from model import all_facts
        w = self.open_tree([Person("z", "Davor", birth={"date": "1901", "place": "Trau"})], extra={"places": {
            "Trogir": {"kind": "town", "lat": 43.5167, "lon": 16.2511, "note": "Grad na otočiću"},
            "Trau": {"kind": "other", "lat": 45.0, "lon": 15.0, "note": "Talijanski naziv"}}})
        dialog = PlacesDialog(w, w.tree, all_facts(w.tree))
        self.addCleanup(dialog.deleteLater)
        dialog.places.setCurrentRow(dialog.shown.index("Trau"))
        dialog.editor.name.setText("Trogir")
        dialog.editor.save.click()
        ops = dialog.operations
        w.ask_places = lambda rows: (None, ops)
        w.show_places()
        record = place_records(w.tree)["Trogir"]
        self.assertEqual((record["kind"], record["lat"], record["lon"]), ("town", 43.5167, 16.2511))
        self.assertIn("Grad na otočiću", record["note"])
        self.assertIn("Talijanski naziv", record["note"])

    def test_refused_place_rename_leaves_nothing_behind(self):
        from dialogs import PlacesDialog
        from model import all_facts
        w = self.open_tree([Person("y", "Nada", birth={"date": "1905", "place": "Seget"})], extra={"places": {
            "Seget Donji": {"parent": "Seget"}, "Seget": {"kind": "municipality"}}})
        dialog = PlacesDialog(w, w.tree, all_facts(w.tree))
        self.addCleanup(dialog.deleteLater)
        dialog.places.setCurrentRow(dialog.shown.index("Seget"))
        dialog.editor.name.setText("Općina Seget")
        dialog.editor.parent_place.setCurrentText("Seget Donji")
        dialog.editor.save.click()
        self.assertTrue(dialog.editor.problem.text())
        dialog.places.setCurrentRow(dialog.shown.index("Seget Donji"))
        dialog.editor.save.click()
        self.assertEqual(sorted(dialog.shown), ["Seget", "Seget Donji"])
        self.assertFalse(any(op[0] == "rename" for op in dialog.operations))

    def test_merge_brings_parentless_brothers_and_sisters_along(self):
        tree = Tree({i: Person(i, n) for i, n in (("ana", "Ana"), ("marko", "Marko"), ("ana2", "Ana"),
                                                     ("ivan", "Ivan"), ("kata", "Kata"))},
                    {"f0": Family("f0", [], children=[{"person": "ana"}, {"person": "marko"}]),
                     "f1": Family("f1", ["ivan", "kata"], children=[{"person": "ana2"}])})
        merge_people(tree, "ana", "ana2")
        self.assertEqual(set(tree.birth_family_of("marko").partners), {"ivan", "kata"})
        self.assertIs(tree.birth_family_of("marko"), tree.birth_family_of("ana"))

    def test_connecting_both_parents_of_a_known_couple_makes_no_second_family(self):
        import edits
        tree = Tree({i: Person(i, i) for i in ("kata", "pero", "lea", "mia")},
                    {"f": Family("f", ["kata", "pero"], "married", [{"person": "lea"}],
                                 {"marriage": {"date": "1980", "place": "Sinj"}})})
        edits.link_parent(tree, "mia", "kata")
        edits.link_parent(tree, "mia", "pero")
        couples = [f for f in tree.families.values() if set(f.partners) == {"kata", "pero"}]
        self.assertEqual(len(couples), 1)
        self.assertEqual(set(couples[0].child_ids), {"lea", "mia"})

    def test_a_long_unbroken_note_keeps_the_panel_buttons_in_view(self):
        w = self.open_tree([Person("ana", "Ana", notes="https://example.org/" + "x" * 300)])
        w.select("ana")  # The program's own checks, run when the test ends, find a cut-off button.

    def test_merging_couple_records_keeps_the_divorce(self):
        tree = Tree({i: Person(i, n) for i, n in (("ana", "Ana"), ("ivo", "Ivo"), ("ivo2", "Ivo"))},
                    {"f1": Family("f1", ["ana", "ivo"], "married"),
                     "f2": Family("f2", ["ana", "ivo2"], "divorced")})
        merge_people(tree, "ivo", "ivo2")
        self.assertEqual([f.relationship for f in tree.families.values()], ["divorced"])


class GedcomFidelityTests(unittest.TestCase):
    """Files from other programs (own review, 24 November 2026): what the user typed
    there comes back out of an export, in the same place."""
    HEAD = "0 HEAD\n1 SOUR Other\n1 GEDC\n2 VERS 5.5.1\n1 CHAR UTF-8\n"

    def export(self, body):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp, True)
        source = temp / "in.ged"
        source.write_text(self.HEAD + body + "0 TRLR\n", encoding="utf-8")
        tree = read_gedcom(source, today=TODAY).tree
        # As the window exports: through the shared copy, nobody hidden.
        from gedcom import write_gedcom
        return tree, write_gedcom(privacy.shareable(tree, TODAY, hide_living=False), temp / "out.ged", today=TODAY)

    def test_shared_notes_on_events_families_and_sources_go_out(self):
        tree, text = self.export(
            "0 @I1@ INDI\n1 NAME Ana /Kovač/\n1 RESI\n2 NOTE @N2@\n1 FAMS @F1@\n"
            "1 BIRT\n2 SOUR @S1@\n"
            "0 @F1@ FAM\n1 WIFE @I1@\n1 NOTE @N1@\n"
            "0 @S1@ SOUR\n1 TITL Register\n1 NOTE @N3@\n"
            "0 @N1@ NOTE The couple lived in Split\n0 @N2@ NOTE Residence note\n"
            "0 @N3@ NOTE Held at the parish office\n0 @N9@ NOTE Loose note nobody points to\n")
        for words in ("The couple lived in Split", "Residence note", "Held at the parish office"):
            self.assertIn(words, text)
        self.assertNotIn("@@", text)
        self.assertNotIn("Loose note nobody points to", text)  # Still stays home.
        self.assertNotIn("@N2@", json.dumps(tree.people[next(iter(tree.people))].extra.get("events")))

    def test_nicknames_family_link_kinds_and_archives_survive(self):
        _tree, text = self.export(
            "0 @I1@ INDI\n1 NAME Robert /Smith/\n1 NAME Robert /Smith/\n2 TYPE aka\n2 NICK Bob\n"
            "1 FAMC @F1@\n2 PEDI step\n"
            "0 @F1@ FAM\n1 CHIL @I1@\n"
            "0 @R2@ REPO\n1 NAME Unused Archive\n1 ADDR Split\n")
        self.assertIn("2 NICK Bob", text)
        self.assertIn("2 PEDI step", text)
        self.assertIn("1 NAME Unused Archive", text)

    def test_coordinates_in_degrees_and_minutes_and_full_precision(self):
        tree, text = self.export(
            "0 @I1@ INDI\n1 NAME Ana //\n1 EDUC University\n2 PLAC Graz\n3 MAP\n4 LATI N47°04'\n4 LONG E15°26'\n"
            "1 RESI\n2 PLAC Split\n3 MAP\n4 LATI N43.508133\n4 LONG E16.440193\n"
            "1 RELI Catholic\n2 PLAC Split\n3 MAP\n4 LATI N43.0\n4 LONG E16.0\n")
        self.assertAlmostEqual(place_records(tree)["Graz"]["lat"], 47 + 4 / 60)
        self.assertEqual(place_records(tree)["Split"]["lat"], 43.508133)  # The first given is kept.
        self.assertIn("4 LATI N43.508133", text)

    def test_details_stay_with_their_own_name_and_family(self):
        _tree, text = self.export(
            "0 @I1@ INDI\n1 NAME Ana /Kovač/\n"
            "1 NAME Annie /Hart/\n2 TYPE aka\n2 _ALIASNOTE Used in America\n"
            "1 NAME Ana /Horvat/\n2 TYPE married\n2 _MARRNOTE From 1920\n"
            "1 FAMC @F2@\n2 PEDI adopted\n2 _PRIMARY Y\n1 FAMC @F1@\n2 PEDI birth\n2 NOTE Natural father\n"
            "0 @F1@ FAM\n1 CHIL @I1@\n0 @F2@ FAM\n1 CHIL @I1@\n")
        self.assertRegex(text, r"1 NAME Annie /Hart/\n(?:2 (?!_MARRNOTE).*\n)*2 _ALIASNOTE Used in America")
        self.assertRegex(text, r"1 NAME Ana /Horvat/\n(?:2 (?!_ALIASNOTE).*\n)*2 _MARRNOTE From 1920")
        self.assertRegex(text, r"2 PEDI adopted\n2 _PRIMARY Y")
        self.assertRegex(text, r"2 PEDI birth\n2 NOTE Natural father")

    def test_long_event_text_is_split_into_short_lines(self):
        _tree, text = self.export("0 @I1@ INDI\n1 NAME Ana //\n1 OCCU " + "word " * 40 + "\n2 CONC " + "more " * 30 + "\n")
        self.assertTrue(all(len(line) <= 255 for line in text.splitlines()))
        self.assertIn("more more", text.replace("\n2 CONC ", ""))


def _line_groups(layout):
    from PySide6.QtCore import QPointF, QRectF
    def components(layout):
        """Connected groups of lines, and the people whose cards each group touches."""
        m = layout.metrics
        segs = [tuple(s) for s in layout.lines]
        parent = list(range(len(segs)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def on(seg, pt):
            x1, y1, x2, y2 = seg
            x, y = pt
            if abs(y1 - y2) < 0.5:
                return abs(y - y1) < 0.6 and min(x1, x2) - 0.6 <= x <= max(x1, x2) + 0.6
            if abs(x1 - x2) < 0.5:
                return abs(x - x1) < 0.6 and min(y1, y2) - 0.6 <= y <= max(y1, y2) + 0.6
            return False

        for i, a in enumerate(segs):
            for j, b in enumerate(segs):
                if i < j and (on(b, a[:2]) or on(b, a[2:]) or on(a, b[:2]) or on(a, b[2:])):
                    parent[find(i)] = find(j)
        boxes = [(c.person_id, QRectF(c.x - 3, c.y - 3, m.card_w + 6, m.card_h + m.label_h + 6)) for c in layout.cards]
        groups = {}
        for i, s in enumerate(segs):
            g = groups.setdefault(find(i), set())
            for pt in (s[:2], s[2:]):
                for pid, box in boxes:
                    if box.contains(QPointF(*pt)):
                        g.add(pid)
        return [g for g in groups.values() if g]


    def wrong_groups(tree, layout):
        """Line groups that join people who are not all members of one family."""
        fams = [set(f.partners) | set(f.child_ids) for f in tree.families.values()]
        return [g for g in components(layout) if len(g) > 1 and not any(g <= fam for fam in fams)]


    return components(layout)


def _wrong_line_groups(tree, layout):
    """Line groups joining people who are not all of one family: a child drawn as the
    child of the wrong couple, or two couples' children on one bar."""
    families = [set(f.partners) | set(f.child_ids) for f in tree.families.values()]
    return [g for g in _line_groups(layout) if len(g) > 1 and not any(g <= f for f in families)]


class ChartAndKinTests(WindowCase):
    """Charts and relations on unusual families (own review, 24 November 2026)."""

    def show(self, people, families, chart, house):
        create_tree(self.folder, Tree({p.id: p for p in people}, {f.id: f for f in families}))
        self.assertTrue(self.window.open_path(self.folder))
        self.window.chart, self.window.house = chart, house
        self.window.refresh(keep_view=False)
        return self.window._layout_for(self.window.tree)

    def test_married_cousins_hang_from_their_own_parents(self):
        people = [Person(i, i) for i in ("ga", "gb", "petar", "pavla", "xena", "xaver", "cvito", "cvita", "kid", "sib")]
        families = [Family("f1", ["ga", "gb"], "married", [{"person": "petar"}, {"person": "pavla"}]),
                    Family("f2", ["petar", "xena"], "married", [{"person": "cvito"}]),
                    Family("f3", ["xaver", "pavla"], "married", [{"person": "cvita"}]),
                    Family("f4", ["cvito", "cvita"], "married", [{"person": "kid"}, {"person": "sib"}])]
        layout = self.show(people, families, "family", "kid")
        self.assertEqual(_wrong_line_groups(self.window.tree, layout), [])

    def test_children_of_four_partners_have_bars_of_their_own(self):
        people = [Person("adam", "Adam", sex="M")]
        families = []
        for n in range(1, 5):
            people.append(Person(f"w{n}", f"Wife{n}", sex="F"))
            kids = [f"k{n}{k}" for k in range(1, 4)]
            people += [Person(k, k) for k in kids]
            families.append(Family(f"f{n}", ["adam", f"w{n}"], "married", [{"person": k} for k in kids]))
        layout = self.show(people, families, "pyramid", "adam")
        self.assertEqual(_wrong_line_groups(self.window.tree, layout), [])
        self.window.card_style = "names"  # The smallest cards: the least room between the rows.
        self.window.refresh(keep_view=False)
        self.assertEqual(_wrong_line_groups(self.window.tree, self.window._layout_for(self.window.tree)), [])

    def test_parents_recorded_twice_are_found_whatever_the_file_order(self):
        import kinship
        tree = Tree({i: Person(i, i, sex="M" if i in ("dad", "bro") else "") for i in ("mum", "dad", "kid", "bro")},
                    {"f1": Family("f1", ["mum"], children=[{"person": "kid", "link": "unknown"}]),
                     "f2": Family("f2", ["dad", "mum"], children=[{"person": "kid", "link": "unknown"},
                                                                    {"person": "bro"}])})
        self.assertEqual(set(tree.birth_family_of("kid").partners), {"dad", "mum"})
        self.assertEqual(kinship.describe(tree, "kid", "dad", "en", lambda k, **kw: k)[0], "father")

    def test_adopted_child_is_related_to_the_adoptive_family(self):
        import kinship
        tree = Tree({i: Person(i, i, sex="M" if "dad" in i or i == "sib" else "F")
                     for i in ("bdad", "bmum", "adad", "amum", "child", "sib", "agran")},
                    {"b": Family("b", ["bdad", "bmum"], children=[{"person": "child", "link": "birth"}]),
                     "a": Family("a", ["adad", "amum"], children=[{"person": "child", "link": "adopted"},
                                                                  {"person": "sib", "link": "birth"}]),
                     "g": Family("g", ["agran"], children=[{"person": "adad"}])})
        words = lambda b: kinship.describe(tree, "child", b, "en", lambda k, **kw: k)[0]  # noqa: E731
        self.assertEqual(words("amum"), "mother")
        self.assertEqual(words("sib"), "brother")
        self.assertIn("grandmother", words("agran"))
        self.assertEqual(words("bmum"), "mother")
        # DNA still counts only the birth family.
        self.assertIsNone(kinship.blood_relation(tree, "child", "amum", biological=True))

    def test_unrelated_people_get_a_sentence_that_reads(self):
        create_tree(self.folder, Tree({"a": Person("a", "Ana"), "b": Person("b", "Ivo")}, {}))
        self.assertTrue(self.window.open_path(self.folder))
        self.window.select("a")
        self.answers.existing = ["b"]
        self.window.find_relationship()
        self.assertEqual(self.answers.informed[-1], "Ana and Ivo are not related through the recorded links.")


class CombineTests(unittest.TestCase):
    """Combining a relative's tree (own review, 24 November 2026)."""

    def run_combine(self, mine, theirs, matches, take=None):
        import combine
        return combine.combine(mine, theirs, matches, take or {}).tree

    def test_choosing_theirs_keeps_yours_in_the_notes(self):
        mine = Tree({"i": Person("i", "Ivan", "Šimić", birth={"date": "1920", "place": "Sinj"})}, {})
        theirs = Tree({"t": Person("t", "Ivan", "Schimitsch", birth={"date": "1920-03-12", "place": "Glavice"})}, {})
        ivan = self.run_combine(mine, theirs, {"t": "i"}, {"t": {"surname", "birth.date", "birth.place"}}).people["i"]
        self.assertEqual((ivan.surname, ivan.birth["date"], ivan.birth["place"]), ("Schimitsch", "1920-03-12", "Glavice"))
        self.assertIn("Šimić", [n["surname"] for n in ivan.extra.get("names", [])])
        self.assertIn("1920", ivan.notes)
        self.assertIn("Sinj", ivan.notes)

    def test_a_choice_for_an_earlier_match_is_not_applied(self):
        mine = Tree({"k1": Person("k1", "Kata", "Kovač"), "k2": Person("k2", "Kata", "Šimić")}, {})
        theirs = Tree({"a": Person("a", "Kata", "Simic")}, {})
        kata = self.run_combine(mine, theirs, {"a": "k2"}, {"a": {"surname"}}).people["k2"]
        self.assertEqual(kata.surname, "Šimić")

    def test_combining_the_same_tree_twice_adds_nothing_twice(self):
        mine = Tree({"i": Person("i", "Ivan", "Šimić", birth={"date": "1920", "place": ""})}, {})
        theirs = Tree({"t": Person("t", "Ivan", "Šimić", birth={"date": "1921", "place": ""}, notes="Bio je kovač.",
                                   extra={"events": [{"type": "residence", "date": "1950", "place": "Trogir",
                                                      "citations": [{"source": "s0"}]}]})},
                      {}, {"sources": {"s0": {"title": "", "note": "usmeno"}}})
        once = self.run_combine(mine, theirs, {"t": "i"})
        twice = self.run_combine(once, theirs, {"t": "i"})
        ivan = twice.people["i"]
        self.assertEqual(ivan.notes.count("Bio je kovač."), 1)
        self.assertEqual(ivan.notes.count("1921"), 1)
        self.assertEqual(len(ivan.extra["events"]), 1)
        self.assertEqual(len(tree_sources(twice)), 1)

    def test_a_different_birth_surname_is_kept_as_a_birth_name(self):
        mine = Tree({"m": Person("m", "Mara", "Šimić", "Kovač")}, {})
        theirs = Tree({"t": Person("t", "Mara", "Šimić", "Kovačević")}, {})
        mara = self.run_combine(mine, theirs, {"t": "m"}).people["m"]
        self.assertEqual(mara.birth_surname, "Kovač")
        self.assertIn({"given": "Mara", "surname": "Kovačević", "type": "birth"}, mara.extra.get("names", []))

    def test_a_matching_source_brings_its_details(self):
        mine = Tree({"i": Person("i", "Ivan", birth={"date": "", "place": "", "citations": [{"source": "s1"}]})}, {},
                    {"sources": {"s1": {"title": "Matica rođenih Sinj", "author": "Župa Sinj"}}})
        theirs = Tree({"t": Person("t", "Ivan", birth={"date": "", "place": "", "citations": [{"source": "x"}]})}, {},
                      {"sources": {"x": {"title": "Matica rođenih Sinj", "author": "Župa Sinj",
                                         "note": "Svezak 3", "publication": "mikrofilm HDA 1234"}}})
        source = self.run_combine(mine, theirs, {"t": "i"}).extra["sources"]["s1"]
        self.assertEqual((source["note"], source["publication"]), ("Svezak 3", "mikrofilm HDA 1234"))

    def test_their_different_wedding_is_kept_in_the_notes(self):
        mine = Tree({"i": Person("i", "Ivan"), "m": Person("m", "Mara")},
                    {"f": Family("f", ["i", "m"], "married", extra={"marriage": {"date": "1948", "place": "Split"}})})
        theirs = Tree({"a": Person("a", "Ivan"), "b": Person("b", "Mara")},
                      {"g": Family("g", ["a", "b"], "married", extra={"marriage": {"date": "1947", "place": "Sinj"}})})
        tree = self.run_combine(mine, theirs, {"a": "i", "b": "m"})
        self.assertEqual(family_marriage_of(tree)["date"], "1948")
        notes = tree.people["i"].notes + tree.people["m"].notes
        self.assertIn("1947", notes)
        self.assertIn("Sinj", notes)

    def test_a_hidden_placeholder_matched_to_the_real_person_is_not_hidden(self):
        mine = Tree({"h": Person("h", "", "Šimić", living="yes", extra={"hidden": True})}, {})
        theirs = Tree({"t": Person("t", "Petra", "Šimić", birth={"date": "1985", "place": "Zagreb"}, living="yes")}, {})
        petra = self.run_combine(mine, theirs, {"t": "h"}).people["h"]
        self.assertFalse(petra.extra.get("hidden"))
        self.assertEqual(petra.display_name, "Petra Šimić")


def family_marriage_of(tree):
    from model import family_marriage
    return family_marriage(next(iter(tree.families.values())))


class KeptDetailsFollowTheirFactTests(unittest.TestCase):
    """Lines kept from another program's file stay with their own event, citation or
    source through edits (own review, 24 November 2026)."""
    FILE = ("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ivan /Šimić/\n"
            "1 BIRT\n2 DATE 1880\n2 SOUR @S1@\n3 PAGE str. 47\n3 QUAY 0\n2 SOUR @S2@\n3 PAGE fol. 12\n"
            "1 OCCU ribar\n2 DATE 1910\n2 AGNC Lučka kapetanija\n1 OCCU brodograditelj\n2 DATE 1925\n"
            "1 SOUR @S3@\n2 PAGE upisnik 4\n"
            "0 @S1@ SOUR\n1 TITL Matica\n0 @S2@ SOUR\n1 TITL Prijepis\n0 @S3@ SOUR\n1 TITL Popis 1931\n0 TRLR\n")

    def setUp(self):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp, True)
        (temp / "in.ged").write_text(self.FILE, encoding="utf-8")
        self.tree = read_gedcom(temp / "in.ged", today=TODAY).tree
        self.ivan = next(iter(self.tree.people.values()))
        self.out = temp / "out.ged"

    def export(self):
        from gedcom import write_gedcom
        return write_gedcom(privacy.shareable(self.tree, TODAY, hide_living=False), self.out, today=TODAY)

    def test_deleting_an_event_takes_its_kept_lines_along(self):
        self.ivan.extra["events"] = [e for e in self.ivan.extra["events"] if e.get("text") != "ribar"]
        text = self.export()
        self.assertNotIn("Lučka kapetanija", text)
        self.assertNotIn("_FT_REF", text)

    def test_kept_lines_stay_with_their_event_through_an_edit(self):
        from edits import clean_events
        from model import person_events
        events = person_events(self.ivan)
        events[0]["place"] = "Kaštel Stari"
        self.ivan.extra["events"] = clean_events(events)
        self.assertRegex(self.export(), r"1 OCCU ribar\n(?:2 .*\n)*2 AGNC Lučka kapetanija")

    def test_removing_a_citation_takes_its_kept_quality_along(self):
        self.ivan.birth["citations"] = self.ivan.birth["citations"][1:]
        text = self.export()
        self.assertNotIn("QUAY 0", text)
        self.assertNotRegex(text, r"\n2 SOUR\n")

    def test_a_quality_set_since_replaces_the_kept_one(self):
        self.ivan.birth["citations"][0]["quality"] = "original"
        text = self.export()
        self.assertIn("3 QUAY 3", text)
        self.assertNotIn("QUAY 0", text)

    def test_a_citation_kept_as_written_counts_and_moves_with_a_merge(self):
        import edits
        from model import cited_sources
        popis = next(k for k, v in tree_sources(self.tree).items() if v["title"] == "Popis 1931")
        matica = next(k for k, v in tree_sources(self.tree).items() if v["title"] == "Matica")
        self.assertEqual(cited_sources(self.tree).get(popis), 1)
        self.assertIn("upisnik 4", self.export())
        sources = {k: v for k, v in tree_sources(self.tree).items() if k != popis}
        edits.set_sources(self.tree, sources, merged={popis: matica}, removed={popis})
        self.assertRegex(self.export(), r"1 SOUR @S\d+@\n2 PAGE upisnik 4")

    def test_a_story_keeps_the_indent_of_its_first_line(self):
        from model import person_story
        self.ivan.extra["story"] = "    Djed je bio ribar.\n\n    Kasnije brodograditelj."
        self.assertTrue(person_story(self.ivan).startswith("    Djed"))


class CheckingToolsTests(unittest.TestCase):
    """Check dates, statistics, timeline and places lists (own review, 24 November 2026)."""

    def warnings(self, people, families=()):
        from model import date_warnings
        tree = Tree({p.id: p for p in people}, {f.id: f for f in families})
        return [w for pid in tree.people for w in date_warnings(tree, pid, TODAY)]

    def test_child_born_long_after_a_parent_died_in_the_next_year(self):
        found = self.warnings([Person("d", "Josip", sex="M", death={"date": "1900-01-15", "place": ""}),
                               Person("m", "Anka", sex="F", death={"date": "1900-03-01", "place": ""}),
                               Person("k", "Marija", birth={"date": "1901-11-20", "place": ""})],
                              [Family("f", ["d", "m"], children=[{"person": "k", "link": "birth"}])])
        self.assertEqual(len(found), 2)
        # A father's child born within ten months of his death is no mistake.
        self.assertEqual(self.warnings([Person("d", "Josip", sex="M", death={"date": "1900-01-15", "place": ""}),
                                        Person("k", "Ivan", birth={"date": "1900-09-20", "place": ""})],
                                       [Family("f", ["d"], children=[{"person": "k", "link": "birth"}])]), [])

    def test_born_after_partner_died_the_same_year(self):
        found = self.warnings([Person("a", "Čedo", death={"date": "1950-01-01", "place": ""}),
                               Person("b", "Šime", birth={"date": "1950-06-01", "place": ""})],
                              [Family("f", ["a", "b"], "married")])
        self.assertEqual(len(found), 1)

    def test_too_old_mother_marriage_before_birth_and_age_at_death(self):
        found = self.warnings([Person("m", "Kata", sex="F", birth={"date": "1820", "place": ""}),
                               Person("k", "Ante", birth={"date": "1890", "place": ""}),
                               Person("a", "Ana", birth={"date": "1900", "place": ""}),
                               Person("b", "Tomo", birth={"date": "1880", "place": ""}),
                               Person("s", "Stara", birth={"date": "1800", "place": ""},
                                      death={"date": "1950", "place": ""}, living="no")],
                              [Family("f", ["m"], children=[{"person": "k", "link": "birth"}]),
                               Family("g", ["a", "b"], "married", extra={"marriage": {"date": "1890"}})])
        self.assertEqual(len(found), 3, found)
        # About, before and after keep their room: none of these is impossible.
        self.assertEqual(self.warnings([Person("m", "Kata", sex="F", birth={"date": "abt 1840", "place": ""}),
                                        Person("k", "Ante", birth={"date": "bef 1900", "place": ""})],
                                       [Family("f", ["m"], children=[{"person": "k", "link": "birth"}])]), [])

    def test_statistics_decades_and_surnames_agree(self):
        from views_dialogs import statistics
        tree = Tree({"a": Person("a", "A", birth={"date": "aft 1909", "place": ""}),
                     "b": Person("b", "B", birth={"date": "bef 1900", "place": ""}),
                     "c": Person("c", "C", birth={"date": "1905", "place": ""})}, {})
        self.assertEqual(statistics(tree, TODAY)["births_per_decade"], [(1900, 1)])

    def test_timeline_and_places_sort_by_real_date(self):
        from model import date_sort_key
        dates = ["after 1900", "1900", "1.6.1900", "about 1900", "before 1900"]
        stored = {d: __import__("model").normalize_date_input(d) for d in dates}
        ordered = sorted(dates, key=lambda d: date_sort_key(stored[d]))
        self.assertEqual(ordered, ["before 1900", "about 1900", "1900", "1.6.1900", "after 1900"])
        self.assertLess(date_sort_key("1950", "death"), date_sort_key("1950", "burial"))
        self.assertLess(date_sort_key("1895", "birth"), date_sort_key("1895", "baptism"))
        self.assertLess(date_sort_key("abt 1700"), date_sort_key("1900"))


class DnaFilesAndNamesTests(WindowCase):
    """DNA files in the companies' own words, and relationship names (own review, 24 November 2026)."""

    def read(self, text):
        return dna.read_match_file(text.encode("utf-8"))

    def test_23andme_segments_are_segments(self):
        kind, rows = self.read("Display Name,Surname,Chromosome Number,Chromosome Start Point,Chromosome End Point,"
                               "Genetic Distance,# SNPs\nAna,K.,1,1000000,20000000,15,3000\nAna,K.,2,5000000,30000000,20,4000\n")
        self.assertEqual((kind, len(rows), rows[0][0]), ("segments", 2, "Ana K."))

    def test_german_segment_file_names_the_match_not_the_tester(self):
        kind, rows = self.read("Name;Name der Übereinstimmung;Chromosom;Startposition;Endposition;Centimorgan;SNPs\n"
                               "Luka Horvat;Dora Horvat;1;1000000;20000000;15,2;3000\n")
        self.assertEqual((kind, rows[0][0]), ("segments", "Dora Horvat"))

    def test_gedmatch_segment_kit_numbers_are_read(self):
        kind, rows = self.read("Kit1 Number,Kit1 Name,Kit2 Number,Kit2 Name,Chr,B37 Start,B37 End,Segment cM,SNPs\n"
                               "A1,Me,B2,Petar Horvat,1,1000000,20000000,15.2,3000\n"
                               "A1,Me,C3,Petar Horvat,2,1000000,20000000,11.1,2000\n")
        self.assertEqual([r[2] for r in rows], ["B2", "C3"])

    def test_german_match_list_figures(self):
        kind, rows = self.read("Name;Geschätzte Verwandtschaft;Gesamte gemeinsame DNA (cM);Gemeinsame Segmente;"
                               "Größtes Segment (cM)\nHans;Cousin;850,5;28;95,3\nBruder;Bruder;2.612;55;180,0\n")
        self.assertEqual([(m["cm"], m.get("longest"), m.get("guess")) for m in rows],
                         [(850.5, 95.3, "Cousin"), (2612.0, 180.0, "Bruder")])

    def test_relation_names_say_half_and_which_way(self):
        import dna_dialog
        import strings
        self.assertEqual(dna_dialog.relation_name(2, 2, True), "half first cousin")
        strings.set_language("de")
        self.addCleanup(strings.set_language, "en")
        self.assertEqual(dna_dialog.relation_name(0, 2), "Grandchild")
        self.assertEqual(dna_dialog.relation_name(2, 0), "Grandparent")

    def test_a_child_with_an_unknown_link_is_still_related_by_dna(self):
        import kinship
        tree = Tree({"d": Person("d", "Ivo", sex="M"), "k": Person("k", "Luka")},
                    {"f": Family("f", ["d"], children=[{"person": "k", "link": "unknown"}])})
        relation = kinship.blood_relation(tree, "k", "d", biological=True)
        self.assertEqual((relation.up, relation.down), (1, 0))

    def test_typed_figures_are_not_added_up_again_from_segments(self):
        import dna_dialog
        w = self.window
        create_tree(self.folder, Tree({"p": Person("p", "Ana")}, {}))
        self.assertTrue(w.open_path(self.folder))
        dialog = dna_dialog.DnaDialog(w, w.tree, "p", w.folder, find_person=lambda title: None)
        self.addCleanup(dialog.deleteLater)
        dialog.tests.append(dna.clean_test({"company": "Other"}))
        dialog._fill_tests(0)
        first = self.temp / "one.csv"
        first.write_text("Match Name,Chromosome,Start Location,End Location,Centimorgans\n"
                         "Dora Horvat,1,1000000,20000000,55\n")
        dialog.import_path(first)
        match = dialog.current_test()["matches"][0]

        class Typed:
            def __init__(self, *args):
                pass

            def exec(self):
                return True

            def values(self):
                return {**match, "cm": 870.0, "segments": 31}

            def deleteLater(self):
                pass

        dialog.selected_matches = lambda: [match]
        real = dna_dialog.MatchDialog
        dna_dialog.MatchDialog = Typed
        self.addCleanup(setattr, dna_dialog, "MatchDialog", real)
        dialog.edit_match()
        second = self.temp / "two.csv"
        second.write_text("Match Name,Chromosome,Start Location,End Location,Centimorgans\n"
                          "Dora Horvat,2,1000000,9000000,12\n")
        dialog.import_path(second)
        self.assertEqual(dialog.current_test()["matches"][0]["cm"], 870.0)


class LanguageTests(unittest.TestCase):
    """What each language shows reads back, and lays out the right way (own review, 24 November 2026)."""

    def tearDown(self):
        import strings
        strings.set_language("en")

    def test_a_new_event_typed_like_an_old_one_gets_what_was_typed(self):
        import edits
        from model import date_input_text
        person = Person("a", "Ana", extra={"events": [{"type": "residence", "date": "from 1700 to 1710 julian"}]})
        shown = date_input_text("from 1700 to 1710 julian")
        typed = edits.clean_events(
            [{"type": "residence", "date": shown}, {"type": "residence", "date": shown},
             {"type": "occupation", "date": shown}],
            [("residence", "from 1700 to 1710 julian")])
        self.assertEqual(typed[0]["date"], "from 1700 to 1710 julian")  # The old row, unchanged.
        own = __import__("model").normalize_date_input(shown)
        self.assertEqual([e["date"] for e in typed[1:]], [own, own])
        del person

    def test_cjk_and_french_date_words_read_back(self):
        import strings
        from model import date_label, normalize_date_input
        for text, stored in (("environ 1921", "abt 1921"), ("约1921年", "abt 1921"), ("1921年", "1921"),
                             ("1950年から1960年まで", "from 1950 to 1960"), ("약 1921년", "abt 1921")):
            self.assertEqual(normalize_date_input(text), stored, text)
        for language in ("ja", "zh_CN", "ko", "fr"):
            strings.set_language(language)
            self.assertEqual(normalize_date_input(date_label("abt 1921")), "abt 1921", language)

    def test_arabic_reports_read_right_to_left(self):
        import strings
        strings.set_language("ar")
        tree = Tree({"a": Person("a", "أحمد")}, {})
        html = reports.family_sheet(tree, "a")
        self.assertIn("dir='rtl'", html[:200])

    def test_counts_never_say_one_people(self):
        import strings
        for key, values in (("import_done", {"people": 1, "families": 1}), ("restore_option", {"when": "x", "people": 1}),
                            ("line_bar", {"surname": "Šimić", "count": 1})):
            self.assertNotIn("1 people", strings.t(key, **values))


class FailedWriteTests(WindowCase):
    """What happens when a write fails (own review, 24 November 2026)."""

    def test_a_cut_off_pdf_or_odt_never_replaces_the_good_one(self):
        import storage
        for name, cut in (("a.pdf", b"%PDF-1.4\n" + b"x" * 4000), ("b.odt", b"PK\x03\x04" + b"x" * 100),
                          ("c.pdf", b"")):
            path = self.temp / name
            path.write_bytes(cut)
            with self.assertRaises(OSError):
                storage.check_written(path)
        good = self.temp / "d.pdf"
        good.write_bytes(b"%PDF-1.4\n...\n%%EOF\n")
        storage.check_written(good)

    def test_report_export_refuses_when_the_writer_left_a_cut_off_file(self):
        import storage
        target = self.temp / "fam.pdf"
        target.write_bytes(b"%PDF-1.4 old and good %%EOF")
        real = storage.check_written

        def full(path):
            raise OSError(28, "No space left on device")

        storage.check_written = full
        self.addCleanup(setattr, storage, "check_written", real)
        tree = Tree({"a": Person("a", "Ana")}, {})
        with self.assertRaises(OSError):
            reports.write_document(reports.family_sheet(tree, "a"), target)
        self.assertEqual(target.read_bytes(), b"%PDF-1.4 old and good %%EOF")
        self.assertEqual([p.name for p in self.temp.iterdir() if p.name.startswith(".fam")], [])

    def test_an_old_backup_that_cannot_go_does_not_stop_the_save(self):
        import shutil as shutil_module
        import storage
        create_tree(self.folder, Tree({"a": Person("a", "Ana")}, {}))
        for n in range(storage.BACKUP_KEEP + 2):
            (self.folder / storage.BACKUP_DIR / f"backup-2020-01-{n + 1:02d}-000000").mkdir()
        real = shutil_module.rmtree

        def stuck(path, *args, **kwargs):
            if kwargs.get("ignore_errors"):
                return real(path, *args, **kwargs)
            raise PermissionError(13, "Permission denied")

        storage.shutil.rmtree = stuck
        self.addCleanup(setattr, storage.shutil, "rmtree", real)
        tree = Tree({"a": Person("a", "Ana"), "b": Person("b", "Ivo")}, {})
        storage.make_backup(self.folder)
        storage.save_tree(self.folder, tree)
        self.assertIn("Ivo", (self.folder / "tree.json").read_text(encoding="utf-8"))

    def test_the_failed_save_message_goes_once_a_save_works(self):
        create_tree(self.folder, Tree({"a": Person("a", "Ana")}, {}))
        self.assertTrue(self.window.open_path(self.folder))
        real = app_module.save_tree
        app_module.save_tree = lambda folder, tree: (_ for _ in ()).throw(OSError(28, "No space left on device"))
        self.window._save()
        self.assertIn("No space", self.window.statusBar().currentMessage())
        app_module.save_tree = real
        self.window._save()
        self.assertIsNone(self.window.save_error)
        self.assertNotIn("No space", self.window.statusBar().currentMessage())

    def test_a_long_file_name_gets_a_short_working_file(self):
        import storage
        path = self.temp / ("x" * 240 + ".pdf")
        temp = storage.temp_beside(path)
        self.addCleanup(temp.unlink, True)
        self.assertLess(len(temp.name), 120)
        self.assertIn(".pdf.", temp.name)

    def test_a_new_tree_that_could_not_be_made_leaves_no_folder(self):
        import storage
        real = storage.atomic_write

        def full(path, text):
            raise OSError(28, "No space left on device")

        storage.atomic_write = full
        self.addCleanup(setattr, storage, "atomic_write", real)
        target = self.temp / "New.tree"
        with self.assertRaises(OSError):
            storage.create_tree(target, Tree())
        self.assertFalse(target.exists())

    def test_a_leftover_export_folder_is_cleaned_up(self):
        import exports
        leftover = self.temp / ".fam-export-abc123"
        (leftover / "new").mkdir(parents=True)
        (leftover / "new" / "photo.jpg").write_bytes(b"x")
        exports.export_gedcom(Tree({"a": Person("a", "Ana")}, {}), self.temp, self.temp / "fam.ged")
        self.assertFalse(leftover.exists())

    def test_a_document_that_could_not_be_copied_is_not_blamed(self):
        import documents as documents_module
        create_tree(self.folder, Tree({"a": Person("a", "Ana")}, {}))
        self.assertTrue(self.window.open_path(self.folder))
        scan = self.temp / "scan.pdf"
        scan.write_bytes(b"%PDF-1.4 %%EOF")
        real = documents_module.store_document

        def full(*args, **kwargs):
            raise OSError(28, "No space left on device")

        documents_module.store_document = full
        self.addCleanup(setattr, documents_module, "store_document", real)
        self.window.attach_documents("a", [str(scan)])
        self.assertIn("No space left on device", self.answers.alerts[-1])
        self.assertNotIn("too big", self.answers.alerts[-1])


class StateTests(WindowCase):
    """Menus and leftovers in each state of the window (own review, 24 November 2026)."""

    def test_highlight_a_family_line_with_no_tree_open(self):
        self.assertFalse(self.window.family_line_action.isEnabled())
        self.window.pick_family_line()  # Ctrl+B still reaches it: nothing may break.

    def test_a_lost_save_is_not_asked_about_again_in_the_sample(self):
        create_tree(self.folder, Tree({"a": Person("a", "Ana")}, {}))
        self.assertTrue(self.window.open_path(self.folder))
        real = app_module.save_tree
        app_module.save_tree = lambda folder, tree: (_ for _ in ()).throw(OSError(28, "No space left on device"))
        self.addCleanup(setattr, app_module, "save_tree", real)
        self.window._save()
        self.answers.confirms = [True]  # Close anyway.
        self.assertTrue(self.window.close_tree())
        app_module.save_tree = real
        self.window.load_sample()
        self.assertTrue(self.window.close_tree())  # No question left to answer.
        self.assertEqual(self.answers.confirms, [])

    def test_file_actions_are_enabled_only_where_they_work(self):
        w = self.window
        for action in (w.combine_action, w.share_action, w.webpage_action, w.liveshare_action):
            self.assertFalse(action.isEnabled())
        w.load_sample()
        self.assertFalse(w.combine_action.isEnabled())
        self.assertFalse(w.share_action.isEnabled())

    def test_the_tour_ends_with_its_tree(self):
        create_tree(self.folder, Tree({"a": Person("a", "Ana")}, {}))
        self.assertTrue(self.window.open_path(self.folder))
        self.window.start_tour()
        self.assertIsNotNone(self.window.tour)
        self.assertTrue(self.window.close_tree())
        self.assertIsNone(self.window.tour)

    def test_a_hidden_person_given_a_name_is_shown_by_it(self):
        import edits
        tree = Tree({"h": Person("h", "", "Šimić", living="yes", extra={"hidden": True})}, {})
        edits.update_person(tree, "h", {"given": "Marin", "surname": "Šimić", "living": "yes"})
        self.assertEqual(tree.people["h"].display_name, "Marin Šimić")


class DamagedAndBigTreeTests(WindowCase):
    """Hand-edited files and very big trees (own review, 24 November 2026)."""

    def write_raw(self, data, prefix=b""):
        create_tree(self.folder, Tree({"a": Person("a", "Ana")}, {}))
        (self.folder / "tree.json").write_bytes(prefix + json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def base(self):
        return json.loads((self.folder / "tree.json").read_text(encoding="utf-8"))

    def test_a_marriage_date_written_as_a_number_opens(self):
        create_tree(self.folder, Tree({"a": Person("a", "Ana", birth={"date": "1900", "place": ""}),
                                       "b": Person("b", "Ivo")}, {"f": Family("f", ["a", "b"], "married")}))
        data = self.base()
        data["families"]["f"]["marriage"] = {"date": 1925, "place": "Split"}
        (self.folder / "tree.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(self.window.open_path(self.folder))
        self.window.select("a")

    def test_sources_that_are_not_records_do_not_stop_edits_or_exports(self):
        create_tree(self.folder, Tree({"a": Person("a", "Ana")}, {}))
        data = self.base()
        data["sources"] = ["Matica"]
        (self.folder / "tree.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(self.window.open_path(self.folder))
        self.answers.people = [{"given": "Mia", "link": "birth"}]
        self.window.run_action("add_child", "a")
        self.assertIn("Mia", (self.folder / "tree.json").read_text(encoding="utf-8"))
        self.assertTrue(self.window.export_gedcom(self.temp / "out.ged", hide=True))

    def test_a_tree_saved_with_a_byte_order_mark_opens_as_it_is(self):
        create_tree(self.folder, Tree({"a": Person("a", "Ana"), "n": Person("n", "Nova")}, {}))
        text = (self.folder / "tree.json").read_bytes()
        (self.folder / "tree.json").write_bytes(b"\xef\xbb\xbf" + text)
        self.assertTrue(self.window.open_path(self.folder))
        self.assertIn("n", self.window.tree.people)
        self.assertEqual(self.answers.confirms, [])  # No offer to go back to a backup.

    def test_not_a_number_is_read_as_nothing_so_saving_still_works(self):
        create_tree(self.folder, Tree({"a": Person("a", "Ana")}, {}))
        text = (self.folder / "tree.json").read_text(encoding="utf-8")
        text = text.replace('"people"', '"places": {"Split": {"lat": NaN, "lon": 16.4}}, "people"', 1)
        (self.folder / "tree.json").write_text(text, encoding="utf-8")
        self.assertTrue(self.window.open_path(self.folder))
        self.answers.people = [{"given": "Mia", "link": "birth"}]
        self.window.run_action("add_child", "a")
        self.assertIsNone(self.window.save_error)

    def test_details_the_window_does_not_show_survive_an_unchanged_ok(self):
        import edits
        from dialogs import person_to_values
        tree = Tree({"a": Person("a", "Ana", birth={"date": "1900", "place": "Split", "time": "10:00",
                                                   "cause": "x"})}, {})
        values = person_to_values(tree.people["a"])
        edits.update_person(tree, "a", values)
        self.assertEqual(tree.people["a"].birth.get("time"), "10:00")

    def test_not_the_same_does_not_search_the_whole_tree_again(self):
        create_tree(self.folder, Tree({i: Person(i, "Ivan", "Šimić") for i in ("a", "b", "c")}, {}))
        self.assertTrue(self.window.open_path(self.folder))
        calls = []
        real = app_module.find_duplicates
        app_module.find_duplicates = lambda tree: calls.append(1) or real(tree)
        self.addCleanup(setattr, app_module, "find_duplicates", real)
        answers = []

        def ask(candidates, selected):
            if answers:
                return None
            answers.append(1)
            return ("not", candidates[0].a, candidates[0].b, 0)

        self.window.ask_duplicates = ask
        self.window.show_duplicates()
        self.assertEqual(len(calls), 1)


class ImportMediaTests(WindowCase):
    """Pictures and documents in GEDCOM files from other programs (own review, 24 November 2026)."""

    def picture(self, path, colour):
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(40, 40, QImage.Format.Format_RGB32)
        image.fill(QColor(colour))
        self.assertTrue(image.save(str(path)))

    def import_text(self, body):
        source = self.temp / "fam.ged"
        source.write_text("0 HEAD\n1 CHAR UTF-8\n" + body + "0 TRLR\n", encoding="utf-8")
        self.assertTrue(self.window.import_gedcom(source, self.folder))
        return self.window.tree

    def colour_of(self, person):
        image = QImage(str(self.folder / person.photo))
        return image.pixelColor(image.width() // 2, image.height() // 2).name()

    def test_the_picture_marked_main_is_the_portrait(self):
        self.picture(self.temp / "m" / "wedding.jpg", "#ff0000")
        self.picture(self.temp / "m" / "face.jpg", "#00ff00")
        tree = self.import_text("0 @I1@ INDI\n1 NAME Ana //\n1 OBJE\n2 FILE m/wedding.jpg\n"
                                "1 OBJE\n2 FILE m/face.jpg\n2 _PRIM Y\n")
        ana = next(iter(tree.people.values()))
        self.assertLess(QColor(self.colour_of(ana)).red(), 60)
        self.assertEqual(len(person_documents(ana)), 1)

    def test_windows_paths_and_web_addresses(self):
        self.picture(self.temp / "b.jpg", "#0000ff")
        self.picture(self.temp / "media" / "my photo.jpg", "#00ff00")
        tree = self.import_text("0 @I1@ INDI\n1 NAME Ana //\n1 OBJE\n2 FILE C:\\Users\\Ana\\Pictures\\b.jpg\n"
                                "0 @I2@ INDI\n1 NAME Ivo //\n1 OBJE\n2 FILE media/my%20photo.jpg\n"
                                "0 @I3@ INDI\n1 NAME Lisa //\n1 OBJE\n2 FILE http://example.org/lisa.jpg\n")
        self.assertTrue(all(p.photo for p in tree.people.values() if p.given in ("Ana", "Ivo")))
        self.assertFalse(any("not copied" in text for text in self.answers.alerts))

    def test_a_shared_record_with_a_missing_file_keeps_it(self):
        (self.temp / "media").mkdir()
        (self.temp / "media" / "found.pdf").write_bytes(b"%PDF-1.4 %%EOF")
        self.import_text("0 @I1@ INDI\n1 NAME Ana //\n1 OBJE @O1@\n"
                         "0 @O1@ OBJE\n1 FILE media/portrait-missing.jpg\n2 TITL The only portrait\n"
                         "1 FILE media/found.pdf\n2 TITL Found scan\n")
        self.assertTrue(any("not copied: 1" in text for text in self.answers.alerts), self.answers.alerts)
        out = self.temp / "out.ged"
        self.assertTrue(self.window.export_gedcom(out, hide=False))
        self.assertIn("portrait-missing.jpg", out.read_text(encoding="utf-8"))

    def test_documents_are_counted_as_documents_and_forms_do_not_double(self):
        (self.temp / "media").mkdir()
        (self.temp / "media" / "scan.pdf").write_bytes(b"%PDF-1.4 %%EOF")
        self.import_text("0 @I1@ INDI\n1 NAME Ana //\n1 OBJE\n2 FILE media/scan.pdf\n3 FORM pdf\n")
        self.assertTrue(any("Documents copied in: 1" in text for text in self.answers.alerts), self.answers.alerts)
        out = self.temp / "out.ged"
        self.assertTrue(self.window.export_gedcom(out, hide=False))
        self.assertEqual(out.read_text(encoding="utf-8").count("FORM pdf"), 1)


class WebShareTests(unittest.TestCase):
    """The shared web page and the live share (own review, 24 November 2026)."""

    def test_no_text_can_bend_the_pages_script(self):
        data = {"title": "T", "home": "a", "people": {"a": {"name": "Ana <script>", "notes": "Old page said: <!--"}}}
        html_text = webshare.page(data)
        script = html_text[html_text.index("const PAYLOAD"):]
        script = script[:script.index("</script>")]
        self.assertNotIn("<!--", script)
        self.assertNotIn("<script", script)

    def test_one_password_whichever_way_its_letters_were_typed(self):
        import unicodedata
        if not webshare.encryption_available():
            self.skipTest("no encryption library")
        import inspect
        self.assertIn('normalize("NFC")', webshare.TEMPLATE)  # The page, when it unlocks.
        self.assertIn('normalize("NFC"', inspect.getsource(webshare.encrypt))  # And when it locks.
        del unicodedata

    def test_stopping_ends_connections_already_open(self):
        import socket
        share = webshare.LiveShare({"title": "T", "home": "a", "people": {"a": {"name": "Ana"}}}, port=0)
        client = socket.create_connection(("127.0.0.1", share.port))
        client.sendall(b"GET /")
        import time
        time.sleep(0.2)
        share.stop()
        client.settimeout(3)
        try:
            client.sendall(f"{share.token} HTTP/1.0\r\n\r\n".encode())
            answer = client.recv(64)
        except OSError:
            answer = b""
        client.close()
        self.assertNotIn(b"200", answer)

    def test_half_an_emoji_in_a_file_does_not_stop_saving(self):
        import storage
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        create_tree(folder / "T.tree", Tree({"a": Person("a", "Ana")}, {}))
        path = folder / "T.tree" / "tree.json"
        path.write_text(path.read_text(encoding="utf-8").replace('"Ana"', '"Ana\\ud83d"'), encoding="utf-8")
        tree = storage.read_tree(folder / "T.tree")
        storage.save_tree(folder / "T.tree", tree)
        self.assertEqual(tree.people["a"].given, "Ana�")


class RepeatedCombineTests(unittest.TestCase):
    """What long random sessions found (own review, 24 November 2026)."""

    def same_tree(self):
        return Tree({"a": Person("a", "Ana", extra={"events": [{"type": "baptism", "date": "1900",
                                                                "people": [{"role": "godfather", "person": "b"}]}]}),
                     "b": Person("b", "Ivo", extra={"dna": {"tests": [{"id": "t1", "company": "Other",
                                                                        "matches": [{"id": "m1", "name": "Ana", "person": "a"}],
                                                                        "segments": []}]}})}, {})

    def test_combining_the_same_tree_repeats_no_event_and_no_dna_test(self):
        import combine
        tree = combine.combine(self.same_tree(), self.same_tree(), {"a": "a", "b": "b"}).tree
        self.assertEqual(len(tree.people["a"].extra["events"]), 1)
        self.assertEqual(len(tree.people["b"].extra["dna"]["tests"]), 1)
        self.assertEqual(len(tree.people["b"].extra["dna"]["tests"][0]["matches"]), 1)

    def test_your_own_copy_keeps_your_place_spellings_and_sources(self):
        import combine
        def tree():
            return Tree({"a": Person("a", "Ana", birth={"date": "", "place": "trogir"},
                                     extra={"events": [{"type": "residence", "date": "", "place": "Trogir",
                                                        "citations": [{"source": "s2"}]}]})}, {},
                        {"sources": {"s1": {"title": "Matica"}, "s2": {"title": "Matica"}}})
        result = combine.combine(tree(), tree(), {"a": "a"}).tree
        ana = result.people["a"]
        self.assertEqual(ana.birth["place"], "trogir")
        self.assertEqual(len(ana.extra["events"]), 1)
        self.assertEqual(ana.extra["events"][0]["citations"], [{"source": "s2"}])
        self.assertEqual(ana.notes, "")

    def test_merging_two_parentless_brothers_leaves_no_empty_family(self):
        tree = Tree({"a": Person("a", "Ivo"), "b": Person("b", "Ivan")},
                    {"f": Family("f", [], children=[{"person": "a"}, {"person": "b"}])})
        merge_people(tree, "a", "b")
        self.assertEqual(tree.families, {})

    def test_merging_someone_with_their_own_dna_match_unlinks_it(self):
        tree = self.same_tree()
        tree.people["b"].extra["dna"]["tests"][0]["matches"][0]["person"] = "a"
        merge_people(tree, "b", "a")
        match = tree.people["b"].extra["dna"]["tests"][0]["matches"][0]
        self.assertNotIn("person", match)
        self.assertEqual(match["name"], "Ana")


class OwnShareCopyTests(WindowCase):
    def test_combining_your_own_share_copy_adds_no_photo_copies(self):
        create_tree(self.folder, Tree({"a": Person("a", "Ivo")}, {}))
        self.assertTrue(self.window.open_path(self.folder))
        self.answers.photos = [str(self.make_photo())]
        self.window.run_action("photo", "a")
        copy = self.temp / "Copy.tree"
        self.window.make_share_copy(copy, hide=False)
        self.window.ask_combine = lambda *args: {"matches": {"a": "a"}, "take_theirs": {}}
        for _ in range(2):
            self.window.combine_with(copy)
        self.assertEqual(person_documents(self.window.tree.people["a"]), [])


class PackagedProgramTests(unittest.TestCase):
    """What the built program offers (own review, 24 November 2026)."""

    def test_odt_reports_are_offered(self):
        from PySide6.QtGui import QTextDocumentWriter
        if not QTextDocumentWriter.supportedDocumentFormats():
            self.skipTest("no document writers at all")
        self.assertTrue(reports.odt_supported())  # Qt calls it "ODF": it was never offered.


class SettingsTests(WindowCase):
    """Preferences, the recent list and starting up (own review, 24 November 2026)."""

    def test_a_tree_opened_by_a_relative_path_is_remembered_whole(self):
        import os
        create_tree(self.folder, Tree({"a": Person("a", "Ana")}, {}))
        here = os.getcwd()
        os.chdir(self.temp)
        self.addCleanup(os.chdir, here)
        self.assertTrue(self.window.open_path("Test.tree"))
        self.assertTrue(Path(self.settings.value("last_tree")).is_absolute())
        self.assertTrue(all(Path(p).is_absolute() for p in self.window._recent_trees()))

    def test_odd_values_in_the_settings_file_do_not_stop_the_start(self):
        from PySide6.QtCore import QPoint
        self.settings.setValue("card_style", ["portrait", "round"])
        self.settings.setValue("recent_trees", QPoint(1, 2))
        window = self.make_window()
        self.assertEqual(window.card_style, "portrait")
        self.assertEqual(window._recent_trees(), [])

    def test_the_same_tree_by_two_paths_is_listed_once(self):
        create_tree(self.folder, Tree({"a": Person("a", "Ana")}, {}))
        link = self.temp / "link"
        link.symlink_to(self.temp, target_is_directory=True)
        self.assertTrue(self.window.open_path(self.folder))
        self.assertTrue(self.window.close_tree())
        self.assertTrue(self.window.open_path(link / "Test.tree"))
        self.assertEqual(len(self.window._recent_trees()), 1)

    def test_preferences_keep_what_another_window_changed(self):
        self.window.ask_preferences = lambda values: {**values, "theme": "light"}
        other = QSettings(self.settings.fileName(), QSettings.Format.IniFormat)
        other.setValue("line_style", "curved")
        other.sync()
        self.window.show_preferences()
        self.settings.sync()
        self.assertEqual(self.settings.value("line_style"), "curved")

    def test_an_unknown_language_is_the_systems_and_system_can_be_chosen(self):
        import strings
        self.addCleanup(strings.set_language, "en")
        strings.set_language("xx", ["hr-HR", "hr"])
        self.assertEqual(strings.LANGUAGE, "hr")
        self.settings.setValue("language", "xx")
        self.window.ask_preferences = lambda values: dict(values)  # OK with "System" as shown.
        self.window.show_preferences()
        self.assertEqual(self.settings.value("language"), strings.SYSTEM)


class KeyboardTests(WindowCase):
    """Using the program without a mouse (own review, 24 November 2026)."""

    def open_family(self):
        ana = self.start_family()
        return ana

    def test_enter_in_a_list_goes_to_the_person(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from research_dialogs import ResearchDialog
        ana = self.open_family()
        mia = self.person_named("Mia").id
        self.window.apply_edit(lambda: __import__("edits").set_tasks(self.window.tree, mia, [{"text": "Matica"}]))
        dialog = ResearchDialog(self.window, self.window.tree)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        dialog.list.setCurrentRow(0)
        dialog.list.setFocus()
        QTest.keyClick(dialog.list, Qt.Key.Key_Return)
        self.assertEqual(dialog.chosen, mia)
        del ana

    def test_enter_in_the_person_window_saves(self):
        from PySide6.QtWidgets import QDialogButtonBox, QPushButton
        from dialogs import PersonDialog
        dialog = PersonDialog(self.window, "Add")
        self.addCleanup(dialog.deleteLater)
        defaults = [b for b in dialog.findChildren(QPushButton) if b.isDefault() or b.autoDefault()]
        self.assertEqual(defaults, [dialog.buttons.button(QDialogButtonBox.StandardButton.Save)])

    def test_escape_ends_the_tour_and_keys_stay_with_it(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.open_family()
        before = self.window.selected
        self.window.start_tour()
        tour = self.window.tour
        QTest.keyClick(tour, Qt.Key.Key_Left)
        self.assertEqual(self.window.selected, before)
        QTest.keyClick(tour, Qt.Key.Key_Escape)
        self.assertIsNone(self.window.tour)

    def test_preferences_and_dna_windows_scroll_rather_than_hide_their_buttons(self):
        from PySide6.QtWidgets import QScrollArea
        from dialogs import PreferencesDialog
        from dna_dialog import DnaDialog
        ana = self.open_family()
        prefs = PreferencesDialog(self.window, {"card_style": "portrait", "generations_up": 2, "detail": "age",
                                                "reopen_last": True, "language": "system"})
        dna_window = DnaDialog(self.window, self.window.tree, ana, self.window.folder, find_person=lambda title: None)
        for dialog in (prefs, dna_window):
            self.addCleanup(dialog.deleteLater)
            self.assertTrue(dialog.findChildren(QScrollArea), type(dialog).__name__)

    def test_shift_arrows_fold_the_selected_branch(self):
        from PySide6.QtCore import Qt
        ana = self.open_family()
        self.window.select(ana)
        self.assertTrue(self.window._fold_key(Qt.Key.Key_Down))
        self.assertIn(ana, self.window.collapsed)
        self.assertTrue(self.window._fold_key(Qt.Key.Key_Up))
        self.assertIn(ana, self.window.folded_up)


class AccessibilityRestTests(WindowCase):
    """The rest of the keyboard and screen-reader review (own review, 24 November 2026)."""

    def test_every_menu_item_has_a_letter_of_its_own(self):
        def check(menu):
            letters = []
            for action in menu.actions():
                if action.isSeparator() or not action.text():
                    continue
                text = action.text()
                self.assertIn("&", text, text)
                letters.append(text[text.index("&") + 1].lower())
                if action.menu() is not None:
                    check(action.menu())
            self.assertEqual(len(letters), len(set(letters)), [a.text() for a in menu.actions()])
        check(self.window.menuBar())

    def test_dialog_fields_have_names_for_screen_readers(self):
        from PySide6.QtWidgets import QLineEdit
        from dialogs import PersonDialog
        dialog = PersonDialog(self.window, "Add")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        unnamed = [w.objectName() for w in dialog.findChildren(QLineEdit) if w.isVisible() and not w.accessibleName()]
        self.assertEqual(unnamed, [])

    def test_the_fan_chart_answers_the_arrow_keys(self):
        from PySide6.QtCore import Qt
        ana = self.start_family()
        self.answers.people = [{"given": "Baka", "link": "birth"}]
        self.window.run_action("add_mother", self.person_named("Mia").id)
        mia = self.person_named("Mia").id
        self.window.chart, self.window.house = "fan", mia
        self.window.refresh(keep_view=False)
        self.window.select(mia)
        before = self.window.selected
        moved = False
        for key in (Qt.Key.Key_Up, Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.window._arrow_key(key)
            moved = moved or self.window.selected != before
        self.assertTrue(moved)
        del ana

    def test_initials_stay_readable_on_a_deceased_card(self):
        import canvas
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        canvas.paint_portrait(painter, QRectF(0, 0, 100, 100), None, True, initials="AŠ", tint="#7a9a8f")
        painter.end()
        back = image.pixelColor(3, 3)
        letters = [image.pixelColor(x, y) for x in range(100) for y in range(100)]
        best = max(canvas._contrast(c, back) for c in letters)
        self.assertGreaterEqual(best, 3.0)

    def test_the_menu_key_opens_the_selected_persons_menu(self):
        ana = self.start_family()
        shown = []
        self.window.show_menu = lambda menu, position: shown.append(position)
        self.window.select(ana)
        self.window._context_menu(None, None)
        self.assertEqual(len(shown), 1)

    def test_a_gedcom_file_on_the_command_line_is_imported(self):
        source = self.temp / "fam.ged"
        source.write_text("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ana //\n0 TRLR\n", encoding="utf-8")
        asked = []
        self.window.ask_save_file = lambda *args, **kwargs: asked.append(args) or str(self.folder)
        self.window.choose_import(str(source))
        self.assertEqual(len(asked), 1)
        self.assertIn("Ana", (self.folder / "tree.json").read_text(encoding="utf-8"))


class UnchangedOkTests(WindowCase):
    """OK with nothing changed saves nothing (own review, 24 November 2026)."""

    def test_ok_in_the_real_windows_with_nothing_changed_leaves_the_file_alone(self):
        from PySide6.QtWidgets import QDialog
        create_tree(self.folder, Tree({"a": Person("a", "Ana", birth={"date": "1900", "place": "Split"},
                                                   extra={"events": [{"type": "residence", "date": "", "zz": 42}],
                                                          "tasks": [{"text": 5}]})}, {}))
        data = json.loads((self.folder / "tree.json").read_text(encoding="utf-8"))
        data["people"]["a"]["birth"]["citations"] = "matica"  # Hand-edited, the wrong shape.
        (self.folder / "tree.json").write_text(json.dumps(data), encoding="utf-8")
        before = (self.folder / "tree.json").read_bytes()
        self.assertTrue(self.window.open_path(self.folder))
        real_exec = QDialog.exec
        QDialog.exec = lambda dialog: QDialog.DialogCode.Accepted  # OK at once, nothing touched.
        self.addCleanup(setattr, QDialog, "exec", real_exec)
        for edit in (self.window._edit_person, self.window._edit_tasks, self.window._edit_story,
                     self.window._edit_documents):
            del self.window.ask_person  # The real windows, not the test stand-ins.
            self.window.ask_person = app_module.MainWindow.ask_person.__get__(self.window)
            edit("a")
        self.assertEqual((self.folder / "tree.json").read_bytes(), before)
        self.assertFalse(self.window.history.can_undo())


class RemainingDataTests(WindowCase):
    """What earlier rounds left over (own review, 24 November 2026)."""

    def gedcom(self, body, name="fam.ged"):
        source = self.temp / name
        source.write_text("0 HEAD\n1 CHAR UTF-8\n" + body + "0 TRLR\n", encoding="utf-8")
        return source

    def picture(self, path, colour="#336699"):
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(40, 40, QImage.Format.Format_RGB32)
        image.fill(QColor(colour))
        self.assertTrue(image.save(str(path)))

    def export_text(self):
        out = self.temp / "out.ged"
        self.assertTrue(self.window.export_gedcom(out, hide=False))
        return out.read_text(encoding="utf-8")

    def test_no_married_name_is_invented(self):
        tree = read_gedcom(self.gedcom("0 @I1@ INDI\n1 NAME Mary Ann /Smith/\n1 NAME Mary /Jones/\n2 TYPE married\n"),
                           today=TODAY).tree
        mary = next(iter(tree.people.values()))
        self.assertEqual((mary.given, mary.surname), ("Mary Ann", "Smith"))
        from gedcom import write_gedcom
        self.assertNotIn("Mary Ann /Jones/", write_gedcom(tree, self.temp / "o.ged", today=TODAY))

    def test_line_breaks_in_notes_pages_and_causes_stay(self):
        tree = read_gedcom(self.gedcom(
            "0 @I1@ INDI\n1 NAME Ana //\n1 OCCU\n2 NOTE Worked on the farm\n3 CONT and later in the mill\n"
            "1 DEAT\n2 CAUS Tuberculosis\n3 CONT after long illness\n2 SOUR @S1@\n3 PAGE Folio 12\n4 CONT second line\n"
            "0 @S1@ SOUR\n1 TITL Parish register\n2 CONT of births\n"), today=TODAY).tree
        ana = next(iter(tree.people.values()))
        self.assertEqual(ana.extra["events"][0]["text"], "Worked on the farm\nand later in the mill")
        self.assertEqual(ana.death["cause"], "Tuberculosis\nafter long illness")
        self.assertEqual(ana.death["citations"][0]["page"], "Folio 12\nsecond line")
        self.assertEqual(next(iter(tree_sources(tree).values()))["title"], "Parish register\nof births")
        from gedcom import write_gedcom
        text = write_gedcom(tree, self.temp / "o.ged", today=TODAY)
        self.assertIn("3 PAGE Folio 12\n4 CONT second line", text)

    def test_turkish_endings_follow_the_number(self):
        import strings
        from model import date_input_text, normalize_date_input
        strings.set_language("tr")
        self.addCleanup(strings.set_language, "en")
        self.assertEqual(date_input_text("from 1950 to 1960"), "1950'den 1960'a kadar")
        self.assertEqual(date_input_text("from 1960"), "1960'tan itibaren")
        self.assertEqual(normalize_date_input("1930'dan 1960'a kadar"), "from 1930 to 1960")

    def test_lists_sort_in_the_languages_own_order(self):
        import strings
        strings.set_language("hr")
        self.addCleanup(strings.set_language, "en")
        names = ["Čačić", "Cvitan", "Ćosić", "Šarić", "Sušić"]
        self.assertEqual(sorted(names, key=strings.collation_key), ["Cvitan", "Čačić", "Ćosić", "Sušić", "Šarić"])

    def test_a_tree_saved_in_the_windows_encoding_opens(self):
        import strings
        strings.set_language("hr")
        self.addCleanup(strings.set_language, "en")
        create_tree(self.folder, Tree({"a": Person("a", "Šime", "Čačić")}, {}))
        text = (self.folder / "tree.json").read_text(encoding="utf-8")
        (self.folder / "tree.json").write_bytes(text.encode("cp1250"))
        self.assertTrue(self.window.open_path(self.folder))
        self.assertEqual(self.window.tree.people["a"].surname, "Čačić")
        self.window._save()  # Written back as UTF-8.
        self.assertIn("Čačić", (self.folder / "tree.json").read_text(encoding="utf-8"))

    def test_pictures_on_facts_and_families_come_in(self):
        (self.temp / "media").mkdir()
        (self.temp / "media" / "birthcert.pdf").write_bytes(b"%PDF-1.4 %%EOF")
        self.picture(self.temp / "media" / "wedding.jpg")
        source = self.gedcom("0 @I1@ INDI\n1 NAME Ana //\n1 FAMS @F1@\n1 BIRT\n2 OBJE\n3 FILE media/birthcert.pdf\n"
                             "0 @I2@ INDI\n1 NAME Ivo //\n1 FAMS @F1@\n"
                             "0 @F1@ FAM\n1 HUSB @I2@\n1 WIFE @I1@\n1 OBJE\n2 FILE media/wedding.jpg\n")
        self.assertTrue(self.window.import_gedcom(source, self.folder))
        people = {p.given: p for p in self.window.tree.people.values()}
        self.assertEqual(len(person_documents(people["Ana"])), 2)
        self.assertEqual(len(person_documents(people["Ivo"])), 1)

    def test_a_zipped_bundle_is_imported_with_its_pictures(self):
        import zipfile
        bundle = self.temp / "fam.gdz"
        self.picture(self.temp / "p.jpg")
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("gedcom.ged", "0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ana //\n1 OBJE\n2 FILE media/p.jpg\n0 TRLR\n")
            archive.write(self.temp / "p.jpg", "media/p.jpg")
            archive.writestr("../../evil.txt", "should never be written")
        self.assertTrue(self.window.import_gedcom(bundle, self.folder))
        self.assertTrue(next(iter(self.window.tree.people.values())).photo)
        self.assertFalse((self.temp.parent / "evil.txt").exists())

    def test_the_portrait_keeps_its_title_and_details_stay_with_their_picture(self):
        (self.temp / "m").mkdir()
        (self.temp / "m" / "scan.pdf").write_bytes(b"%PDF-1.4 %%EOF")
        self.picture(self.temp / "m" / "ana.jpg")
        self.import_and_export = self.gedcom(
            "0 @I1@ INDI\n1 NAME Ana //\n1 OBJE\n2 FILE m/scan.pdf\n2 DATE 12 MAR 1901\n2 NOTE Parish register\n"
            "1 OBJE\n2 FILE m/ana.jpg\n2 TITL Ana in 1950\n")
        self.assertTrue(self.window.import_gedcom(self.import_and_export, self.folder))
        text = self.export_text()
        self.assertIn("2 TITL Ana in 1950", text)
        self.assertRegex(text, r"2 FILE [^\n]*\.pdf\n(?:[23] .*\n)*2 DATE 12 MAR 1901\n2 NOTE Parish register")


if __name__ == "__main__":
    unittest.main()
