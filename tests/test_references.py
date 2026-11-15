"""Every place one person points at another: people at events, faces in pictures and
not-duplicate marks. Deleting, merging and combining must leave none pointing at nobody."""
import datetime
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import combine  # noqa: E402
import edits  # noqa: E402
import privacy  # noqa: E402
from model import Family, Person, Tree, face_links, not_duplicates, roles_of, validate  # noqa: E402

PHOTO = "media/docs/group.jpg"


def everywhere():
    """X is a godfather, a face in a group photo and half of a not-duplicate mark."""
    people = {k: Person(k, given=k.upper(), surname="Šimić", sex="M", living="no", death={"date": "", "place": ""})
              for k in ("x", "y", "child", "other")}
    people["child"].birth = {"date": "1950", "place": "", "people": [{"person": "x", "role": "godfather"}]}
    people["other"].extra["documents"] = [{"file": PHOTO, "title": "Wedding 1960"}]
    families = {"f": Family("f", ["y"], "unknown", [{"person": "child", "link": "birth"}],
                            {"marriage": {"date": "1949", "people": [{"person": "x", "role": "witness"}]}})}
    extra = {"faces": {PHOTO: [{"rect": [0.1, 0.1, 0.2, 0.3], "person": "x"},
                               {"rect": [0.5, 0.1, 0.2, 0.3], "person": "y"}]},
             "not_duplicates": [["other", "x"]]}
    return Tree(people, families, extra)


class ReferenceTests(unittest.TestCase):
    def test_deleting_leaves_names_and_unnamed_faces(self):
        tree = everywhere()
        edits.delete_person(tree, "x")
        self.assertIn({"role": "godfather", "name": "X Šimić"}, tree.people["child"].birth["people"])
        self.assertEqual([f.get("person") for f in face_links(tree)[PHOTO]], [None, "y"])
        self.assertEqual(not_duplicates(tree), [])
        self.assertEqual(validate(tree), [])

    def test_merging_points_everything_at_the_one_kept(self):
        tree = everywhere()
        edits.merge_people(tree, "y", "x")
        self.assertEqual(sorted(r for r, *_rest in roles_of(tree, "y")), ["godfather", "witness"])
        self.assertEqual([f.get("person") for f in face_links(tree)[PHOTO]], ["y", "y"])
        self.assertEqual(not_duplicates(tree), [["other", "y"]])
        self.assertEqual(validate(tree), [])

    def test_merging_the_two_halves_of_a_mark_removes_it(self):
        tree = everywhere()
        edits.merge_people(tree, "other", "x")
        self.assertEqual(not_duplicates(tree), [])

    def test_combining_with_itself_changes_nothing(self):
        mine = everywhere()
        before = json.dumps(mine.to_dict(), sort_keys=True)
        result = combine.combine(mine, everywhere(), {k: k for k in mine.people},
                                 copy_documents=lambda their_id, documents: documents)
        self.assertEqual(json.dumps(result.tree.to_dict(), sort_keys=True), before)
        self.assertEqual(validate(result.tree), [])

    def test_a_relatives_faces_come_with_their_pictures_only(self):
        mine = Tree({"m": Person("m", given="Y", surname="Šimić", sex="M")}, {})
        theirs = everywhere()
        with_files = combine.combine(mine, theirs, {"y": "m"}, copy_documents=lambda their_id, documents: documents)
        self.assertEqual([f.get("person") for f in face_links(with_files.tree)[PHOTO]][1], "m")
        self.assertEqual(validate(with_files.tree), [])
        without = combine.combine(mine, theirs, {"y": "m"})
        self.assertEqual(face_links(without.tree), {})  # No picture came across, so no faces either.

    def test_a_shared_copy_never_names_a_hidden_face(self):
        tree = everywhere()
        tree.people["x"].living, tree.people["x"].death = "yes", None
        shared = privacy.shareable(tree, datetime.date(2026, 11, 13))
        self.assertEqual([f.get("person") for f in face_links(shared)[PHOTO]], [None, "y"])
        self.assertNotIn("not_duplicates", shared.extra)
        tree.people["other"].extra["documents"][0]["private"] = True
        self.assertEqual(face_links(privacy.shareable(tree, datetime.date(2026, 11, 13))), {})


if __name__ == "__main__":
    unittest.main()
