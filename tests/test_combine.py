"""Combining a relative's tree with yours: matching, differences and the combined result."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import combine  # noqa: E402
from edits import copy_tree  # noqa: E402
from gedcom import read_gedcom, write_gedcom  # noqa: E402
from model import Family, Person, Tree, validate  # noqa: E402
from sample import sample_tree  # noqa: E402


def accepted(suggestions):
    return {s.theirs: s.mine for s in suggestions if s.accepted}


def people(tree):
    """Each person's details, without ids, for comparing two trees."""
    return sorted(str({k: v for k, v in p.to_dict().items()}) for p in tree.people.values())


def couples(tree):
    """Who is a parent of whom, by name, for comparing two trees."""
    name = lambda pid: tree.people[pid].display_name  # noqa: E731
    return sorted((tuple(sorted(name(p) for p in f.partners)), tuple(sorted(name(c) for c in f.child_ids)))
                  for f in tree.families.values())


def radic():
    """Two people called Ivan Radić with no dates: a grandfather and a grandson."""
    names = {"ivan": ("Ivan", "Radić", "M"), "durda": ("Đurđa", "Radić", "F"), "davor": ("Davor", "Radić", "M"),
             "dragan": ("Dragan", "Radić", "M"), "ivan2": ("Ivan", "Radić", "M")}
    tree = Tree({k: Person(k, given=g, surname=s, sex=x) for k, (g, s, x) in names.items()}, {
        "f1": Family("f1", ["ivan", "durda"], "married", [{"person": "davor", "link": "birth"},
                                                         {"person": "dragan", "link": "birth"}]),
        "f2": Family("f2", ["dragan"], "unknown", [{"person": "ivan2", "link": "birth"}]),
    })
    return tree


class MatchingTests(unittest.TestCase):
    def test_a_tree_combined_with_itself_changes_nothing(self):
        mine = sample_tree()
        suggestions = combine.suggest_matches(mine, copy_tree(mine))
        self.assertTrue(all(s.accepted and s.mine == s.theirs for s in suggestions))
        result = combine.combine(mine, copy_tree(mine), accepted(suggestions))
        self.assertEqual((result.added, result.joined), (0, len(mine.people)))
        self.assertEqual(people(result.tree), people(mine))
        self.assertEqual(couples(result.tree), couples(mine))
        self.assertEqual(validate(result.tree), [])

    def test_a_tree_combined_with_its_own_gedcom_changes_nothing(self):
        mine = sample_tree()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "family.ged"
            path.write_text(write_gedcom(mine, path), encoding="utf-8")
            theirs = read_gedcom(path).tree
        suggestions = combine.suggest_matches(mine, theirs)
        self.assertEqual(sum(s.accepted for s in suggestions), len(mine.people))
        result = combine.combine(mine, theirs, accepted(suggestions))
        self.assertEqual(result.added, 0)
        self.assertEqual(couples(result.tree), couples(mine))
        self.assertEqual(len(result.tree.people), len(mine.people))

    def test_two_people_with_the_same_name_are_told_apart_by_their_family(self):
        mine = radic()
        theirs = Tree({k: Person(k, given=g, surname="Radić", sex=x) for k, g, x in
                       (("a", "Ivan", "M"), ("b", "Đurđa", "F"), ("c", "Davor", "M"))}, {
            "x": Family("x", ["a", "b"], "married", [{"person": "c", "link": "birth"}])})
        found = {s.theirs: s for s in combine.suggest_matches(mine, theirs)}
        self.assertEqual(found["a"].mine, "ivan")
        self.assertTrue(found["a"].accepted)
        self.assertIn("ivan2", found["a"].alternatives)

    def test_a_name_alone_is_only_a_possible_match(self):
        mine = radic()
        theirs = Tree({"a": Person("a", given="Ivan", surname="Radić", sex="M")}, {})
        suggestion = combine.suggest_matches(mine, theirs)[0]
        self.assertEqual(suggestion.confidence, combine.POSSIBLE)
        self.assertFalse(suggestion.accepted)

    def test_different_birth_years_or_sexes_never_match(self):
        a = Person("a", given="Ivan", birth={"date": "1900", "place": ""})
        self.assertIsNone(combine.person_score(a, Person("b", given="Ivan", birth={"date": "1950", "place": ""})))
        self.assertIsNone(combine.person_score(Person("a", given="Ivan", sex="M"), Person("b", given="Ivan", sex="F")))
        self.assertIsNotNone(combine.person_score(a, Person("b", given="ivan", birth={"date": "1901", "place": ""})))

    def test_no_two_of_theirs_get_the_same_person_of_mine(self):
        mine = Tree({"m": Person("m", given="Ivan", surname="Radić")}, {})
        theirs = Tree({"a": Person("a", given="Ivan", surname="Radić"),
                       "b": Person("b", given="Ivan", surname="Radić")}, {})
        chosen = [s.mine for s in combine.suggest_matches(mine, theirs) if s.mine]
        self.assertEqual(len(chosen), len(set(chosen)))
        with self.assertRaises(ValueError):
            combine.combine(mine, theirs, {"a": "m", "b": "m"})


class CombiningTests(unittest.TestCase):
    def test_new_relatives_come_in_connected(self):
        mine = radic()
        theirs = Tree({k: Person(k, given=g, surname="Radić", sex="M") for k, g in
                       (("a", "Ivan"), ("c", "Davor"), ("d", "Filip"))}, {
            "x": Family("x", ["a"], "unknown", [{"person": "c", "link": "birth"}]),
            "y": Family("y", ["c"], "unknown", [{"person": "d", "link": "birth"}])})
        result = combine.combine(mine, theirs, {"a": "ivan", "c": "davor"})
        tree = result.tree
        self.assertEqual((result.added, result.joined), (1, 2))
        filip = next(p for p in tree.people.values() if p.given == "Filip")
        self.assertEqual([f.partners for f, _l in tree.parent_families(filip.id)], [["davor"]])
        # Their Davor had only his father recorded; he stays in Ivan and Đurđa's family.
        self.assertEqual([f.id for f, _l in tree.parent_families("davor")], ["f1"])
        self.assertEqual(validate(tree), [])

    def test_their_version_of_a_detail_wins_when_chosen(self):
        mine = Tree({"m": Person("m", given="Ivan", birth={"date": "1900", "place": "Split"})}, {})
        theirs = Tree({"t": Person("t", given="Ivan", birth={"date": "1900", "place": "Trogir"})}, {})
        self.assertEqual([d[0] for d in combine.differences(mine.people["m"], theirs.people["t"])], ["birth.place"])
        self.assertEqual(combine.differences(Person("a", given="Ivan", surname="Radić"),
                                             Person("b", given="Ivan", surname="Radic")), [])
        kept = combine.combine(mine, theirs, {"t": "m"}).tree.people["m"]
        self.assertEqual(kept.birth["place"], "Split")
        self.assertIn("Trogir", kept.notes)  # The other version isn't lost.
        taken = combine.combine(mine, theirs, {"t": "m"}, {"t": {"birth.place"}}).tree.people["m"]
        self.assertEqual(taken.birth["place"], "Trogir")

    def test_a_match_that_would_contradict_the_tree_names_the_pair(self):
        mine = radic()
        # Their Davor is the father of their Ivan: matching both makes Davor his own grandfather.
        theirs = Tree({k: Person(k, given=g, surname="Radić", sex="M") for k, g in (("z", "Davor"), ("i", "Ivan"))},
                      {"x": Family("x", ["z"], "unknown", [{"person": "i", "link": "birth"}])})
        with self.assertRaises(combine.CombineError) as caught:
            combine.combine(mine, theirs, {"z": "davor", "i": "ivan"})
        self.assertIn("Radić", caught.exception.theirs)
        self.assertEqual(len(mine.people), 5)  # Your tree is untouched by a refused combination.

    def test_photos_are_copied_through_the_given_function(self):
        mine = Tree({"m": Person("m", given="Ivan")}, {})
        theirs = Tree({"t": Person("t", given="Ana", photo="media/a.jpg")}, {})
        result = combine.combine(mine, theirs, {}, copy_photo=lambda pid, stored: "media/copied.jpg" if stored else "")
        self.assertEqual({p.photo for p in result.tree.people.values()}, {"", "media/copied.jpg"})
        result = combine.combine(mine, theirs, {})
        self.assertEqual({p.photo for p in result.tree.people.values()}, {""})  # Never their path as is.


if __name__ == "__main__":
    unittest.main()
