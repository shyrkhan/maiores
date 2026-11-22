"""What Maiores tells you must match what is on disk, and nothing private may slip out.
Each test here reproduces a finding of the November 2026 review (data loss, recovery,
privacy, leaks) and checks the fix."""
import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtGui import QColor, QImage  # noqa: E402

import app as app_module  # noqa: E402
import dna  # noqa: E402
import documents  # noqa: E402
import privacy  # noqa: E402
from edits import merge_people  # noqa: E402
from gedcom import read_gedcom  # noqa: E402
from model import Person, Tree, face_links, person_documents, tree_sources, place_records  # noqa: E402
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

if __name__ == "__main__":
    unittest.main()
