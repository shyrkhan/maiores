"""Documents attached to people, and what is left out of copies made for other people."""
import datetime
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import combine  # noqa: E402
import documents  # noqa: E402
import privacy  # noqa: E402
from edits import merge_people  # noqa: E402
from gedcom import read_gedcom, write_gedcom  # noqa: E402
from model import Family, Person, Tree, files_of, person_documents, validate  # noqa: E402

TODAY = datetime.date(2026, 11, 13)


def family():
    people = {
        "grandpa": Person("grandpa", given="Ante", surname="Šimić", sex="M", living="no",
                          birth={"date": "1921", "place": "Trogir"}, death={"date": "1988", "place": ""}),
        "old": Person("old", given="Mara", surname="Šimić", sex="F", birth={"date": "1880", "place": ""}),
        "dad": Person("dad", given="Luka", surname="Šimić", sex="M", living="yes",
                      birth={"date": "1950", "place": "Split"}, notes="Lives in Split",
                      photo="media/luka.jpg"),
        "unknown": Person("unknown", given="Ivo", surname="Šimić", sex="M"),
    }
    people["grandpa"].extra = {"documents": [
        {"file": "media/docs/birth.pdf", "title": "Birth certificate", "kind": "certificate", "date": "1921"},
        {"file": "media/docs/medical.pdf", "title": "Hospital record", "kind": "record", "private": True}],
        "notes_private": True}
    people["grandpa"].notes = "Family argument about the will"
    families = {"f": Family("f", ["grandpa"], "unknown", [{"person": "dad", "link": "birth"}]),
                "g": Family("g", ["dad"], "married", [], {"marriage": {"date": "1975", "place": "Split"}})}
    return Tree(people, families)


class LivingRuleTests(unittest.TestCase):
    def test_when_in_doubt_someone_counts_as_living(self):
        tree = family()
        living = {pid for pid, p in tree.people.items() if privacy.counts_as_living(p, TODAY)}
        # Ante died; Mara was born 146 years ago; Luka is marked living; Ivo has no dates at all.
        self.assertEqual(living, {"dad", "unknown"})


class ShareableTests(unittest.TestCase):
    def test_living_people_keep_only_surname_and_sex(self):
        shared = privacy.shareable(family(), TODAY)
        luka = shared.people["dad"]
        self.assertEqual((luka.given, luka.surname, luka.sex, luka.birth, luka.photo, luka.notes),
                         ("", "Šimić", "M", None, "", ""))
        self.assertTrue(privacy.is_hidden(luka))
        self.assertNotIn("marriage", shared.families["g"].extra)  # When and where a living couple married.
        self.assertEqual(shared.families["f"].child_ids, ["dad"])  # The family stays connected.
        self.assertEqual(validate(shared), [])

    def test_private_items_never_leave_even_when_living_people_are_shown(self):
        shared = privacy.shareable(family(), TODAY, hide_living=False)
        ante = shared.people["grandpa"]
        self.assertEqual([d["title"] for d in person_documents(ante)], ["Birth certificate"])
        self.assertEqual(ante.notes, "")
        self.assertEqual(shared.people["dad"].given, "Luka")

    def test_a_private_person_is_hidden_even_after_death(self):
        tree = family()
        tree.people["grandpa"].extra["private"] = True
        self.assertTrue(privacy.is_hidden(privacy.shareable(tree, TODAY, hide_living=False).people["grandpa"]))

    def test_your_own_tree_is_not_changed(self):
        tree = family()
        before = tree.to_dict()
        privacy.shareable(tree, TODAY)
        self.assertEqual(tree.to_dict(), before)

    def test_files_of_lists_portrait_and_documents(self):
        tree = family()
        self.assertEqual(files_of(tree.people["grandpa"]), ["media/docs/birth.pdf", "media/docs/medical.pdf"])
        self.assertEqual(files_of(privacy.shareable(tree, TODAY).people["grandpa"]), ["media/docs/birth.pdf"])
        self.assertEqual(files_of(tree.people["dad"]), ["media/luka.jpg"])

    def test_hidden_people_survive_gedcom_and_never_hide_your_own_record(self):
        mine = family()
        shared = privacy.shareable(mine, TODAY)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shared.ged"
            path.write_text(write_gedcom(shared, path), encoding="utf-8")
            back = read_gedcom(path, TODAY).tree
        hidden = [p for p in back.people.values() if privacy.is_hidden(p)]
        self.assertEqual(sorted(p.surname for p in hidden), ["Šimić", "Šimić"])
        # Combining the shared copy back: hidden people match through their family.
        found = {s.theirs: s for s in combine.suggest_matches(mine, back)}
        luka = next(s for s in found.values() if privacy.is_hidden(back.people[s.theirs]) and s.mine == "dad")
        self.assertTrue(luka.accepted)
        result = combine.combine(mine, back, {s.theirs: s.mine for s in found.values() if s.accepted})
        self.assertFalse(privacy.is_hidden(result.tree.people["dad"]))
        self.assertEqual(result.tree.people["dad"].given, "Luka")
        self.assertEqual(result.tree.people["dad"].living, "yes")


class HiddenBrothersTests(unittest.TestCase):
    def test_two_hidden_brothers_are_not_guessed(self):
        people = {"dad": Person("dad", given="Ante", surname="Šimić", sex="M", living="no",
                                birth={"date": "1921", "place": ""}, death={"date": "1988", "place": ""}),
                  "a": Person("a", given="Luka", surname="Šimić", sex="M", living="yes"),
                  "b": Person("b", given="Josip", surname="Šimić", sex="M", living="yes")}
        mine = Tree(people, {"f": Family("f", ["dad"], "unknown", [{"person": "a", "link": "birth"},
                                                                   {"person": "b", "link": "birth"}])})
        shared = privacy.shareable(mine, TODAY)
        found = {s.theirs: s for s in combine.suggest_matches(mine, shared)}
        self.assertTrue(found["dad"].accepted)
        self.assertFalse(found["a"].accepted or found["b"].accepted)


class DocumentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.tree_folder = self.root / "Mine.tree"
        self.tree_folder.mkdir()

    def file(self, name, content=b"scan"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_a_document_is_copied_in_once_by_its_content(self):
        first = documents.store_document(self.file("a.PDF"), self.tree_folder)
        again = documents.store_document(self.file("copy.pdf"), self.tree_folder)
        other = documents.store_document(self.file("b.pdf", b"another scan"), self.tree_folder)
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)
        self.assertTrue(first.startswith("media/docs/") and first.endswith(".pdf"))
        self.assertEqual(documents.resolve_document(self.tree_folder, first).read_bytes(), b"scan")

    def test_programs_and_scripts_are_refused(self):
        for name in ("setup.exe", "run.sh", "x.bat", "app.desktop", "link.lnk", "noext"):
            with self.assertRaises(documents.DocumentError):
                documents.store_document(self.file(name), self.tree_folder)
        planted = self.tree_folder / "media" / "docs"
        planted.mkdir(parents=True)
        (planted / "evil.sh").write_text("echo")
        self.assertIsNone(documents.resolve_document(self.tree_folder, "media/docs/evil.sh"))
        self.assertIsNone(documents.resolve_document(self.tree_folder, "media/../../outside.pdf"))

    def test_a_relative_trees_document_comes_across(self):
        theirs = self.root / "Theirs.tree"
        theirs.mkdir()
        stored = documents.store_document(self.file("letter.pdf", b"letter"), theirs)
        copied = documents.copy_from_tree(theirs, stored, self.tree_folder)
        self.assertEqual(documents.resolve_document(self.tree_folder, copied).read_bytes(), b"letter")
        self.assertEqual(documents.copy_from_tree(theirs, "media/docs/missing.pdf", self.tree_folder), "")

    def test_unsafe_document_paths_are_reported(self):
        tree = Tree({"a": Person("a", given="A", extra={"documents": [{"file": "../etc/passwd"}]})}, {})
        self.assertEqual([i.code for i in validate(tree)], ["unsafe_document"])

    def test_merging_keeps_both_peoples_documents(self):
        tree = Tree({"a": Person("a", given="Ivan", extra={"documents": [{"file": "media/docs/1.pdf"}]}),
                     "b": Person("b", given="Ivan", extra={"documents": [{"file": "media/docs/2.pdf"},
                                                                          {"file": "media/docs/1.pdf"}]})}, {})
        merge_people(tree, "a", "b")
        self.assertEqual([d["file"] for d in person_documents(tree.people["a"])],
                         ["media/docs/1.pdf", "media/docs/2.pdf"])

    def test_documents_go_out_and_come_back_through_gedcom(self):
        stored = documents.store_document(self.file("will.pdf", b"will"), self.tree_folder)
        tree = Tree({"a": Person("a", given="Ante", living="no", death={"date": "", "place": ""},
                                 extra={"documents": [{"file": stored, "title": "The will"}]})}, {})
        out = self.root / "out"
        out.mkdir()
        from exports import export_gedcom
        export_gedcom(tree, self.tree_folder, out / "family.ged")
        result = read_gedcom(out / "family.ged", TODAY)
        person_id = next(iter(result.tree.people))
        self.assertNotIn(person_id, result.photos)  # A document never becomes the portrait.
        [(path, title)] = result.documents[person_id]
        self.assertEqual((path.read_bytes(), title), (b"will", "The will"))


if __name__ == "__main__":
    unittest.main()
