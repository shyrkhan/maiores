"""GEDCOM: our own files come back the same, and other programs' files are readable."""
import datetime
import random
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edits
from edits import make_person
from gedcom import GedcomError, date_from_gedcom, date_to_gedcom, read_gedcom, write_gedcom
from model import Tree, validate
from sample import sample_tree

TODAY = datetime.date(2026, 11, 4)


def shape(tree):
    """A tree described without its random IDs, so two copies can be compared."""

    def person_key(person):
        return (person.given, person.surname, person.birth_surname, person.birth_date)

    people = sorted(
        (
            person_key(p),
            p.sex,
            p.living,
            (p.birth or {}).get("place", ""),
            p.death_date,
            (p.death or {}).get("place", ""),
            p.notes,
        )
        for p in tree.people.values()
    )
    families = sorted(
        (
            sorted(person_key(tree.people[x]) for x in f.partners),
            f.relationship,
            sorted((person_key(tree.people[c["person"]]), c.get("link")) for c in f.children),
        )
        for f in tree.families.values()
    )
    return people, families


class GedcomCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.path = self.folder / "family.ged"

    def round_trip(self, tree):
        self.path.write_text(write_gedcom(tree, self.path, today=TODAY), encoding="utf-8")
        return read_gedcom(self.path, today=TODAY)

    def read_text(self, text, encoding="utf-8"):
        self.path.write_bytes(text.encode(encoding))
        return read_gedcom(self.path, today=TODAY)

    def only_person(self, result):
        return next(iter(result.tree.people.values()))


class DateTests(unittest.TestCase):
    def test_both_directions(self):
        cases = {
            "1921": "1921",
            "1921-05": "MAY 1921",
            "1921-05-14": "14 MAY 1921",
            "abt 1921": "ABT 1921",
            "bef 1900": "BEF 1900",
            "aft 1900": "AFT 1900",
            "1880/1885": "BET 1880 AND 1885",
        }
        for stored, written in cases.items():
            self.assertEqual(date_to_gedcom(stored), written)
            self.assertEqual(date_from_gedcom(written), stored)

    def test_other_programs_forms(self):
        self.assertEqual(date_from_gedcom("EST 1921"), "abt 1921")
        self.assertEqual(date_from_gedcom("CAL 1921"), "abt 1921")
        self.assertEqual(date_from_gedcom("abt 14 may 1921"), "abt 1921-05-14")
        self.assertEqual(date_from_gedcom("FROM 1880 TO 1885"), "1880/1885")
        # Exact dates in a range keep their days (they were cut to the years before 1.4.3).
        self.assertEqual(date_from_gedcom("BET 2 JAN 1880 AND 3 MAR 1885"), "1880-01-02/1885-03-03")
        self.assertEqual(date_from_gedcom("BET ABT 1880 AND 1885"), None)

    def test_not_understood(self):
        for text in ("Summer of 1920", "14 1921", "31 FOO 1921", "32 JAN 1921", "(unknown)", "510 BC",
                     "BET 12 AND 19 AUG 1295"):
            self.assertIsNone(date_from_gedcom(text), text)

    def test_years_before_1000(self):
        self.assertEqual(date_from_gedcom("850"), "0850")
        self.assertEqual(date_from_gedcom("23 Aug 963"), "0963-08-23")
        self.assertEqual(date_from_gedcom("est 500"), "abt 0500")
        self.assertEqual(date_from_gedcom("BET 976 AND 994"), "0976/0994")


class RoundTripTests(GedcomCase):
    def test_sample_comes_back_the_same(self):
        tree = sample_tree()
        result = self.round_trip(tree)
        self.assertEqual(shape(result.tree), shape(tree))
        self.assertEqual(result.warnings, [])
        self.assertEqual(validate(result.tree), [])

    def test_everything_we_store_survives(self):
        tree = Tree()
        a = make_person(
            {
                "given": "Marija Ana",
                "surname": "Šimić",
                "birth_surname": "Đurić",
                "sex": "F",
                "birth_date": "about 1921",
                "birth_place": "Trogir, Hrvatska",
                "living": "no",
                "death_date": "14.5.1990",
                "death_place": "Split",
                "notes": 'Line one with "quotes"\nSecond @ line\n\n' + "long " * 200,
            }
        )
        b = make_person({"given": "Čedo", "sex": "X", "living": "unknown"})
        c = make_person({"given": "Žana", "living": "yes", "birth_date": "1980-1985"})
        d = make_person({"given": "Dead no date", "living": "no"})
        edits.add_first_person(tree, a)
        edits.add_partner(tree, a.id, b, "divorced")
        edits.add_child(tree, a.id, c, "adopted")
        edits.add_sibling(tree, c.id, d, "unknown")
        result = self.round_trip(tree)
        self.assertEqual(shape(result.tree), shape(tree))
        self.assertEqual(validate(result.tree), [])

    def test_all_relationship_types(self):
        for relationship in ("married", "partners", "divorced", "unknown"):
            tree = Tree()
            a, b = make_person({"given": "A"}), make_person({"given": "B"})
            edits.add_first_person(tree, a)
            edits.add_partner(tree, a.id, b, relationship)
            self.assertEqual(shape(self.round_trip(tree).tree), shape(tree), relationship)

    def test_single_parents_and_same_sex_couples(self):
        tree = Tree()
        a = make_person({"given": "A", "sex": "F"})
        edits.add_first_person(tree, a)
        edits.add_child(tree, a.id, make_person({"given": "Kid"}))
        edits.add_partner(tree, a.id, make_person({"given": "B", "sex": "F"}), new_family=True)
        self.assertEqual(shape(self.round_trip(tree).tree), shape(tree))

    def test_random_trees(self):
        for seed in range(15):
            rng = random.Random(seed)
            tree = Tree()
            edits.add_first_person(tree, make_person({"given": "Root"}))
            for number in range(60):
                target = rng.choice(sorted(tree.people))
                person = make_person(
                    {
                        "given": f"Š{number}",
                        "surname": rng.choice(["Šimić", "", "Čulić"]),
                        "birth_date": rng.choice(["", "1900", "abt 1900", "1900-02-03"]),
                        "living": rng.choice(["yes", "no", "unknown"]),
                    }
                )
                action = rng.choice(["partner", "child", "parent"])
                if action == "partner" and len(edits.open_single_parent_families(tree, target)) <= 1:
                    edits.add_partner(tree, target, person)
                elif action == "child" and len(tree.families_of(target)) <= 1:
                    edits.add_child(tree, target, person)
                elif action == "parent" and edits.can_add_parent(tree, target):
                    edits.add_parent(tree, target, person)
            self.assertEqual(shape(self.round_trip(tree).tree), shape(tree), seed)

    def test_long_lines_stay_within_the_limit(self):
        tree = Tree()
        edits.add_first_person(tree, make_person({"given": "A", "notes": "x" * 2000}))
        text = write_gedcom(tree, self.path, today=TODAY)
        self.assertLess(max(len(line) for line in text.splitlines()), 255)

    def test_head_is_valid(self):
        text = write_gedcom(sample_tree(), self.path, today=TODAY)
        lines = text.splitlines()
        self.assertEqual(lines[0], "0 HEAD")
        self.assertEqual(lines[-1], "0 TRLR")
        self.assertIn("2 VERS 5.5.1", lines)
        self.assertIn("1 CHAR UTF-8", lines)


OTHER_PROGRAM = """0 HEAD
1 SOUR Ancestry.com
1 GEDC
2 VERS 5.5.1
1 CHAR UTF-8
0 @N1@ NOTE A shared note
1 CONT with two lines
0 @I1@ INDI
1 NAME John Michael /Smith/ Jr
2 GIVN John Michael
1 SEX M
1 BIRT
2 DATE 1 JAN 1900
2 PLAC London
1 DEAT
2 DATE Summer of 1970
1 NOTE @N1@
1 FAMS @F1@
1 RESI
2 PLAC Somewhere
0 @I2@ INDI
1 NAME Mary /Jones/
1 NAME Mary /Smith/
2 TYPE married
1 SEX F
1 BIRT
2 DATE ABT 1990
1 FAMS @F1@
0 @I3@ INDI
1 NAME Tom //
1 FAMC @F1@
2 PEDI adopted
0 @I4@ INDI
1 NAME /Nameless/
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 CHIL @I3@
1 CHIL @I99@
1 MARR
2 DATE 1920
0 TRLR
"""


class OtherProgramTests(GedcomCase):
    def setUp(self):
        super().setUp()
        self.result = self.read_text(OTHER_PROGRAM)
        self.tree = self.result.tree
        self.by_given = {p.given: p for p in self.tree.people.values()}

    def test_names(self):
        self.assertIn("John Michael Jr", self.by_given)
        mary = self.by_given["Mary"]
        self.assertEqual(mary.surname, "Smith")
        self.assertEqual(mary.birth_surname, "Jones")
        self.assertEqual(self.by_given[""].surname, "Nameless")

    def test_date_it_cannot_read_is_kept_in_notes(self):
        john = self.by_given["John Michael Jr"]
        self.assertEqual(john.birth_date, "1900-01-01")
        self.assertEqual(john.death_date, "")
        self.assertIn("Summer of 1970", john.notes)
        self.assertIn("A shared note\nwith two lines", john.notes)

    def test_family_and_broken_link_reported(self):
        family = next(iter(self.tree.families.values()))
        self.assertEqual(family.relationship, "married")
        self.assertEqual(len(family.partners), 2)
        self.assertEqual(family.children[0]["link"], "adopted")
        codes = dict(self.result.warnings)
        self.assertEqual(codes["broken_links"], 1)
        self.assertEqual(codes["odd_dates"], 1)
        self.assertEqual(validate(self.tree), [])

    def test_living_is_worked_out_carefully(self):
        self.assertEqual(self.by_given["John Michael Jr"].living, "no")
        self.assertEqual(self.by_given["Mary"].living, "yes")
        self.assertEqual(self.by_given["Tom"].living, "unknown")


class RealProgramTests(unittest.TestCase):
    """A file really written by Gramps 6.0.8, after importing one of ours."""

    def test_gramps_file_reads_cleanly(self):
        result = read_gedcom(Path(__file__).parent / "fixtures" / "from_gramps.ged", today=TODAY)
        self.assertEqual(result.warnings, [])
        self.assertEqual(validate(result.tree), [])
        self.assertEqual(len(result.tree.people), 18)
        self.assertEqual(len(result.tree.families), 7)
        people = {p.given: p for p in result.tree.people.values()}
        duro = people["Đuro Marija"]
        self.assertEqual((duro.surname, duro.birth_surname), ("Čulić", "Žanić"))
        self.assertEqual(duro.birth_date, "1950-05-14")
        self.assertEqual(duro.death_date, "abt 1990")
        self.assertEqual(duro.notes, "Prva linija\nDruga @ linija")
        self.assertEqual(people["Adopted"].birth_date, "1980/1985")
        self.assertEqual(result.tree.birth_family_of(people["Adopted"].id).children[0]["link"], "adopted")
        self.assertEqual(result.tree.families_of(duro.id)[0].relationship, "divorced")


class AwkwardFileTests(GedcomCase):
    MINIMAL = "0 HEAD\n1 CHAR {char}\n0 @I1@ INDI\n1 NAME Šime /Čulić/\n0 TRLR\n"

    def test_encodings(self):
        for encoding, char in (("utf-8", "UTF-8"), ("utf-8-sig", "UTF-8"), ("utf-16", "UNICODE"), ("cp1250", "ANSI")):
            result = self.read_text(self.MINIMAL.format(char=char), encoding)
            person = self.only_person(result)
            self.assertEqual((person.given, person.surname), ("Šime", "Čulić"), encoding)

    def test_guessed_encoding_is_reported(self):
        result = self.read_text(self.MINIMAL.format(char="ANSI"), "cp1250")
        self.assertIn("encoding_guess", dict(result.warnings))

    def test_windows_line_endings(self):
        result = self.read_text(self.MINIMAL.format(char="UTF-8").replace("\n", "\r\n"))
        self.assertEqual(self.only_person(result).surname, "Čulić")

    def test_not_gedcom_is_refused(self):
        for text in ("", "hello there", "{\"json\": true}", "1 NAME x\n"):
            with self.assertRaises(GedcomError):
                self.read_text(text)

    def test_missing_file(self):
        with self.assertRaises(GedcomError):
            read_gedcom(self.folder / "nope.ged")

    def test_bad_lines_are_counted_not_fatal(self):
        result = self.read_text("0 HEAD\nrubbish line\n0 @I1@ INDI\n1 NAME A /B/\n0 TRLR\n")
        self.assertEqual(dict(result.warnings)["bad_lines"], 1)
        self.assertEqual(len(result.tree.people), 1)

    def test_garbage_bytes_do_not_crash(self):
        rng = random.Random(3)
        base = OTHER_PROGRAM.encode()
        for _ in range(40):
            data = bytearray(base)
            for _ in range(30):
                data[rng.randrange(len(data))] = rng.randrange(256)
            self.path.write_bytes(bytes(data))
            try:
                read_gedcom(self.path, today=TODAY)
            except GedcomError:
                pass

    def test_file_with_loop_and_extra_parents_loads_and_is_reported(self):
        text = (
            "0 HEAD\n0 @A@ INDI\n1 NAME A\n0 @B@ INDI\n1 NAME B\n0 @C@ INDI\n1 NAME C\n"
            "0 @F1@ FAM\n1 HUSB @A@\n1 CHIL @B@\n0 @F2@ FAM\n1 HUSB @B@\n1 CHIL @A@\n"
            "0 @F3@ FAM\n1 HUSB @A@\n1 WIFE @B@\n1 WIFE @C@\n0 TRLR\n"
        )
        result = self.read_text(text)
        codes = {issue.code for issue in validate(result.tree)}
        self.assertIn("ancestor_loop", codes)
        self.assertEqual(dict(result.warnings)["extra_partners"], 1)

    def test_photo_only_inside_the_gedcom_folder(self):
        inside = self.folder / "pic.jpg"
        inside.write_bytes(b"x")
        text = "0 HEAD\n0 @A@ INDI\n1 NAME In\n1 OBJE\n2 FILE pic.jpg\n0 @B@ INDI\n1 NAME Out\n1 OBJE\n2 FILE ../outside.jpg\n0 @C@ INDI\n1 NAME Abs\n1 OBJE\n2 FILE /etc/passwd\n0 TRLR\n"
        result = self.read_text(text)
        by_given = {p.given: p.id for p in result.tree.people.values()}
        self.assertEqual(result.photos, {by_given["In"]: inside.resolve()})
        self.assertEqual(dict(result.warnings)["photos_skipped"], 2)


if __name__ == "__main__":
    unittest.main()


class LifeEventGedcomTests(unittest.TestCase):
    def test_events_marriage_and_sources_survive_a_round_trip(self):
        import tempfile
        from pathlib import Path
        from gedcom import read_gedcom, write_gedcom
        from model import tree_sources
        from sample import sample_tree
        tree = sample_tree()
        tree.extra["sources"] = {"s-work": {"title": "radna knjižica"},
                                 "s-book": {"title": "matična knjiga", "author": "župni ured",
                                            "repository": "Državni arhiv u Splitu", "note": "mikrofilm"},
                                 "s-mar": {"title": "vjenčani list"}}
        tree.people["luka"].extra["events"] = [
            {"type": "occupation", "date": "1975", "place": "Split", "text": "stolar",
             "citations": [{"source": "s-work"}]},
            {"type": "military", "date": "1968/1970", "text": "JNA"},
            {"type": "burial", "date": "2017-03-02", "place": "Trogir"},
        ]
        tree.people["luka"].birth["citations"] = [{"source": "s-book", "page": "str. 47", "quality": "original"}]
        tree.families["f-luka"].extra["marriage"] = {"date": "1975-06-14", "place": "Split",
                                                     "citations": [{"source": "s-mar", "quality": "copy"}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x.ged"
            path.write_text(write_gedcom(tree, path), encoding="utf-8")
            back = read_gedcom(path).tree
        titles = {k: v["title"] for k, v in tree_sources(back).items()}
        luka = next(p for p in back.people.values() if p.given == "Luka")
        self.assertEqual([e["type"] for e in luka.extra["events"]], ["occupation", "military", "burial"])
        self.assertEqual(titles[luka.extra["events"][0]["citations"][0]["source"]], "radna knjižica")
        [citation] = luka.birth["citations"]
        self.assertEqual((titles[citation["source"]], citation["page"], citation["quality"]),
                         ("matična knjiga", "str. 47", "original"))
        book = tree_sources(back)[citation["source"]]
        self.assertEqual((book["author"], book["repository"], book["note"]),
                         ("župni ured", "Državni arhiv u Splitu", "mikrofilm"))
        marriages = [f.extra["marriage"] for f in back.families.values() if "marriage" in f.extra]
        self.assertEqual(len(marriages), 1)
        self.assertEqual((marriages[0]["date"], titles[marriages[0]["citations"][0]["source"]]),
                         ("1975-06-14", "vjenčani list"))

    def test_shared_source_records_from_other_programs(self):
        import tempfile
        from pathlib import Path
        from gedcom import read_gedcom
        from model import tree_sources
        text = ("0 HEAD\n1 CHAR UTF-8\n0 @S1@ SOUR\n1 TITL Parish book of Trogir\n1 REPO @R1@\n"
                "0 @R1@ REPO\n1 NAME State Archive in Split\n"
                "0 @I1@ INDI\n1 NAME Ana /Kovač/\n1 BIRT\n2 DATE 3 MAR 1901\n2 SOUR @S1@\n3 PAGE p. 12\n"
                "1 OCCU seamstress\n2 SOUR Census 1931\n1 RESI\n2 SOUR Census 1931\n0 TRLR\n")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "s.ged"
            path.write_text(text, encoding="utf-8")
            tree = read_gedcom(path).tree
        ana = next(iter(tree.people.values()))
        sources = tree_sources(tree)
        self.assertEqual(sorted(s["title"] for s in sources.values()), ["Census 1931", "Parish book of Trogir"])
        self.assertEqual(sources[ana.birth["citations"][0]["source"]]["repository"], "State Archive in Split")
        self.assertEqual(ana.birth["citations"][0]["page"], "p. 12")
        census = [e["citations"][0]["source"] for e in ana.extra["events"]]
        self.assertEqual(census[0], census[1])  # The same text twice is one source.


class SiteExportTests(GedcomCase):
    """Files as other programs and sites write them."""

    def test_myheritage_married_name_inside_the_name(self):
        person = self.only_person(self.read_text(
            "0 HEAD\n1 SOUR MYHERITAGE\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Catelyn /Tully/\n2 GIVN Catelyn\n"
            "2 SURN Tully\n2 _MARNM Stark\n1 SEX F\n0 TRLR\n"))
        self.assertEqual((person.given, person.surname, person.birth_surname), ("Catelyn", "Stark", "Tully"))

    def test_married_name_first_and_birth_name_after(self):
        person = self.only_person(self.read_text(
            "0 HEAD\n1 CHAR UTF-8\n0 @I1@ INDI\n1 NAME Ana /Horvat/\n2 TYPE married\n"
            "1 NAME Ana /Kovač/\n2 TYPE birth\n0 TRLR\n"))
        self.assertEqual((person.surname, person.birth_surname), ("Horvat", "Kovač"))

    def test_families_pointing_at_missing_people_are_reported_not_kept(self):
        result = self.read_text("0 HEAD\n1 CHAR UTF-8\n0 @F1@ FAM\n1 CHIL @I9@\n0 TRLR\n")
        self.assertEqual(len(result.tree.families), 0)
        self.assertIn(("broken_links", 1), result.warnings)

    def test_a_web_page_saved_as_ged_is_refused(self):
        with self.assertRaises(GedcomError):
            self.read_text("\n\n<!DOCTYPE html>\n<html><body>Not a family tree</body></html>\n")


class BigTreeTests(unittest.TestCase):
    def test_own_ancestor_check_finds_every_loop_in_one_pass(self):
        from model import Family, Person, _people_in_ancestor_loops
        people = {k: Person(k, given=k) for k in "abcdef"}
        families = {  # a -> b -> c -> a is a loop; d -> e is not; f is their own child.
            "1": Family("1", ["a"], "unknown", [{"person": "b", "link": "birth"}]),
            "2": Family("2", ["b"], "unknown", [{"person": "c", "link": "birth"}]),
            "3": Family("3", ["c"], "unknown", [{"person": "a", "link": "birth"}]),
            "4": Family("4", ["d"], "unknown", [{"person": "e", "link": "birth"}]),
            "5": Family("5", ["f"], "unknown", [{"person": "f", "link": "birth"}]),
        }
        self.assertEqual(_people_in_ancestor_loops(Tree(people, families)), ["a", "b", "c", "f"])

    def test_lookups_share_one_index_only_while_looking(self):
        tree = sample_tree()
        self.assertIsNot(tree.index(), tree.index())
        with tree.looking():
            self.assertIs(tree.index(), tree.index())
            with tree.looking():
                self.assertIs(tree.index(), tree.index())
            self.assertIsNotNone(tree._held_index)
        self.assertIsNone(tree._held_index)
        self.assertEqual(tree._held_cache, {})


KEPT_FILE = """0 HEAD
1 SOUR MYHERITAGE
2 NAME MyHeritage Family Tree Builder
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Ivan /Horvat/ Jr.
2 GIVN Ivan
2 SURN Horvat
1 SEX M
1 BIRT
2 DATE 3 MAR 1901
3 TIME 10:30
2 PLAC Split
2 _PRIM Y
1 TITL Graf
1 NATI Croatian
1 DEAT
2 DATE 1960
2 CAUS heart failure
1 _MYHERITAGE_LINK @I2@
2 _NOTE as a friend
1 RIN 77
1 FAMC @F1@
0 @I2@ INDI
1 NAME Ana /Kovač/
1 SEX F
1 FAMS @F1@
1 NOTE @N1@
0 @I3@ INDI
1 NAME Marko /Kovač/
1 FAMS @F1@
0 @F1@ FAM
1 HUSB @I3@
1 WIFE @I2@
1 CHIL @I1@
2 _FREL Adopted
2 _MREL Adopted
1 MARR
2 DATE 1899
2 _OFFICIANT Fr. Petar
0 @S1@ SOUR
1 TITL Parish book
1 PUBL Split, 1890
0 @N1@ NOTE A note shared by records
1 CHAN
2 DATE 1 JAN 2020
0 @N2@ NOTE Nobody points at me
0 TRLR
"""


class KeepEverythingTests(GedcomCase):
    """Whatever the importer does not use is kept, shown, and written back out."""

    def setUp(self):
        super().setUp()
        self.result = self.read_text(KEPT_FILE)
        self.tree = self.result.tree
        self.ivan = next(p for p in self.tree.people.values() if p.given.startswith("Ivan"))

    def exported(self, tree=None):
        return write_gedcom(tree or self.tree, self.path, today=TODAY)

    def test_what_we_understand_is_read(self):
        from model import person_events
        kinds = {e["type"]: e.get("text") for e in person_events(self.ivan)}
        self.assertEqual(kinds, {"rank": "Graf", "nationality": "Croatian"})
        self.assertEqual(self.ivan.death["cause"], "heart failure")
        family = next(iter(self.tree.families.values()))
        self.assertEqual(family.children[0]["link"], "adopted")
        self.assertEqual(self.tree.extra["gedcom_from"], "MyHeritage Family Tree Builder")

    def test_nothing_is_lost_on_the_way_out(self):
        text = self.exported()
        for line in ("3 TIME 10:30", "2 _PRIM Y", "1 RIN 77", "2 _NOTE as a friend", "2 _FREL Adopted",
                     "2 _OFFICIANT Fr. Petar", "1 PUBL Split, 1890", "Nobody points at me", "1 TITL Graf",
                     "1 NATI Croatian", "2 CAUS heart failure", "A note shared by records", "1 NAME Ivan /Horvat/ Jr."):
            self.assertIn(line, text, line)
        # The kept line pointing at Ana points at Ana's new pointer.
        ana_pointer = re.search(r"^0 (@I\d+@) INDI\n1 NAME Ana", text, re.M)[1]
        self.assertIn(f"1 _MYHERITAGE_LINK {ana_pointer}", text)
        # The time stays under the birth date, inside the birth.
        self.assertRegex(text, r"1 BIRT\n2 DATE 3 MAR 1901\n3 TIME 10:30")
        self.assertEqual(validate(read_gedcom(self.path.with_suffix(".x") if False else self.write_and_read(text)).tree), [])

    def write_and_read(self, text):
        path = self.folder / "again.ged"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reading_back_our_own_file_changes_nothing_more(self):
        first = self.exported()
        again = read_gedcom(self.write_and_read(first), today=TODAY).tree
        second = write_gedcom(again, self.path, today=TODAY)
        self.assertEqual(first, second)

    def test_a_line_about_someone_deleted_is_left_out(self):
        ana = next(pid for pid, p in self.tree.people.items() if p.given == "Ana")
        edits.delete_person(self.tree, ana)
        self.assertNotIn("_MYHERITAGE_LINK", self.exported())

    def test_editing_keeps_what_the_windows_do_not_show(self):
        from dialogs import person_to_values
        values = person_to_values(self.ivan)
        values["notes"] = "edited"
        edits.update_person(self.tree, self.ivan.id, values)
        self.assertEqual(self.ivan.death.get("cause"), "heart failure")

    def test_shared_copies_leave_kept_records_at_home(self):
        import datetime
        import privacy
        shared = privacy.shareable(self.tree, datetime.date(2026, 11, 15), hide_living=False)
        # A loose note stays home; a note shared people point at goes with them.
        exported = self.exported(shared)
        self.assertNotIn("Nobody points at me", exported)
        self.assertIn("A note shared by records", exported)

    def test_the_panel_shows_kept_details_but_not_bookkeeping(self):
        from model import kept_details
        shown = kept_details(self.tree, self.ivan.extra["gedcom"])
        self.assertIn("BIRT › DATE › TIME 10:30", shown)
        self.assertIn("_MYHERITAGE_LINK Ana Kovač", shown)
        self.assertFalse(any("RIN" in line or "_PRIM" in line for line in shown))
