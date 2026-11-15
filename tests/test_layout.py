"""Layout tests: nothing overlaps, and awkward families do not break it."""
import itertools
import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import house_layout as hl
from house_layout import layout_ancestors, layout_house
from model import Family, Person, Tree
from sample import sample_tree


def family(key, partners, children=()):
    return Family(key, list(partners), "married", [{"person": c, "link": "birth"} for c in children])


def tree_of(names, families=()):
    return Tree({n: Person(n, given=n) for n in names}, {f.id: f for f in families})


class LayoutCase(unittest.TestCase):
    def assert_no_overlap(self, layout):
        for one, two in itertools.combinations(layout.cards, 2):
            if one.y == two.y:
                self.assertGreaterEqual(
                    abs(one.x - two.x), hl.PORTRAIT_W, f"{one.person_id} / {two.person_id}"
                )

    def ids(self, layout):
        return [card.person_id for card in layout.cards]

    def card(self, layout, person_id):
        return next(c for c in layout.cards if c.person_id == person_id)


class AncestorLayoutTests(LayoutCase):
    def test_shows_both_sides_of_the_family(self):
        layout = layout_ancestors(sample_tree(), "ivana")
        self.assertEqual(
            set(self.ids(layout)), {"ivana", "luka", "mara", "ante", "ruzica", "stipe", "jela"}
        )
        self.assert_no_overlap(layout)

    def test_each_generation_is_a_row_above(self):
        layout = layout_ancestors(sample_tree(), "ivana")
        self.assertEqual(self.card(layout, "ivana").y, 0)
        self.assertEqual(self.card(layout, "luka").y, -hl.ROW_H)
        self.assertEqual(self.card(layout, "ante").y, -2 * hl.ROW_H)

    def test_child_is_centred_under_parents(self):
        layout = layout_ancestors(sample_tree(), "ivana")
        luka, mara, ivana = (self.card(layout, k) for k in ("luka", "mara", "ivana"))
        self.assertEqual(ivana.x, (luka.x + mara.x) / 2)

    def test_person_with_no_parents_or_one_parent(self):
        self.assertEqual(self.ids(layout_ancestors(sample_tree(), "ante")), ["ante"])
        tree = tree_of("ab", [family("f", ["a"], ["b"])])
        layout = layout_ancestors(tree, "b")
        self.assertEqual(self.card(layout, "a").x, self.card(layout, "b").x)

    def test_loops_and_unknown_people_are_safe(self):
        tree = tree_of("ab", [family("f", ["a"], ["b"]), family("g", ["b"], ["a"])])
        self.assertEqual(set(self.ids(layout_ancestors(tree, "a"))), {"a", "b"})
        self.assertEqual(layout_ancestors(tree, "nope").cards, [])

    def test_deep_pedigree_is_limited(self):
        names, families = ["p0"], []
        for n in range(40):
            names.append(f"p{n + 1}")
            families.append(family(f"f{n}", [f"p{n + 1}"], [f"p{n}"]))
        layout = layout_ancestors(tree_of(names, families), "p0")
        self.assertEqual(len(layout.cards), hl.MAX_ANCESTOR_GENERATIONS + 1)


class HouseLayoutTests(LayoutCase):
    def test_sample_house_shape(self):
        layout = layout_house(sample_tree(), "ante")
        self.assert_no_overlap(layout)
        self.assertEqual(len(layout.cards), 13)
        self.assertEqual({c.y for c in layout.cards}, {0.0, hl.ROW_H, 2 * hl.ROW_H})

    def test_partner_sits_right_of_blood_relative_in_same_row(self):
        layout = layout_house(sample_tree(), "ante")
        luka, mara = self.card(layout, "luka"), self.card(layout, "mara")
        self.assertEqual(luka.y, mara.y)
        self.assertGreater(mara.x, luka.x)
        self.assertTrue(luka.blood)
        self.assertFalse(mara.blood)

    def test_partners_parents_are_not_shown(self):
        ids = self.ids(layout_house(sample_tree(), "ante"))
        self.assertNotIn("stipe", ids)
        self.assertNotIn("zvonko", ids)

    def test_child_line_reaches_the_blood_relatives_portrait(self):
        layout = layout_house(sample_tree(), "ante")
        luka = self.card(layout, "luka")
        wanted = (luka.x + hl.PORTRAIT_W / 2, luka.y)
        self.assertIn(wanted, [(x2, y2) for _, _, x2, y2 in layout.lines])

    def test_single_child_centres_under_the_couple(self):
        layout = layout_house(sample_tree(), "ante")
        josip, ana, tomo = (self.card(layout, k) for k in ("josip", "ana", "tomo"))
        couple_middle = (josip.x + hl.PORTRAIT_W + ana.x) / 2
        self.assertEqual(tomo.x + hl.PORTRAIT_W / 2, couple_middle)

    def test_remarriage_with_children_from_both(self):
        tree = tree_of(
            "abcxyz",
            [family("f", ["a", "b"], ["x", "y"]), family("g", ["a", "c"], ["z"])],
        )
        layout = layout_house(tree, "a")
        self.assert_no_overlap(layout)
        self.assertEqual(sorted(self.ids(layout)), list("abcxyz"))

    def test_single_parent_and_person_with_no_family(self):
        tree = tree_of("abc", [family("f", ["a"], ["b", "c"])])
        layout = layout_house(tree, "a")
        self.assert_no_overlap(layout)
        self.assertEqual(len(layout.cards), 3)
        self.assertEqual(len(layout_house(tree_of("a"), "a").cards), 1)

    def test_missing_people_are_skipped_not_fatal(self):
        tree = tree_of("a", [family("f", ["a", "ghost"], ["phantom"])])
        self.assertEqual(self.ids(layout_house(tree, "a")), ["a"])

    def test_cousin_marriage_does_not_repeat_their_children(self):
        tree = tree_of(
            ["top", "p1", "p2", "x", "y", "kid"],
            [
                family("f", ["top"], ["p1", "p2"]),
                family("g", ["p1"], ["x"]),
                family("h", ["p2"], ["y"]),
                family("m", ["x", "y"], ["kid"]),
            ],
        )
        layout = layout_house(tree, "top")
        self.assertEqual(self.ids(layout).count("kid"), 1)
        self.assert_no_overlap(layout)

    def test_ancestor_loop_does_not_hang(self):
        tree = tree_of("ab", [family("f", ["a"], ["b"]), family("g", ["b"], ["a"])])
        self.assertEqual(self.ids(layout_house(tree, "a")), ["a", "b"])

    def test_wide_family_with_many_generations(self):
        names = ["root"]
        families = []
        for one in range(5):
            names.append(f"c{one}")
            names.append(f"s{one}")
            kids = [f"k{one}{two}" for two in range(5)]
            names.extend(kids)
            families.append(family(f"f{one}", [f"c{one}", f"s{one}"], kids))
        families.append(family("top", ["root"], [f"c{n}" for n in range(5)]))
        layout = layout_house(tree_of(names, families), "root")
        self.assert_no_overlap(layout)
        self.assertEqual(len(layout.cards), len(names))

    def test_person_sits_between_two_partners(self):
        tree = tree_of(
            "abcxz",
            [family("f", ["a", "b"], ["x"]), family("g", ["a", "c"], ["z"])],
        )
        layout = layout_house(tree, "a")
        self.assert_no_overlap(layout)
        a, b, c = (self.card(layout, k) for k in "abc")
        self.assertLess(c.x, a.x)
        self.assertLess(a.x, b.x)
        self.assertLess(self.card(layout, "z").x, self.card(layout, "x").x)

    def test_three_partners_and_a_single_parent_family_do_not_overlap(self):
        tree = tree_of(
            "abcdwxyz",
            [
                family("f", ["a", "b"], ["w"]),
                family("g", ["a", "c"], ["x"]),
                family("h", ["a", "d"], ["y"]),
                family("i", ["a"], ["z"]),
            ],
        )
        layout = layout_house(tree, "a")
        self.assert_no_overlap(layout)
        self.assertEqual(len(layout.cards), 8)

    def test_collapsed_person_hides_descendants_but_keeps_partner(self):
        tree = sample_tree()
        layout = layout_house(tree, "ante", {"luka"})
        ids = self.ids(layout)
        self.assertIn("luka", ids)
        self.assertIn("mara", ids)
        for hidden in ("ivana", "marko", "petar"):
            self.assertNotIn(hidden, ids)
        self.assertEqual(layout.hidden, {"luka": 3})
        self.assert_no_overlap(layout)

    def test_collapsing_someone_with_no_descendants_shows_nothing(self):
        layout = layout_house(sample_tree(), "ante", {"tomo"})
        self.assertEqual(layout.hidden, {})

    def test_family_line_heads_lists_each_couple_once(self):
        heads = dict(sample_tree().family_line_heads())
        self.assertEqual(heads["ante"], 8)
        self.assertEqual(heads["stipe"], 5)
        self.assertNotIn("ruzica", heads)
        self.assertNotIn("mara", heads)
        self.assertNotIn("luka", heads)

    def test_absurdly_deep_data_does_not_crash(self):
        names = [f"p{n}" for n in range(1500)]
        families = [family(f"f{n}", [f"p{n}"], [f"p{n + 1}"]) for n in range(1499)]
        tree = tree_of(names, families)
        layout = layout_house(tree, "p0")
        self.assertEqual(len(layout.cards), hl.MAX_GENERATIONS + 1)

    def test_big_tree_stays_fast(self):
        rng = random.Random(1)
        names = ["root"]
        families = []
        frontier = ["root"]
        while len(names) < 5000:
            parent = frontier.pop(0)
            spouse = f"s{len(names)}"
            kids = [f"k{len(names)}_{n}" for n in range(rng.randint(1, 5))]
            names.extend([spouse] + kids)
            frontier.extend(kids)
            families.append(family(f"f{len(names)}", [parent, spouse], kids))
        tree = tree_of(names, families)
        start = time.perf_counter()
        self.assertEqual(tree.default_house_root(), "root")
        layout = layout_house(tree, "root")
        seconds = time.perf_counter() - start
        self.assertEqual(len(layout.cards), len(names))
        self.assert_no_overlap_fast(layout)
        self.assertLess(seconds, 2.0)

    def assert_no_overlap_fast(self, layout):
        rows = {}
        for card in layout.cards:
            rows.setdefault(card.y, []).append(card.x)
        for xs in rows.values():
            xs.sort()
            for one, two in zip(xs, xs[1:]):
                self.assertGreaterEqual(two - one, hl.PORTRAIT_W)

    def test_third_partner_is_not_joined_to_the_second(self):
        tree = tree_of(
            "abcdwxy",
            [
                family("f", ["a", "b"], ["w"]),
                family("g", ["a", "c"], ["x"]),
                family("h", ["a", "d"], ["y"]),
            ],
        )
        layout = layout_house(tree, "a")
        self.assert_no_overlap(layout)
        b, d = self.card(layout, "b"), self.card(layout, "d")
        middle = hl.PORTRAIT_H / 2
        for x1, y1, x2, y2 in layout.lines:
            if y1 == y2 == middle:
                self.assertLessEqual(max(x1, x2), b.x, "a line at card height reaches past the first partner")
        self.assertIn((d.x + hl.PORTRAIT_W / 2, d.y), [(x2, y2) for _, _, x2, y2 in layout.lines])

    def test_single_parent_line_starts_below_the_name(self):
        layout = layout_house(tree_of("ab", [family("f", ["a"], ["b"])]), "a")
        tops = [y1 for _, y1, _, y2 in layout.lines if y2 != y1]
        self.assertGreaterEqual(min(tops), hl.PORTRAIT_H + hl.LABEL_H)

    def test_unknown_root_gives_an_empty_house(self):
        self.assertEqual(layout_house(tree_of("a"), "nope").cards, [])

    def test_default_house_is_the_largest(self):
        self.assertEqual(sample_tree().default_house_root(), "ante")
        self.assertIsNone(Tree().default_house_root())

    def test_default_head_follows_listing_not_random_ids(self):
        first_listed, second_listed = "p-ffff", "p-0000"
        tree = tree_of(
            [second_listed, first_listed, "kid"],
            [family("f", [first_listed, second_listed], ["kid"])],
        )
        self.assertEqual(tree.default_house_root(), first_listed)

        swapped_ids = tree_of(
            ["p-ffff", "p-0000", "kid"],
            [family("f", ["p-0000", "p-ffff"], ["kid"])],
        )
        self.assertEqual(swapped_ids.default_house_root(), "p-0000")

    def test_bigger_branch_beats_being_listed_first(self):
        tree = tree_of(
            ["small", "big", "a", "b"],
            [family("f", ["small"], ["a"]), family("g", ["big"], ["a", "b"])],
        )
        self.assertEqual(tree.default_house_root(), "big")


if __name__ == "__main__":
    unittest.main()
