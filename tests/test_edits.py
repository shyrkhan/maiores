"""Edit rules, including long random sessions that must never damage the data."""
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edits
from edits import EditError, History, copy_tree, make_person
from house_layout import layout_house
from model import Family, Person, Tree, date_input_text, normalize_date_input, validate
from sample import sample_tree
from storage import create_tree, open_tree, save_tree


def person(name="X", **values):
    return make_person({"given": name, **values})


def with_person(name="A"):
    tree = Tree()
    somebody = person(name)
    edits.add_first_person(tree, somebody)
    return tree, somebody.id


class DateInputTests(unittest.TestCase):
    def test_accepted(self):
        cases = {
            "1921": "1921",
            "14.5.1921.": "1921-05-14",
            "14. 5. 1921.": "1921-05-14",
            "5.1921": "1921-05",
            "1921-05-14": "1921-05-14",
            "about 1921": "abt 1921",
            "oko 1921": "abt 1921",
            "c. 1921": "abt 1921",
            "prije 1900": "bef 1900",
            "after 1900": "aft 1900",
            "1880-1885": "1880/1885",
            "": "",
        }
        for typed, stored in cases.items():
            self.assertEqual(normalize_date_input(typed), stored, typed)

    def test_refused(self):
        for typed in ("3/2/1951", "32.1.1999", "29.2.2023", "soon", "about 1880-1885", "1885-1880"):
            self.assertIsNone(normalize_date_input(typed), typed)

    def test_shown_text_reads_back_the_same(self):
        for stored in ("1921", "1921-05", "1921-05-14", "abt 1921", "bef 1900", "aft 1900", "1880/1885"):
            self.assertEqual(normalize_date_input(date_input_text(stored)), stored)


class FieldTests(unittest.TestCase):
    def test_death_date_marks_deceased(self):
        somebody = person(living="yes", death_date="1990")
        self.assertEqual(somebody.living, "no")
        self.assertEqual(somebody.death_date, "1990")

    def test_living_has_no_death_record(self):
        self.assertIsNone(person(living="yes").death)

    def test_deceased_without_date_is_allowed(self):
        somebody = person(living="no")
        self.assertEqual(somebody.living, "no")
        self.assertEqual(somebody.death, {"date": "", "place": ""})

    def test_bad_dates_are_refused(self):
        with self.assertRaises(EditError):
            person(birth_date="soon")
        with self.assertRaises(EditError):
            person(birth_date="2000", death_date="1990")

    def test_refused_update_changes_nothing(self):
        tree, somebody = with_person("Keep")
        with self.assertRaises(EditError):
            edits.update_person(tree, somebody, {"given": "Lost", "birth_date": "soon"})
        self.assertEqual(tree.people[somebody].given, "Keep")


class AddPartnerTests(unittest.TestCase):
    def test_creates_a_couple(self):
        tree, a = with_person()
        b = person("B")
        edits.add_partner(tree, a, b)
        family = tree.families_of(a)[0]
        self.assertEqual(family.partners, [a, b.id])
        self.assertEqual(family.relationship, "married")

    def test_fills_free_slot_so_existing_child_gets_both_parents(self):
        tree, a = with_person()
        child = person("Child")
        edits.add_child(tree, a, child)
        partner = person("B")
        edits.add_partner(tree, a, partner)
        self.assertEqual(len(tree.families), 1)
        family = tree.birth_family_of(child.id)
        self.assertEqual(family.partners, [a, partner.id])

    def test_can_decline_to_fill_the_slot(self):
        tree, a = with_person()
        child = person("Child")
        edits.add_child(tree, a, child)
        edits.add_partner(tree, a, person("B"), new_family=True)
        self.assertEqual(len(tree.families), 2)
        self.assertEqual(len(tree.birth_family_of(child.id).partners), 1)

    def test_several_free_slots_must_be_chosen(self):
        tree, a = with_person()
        edits.add_child(tree, a, person("One"), new_family=True)
        edits.add_child(tree, a, person("Two"), new_family=True)
        before = copy_tree(tree)
        with self.assertRaises(EditError):
            edits.add_partner(tree, a, person("B"))
        self.assertEqual(tree, before)

    def test_second_partner_gets_own_family(self):
        tree, a = with_person()
        edits.add_partner(tree, a, person("B"))
        edits.add_partner(tree, a, person("C"))
        self.assertEqual(len(tree.families_of(a)), 2)


class AddChildTests(unittest.TestCase):
    def test_no_family_creates_single_parent_family(self):
        tree, a = with_person()
        child = person("Child")
        edits.add_child(tree, a, child)
        self.assertEqual(tree.birth_family_of(child.id).partners, [a])

    def test_one_family_is_used(self):
        tree, a = with_person()
        partner = person("B")
        edits.add_partner(tree, a, partner)
        child = person("Child")
        edits.add_child(tree, a, child)
        self.assertEqual(tree.birth_family_of(child.id).partners, [a, partner.id])

    def test_several_families_require_a_choice(self):
        tree, a = with_person()
        edits.add_partner(tree, a, person("B"))
        second = person("C")
        edits.add_partner(tree, a, second)
        before = copy_tree(tree)
        with self.assertRaises(EditError):
            edits.add_child(tree, a, person("Child"))
        self.assertEqual(tree, before)
        chosen = next(f for f in tree.families_of(a) if second.id in f.partners)
        child = person("Child")
        edits.add_child(tree, a, child, family_id=chosen.id)
        self.assertIn(second.id, tree.birth_family_of(child.id).partners)

    def test_unknown_other_parent(self):
        tree, a = with_person()
        edits.add_partner(tree, a, person("B"))
        edits.add_partner(tree, a, person("C"))
        child = person("Child")
        edits.add_child(tree, a, child, new_family=True)
        self.assertEqual(tree.birth_family_of(child.id).partners, [a])

    def test_adoption_is_recorded(self):
        tree, a = with_person()
        child = person("Child")
        edits.add_child(tree, a, child, link="adopted")
        self.assertEqual(tree.birth_family_of(child.id).children[0]["link"], "adopted")


class AddParentAndSiblingTests(unittest.TestCase):
    def test_no_birth_family_creates_one(self):
        tree, a = with_person()
        parent = person("P")
        edits.add_parent(tree, a, parent)
        self.assertEqual(tree.birth_family_of(a).partners, [parent.id])

    def test_second_parent_joins_the_same_family(self):
        tree, a = with_person()
        one, two = person("P"), person("Q")
        edits.add_parent(tree, a, one)
        edits.add_parent(tree, a, two)
        self.assertEqual(len(tree.families), 1)
        self.assertEqual(tree.birth_family_of(a).partners, [one.id, two.id])

    def test_third_parent_is_refused(self):
        tree, a = with_person()
        edits.add_parent(tree, a, person("P"))
        edits.add_parent(tree, a, person("Q"))
        before = copy_tree(tree)
        self.assertFalse(edits.can_add_parent(tree, a))
        with self.assertRaises(EditError):
            edits.add_parent(tree, a, person("R"))
        self.assertEqual(tree, before)

    def test_sibling_without_known_parents_then_a_parent_joins_both(self):
        tree, a = with_person()
        self.assertTrue(edits.can_add_sibling(tree, a))
        sibling = person("S")
        edits.add_sibling(tree, a, sibling)
        self.assertEqual(tree.birth_family_of(sibling.id), tree.birth_family_of(a))
        self.assertEqual(tree.birth_family_of(a).partners, [])
        parent = person("P")
        edits.add_parent(tree, a, parent)
        self.assertEqual(tree.birth_family_of(sibling.id).partners, [parent.id])
        self.assertEqual(validate(tree), [])

    def test_new_people_appear_in_the_view(self):
        tree, a = with_person()
        parent = person("P")
        edits.add_parent(tree, a, parent)
        sibling = person("S")
        edits.add_sibling(tree, a, sibling)
        shown = {card.person_id for card in layout_house(tree, tree.top_ancestor_of(a)).cards}
        self.assertEqual(shown, {a, parent.id, sibling.id})


class DeleteTests(unittest.TestCase):
    def test_empty_family_is_dropped(self):
        tree, a = with_person()
        partner = person("B")
        edits.add_partner(tree, a, partner)
        edits.delete_person(tree, partner.id)
        self.assertEqual(tree.families, {})
        self.assertEqual(validate(tree), [])

    def test_children_keep_remaining_parent(self):
        tree = sample_tree()
        edits.delete_person(tree, "luka")
        self.assertNotIn("luka", tree.people)
        self.assertEqual(tree.birth_family_of("ivana").partners, ["mara"])
        self.assertEqual(validate(tree), [])

    def test_only_child_of_unknown_parents_leaves_no_family(self):
        tree, a = with_person()
        parent = person("P")
        edits.add_parent(tree, a, parent)
        edits.delete_person(tree, parent.id)
        self.assertEqual(tree.families, {})

    def test_siblings_stay_connected_without_parents(self):
        tree, a = with_person()
        parent = person("P")
        edits.add_parent(tree, a, parent)
        sibling = person("S")
        edits.add_sibling(tree, a, sibling)
        edits.delete_person(tree, parent.id)
        self.assertEqual(
            set(tree.birth_family_of(a).child_ids), {a, sibling.id}
        )

    def test_missing_person_is_refused(self):
        with self.assertRaises(EditError):
            edits.delete_person(sample_tree(), "nobody")


class LinkTests(unittest.TestCase):
    def test_partner_loops_and_repeats_are_refused(self):
        tree = sample_tree()
        before = copy_tree(tree)
        for one, two in (("ante", "ante"), ("ante", "luka"), ("ivana", "ante"), ("luka", "mara")):
            with self.assertRaises(EditError):
                edits.link_partner(tree, one, two)
        self.assertEqual(tree, before)

    def test_child_rules(self):
        tree = sample_tree()
        before = copy_tree(tree)
        with self.assertRaises(EditError):
            edits.link_child(tree, "ivana", "ante")
        with self.assertRaises(EditError):
            edits.link_child(tree, "luka", "tomo")
        with self.assertRaises(EditError):
            edits.link_child(tree, "ante", "ante")
        self.assertEqual(tree, before)
        edits.link_child(tree, "zvonko", "ana")
        self.assertEqual(tree.birth_family_of("ana").partners, ["zvonko"])
        self.assertEqual(validate(tree), [])

    def test_parent_rules(self):
        tree = sample_tree()
        before = copy_tree(tree)
        with self.assertRaises(EditError):
            edits.link_parent(tree, "ante", "ivana")
        with self.assertRaises(EditError):
            edits.link_parent(tree, "ivana", "zvonko")
        self.assertEqual(tree, before)
        edits.link_parent(tree, "ana", "zvonko")
        self.assertEqual(tree.birth_family_of("ana").partners, ["zvonko"])
        self.assertEqual(validate(tree), [])

    def test_siblings_cannot_become_parent_and_child(self):
        tree, a = with_person()
        edits.add_parent(tree, a, person("P"))
        sibling = person("S")
        edits.add_sibling(tree, a, sibling)
        before = copy_tree(tree)
        with self.assertRaises(EditError):
            edits.link_parent(tree, a, sibling.id)
        self.assertEqual(tree, before)

    def test_other_parent_cannot_become_a_descendant(self):
        tree, a = with_person()
        partner = person("B")
        edits.add_partner(tree, a, partner)
        grandchild_of_partner = person("G")
        edits.add_child(tree, partner.id, person("K"), new_family=True)
        kid = next(p for p in tree.people.values() if p.given == "K")
        edits.add_child(tree, kid.id, grandchild_of_partner)
        family = next(f for f in tree.families_of(a) if partner.id in f.partners)
        before = copy_tree(tree)
        edits.link_partner(tree, a, kid.id)
        tree = before
        with self.assertRaises(EditError):
            edits.link_child(tree, a, partner.id, family_id=family.id)
        self.assertEqual(tree, before)

    def test_new_parent_cannot_descend_from_a_sibling(self):
        tree, a = with_person()
        edits.add_parent(tree, a, person("P"))
        sibling = person("S")
        edits.add_sibling(tree, a, sibling)
        nephew = person("N")
        edits.add_child(tree, sibling.id, nephew)
        before = copy_tree(tree)
        with self.assertRaises(EditError):
            edits.link_parent(tree, a, nephew.id)
        self.assertEqual(tree, before)

    def test_is_ancestor_handles_loops(self):
        tree = Tree(
            {n: Person(n) for n in "ab"},
            {
                "f": Family("f", ["a"], "unknown", [{"person": "b", "link": "birth"}]),
                "g": Family("g", ["b"], "unknown", [{"person": "a", "link": "birth"}]),
            },
        )
        self.assertTrue(edits.is_ancestor(tree, "a", "b"))
        self.assertFalse(edits.is_ancestor(tree, "x", "a"))


class MergeTests(unittest.TestCase):
    def test_merge_keeps_sources_and_every_life_event(self):
        tree = Tree({
            "a": Person("a", given="Ivan", birth={"date": "1900", "place": "", "citations": [{"source": "s1"}]},
                        extra={"events": [{"type": "occupation", "text": "farmer"}]}),
            "b": Person("b", given="Ivan", birth={"date": "", "place": "Split"},
                        extra={"events": [{"type": "occupation", "text": "farmer"},
                                          {"type": "residence", "place": "Trogir"}]}),
        }, {})
        edits.merge_people(tree, "a", "b")
        ivan = tree.people["a"]
        self.assertEqual(ivan.birth, {"date": "1900", "place": "Split", "citations": [{"source": "s1"}]})
        self.assertEqual([e["type"] for e in ivan.extra["events"]], ["occupation", "residence"])

    def test_the_same_single_parent_twice_becomes_one_family(self):
        tree = Tree({k: Person(k, given=k) for k in ("dad", "ivan", "dad2", "ivan2", "ana")}, {
            "f1": Family("f1", ["dad"], "unknown", [{"person": "ivan", "link": "birth"}]),
            "f2": Family("f2", ["dad2"], "unknown", [{"person": "ivan2", "link": "birth"},
                                                     {"person": "ana", "link": "birth"}]),
        })
        edits.merge_people(tree, "dad", "dad2")
        edits.merge_people(tree, "ivan", "ivan2")
        self.assertEqual(len(tree.families), 1)
        self.assertEqual(sorted(next(iter(tree.families.values())).child_ids), ["ana", "ivan"])

    def test_a_parent_known_on_one_side_only_is_the_same_family(self):
        """Their Ivan has only a father recorded, mine has both parents: merging is no conflict."""
        tree = Tree({k: Person(k, given=k) for k in ("dad", "mum", "ivan", "dad2", "ivan2", "half")}, {
            "f1": Family("f1", ["dad", "mum"], "married", [{"person": "ivan", "link": "birth"}]),
            "f2": Family("f2", ["dad2"], "unknown", [{"person": "ivan2", "link": "birth"},
                                                     {"person": "half", "link": "birth"}]),
        })
        edits.merge_people(tree, "dad", "dad2")
        edits.merge_people(tree, "ivan", "ivan2")
        self.assertEqual([f.id for f, _link in tree.parent_families("ivan")], ["f1"])
        # The other child's mother is still unknown: they are not moved into dad and mum's family.
        self.assertEqual(tree.families["f2"].partners, ["dad"])
        self.assertEqual(tree.families["f2"].child_ids, ["half"])
        self.assertEqual(validate(tree), [])

    def test_details_are_combined_and_differences_kept(self):
        tree = Tree()
        a = person("Ana", surname="Šimić", birth_date="1950", birth_place="", notes="First")
        b = person("Anica", surname="Šimić", birth_date="1951", birth_place="Trogir", notes="Second")
        tree.people = {a.id: a, b.id: b}
        edits.merge_people(tree, a.id, b.id)
        self.assertEqual(list(tree.people), [a.id])
        merged = tree.people[a.id]
        self.assertEqual(merged.given, "Ana")
        self.assertEqual(merged.birth_date, "1950")
        self.assertEqual((merged.birth or {}).get("place"), "Trogir")
        for text in ("First", "Second", "1951"):
            self.assertIn(text, merged.notes)
        self.assertIn({"given": "Anica", "surname": "Šimić", "type": "other"}, merged.extra["names"])
        self.assertEqual(validate(tree), [])

    def test_connections_move_across(self):
        tree = Tree()
        a, duplicate, partner, kid = person("A"), person("A copy"), person("P"), person("K")
        edits.add_first_person(tree, a)
        tree.people[duplicate.id] = duplicate
        edits.add_partner(tree, duplicate.id, partner)
        edits.add_child(tree, duplicate.id, kid)
        edits.merge_people(tree, a.id, duplicate.id)
        self.assertEqual(tree.birth_family_of(kid.id).partners, [a.id, partner.id])
        self.assertEqual(validate(tree), [])

    def test_duplicate_couples_become_one_family(self):
        tree = Tree()
        a, a2, b, kid1, kid2 = person("A"), person("A2"), person("B"), person("K1"), person("K2")
        edits.add_first_person(tree, a)
        tree.people[a2.id] = a2
        edits.add_partner(tree, a.id, b)
        edits.add_child(tree, a.id, kid1)
        edits.link_partner(tree, a2.id, b.id)
        edits.add_child(tree, a2.id, kid2)
        edits.merge_people(tree, a.id, a2.id)
        self.assertEqual(len(tree.families), 1)
        self.assertEqual(set(next(iter(tree.families.values())).child_ids), {kid1.id, kid2.id})

    def test_duplicate_children_of_merged_parents(self):
        tree = Tree()
        p1, p2, c = person("P1"), person("P2"), person("C")
        edits.add_first_person(tree, p1)
        tree.people[p2.id] = p2
        edits.add_child(tree, p1.id, c)
        tree.families["x"] = Family("x", [p2.id], "unknown", [{"person": c.id, "link": "birth"}])
        self.assertTrue(validate(tree))
        tree.families["x"].children = []
        del tree.families["x"]
        edits.merge_people(tree, p1.id, p2.id)
        self.assertEqual(validate(tree), [])

    def test_siblings_can_merge_without_repeating_a_child(self):
        tree, a = with_person()
        edits.add_parent(tree, a, person("P"))
        sibling = person("S")
        edits.add_sibling(tree, a, sibling)
        edits.merge_people(tree, a, sibling.id)
        self.assertEqual(tree.birth_family_of(a).child_ids, [a])
        self.assertEqual(validate(tree), [])

    def test_impossible_merges_are_refused_unchanged(self):
        tree = sample_tree()
        before = copy_tree(tree)
        for keep, remove in (
            ("ante", "ante"),
            ("ante", "ruzica"),
            ("ante", "ivana"),
            ("ivana", "ante"),
            ("luka", "zvonko"),
        ):
            with self.assertRaises(EditError, msg=(keep, remove)):
                edits.merge_people(tree, keep, remove)
            self.assertEqual(tree, before)

    def test_living_and_deceased_merge_to_deceased(self):
        tree = Tree()
        a, b = person("A", living="yes"), person("B", living="no", death_date="1990")
        tree.people = {a.id: a, b.id: b}
        edits.merge_people(tree, a.id, b.id)
        merged = tree.people[a.id]
        self.assertEqual((merged.living, merged.death_date), ("no", "1990"))
        self.assertEqual(validate(tree), [])


class HeadTests(unittest.TestCase):
    def test_make_head_changes_default_view_and_keeps_partners(self):
        tree = sample_tree()
        edits.make_head(tree, "ruzica", "ante")
        self.assertEqual(tree.families["f-ante"].partners, ["ruzica", "ante"])
        self.assertEqual(tree.default_house_root(), "ruzica")


class HistoryTests(unittest.TestCase):
    def test_undo_and_redo_restore_exact_data(self):
        tree = sample_tree()
        original = copy_tree(tree)
        history = History()
        history.push(copy_tree(tree))
        edits.delete_person(tree, "luka")
        changed = copy_tree(tree)
        tree = history.undo(tree)
        self.assertEqual(tree, original)
        tree = history.redo(tree)
        self.assertEqual(tree, changed)

    def test_snapshot_does_not_share_data(self):
        tree = sample_tree()
        snapshot = copy_tree(tree)
        tree.families["f-ante"].partners.append("x")
        tree.people["ante"].birth["date"] = "1000"
        self.assertEqual(snapshot, sample_tree())

    def test_new_edit_clears_redo(self):
        tree = sample_tree()
        history = History()
        history.push(copy_tree(tree))
        tree = history.undo(tree)
        self.assertTrue(history.can_redo())
        history.push(copy_tree(tree))
        self.assertFalse(history.can_redo())

    def test_limit(self):
        history = History(limit=3)
        for number in range(10):
            history.push(Tree({f"p{number}": Person(f"p{number}", given=str(number))}, {}))
        self.assertEqual([next(iter(t.people)) for t in history.undo_stack], ["p7", "p8", "p9"])

    def test_snapshots_are_kept_compressed_and_come_back_equal(self):
        from sample import sample_tree
        history = History()
        tree = sample_tree()
        history.push(copy_tree(tree))
        self.assertIsInstance(list.__getitem__(history.undo_stack, 0), bytes)
        self.assertEqual(history.undo(Tree()), tree)


class RandomSessionTests(unittest.TestCase):
    """Long sequences of edits: no data problems, no crashes, nothing lost on save."""

    def random_person(self, rng):
        born = rng.randint(1800, 2020)
        values = {
            "given": rng.choice(["Ana", "Đuro", "Šime", "Žana", "Ćiro", ""]),
            "surname": rng.choice(["Šimić", "Čulić", "Bilić", ""]),
            "birth_date": rng.choice(["", str(born), f"about {born}", f"14.5.{born}"]),
            "living": rng.choice(["yes", "no", "unknown"]),
            "notes": rng.choice(["", 'He said "hello"\nnew line', "<b>not html</b>"]),
        }
        if values["living"] == "no" and rng.random() < 0.7:
            values["death_date"] = str(born + rng.randint(0, 90))
        return make_person(values)

    def one_edit(self, rng, tree):
        if not tree.people:
            edits.add_first_person(tree, self.random_person(rng))
            return
        target = rng.choice(sorted(tree.people))
        families = tree.families_of(target)
        action = rng.choice(
            ["partner", "partner", "child", "child", "child", "parent", "sibling", "delete", "update", "head", "link", "link", "merge"]
        )
        if action == "merge":
            other = rng.choice(sorted(tree.people))
            before = copy_tree(tree)
            try:
                edits.merge_people(tree, target, other)
            except EditError:
                self.assertEqual(tree, before, "a refused merge changed the tree")
            return
        if action == "link":
            other = rng.choice(sorted(tree.people))
            kind = rng.choice([edits.link_partner, edits.link_child, edits.link_parent])
            before = copy_tree(tree)
            try:
                kind(tree, target, other)
            except EditError:
                self.assertEqual(tree, before, "a refused link changed the tree")
            return
        if action == "partner":
            open_families = edits.open_single_parent_families(tree, target)
            if len(open_families) > 1:
                edits.add_partner(tree, target, self.random_person(rng), family_id=open_families[0].id)
            else:
                edits.add_partner(tree, target, self.random_person(rng))
        elif action == "child":
            if len(families) > 1:
                edits.add_child(tree, target, self.random_person(rng), family_id=rng.choice(families).id)
            else:
                edits.add_child(tree, target, self.random_person(rng))
        elif action == "parent" and edits.can_add_parent(tree, target):
            edits.add_parent(tree, target, self.random_person(rng))
        elif action == "sibling" and edits.can_add_sibling(tree, target):
            edits.add_sibling(tree, target, self.random_person(rng))
        elif action == "delete" and rng.random() < 0.4:
            edits.delete_person(tree, target)
        elif action == "update":
            edits.update_person(tree, target, {"given": "Changed", "living": "unknown"})
        elif action == "head" and families and len(families[0].partners) == 2:
            other = next(p for p in families[0].partners if p != target)
            edits.make_head(tree, target, other)

    def test_random_sessions(self):
        for seed in range(25):
            rng = random.Random(seed)
            tree = Tree()
            history = History()
            with tempfile.TemporaryDirectory() as temp:
                folder = Path(temp) / "Random.tree"
                create_tree(folder, tree)
                for step in range(120):
                    history.push(copy_tree(tree))
                    self.one_edit(rng, tree)
                    self.assertEqual(validate(tree), [], f"seed {seed} step {step}")
                    if rng.random() < 0.1:
                        tree = history.undo(tree)
                    if step % 15 == 0:
                        save_tree(folder, tree)
                        self.assertEqual(open_tree(folder).tree, tree, f"seed {seed} step {step}")
                    root = tree.default_house_root()
                    if root is not None:
                        layout = layout_house(tree, root)
                        self.assertTrue(layout.cards, f"seed {seed} step {step}")


if __name__ == "__main__":
    unittest.main()


class AlreadySiblingsTests(unittest.TestCase):
    def test_siblings_in_any_shared_family_are_already_siblings(self):
        # Found by the explorer: one sibling's place in a no-parents family was marked adopted,
        # and linking them again added her a second time.
        tree, a = with_person()
        b = person("B")
        edits.add_sibling(tree, a, b, link="adopted")
        before = copy_tree(tree)
        with self.assertRaises(EditError):
            edits.link_sibling(tree, b.id, a)
        self.assertEqual(tree, before)
        self.assertEqual(validate(tree), [])

    def test_linking_a_parent_to_a_parentless_sibling_group(self):
        # Found by the explorer: refused as "already has parents: ." with an empty list.
        tree, a = with_person()
        b = person("B")
        edits.add_sibling(tree, a, b)
        parent = person("P")
        tree.people[parent.id] = parent
        edits.link_child(tree, parent.id, a)
        self.assertEqual(tree.birth_family_of(a).partners, [parent.id])
        self.assertEqual(tree.birth_family_of(b.id).partners, [parent.id])  # The whole group.
        self.assertEqual(validate(tree), [])


class SiblingGroupTests(unittest.TestCase):
    """Found by the explorer: linking someone who stood with brothers and sisters whose
    parents are unknown gave them two birth families."""

    def test_a_group_without_parents_joins_whole(self):
        tree = Tree()
        ante, mum, dad = person("Ante"), person("Mum"), person("Dad")
        luka, jela = person("Luka"), person("Jela")
        for p in (ante, mum, dad, luka, jela):
            tree.people[p.id] = p
        tree.families["home"] = Family("home", [dad.id, mum.id], "married", [{"person": ante.id, "link": "birth"}])
        tree.families["group"] = Family("group", [], "unknown", [{"person": luka.id, "link": "birth"},
                                                                 {"person": jela.id, "link": "adopted"}])
        edits.link_sibling(tree, ante.id, luka.id)
        self.assertEqual(validate(tree), [])
        self.assertNotIn("group", tree.families)
        home = tree.families["home"]
        self.assertEqual({c["person"]: c["link"] for c in home.children},
                         {ante.id: "birth", luka.id: "birth", jela.id: "adopted"})

    def test_an_adopted_sibling_keeps_their_own_group(self):
        tree = Tree()
        ante, dad, luka, jela = person("Ante"), person("Dad"), person("Luka"), person("Jela")
        for p in (ante, dad, luka, jela):
            tree.people[p.id] = p
        tree.families["home"] = Family("home", [dad.id], "unknown", [{"person": ante.id, "link": "birth"}])
        tree.families["group"] = Family("group", [], "unknown", [{"person": luka.id, "link": "birth"},
                                                                 {"person": jela.id, "link": "birth"}])
        edits.link_sibling(tree, ante.id, luka.id, "adopted")
        self.assertEqual(validate(tree), [])
        self.assertIn("group", tree.families)  # Adopted into this family; born into the other.
        self.assertIn(luka.id, tree.families["home"].child_ids)
