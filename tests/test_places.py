"""Places with the places they lie in, coordinates and old names; research to-do; life stories."""
import datetime
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import combine  # noqa: E402
import edits  # noqa: E402
import privacy  # noqa: E402
from gedcom import read_gedcom, write_gedcom  # noqa: E402
from model import (  # noqa: E402
    Person, Tree, fact_places, person_story, person_tasks, place_chain, place_coordinates, place_records, validate,
)
from test_sources import parish_tree  # noqa: E402

TODAY = datetime.date(2026, 11, 13)


class PlaceTests(unittest.TestCase):
    def test_a_place_lies_in_others_and_borrows_their_coordinates(self):
        tree = parish_tree()
        self.assertEqual(place_chain(tree, "Trogir"), ["Trogir", "Splitsko-dalmatinska", "Hrvatska"])
        self.assertEqual(place_coordinates(tree, "Trogir"), (43.5167, 16.25))
        edits.set_place(tree, "Seget", {"parent": "Trogir"})
        self.assertEqual(place_coordinates(tree, "Seget"), (43.5167, 16.25))  # Near enough until set.
        self.assertIsNone(place_coordinates(tree, "Nowhere"))
        self.assertEqual(validate(tree), [])

    def test_a_place_can_not_lie_inside_itself(self):
        tree = parish_tree()
        with self.assertRaises(edits.EditError):
            edits.set_place(tree, "Hrvatska", {"parent": "Trogir"})
        tree.extra["places"]["Hrvatska"]["parent"] = "Trogir"  # A hand-edited file.
        self.assertIn("place_loop", [i.code for i in validate(tree)])
        self.assertEqual(place_chain(tree, "Trogir"), ["Trogir", "Splitsko-dalmatinska", "Hrvatska"])

    def test_renaming_a_place_changes_every_fact_and_merging_keeps_both_details(self):
        tree = parish_tree()
        tree.people["ivan"].birth = {"date": "1920", "place": "Trau"}
        edits.set_place(tree, "Trau", {"note": "as written in 1920", "old_names": [{"name": "Tragurium"}]})
        edits.rename_place(tree, "Trau", "Trogir")
        self.assertEqual(tree.people["ivan"].birth["place"], "Trogir")
        trogir = place_records(tree)["Trogir"]
        self.assertEqual(trogir["lat"], 43.5167)  # The place renamed onto keeps its details...
        self.assertEqual(trogir["note"], "as written in 1920")  # ...and gaps are filled from the other.
        self.assertEqual([o["name"] for o in trogir["old_names"]], ["Traù", "Tragurium"])
        self.assertNotIn("Trau", place_records(tree))
        edits.rename_place(tree, "Splitsko-dalmatinska", "Split-Dalmatia")
        self.assertEqual(place_records(tree)["Trogir"]["parent"], "Split-Dalmatia")

    def test_forgetting_a_place_keeps_the_facts(self):
        tree = parish_tree()
        edits.remove_place(tree, "Splitsko-dalmatinska")
        self.assertNotIn("parent", place_records(tree)["Trogir"])
        self.assertEqual(fact_places(tree), {"Trogir": 3})


class TasksAndStoryTests(unittest.TestCase):
    def test_tasks_and_stories_are_kept_and_merged(self):
        tree = parish_tree()
        edits.set_tasks(tree, "davor", [{"text": " Ask aunt Kata ", "done": False}, {"text": "  "}])
        self.assertEqual(person_tasks(tree.people["davor"]), [{"text": "Ask aunt Kata", "done": False, "note": ""}])
        edits.set_story(tree, "davor", "Davor went to sea.")
        tree.people["z2"] = Person("z2", given="Davor", surname="Radić", sex="M",
                                   extra={"tasks": [{"text": "Census 1961"}], "story": "He loved football."})
        edits.merge_people(tree, "davor", "z2")
        davor = tree.people["davor"]
        self.assertEqual([t["text"] for t in person_tasks(davor)], ["Ask aunt Kata", "Census 1961"])
        self.assertEqual(person_story(davor), "Davor went to sea.\n\nHe loved football.")


class SharingTests(unittest.TestCase):
    def test_a_shared_copy_has_no_tasks_and_only_places_still_named(self):
        tree = parish_tree()
        for person in tree.people.values():
            person.living, person.death = "no", {"date": "", "place": ""}
        edits.set_place(tree, "Split", {"lat": 43.5, "lon": 16.44})  # Nobody's fact says Split.
        shared = privacy.shareable(tree, TODAY)
        self.assertFalse(any(person_tasks(p) for p in shared.people.values()))
        self.assertEqual(set(place_records(shared)), {"Trogir", "Splitsko-dalmatinska", "Hrvatska"})
        self.assertEqual(person_story(shared.people["ivan"]), person_story(tree.people["ivan"]))

    def test_a_living_persons_places_and_a_private_story_stay_home(self):
        tree = parish_tree()
        tree.people["ivan"].extra["story_private"] = True
        tree.people["dragan"].birth["place"] = ""  # Only living Davor's facts name Trogir now.
        tree.people["ivan"].living, tree.people["ivan"].death = "no", {"date": "", "place": ""}
        shared = privacy.shareable(tree, TODAY)  # Davor, born in Trogir, has no death: hidden.
        self.assertEqual(person_story(shared.people["ivan"]), "")
        self.assertEqual(place_records(shared), {})


class ExchangeTests(unittest.TestCase):
    def test_coordinates_and_stories_go_through_gedcom(self):
        tree = parish_tree()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "f.ged"
            text = write_gedcom(tree, path)
            self.assertIn("4 LATI N43.5167", text)
            self.assertIn("4 LONG E16.2500", text)
            path.write_text(text, encoding="utf-8")
            back = read_gedcom(path, TODAY).tree
        self.assertEqual(place_records(back)["Trogir"], {"lat": 43.5167, "lon": 16.25})
        ivan = next(p for p in back.people.values() if p.given == "Ivan")
        self.assertEqual(person_story(ivan), person_story(tree.people["ivan"]))
        self.assertEqual(person_tasks(ivan), [])  # Research to-do never leaves.

    def test_other_programs_coordinates_are_read(self):
        text = ("0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ana /Kovač/\n1 BIRT\n2 PLAC Seget\n3 MAP\n"
                "4 LATI S12.5\n4 LONG W77,25\n0 TRLR\n")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "o.ged"
            path.write_text(text, encoding="utf-8")
            tree = read_gedcom(path, TODAY).tree
        self.assertEqual(place_records(tree)["Seget"], {"lat": -12.5, "lon": -77.25})

    def test_a_relatives_places_join_yours_by_name(self):
        mine = Tree({"z": Person("z", given="Davor", surname="Radić", sex="M",
                                 birth={"date": "1957", "place": "Trogir"})}, {},
                    {"places": {"Trogir": {"kind": "town"}}})
        theirs = parish_tree()
        theirs.people["davor"].birth["place"] = "TROGIR"
        result = combine.combine(mine, theirs, {"davor": "z"}).tree
        trogir = place_records(result)["Trogir"]
        self.assertEqual((trogir["kind"], trogir["lat"]), ("town", 43.5167))  # Yours wins, gaps filled.
        self.assertNotIn("TROGIR", fact_places(result))
        self.assertEqual(validate(result), [])


if __name__ == "__main__":
    unittest.main()


class CalendarAndPeriodTests(unittest.TestCase):
    def test_old_calendars_and_periods_read_and_check(self):
        from model import date_warnings, normalize_date_input, parse_date
        self.assertEqual(parse_date("1708/09-02-10").year, 1709)  # Calculations use the new-style year.
        self.assertIsNotNone(parse_date("1700-02-29 julian"))  # A real day in the old calendar...
        self.assertIsNone(parse_date("1700-02-29"))  # ...but not in the new one.
        self.assertIsNone(normalize_date_input("1708/10"))
        self.assertIsNone(normalize_date_input("from 1960 to 1950"))
        tree = Tree({"a": Person("a", given="A", birth={"date": "1708/09-02-10", "place": ""},
                                 death={"date": "1709-03-01", "place": ""}, living="no")}, {})
        self.assertEqual(validate(tree), [])  # Died in 1709, born 1708/09: the same new-style year.
        self.assertEqual(date_warnings(tree, "a", datetime.date(2026, 11, 13)), [])

    def test_a_birth_or_marriage_is_never_a_period(self):
        tree = parish_tree()
        from dialogs import person_to_values
        with self.assertRaises(edits.EditError):
            edits.update_person(tree, "ivan", {**person_to_values(tree.people["ivan"]), "birth_date": "from 1950"})
        with self.assertRaises(edits.EditError):
            edits.set_marriage(tree, "f", "from 1950 to 1960")
        edits.update_person(tree, "davor", {**person_to_values(tree.people["davor"])})  # Periods on events stay.
        self.assertEqual(tree.people["davor"].extra["events"][0]["date"], "from 1950 to 1960")

    def test_every_form_goes_through_gedcom(self):
        from gedcom import date_from_gedcom, date_to_gedcom
        for stored in ("1708-02-10 julian", "abt 1708 julian", "1708/09", "1708/09-02-10", "from 1950 to 1960",
                       "from 1950", "to 1960", "from 1950-03-01 to 1960-07-15", "from 1700 julian to 1710 julian"):
            self.assertEqual(date_from_gedcom(date_to_gedcom(stored), period=True), stored, stored)
        self.assertEqual(date_from_gedcom("FROM 1950 TO 1960"), "1950/1960")  # On a birth: a range.
        self.assertEqual(date_from_gedcom("JULIAN 10 FEB 1708"), "1708-02-10 julian")  # GEDCOM 7 spelling.
        tree = parish_tree()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "d.ged"
            text = write_gedcom(tree, path)
            self.assertIn("2 DATE ABT @#DJULIAN@ 1712", text)  # The calendar escape keeps its single @.
            path.write_text(text, encoding="utf-8")
            back = read_gedcom(path, TODAY).tree
        davor = next(p for p in back.people.values() if p.given == "Davor")
        self.assertEqual([e["date"] for e in davor.extra["events"]], ["from 1950 to 1960", "from 1975"])
        ivan = next(p for p in back.people.values() if p.given == "Ivan")
        self.assertEqual(ivan.birth["date"], "1708/09-02-10")
