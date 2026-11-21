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

        def failing(*args, **kwargs):
            raise OSError("simulated write failure")

        documents.store_document = failing
        self.addCleanup(setattr, documents, "store_document", real)
        self.window.import_gedcom(source / "family.ged", self.temp / "Imported")
        self.assertTrue(any("could not be copied in: 1" in text for text in self.answers.informed + self.answers.alerts),
                        self.answers.informed)

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


if __name__ == "__main__":
    unittest.main()
