"""Other names, the people at events (godparents, witnesses) and sources with citations."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import edits  # noqa: E402
import storage  # noqa: E402
from model import (  # noqa: E402
    FORMAT_VERSION, Family, Person, Tree, cited_sources, family_marriage, person_events, person_names, roles_of,
    tree_sources, validate,
)

BOOK = {"title": "Matična knjiga krštenih, župa sv. Lovre, Trogir 1900-1925", "repository": "Državni arhiv u Splitu"}


def parish_tree():
    """Davor's baptism: Dragan was his godfather, a priest is named only in writing."""
    people = {
        "ivan": Person("ivan", given="Ivan", surname="Radić", sex="M"),
        "davor": Person("davor", given="Davor", surname="Radić", sex="M", birth={
            "date": "1957", "place": "Trogir",
            "citations": [{"source": "s1", "page": "str. 47, br. 112", "quality": "original"}],
            "people": [{"person": "dragan", "role": "godfather"}, {"name": "don Ante", "role": "priest"}]}),
        "dragan": Person("dragan", given="Dragan", surname="Radić", sex="M"),
    }
    people["ivan"].extra["names"] = [{"given": "Joannes", "surname": "Radich", "type": "latin",
                                      "citations": [{"source": "s1"}]}]
    families = {"f": Family("f", ["ivan"], "unknown", [{"person": "davor", "link": "birth"},
                                                       {"person": "dragan", "link": "birth"}],
                            {"marriage": {"date": "1950", "people": [{"name": "Kata", "role": "witness"}]}})}
    people["ivan"].birth = {"date": "1708/09-02-10", "place": ""}
    people["dragan"].birth = {"date": "abt 1712 julian", "place": "Trogir"}
    people["davor"].extra["events"] = [{"type": "residence", "date": "from 1950 to 1960", "place": "Trogir"},
                                       {"type": "occupation", "date": "from 1975", "text": "stolar"}]
    people["ivan"].extra["tasks"] = [{"text": "Find Ivan's death in the Trogir books", "done": False}]
    people["ivan"].extra["story"] = "Ivan was a fisherman.\n\nHe built the house in 1950."
    places = {"Trogir": {"parent": "Splitsko-dalmatinska", "kind": "town", "lat": 43.5167, "lon": 16.25,
                         "old_names": [{"name": "Traù", "until": "1918"}]},
              "Splitsko-dalmatinska": {"parent": "Hrvatska", "kind": "county"}, "Hrvatska": {"kind": "country"}}
    return Tree(people, families, {"sources": {"s1": BOOK}, "places": places})


class ModelTests(unittest.TestCase):
    def test_the_tree_reads_its_sources_names_and_roles(self):
        tree = parish_tree()
        self.assertEqual(tree_sources(tree)["s1"]["title"], BOOK["title"])
        self.assertEqual(cited_sources(tree), {"s1": 2})
        self.assertEqual(person_names(tree.people["ivan"])[0]["given"], "Joannes")
        self.assertEqual([(role, owner, kind) for role, owner, kind, _f in roles_of(tree, "dragan")],
                         [("godfather", "davor", "birth")])
        self.assertEqual(family_marriage(tree.families["f"])["people"], [{"role": "witness", "name": "Kata"}])
        self.assertEqual(validate(tree), [])

    def test_dangling_references_are_reported(self):
        tree = parish_tree()
        del tree.extra["sources"]["s1"]
        tree.people["davor"].birth["people"].append({"person": "nobody", "role": "godmother"})
        self.assertEqual(sorted(i.code for i in validate(tree)),
                         ["missing_role_person", "missing_source", "missing_source"])


class EditTests(unittest.TestCase):
    def test_editing_without_changes_keeps_everything(self):
        from dialogs import person_to_values
        tree = parish_tree()
        before = json.dumps(tree.to_dict(), sort_keys=True)
        for person_id in tree.people:
            edits.update_person(tree, person_id, person_to_values(tree.people[person_id]))
        marriage = family_marriage(tree.families["f"])
        edits.set_marriage(tree, "f", marriage["date"], marriage["place"], marriage.get("citations"),
                           marriage.get("people"))
        self.assertEqual(json.dumps(tree.to_dict(), sort_keys=True), before)

    def test_life_events_keep_their_citations_and_people(self):
        tree = parish_tree()
        event = {"type": "baptism", "date": "1957", "citations": [{"source": "s1", "page": "47"}],
                 "people": [{"person": "dragan", "role": "godfather"}]}
        edits.update_person(tree, "davor", {**_values(tree, "davor"), "events": [event]})
        self.assertEqual(person_events(tree.people["davor"])[0]["people"], [{"role": "godfather", "person": "dragan"}])

    def test_a_citation_never_invents_a_death(self):
        tree = parish_tree()
        edits.update_person(tree, "ivan", {**_values(tree, "ivan"), "death_citations": [{"source": "s1"}]})
        self.assertIsNone(tree.people["ivan"].death)

    def test_deleting_a_godparent_keeps_their_name_in_the_record(self):
        tree = parish_tree()
        edits.delete_person(tree, "dragan")
        self.assertIn({"role": "godfather", "name": "Dragan Radić"}, tree.people["davor"].birth["people"])
        self.assertEqual(validate(tree), [])

    def test_merging_moves_roles_and_turns_a_second_name_into_another_name(self):
        tree = parish_tree()
        tree.people["slobo"] = Person("slobo", given="Bobo", surname="Radić", sex="M")
        tree.people["davor"].birth["people"].append({"person": "slobo", "role": "witness"})
        edits.merge_people(tree, "dragan", "slobo")
        roles = [(r, o) for r, o, _k, _f in roles_of(tree, "dragan")]
        self.assertEqual(roles, [("godfather", "davor"), ("witness", "davor")])
        self.assertIn({"given": "Bobo", "surname": "Radić", "type": "other"}, tree.people["dragan"].extra["names"])
        self.assertEqual(validate(tree), [])

    def test_merging_combines_citations_without_repeats(self):
        tree = parish_tree()
        tree.people["z2"] = Person("z2", given="Davor", surname="Radić", birth={
            "date": "1957", "place": "", "citations": [{"source": "s1", "page": "str. 47, br. 112", "quality": "original"},
                                                       {"source": "s1", "page": "str. 3"}]})
        edits.merge_people(tree, "davor", "z2")
        self.assertEqual([c["page"] for c in tree.people["davor"].birth["citations"]], ["str. 47, br. 112", "str. 3"])


class CombineAndShareTests(unittest.TestCase):
    def test_combining_with_its_own_gedcom_keeps_names_roles_and_sources_once(self):
        import combine
        from gedcom import read_gedcom, write_gedcom
        mine = parish_tree()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "f.ged"
            path.write_text(write_gedcom(mine, path), encoding="utf-8")
            theirs = read_gedcom(path).tree
        self.assertEqual(person_names(next(p for p in theirs.people.values() if p.given == "Ivan"))[0]["given"],
                         "Joannes")
        suggestions = combine.suggest_matches(mine, theirs)
        result = combine.combine(mine, theirs, {s.theirs: s.mine for s in suggestions if s.accepted})
        tree = result.tree
        self.assertEqual(result.added, 0)
        self.assertEqual(len(tree_sources(tree)), 1)  # Their copy of the parish book is yours.
        self.assertEqual(cited_sources(tree), {"s1": 2})
        self.assertEqual(tree.people["davor"].birth["people"],
                         [{"role": "godfather", "person": "dragan"}, {"role": "priest", "name": "don Ante"}])
        self.assertEqual(family_marriage(tree.families["f"])["people"], [{"role": "witness", "name": "Kata"}])
        self.assertEqual(len(person_names(tree.people["ivan"])), 1)
        self.assertEqual(validate(tree), [])

    def test_a_relatives_sources_and_godparents_come_across(self):
        import combine
        mine = Tree({"z": Person("z", given="Davor", surname="Radić", sex="M", birth={"date": "1957", "place": ""})},
                    {}, {"sources": {"mine": {"title": "Obiteljska Biblija"}}})
        theirs = parish_tree()
        result = combine.combine(mine, theirs, {"davor": "z"})
        tree = result.tree
        self.assertEqual(sorted(s["title"] for s in tree_sources(tree).values()), sorted(["Obiteljska Biblija", BOOK["title"]]))
        godfather = tree.people["z"].birth["people"][0]
        self.assertEqual(tree.people[godfather["person"]].given, "Dragan")
        self.assertEqual(validate(tree), [])

    def test_a_shared_copy_keeps_only_sources_still_cited(self):
        import datetime
        import privacy
        tree = parish_tree()
        tree.extra["sources"]["s2"] = {"title": "Hospital record of Davor"}
        tree.people["davor"].extra["notes_private"] = True
        tree.people["davor"].birth["citations"].append({"source": "s2", "document": "media/docs/x.pdf"})
        tree.people["davor"].living = "yes"
        tree.people["ivan"].living = "no"
        tree.people["ivan"].death = {"date": "1980", "place": ""}
        shared = privacy.shareable(tree, datetime.date(2026, 11, 13))
        self.assertEqual(set(tree_sources(shared)), {"s1"})  # Ivan's other name still cites the book.
        self.assertEqual(validate(shared), [])


def _values(tree, person_id):
    from dialogs import person_to_values
    return person_to_values(tree.people[person_id])


class MigrationTests(unittest.TestCase):
    OLD = {
        "format_version": 1,
        "people": {"a": {"given": "Ana", "birth": {"date": "1921", "place": "", "source": "Parish book"},
                         "events": [{"type": "occupation", "text": "tailor", "source": "Parish book"},
                                    {"type": "residence", "place": "Split", "source": "Census 1931"}]},
                   "b": {"given": "Ivo", "living": "no", "death": {"date": "", "place": "", "source": " "}}},
        "families": {"f": {"partners": ["a", "b"], "children": [], "marriage": {"date": "1940", "source": "Census 1931"}}},
    }

    def folder(self, data):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name) / "Old.tree"
        folder.mkdir()
        (folder / "tree.json").write_text(json.dumps(data), encoding="utf-8")
        return folder

    def check(self, tree):
        sources = tree_sources(tree)
        self.assertEqual(sorted(s["title"] for s in sources.values()), ["Census 1931", "Parish book"])
        by_title = {s["title"]: k for k, s in sources.items()}
        ana = tree.people["a"]
        self.assertEqual(ana.birth["citations"], [{"source": by_title["Parish book"]}])
        self.assertNotIn("source", ana.birth)
        self.assertEqual([e["citations"][0]["source"] for e in person_events(ana)],
                         [by_title["Parish book"], by_title["Census 1931"]])
        self.assertEqual(family_marriage(tree.families["f"])["citations"], [{"source": by_title["Census 1931"]}])
        self.assertNotIn("citations", tree.people["b"].death)  # An empty old source line is just dropped.
        self.assertEqual(validate(tree), [])
        self.assertFalse(any("source" in fact for _o, _k, fact in __import__("model").stored_facts(tree)))

    def test_opening_converts_an_old_tree_and_keeps_the_old_file(self):
        folder = self.folder(self.OLD)
        self.check(storage.open_tree(folder).tree)
        [backup] = storage._backups(folder)
        self.assertEqual(json.loads((backup / "tree.json").read_text(encoding="utf-8"))["format_version"], 1)

    def test_reading_a_relatives_old_tree_converts_it_without_writing(self):
        folder = self.folder(self.OLD)
        before = (folder / "tree.json").read_bytes()
        self.check(storage.read_tree(folder))
        self.assertEqual((folder / "tree.json").read_bytes(), before)
        self.assertFalse((folder / "backups").exists())

    def test_restoring_an_old_backup_converts_it(self):
        folder = self.folder(self.OLD)
        backup = folder / "backups" / "backup-old"
        backup.mkdir(parents=True)
        (backup / "tree.json").write_text(json.dumps(self.OLD), encoding="utf-8")
        self.check(storage.read_backup(backup))

    def test_a_converted_tree_is_saved_in_the_new_format(self):
        folder = self.folder(self.OLD)
        opened = storage.open_tree(folder)
        storage.save_tree(folder, opened.tree)
        saved = json.loads((folder / "tree.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["format_version"], FORMAT_VERSION)
        self.check(storage.open_tree(folder).tree)


if __name__ == "__main__":
    unittest.main()
