"""DNA: reading match lists, segment and raw files, comparing raw files, and what an amount
of shared DNA says about a relationship."""
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dna  # noqa: E402
from model import Family, Person, Tree  # noqa: E402


class Simulated:
    """Genomes passed down the way real ones are: each child gets one of each pair of a
    parent's chromosomes, cut over from one copy to the other at crossovers placed by the
    genetic map. A few letters are misread, as on real chips."""

    def __init__(self, seed=1, per_chromosome=6000, errors=0.001):
        self.rng = random.Random(seed)
        self.errors = errors
        self.sites = {}
        for chromosome in dna.AUTOSOMES:
            positions, _cms = dna._genetic_map()[chromosome]
            first, last = positions[0], positions[-1]
            step = (last - first) / per_chromosome
            places = [int(first + step * i) for i in range(per_chromosome)]
            self.sites[chromosome] = [(p, dna.position_cm(chromosome, p), self.rng.uniform(0.1, 0.9)) for p in places]

    def founder(self):
        return {c: [[("A" if self.rng.random() < f else "G") for _p, _cm, f in sites] for _ in range(2)]
                for c, sites in self.sites.items()}

    def _gamete(self, person):
        out = {}
        for chromosome, (one, two) in person.items():
            sites, current = self.sites[chromosome], self.rng.randrange(2)
            next_cross = self.rng.expovariate(1 / 100)
            copy, start_cm = [], sites[0][1]
            for index, (_p, cm, _f) in enumerate(sites):
                while cm - start_cm > next_cross:
                    current, start_cm = 1 - current, start_cm + next_cross
                    next_cross = self.rng.expovariate(1 / 100)
                copy.append((one, two)[current][index])
            out[chromosome] = copy
        return out

    def child(self, mother, father):
        a, b = self._gamete(mother), self._gamete(father)
        return {c: [a[c], b[c]] for c in self.sites}

    def calls(self, person):
        found = {}
        for chromosome, (one, two) in person.items():
            row = {}
            for index, (position, _cm, _f) in enumerate(self.sites[chromosome]):
                letters = [one[index], two[index]]
                if self.rng.random() < self.errors:
                    letters[0] = "G" if letters[0] == "A" else "A"
                row[position] = "".join(sorted(letters))
            found[chromosome] = row
        return found


class CompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sim = Simulated()
        grandma, grandpa, aunt_in_law, uncle_in_law = (sim.founder() for _ in range(4))
        mother = sim.child(grandma, grandpa)
        uncle = sim.child(grandma, grandpa)
        me = sim.child(mother, uncle_in_law)
        cousin = sim.child(aunt_in_law, uncle)
        cls.calls = {name: sim.calls(person) for name, person in (
            ("grandma", grandma), ("mother", mother), ("uncle", uncle), ("me", me), ("cousin", cousin),
            ("stranger", aunt_in_law), ("other_stranger", uncle_in_law))}

    def shared(self, a, b):
        return dna.summary(dna.compare(self.calls[a], self.calls[b]))[0]

    def test_parent_and_child_share_everything(self):
        total = self.shared("mother", "me")
        self.assertGreater(total, 3300)  # The whole map is about 3,580 cM.

    def test_siblings_grandparents_and_cousins_fall_in_their_ranges(self):
        for a, b, relation in (("mother", "uncle", (1, 1, False)), ("grandma", "me", (2, 0, False)),
                               ("me", "cousin", (2, 2, False))):
            _avg, low, high = dna.expected(*relation)
            total = self.shared(a, b)
            self.assertTrue(low <= total <= high, (a, b, total, low, high))

    def test_strangers_share_nothing(self):
        self.assertLess(self.shared("stranger", "other_stranger"), 30)

    def test_a_reading_error_does_not_cut_a_segment(self):
        segments = dna.compare(self.calls["mother"], self.calls["me"])
        longest = max(s["cm"] for s in segments)
        self.assertGreater(longest, 150)  # Whole chromosomes, despite 0.1% misread letters.


class TableTests(unittest.TestCase):
    def test_amounts_name_their_likely_relations(self):
        first = dna.possible(866)[0]
        self.assertEqual(first[:3], (2, 2, False))  # First cousin, on the average exactly.
        self.assertEqual(dna.possible(3500)[0][:2], (1, 0))  # Parent or child.
        self.assertEqual(dna.possible(None), [])
        self.assertTrue(all(up >= down for up, down, _h, _f in dna.possible(300)))

    def test_the_tree_is_checked_against_the_dna(self):
        people = {k: Person(k, given=k) for k in ("gp", "gm", "mum", "aunt", "me", "cousin", "x")}
        tree = Tree(people, {
            "f1": Family("f1", ["gp", "gm"], "married", [{"person": "mum", "link": "birth"},
                                                        {"person": "aunt", "link": "birth"}]),
            "f2": Family("f2", ["mum"], "unknown", [{"person": "me", "link": "birth"}]),
            "f3": Family("f3", ["aunt"], "unknown", [{"person": "cousin", "link": "birth"}]),
        })
        fits, relation, figures = dna.check(tree, "me", {"person": "cousin", "cm": 800})
        self.assertEqual((fits, relation.up, relation.down), ("fits", 2, 2))
        self.assertEqual(dna.check(tree, "me", {"person": "cousin", "cm": 90})[0], "low")
        self.assertEqual(dna.check(tree, "me", {"person": "x", "cm": 90})[0], "unrelated")
        self.assertEqual(dna.check(tree, "me", {"person": "", "cm": 90})[0], "unknown")


MYHERITAGE = b'''Name,Age,Country,Shared DNA,Shared segments,Largest segment,Estimated relationship
"Ana Kova\xc4\x8d",50,Croatia,"6.5% (465.3 cM)",17,"70.1 cM","1st cousin once removed"
Ivo Peri\xc4\x87,,,"1.2% (89 cM)",5,22.4 cM,3rd - 4th cousin
'''
FTDNA = b'''Full Name,First Name,Middle Name,Last Name,Match Date,Relationship Range,Shared DNA,Longest Block,Email
Mara Bilic,Mara,,Bilic,1/2/2020,2nd Cousin - 3rd Cousin,"1,203",45.5,mara@example.com
'''
TWENTYTHREE = b'''Display Name,Surname,Predicted Relationship,Percent DNA Shared,# Segments Shared
Luka,Simic,First Cousin,11.6,22
'''
SEGMENTS_FTDNA = b'''MATCHNAME,CHROMOSOME,START LOCATION,END LOCATION,CENTIMORGANS,MATCHING SNPS
Ana Kova\xc4\x8d,1,72017,10000000,21.5,4200
Ana Kova\xc4\x8d,7,20000000,40000000,,5300
New Person,X,1000000,5000000,8.0,700
'''
SEGMENTS_GEDMATCH = b'''Kit1 Number,Kit1 Name,Kit2 Number,Kit2 Name,Chr,B37 Start,B37 End,Segment cM,SNPs
A1,Me,B2,Petar Horvat,3,100000,9000000,12.3,1500
'''


class FileTests(unittest.TestCase):
    def test_match_lists_from_each_company(self):
        kind, matches = dna.read_match_file(MYHERITAGE, "MyHeritage")
        self.assertEqual(kind, "matches")
        ana = matches[0]
        self.assertEqual((ana["name"], ana["cm"], ana["segments"], ana["longest"]), ("Ana Kovač", 465.3, 17, 70.1))
        self.assertEqual(ana["guess"], "1st cousin once removed")
        kind, matches = dna.read_match_file(FTDNA)
        self.assertEqual((matches[0]["name"], matches[0]["cm"], matches[0]["longest"]), ("Mara Bilic", 1203, 45.5))
        self.assertNotIn("mara@example.com", str(matches))  # Other people's email stays out.
        kind, matches = dna.read_match_file(TWENTYTHREE)
        self.assertEqual(matches[0]["name"], "Luka Simic")
        self.assertAlmostEqual(matches[0]["cm"], 11.6 * dna.GENOME_CM / 100, places=0)
        self.assertEqual(dna.read_match_file(b"just,some\n1,2\n")[0], "unknown")

    def test_segment_files_join_their_matches(self):
        test = dna.clean_test({"company": "FamilyTreeDNA"})
        dna.add_matches(test, dna.read_match_file(MYHERITAGE)[1])
        kind, found = dna.read_match_file(SEGMENTS_FTDNA)
        self.assertEqual(kind, "segments")
        self.assertEqual(dna.add_segments(test, found), 3)
        self.assertEqual(dna.add_segments(test, found), 0)  # The same file twice adds nothing.
        ana = next(m for m in test["matches"] if m["name"] == "Ana Kovač")
        own = [s for s in test["segments"] if s["match"] == ana["id"]]
        self.assertEqual(len(own), 2)
        self.assertGreater(next(s for s in own if s["chr"] == "7")["cm"], 5)  # Worked out from the map.
        newcomer = next(m for m in test["matches"] if m["name"] == "New Person")
        self.assertIsNone(newcomer["cm"])  # Only an X segment: no autosomal total.
        kind, found = dna.read_match_file(SEGMENTS_GEDMATCH)
        self.assertEqual((kind, found[0][0], found[0][1]["chr"]), ("segments", "Petar Horvat", "3"))

    def test_raw_files_from_each_company(self):
        files = {
            "23andme.txt": "# This data file generated by 23andMe ... build 37\n# rsid\tchromosome\tposition\tgenotype\n"
                           "rs1\t1\t1000\tAG\nrs2\t1\t2000\t--\nrs3\tX\t3000\tA\nrs4\tMT\t10\tG\n",
            "ancestry.txt": "#AncestryDNA raw data download\nrsid\tchromosome\tposition\tallele1\tallele2\n"
                            "rs1\t1\t1000\tG\tA\nrs2\t1\t2000\t0\t0\nrs3\t23\t3000\tA\tA\n",
            "myheritage.csv": '# MyHeritage DNA raw data.\nRSID,CHROMOSOME,POSITION,RESULT\n"rs1","1","1000","AG"\n'
                              '"rs2","1","2000","--"\n',
        }
        with tempfile.TemporaryDirectory() as folder:
            for name, text in files.items():
                path = Path(folder) / name
                path.write_text(text, encoding="utf-8")
                calls, info = dna.read_raw(path)
                self.assertEqual(calls["1"], {1000: "AG"}, name)
                self.assertEqual(info["build"], "37", name)

    def test_stored_tests_are_cleaned(self):
        person = Person("p", given="P")
        person.extra["dna"] = {"tests": [{"company": "MyHeritage", "kind": "nonsense", "matches": [
            {"name": "A", "cm": "12.5"}, {"name": "", "cm": 3}, "junk"], "segments": [
            {"match": "nobody", "chr": "1", "start": 1, "end": 2}]}, "junk"]}
        tests = dna.tests_of(person)
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0]["kind"], "autosomal")
        self.assertEqual([m["cm"] for m in tests[0]["matches"]], [12.5])
        self.assertEqual(tests[0]["segments"], [])


if __name__ == "__main__":
    unittest.main()


class WindowTests(unittest.TestCase):
    """The DNA window on the sample family, with raw files simulated for a mother and son."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import datetime
        from PySide6.QtCore import QSettings
        import app as app_module
        from sample import sample_tree
        from storage import create_tree
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        create_tree(folder / "S.tree", sample_tree())
        self.window = app_module.MainWindow(QSettings(str(folder / "s.ini"), QSettings.Format.IniFormat),
                                            today=datetime.date(2026, 11, 15))
        self.window.trees_folder = folder / "none"
        self.window.alert = self.window.inform = lambda *a: None
        self.window.open_path(folder / "S.tree")
        self.id = {p.given: k for k, p in self.window.tree.people.items()}
        sim = Simulated(seed=5, per_chromosome=3000)
        dad, mum = sim.founder(), sim.founder()
        son = sim.child(mum, dad)
        self.raw = {}
        for name, person in (("Mara", mum), ("Ivana", son)):
            path = folder / f"{name}.txt"
            lines = ["# rsid\tchromosome\tposition\tgenotype"]
            for chromosome, row in sim.calls(person).items():
                lines += [f"rs{chromosome}{p}\t{chromosome}\t{p}\t{g}" for p, g in row.items()]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.raw[name] = path

    def tearDown(self):
        self.window.close()
        self.temp.cleanup()

    def open_dialog(self, given):
        from dna_dialog import DnaDialog
        return DnaDialog(self.window, self.window.tree, self.id[given], self.window.folder,
                         find_person=lambda title: None)

    def test_import_compare_and_save(self):
        dialog = self.open_dialog("Ivana")
        dialog.tests.append(dna.clean_test({"company": "23andMe"}))
        dialog._fill_tests(0)
        matches_file = Path(self.temp.name) / "matches.csv"
        matches_file.write_bytes(MYHERITAGE)
        self.assertIn("2", dialog.import_path(matches_file))
        self.assertIn("Raw", dialog.import_path(self.raw["Ivana"]))
        mother = self.open_dialog("Mara")
        mother.tests.append(dna.clean_test({"company": "MyHeritage"}))
        mother._fill_tests(0)
        mother.import_path(self.raw["Mara"])
        changes = mother.values()
        self.window.show_dna  # The window saves through edits.set_dna, one undoable edit.
        self.window.apply_edit(lambda: __import__("edits").set_dna(self.window.tree, changes), focus=self.id["Mara"])
        dialog.tree = self.window.tree
        report = dialog.compare_tests(self.id["Mara"], dna.tests_of(self.window.tree.people[self.id["Mara"]])[0])
        self.assertIn("cM", report)
        match = next(m for m in dialog.current_test()["matches"] if m["person"] == self.id["Mara"])
        self.assertGreater(match["cm"], 3300)  # Mother and son: everything.
        self.assertEqual(dna.check(self.window.tree, self.id["Ivana"], match)[0], "fits")
        both = dialog.values()
        self.assertEqual(set(both), {self.id["Ivana"], self.id["Mara"]})  # The mother gets the match too.
        self.window.apply_edit(lambda: __import__("edits").set_dna(self.window.tree, both), focus=self.id["Ivana"])
        dialog._fill_map()
        dialog.chromosomes.grab()  # Paints.
        # The panel tells the mother how she shares DNA with her son, and that it fits.
        self.window.select(self.id["Mara"])
        text = self.window.panel.details.text()
        self.assertIn("DNA", text)
        self.window.undo()
        self.assertEqual(dna.tests_of(self.window.tree.people[self.id["Ivana"]]), [])
        dialog.deleteLater()
        mother.deleteLater()

    def test_cancel_removes_raw_files_imported_now(self):
        dialog = self.open_dialog("Ivana")
        dialog.tests.append(dna.clean_test({"company": "23andMe"}))
        dialog._fill_tests(0)
        dialog.import_path(self.raw["Ivana"])
        written = list((Path(self.window.folder) / "dna").glob("*"))
        self.assertEqual(len(written), 1)
        dialog.reject()
        self.assertEqual(list((Path(self.window.folder) / "dna").glob("*")), [])

    def test_dna_stays_out_of_shared_copies(self):
        import datetime
        import privacy
        from gedcom import write_gedcom
        person = self.window.tree.people[self.id["Ivana"]]
        dna.store_tests(person, [dna.clean_test({"company": "MyHeritage", "kit": "KIT-SECRET",
                                                 "matches": [{"name": "Hidden Cousin", "cm": 100}]})])
        shared = privacy.shareable(self.window.tree, datetime.date(2026, 11, 15), hide_living=False)
        self.assertNotIn("dna", shared.people[self.id["Ivana"]].extra)
        self.assertNotIn("KIT-SECRET", write_gedcom(self.window.tree, None))
        self.assertNotIn("Hidden Cousin", write_gedcom(self.window.tree, None))

    def test_merging_and_deleting_keep_the_links_right(self):
        import edits
        tree = self.window.tree
        ivana = tree.people[self.id["Ivana"]]
        dna.store_tests(ivana, [dna.clean_test({"company": "MyHeritage",
                                                "matches": [{"name": "Mara", "cm": 3400, "person": self.id["Mara"]}]})])
        edits.delete_person(tree, self.id["Mara"])
        match = dna.tests_of(ivana)[0]["matches"][0]
        self.assertEqual((match["person"], match["name"]), ("", "Mara"))  # The match stays, unlinked.
