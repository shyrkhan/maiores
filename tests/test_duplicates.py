"""Finding people recorded twice in one tree."""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import edits  # noqa: E402
from duplicates import find_duplicates  # noqa: E402
from model import Family, Person, Tree  # noqa: E402


def person(pid, given, surname="Radić", sex="M", born="", **extra):
    return Person(pid, given=given, surname=surname, sex=sex, birth={"date": born, "place": ""} if born else None,
                  extra=extra)


def pairs(tree):
    return {(c.a, c.b): c for c in find_duplicates(tree)}


class FinderTests(unittest.TestCase):
    def test_someone_added_twice_in_two_branches_is_found(self):
        # Ivan entered once as Ante's son and again as Mara's husband, with the same birth year.
        tree = Tree({"ante": person("ante", "Ante", born="1890"), "ivan1": person("ivan1", "Ivan", born="1921"),
                     "ivan2": person("ivan2", "Ivan", born="1921"), "mara": person("mara", "Mara", sex="F")},
                    {"f1": Family("f1", ["ante"], "unknown", [{"person": "ivan1", "link": "birth"}]),
                     "f2": Family("f2", ["ivan2", "mara"], "married", [])})
        found = pairs(tree)
        self.assertIn(("ivan1", "ivan2"), found)
        self.assertIn("dup_same_birth", found[("ivan1", "ivan2")].reasons)
        self.assertEqual(found[("ivan1", "ivan2")].blocked, "")

    def test_brothers_with_the_same_name_and_no_dates_are_only_a_maybe(self):
        tree = Tree({"dad": person("dad", "Ante"), "a": person("a", "Ivan"), "b": person("b", "Ivan")},
                    {"f": Family("f", ["dad"], "unknown", [{"person": "a", "link": "birth"},
                                                           {"person": "b", "link": "birth"}])})
        found = pairs(tree)[("a", "b")]
        self.assertIn("dup_maybe_siblings", found.reasons)
        self.assertLessEqual(found.score, 2.0)

    def test_pairs_a_merge_would_refuse_say_why(self):
        tree = Tree({"a": person("a", "Ivan", born="1900"), "b": person("b", "Ivan", born="1900"),
                     "c": person("c", "Ivan", born="1901")},
                    {"f": Family("f", ["a", "b"], "married", [{"person": "c", "link": "birth"}])})
        found = pairs(tree)
        self.assertEqual(found[("a", "b")].blocked, "dup_blocked_partners")
        self.assertEqual(found[("a", "c")].blocked, "dup_blocked_ancestor")

    def test_different_people_never_show(self):
        tree = Tree({"a": person("a", "Ivan", born="1900"), "b": person("b", "Ivan", born="1950"),
                     "c": person("c", "Ivana", sex="F"), "d": person("d", "Ivan", sex="F")}, {})
        self.assertEqual(pairs(tree), {})

    def test_a_pair_marked_different_stays_away_and_hidden_people_are_skipped(self):
        tree = Tree({"a": person("a", "Ivan", born="1921"), "b": person("b", "Ivan", born="1921"),
                     "h": person("h", "", hidden=True)}, {})
        self.assertIn(("a", "b"), pairs(tree))
        edits.mark_not_duplicate(tree, "b", "a")
        self.assertEqual(pairs(tree), {})

    def test_other_names_count(self):
        tree = Tree({"a": person("a", "Ivan", born="1921", names=[{"given": "Joannes", "surname": "Radich"}]),
                     "b": person("b", "Joannes", surname="Radich", born="1921")}, {})
        self.assertIn(("a", "b"), pairs(tree))

    def test_a_large_tree_is_quick(self):
        sys.path.insert(0, str(ROOT / "devtools"))
        from perf import generate
        tree = generate(6000)
        start = time.perf_counter()
        find_duplicates(tree)
        self.assertLess(time.perf_counter() - start, 10.0)


if __name__ == "__main__":
    unittest.main()
