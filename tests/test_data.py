"""Data safety tests: dates, checks, saving, crashes, backups and bad files."""
import datetime
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import storage
from model import Family, Person, Tree, parse_date, validate
from sample import sample_tree
from storage import TreeLoadError, create_tree, make_backup, open_tree, save_tree

TODAY = datetime.date(2026, 11, 4)


def codes(tree):
    return {issue.code for issue in validate(tree)}


def family(key, partners, children=(), link="birth", relationship="married"):
    return Family(
        key, list(partners), relationship, [{"person": c, "link": link} for c in children]
    )


def tree_of(names, families=()):
    return Tree({n: Person(n, given=n) for n in names}, {f.id: f for f in families})


class TempFolder(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name) / "Test.tree"


class DateTests(unittest.TestCase):
    def test_accepted_forms(self):
        for text in ("1921", "1921-05", "1921-05-14", "abt 1921", "bef 1900", "aft 1900", "1880/1885"):
            self.assertIsNotNone(parse_date(text), text)

    def test_rejected_forms(self):
        for text in ("", "1921-13", "1921-02-30", "21", "soon", "1890/1880", "abt", "0000"):
            self.assertIsNone(parse_date(text), text)

    def test_leap_day(self):
        self.assertIsNotNone(parse_date("2024-02-29"))
        self.assertIsNone(parse_date("2023-02-29"))


class LabelTests(unittest.TestCase):
    def label(self, born, living="yes", died=None):
        return Person(
            "x",
            birth={"date": born} if born else None,
            death={"date": died} if died else None,
            living=living,
        ).age_label(TODAY)

    def test_exact_age_before_and_after_birthday(self):
        self.assertEqual(self.label("1980-11-04"), "46")
        self.assertEqual(self.label("1980-11-05"), "45")

    def test_year_only_is_approximate(self):
        self.assertEqual(self.label("1980"), "c. 46")
        self.assertEqual(self.label("abt 1980"), "c. 46")

    def test_deceased_show_years(self):
        self.assertEqual(self.label("abt 1921", "no", "1988"), "c. 1921 - 1988")

    def test_unknown_details_show_question_marks(self):
        self.assertEqual(self.label("", "no", "1988"), "? - 1988")
        self.assertEqual(self.label("1925", "no"), "1925 - ?")
        self.assertEqual(self.label("", "unknown"), "")

    def test_future_birth_is_not_a_negative_age(self):
        self.assertEqual(self.label("2030-01-01"), "2030 -")

    def test_empty_name_is_labelled(self):
        self.assertEqual(Person("x").display_name, "Unknown")


class ValidationTests(unittest.TestCase):
    def test_sample_has_no_problems(self):
        self.assertEqual(validate(sample_tree()), [])

    def test_missing_person_is_reported_and_kept(self):
        tree = tree_of(["a"], [family("f", ["a", "ghost"])])
        self.assertIn("missing_person", codes(tree))
        self.assertEqual(tree.families["f"].partners, ["a", "ghost"])

    def test_structure_problems(self):
        self.assertIn(
            "too_many_partners", codes(tree_of("abc", [family("f", ["a", "b", "c"])]))
        )
        self.assertIn("repeated_person", codes(tree_of("ab", [family("f", ["a"], ["b", "b"])])))
        self.assertIn("own_child", codes(tree_of("a", [family("f", ["a"], ["a"])])))
        self.assertIn(
            "bad_relationship",
            codes(tree_of("a", [family("f", ["a"], relationship="enemies")])),
        )
        self.assertIn("bad_child_link", codes(tree_of("ab", [family("f", ["a"], ["b"], "odd")])))

    def test_person_problems(self):
        checks = {
            "bad_date": Person("x", birth={"date": "soon"}),
            "bad_living": Person("x", living="maybe"),
            "dead_marked_living": Person("x", death={"date": "1990"}, living="yes"),
            "death_before_birth": Person(
                "x", birth={"date": "1990"}, death={"date": "1980"}, living="no"
            ),
        }
        for code, person in checks.items():
            self.assertIn(code, codes(Tree({"x": person})), code)

    def test_ancestor_loop(self):
        tree = tree_of("ab", [family("f", ["a"], ["b"]), family("g", ["b"], ["a"])])
        self.assertIn("ancestor_loop", codes(tree))

    def test_two_birth_families(self):
        tree = tree_of("abc", [family("f", ["a"], ["c"]), family("g", ["b"], ["c"])])
        self.assertIn("two_birth_families", codes(tree))

    def test_adoption_is_not_two_birth_families(self):
        tree = tree_of(
            "abc", [family("f", ["a"], ["c"]), family("g", ["b"], ["c"], "adopted")]
        )
        self.assertEqual(codes(tree), set())

    def test_photo_must_stay_in_media_folder(self):
        for path in ("/etc/passwd", "../secret.jpg", "media/../../x.jpg", "x.jpg", "C:\\x.jpg", "media\\x.jpg"):
            tree = Tree({"x": Person("x", photo=path)})
            self.assertIn("unsafe_photo", codes(tree), path)
        self.assertEqual(codes(Tree({"x": Person("x", photo="media/x.jpg")})), set())

    def test_top_ancestor_survives_a_loop(self):
        tree = tree_of("ab", [family("f", ["a"], ["b"]), family("g", ["b"], ["a"])])
        self.assertIn(tree.top_ancestor_of("a"), ("a", "b"))


class RoundTripTests(TempFolder):
    def test_everything_survives_save_and_open(self):
        tree = sample_tree()
        create_tree(self.folder, tree)
        self.assertEqual(open_tree(self.folder).tree, tree)

    def test_croatian_letters_stored_readably(self):
        create_tree(self.folder, sample_tree())
        text = (self.folder / "tree.json").read_text(encoding="utf-8")
        self.assertIn("Šimić", text)
        self.assertIn("Ružica", text)

    def test_unknown_fields_from_newer_data_survive(self):
        data = sample_tree().to_dict()
        data["future_top"] = {"a": 1}
        data["people"]["ante"]["nickname"] = "Stari"
        data["families"]["f-ante"]["future"] = [1, 2]
        self.folder.mkdir()
        (self.folder / "tree.json").write_text(json.dumps(data), encoding="utf-8")
        save_tree(self.folder, open_tree(self.folder).tree)
        saved = json.loads((self.folder / "tree.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["future_top"], {"a": 1})
        self.assertEqual(saved["people"]["ante"]["nickname"], "Stari")
        self.assertEqual(saved["families"]["f-ante"]["future"], [1, 2])

    def test_create_refuses_to_replace_a_tree(self):
        create_tree(self.folder, sample_tree())
        with self.assertRaises(FileExistsError):
            create_tree(self.folder, Tree())
        self.assertEqual(open_tree(self.folder).tree, sample_tree())

    def test_view_remembers_house(self):
        create_tree(self.folder, sample_tree())
        storage.save_view(self.folder, "stipe")
        self.assertEqual(open_tree(self.folder).house, "stipe")

    def test_view_for_missing_person_falls_back(self):
        create_tree(self.folder, sample_tree())
        storage.save_view(self.folder, "nobody")
        self.assertIsNone(open_tree(self.folder).house)


class CrashSafetyTests(TempFolder):
    def setUp(self):
        super().setUp()
        create_tree(self.folder, sample_tree())
        self.original = (self.folder / "tree.json").read_bytes()

    def changed_tree(self):
        tree = sample_tree()
        tree.people["ante"].given = "Changed"
        return tree

    def assert_original_intact(self):
        self.assertEqual((self.folder / "tree.json").read_bytes(), self.original)

    def test_failed_rename_keeps_old_file_and_cleans_up(self):
        with mock.patch("storage.os.replace", side_effect=OSError("disk trouble")):
            with self.assertRaises(OSError):
                save_tree(self.folder, self.changed_tree())
        self.assert_original_intact()
        self.assertEqual(list(self.folder.glob(".*.tmp")), [])

    def test_failed_flush_keeps_old_file(self):
        with mock.patch("storage.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                storage.atomic_write(self.folder / "tree.json", "broken")
        self.assert_original_intact()

    def test_data_that_cannot_be_written_never_touches_the_file(self):
        tree = sample_tree()
        tree.people["ante"].extra["bad"] = object()
        with self.assertRaises(TypeError):
            save_tree(self.folder, tree)
        self.assert_original_intact()

    def test_process_killed_mid_save_leaves_a_working_tree(self):
        script = textwrap.dedent(
            f"""
            import os, sys
            sys.path.insert(0, {str(ROOT)!r})
            import storage
            from sample import sample_tree
            tree = sample_tree()
            tree.people["ante"].given = "Changed"
            storage.os.replace = lambda *a: os._exit(9)
            storage.save_tree({str(self.folder)!r}, tree)
            """
        )
        result = subprocess.run([sys.executable, "-c", script], check=False)
        self.assertEqual(result.returncode, 9)
        self.assert_original_intact()
        self.assertEqual(open_tree(self.folder).tree, sample_tree())

    def test_real_save_replaces_content(self):
        save_tree(self.folder, self.changed_tree())
        self.assertEqual(open_tree(self.folder).tree.people["ante"].given, "Changed")


class BackupTests(TempFolder):
    def setUp(self):
        super().setUp()
        create_tree(self.folder, sample_tree())

    def backups(self):
        return storage._backups(self.folder)

    def test_open_makes_a_backup_with_the_data(self):
        open_tree(self.folder)
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(
            (self.backups()[0] / "tree.json").read_bytes(),
            (self.folder / "tree.json").read_bytes(),
        )

    def test_reopening_unchanged_does_not_erode_history(self):
        for _ in range(5):
            open_tree(self.folder)
        self.assertEqual(len(self.backups()), 1)

    def test_save_backs_up_previous_version_first(self):
        before = (self.folder / "tree.json").read_bytes()
        tree = sample_tree()
        tree.people["ante"].given = "Changed"
        save_tree(self.folder, tree)
        self.assertEqual((self.backups()[-1] / "tree.json").read_bytes(), before)

    def test_old_backups_are_pruned_oldest_first(self):
        tree = sample_tree()
        for number in range(6):
            tree.people["ante"].notes = str(number)
            (self.folder / "tree.json").write_text(json.dumps(tree.to_dict()), encoding="utf-8")
            make_backup(self.folder, keep=3)
        kept = [
            json.loads((b / "tree.json").read_text(encoding="utf-8"))["people"]["ante"]["notes"]
            for b in self.backups()
        ]
        self.assertEqual(kept, ["3", "4", "5"])

    def test_pruning_leaves_other_files_alone(self):
        keep_me = self.folder / "backups" / "my-own-copy.json"
        keep_me.write_text("{}")
        for number in range(4):
            (self.folder / "tree.json").write_text(json.dumps({"format_version": 1, "n": number}))
            make_backup(self.folder, keep=1)
        self.assertTrue(keep_me.exists())


class BadFileTests(TempFolder):
    def write(self, text):
        self.folder.mkdir(exist_ok=True)
        (self.folder / "tree.json").write_text(text, encoding="utf-8")

    def assert_refused_untouched(self, text):
        self.write(text)
        with self.assertRaises(TreeLoadError):
            open_tree(self.folder)
        self.assertEqual((self.folder / "tree.json").read_text(encoding="utf-8"), text)
        self.assertEqual(storage._backups(self.folder), [])

    def test_missing_tree(self):
        self.folder.mkdir()
        with self.assertRaises(TreeLoadError):
            open_tree(self.folder)

    def test_corrupt_json(self):
        self.assert_refused_untouched('{"format_version": 1, "people": {"a"')

    def test_wrong_top_level(self):
        self.assert_refused_untouched("[1, 2, 3]")

    def test_missing_or_bad_version(self):
        self.assert_refused_untouched('{"people": {}}')
        self.assert_refused_untouched('{"format_version": true}')
        self.assert_refused_untouched('{"format_version": 0}')

    def test_newer_version_is_refused(self):
        self.assert_refused_untouched('{"format_version": 999, "people": {}}')

    def test_wrong_field_types(self):
        self.assert_refused_untouched('{"format_version": 1, "people": {"a": {"given": 5}}}')
        self.assert_refused_untouched('{"format_version": 1, "people": {"a": {"birth": "1900"}}}')
        self.assert_refused_untouched('{"format_version": 1, "families": {"f": {"children": ["a"]}}}')

    def test_not_utf8_is_read_in_the_windows_encoding(self):
        # Saved again by an old Windows editor: still readable, not "damaged".
        self.folder.mkdir()
        (self.folder / "tree.json").write_bytes(b'{"format_version": 1, "people": {"a": {"given": "J\xf6rg"}}}')
        self.assertEqual(open_tree(self.folder).tree.people["a"].given, "Jörg")

    def test_corrupt_view_does_not_block_the_family(self):
        create_tree(self.folder, sample_tree())
        (self.folder / "view.json").write_text("garbage")
        opened = open_tree(self.folder)
        self.assertEqual(opened.tree, sample_tree())
        self.assertIn("view_unreadable", {i.code for i in opened.issues})

    def test_broken_links_open_with_a_report(self):
        data = {"format_version": 1, "people": {}, "families": {"f": {"partners": ["ghost"]}}}
        self.write(json.dumps(data))
        opened = open_tree(self.folder)
        self.assertIn("missing_person", {i.code for i in opened.issues})
        self.assertEqual(opened.tree.families["f"].partners, ["ghost"])


class MigrationTests(TempFolder):
    def test_old_format_is_backed_up_then_migrated(self):
        self.folder.mkdir()
        old = '{"format_version": 1, "people": {}}'
        (self.folder / "tree.json").write_text(old)

        def upgrade(data):
            return {**data, "migrated": True}

        with mock.patch.object(storage, "FORMAT_VERSION", 2), mock.patch.dict(
            storage.MIGRATIONS, {1: upgrade}
        ):
            opened = open_tree(self.folder)
        self.assertTrue(opened.tree.extra["migrated"])
        first = storage._backups(self.folder)[0]
        self.assertEqual((first / "tree.json").read_text(), old)


if __name__ == "__main__":
    unittest.main()


class FamilyLineHeadTests(unittest.TestCase):
    def test_heads_are_never_empty_after_cross_links(self):
        # Luka (no parents) is only ever a second partner; everyone else has parents.
        from model import Family, Person, Tree
        people = {k: Person(k, given=k) for k in ("luka", "iva", "start")}
        families = {
            "f1": Family("f1", ["iva", "luka"], "married", [{"person": "start", "link": "birth"}]),
            "f2": Family("f2", ["start", "luka"], "married", [{"person": "iva", "link": "birth"}]),
        }
        tree = Tree(people, families)
        self.assertTrue(tree.family_line_heads())


class LanguageTests(unittest.TestCase):
    def test_every_language_passes_the_translation_check(self):
        import strings
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        from i18n_check import problems
        self.assertGreater(len(strings.LANGUAGES), 2)
        for code, table in strings.STRINGS.items():
            self.assertEqual(problems(strings.STRINGS["en"], table), [], code)

    def test_dates_shown_in_every_language_can_be_typed_back(self):
        import strings
        from model import date_input_text, normalize_date_input
        try:
            for code in strings.LANGUAGES:
                strings.set_language(code)
                for stored in ("abt 1921", "bef 1900", "aft 1900", "1880/1885", "1921-05-14", "abt 1921-05",
                               "1921", "1708-02-10 julian", "abt 1708 julian", "1708/09", "1708/09-02-10",
                               "1700-02-29 julian", "from 1950 to 1960", "from 1950", "to 1960",
                               "from 1950-03-01 to 1960-07-15", "from 1700 julian to 1710 julian"):
                    shown = date_input_text(stored)
                    self.assertEqual(normalize_date_input(shown), stored, (code, shown))
        finally:
            strings.set_language("en")

    def test_the_computer_language_picks_the_nearest_table(self):
        from strings import pick_language
        self.assertEqual(pick_language(["de-AT", "en-US"]), "de")
        self.assertEqual(pick_language(["hr-HR"]), "hr")
        self.assertEqual(pick_language(["pt-PT"]), "pt_BR")
        self.assertEqual(pick_language(["zh-Hant-TW"]), "zh_TW")
        self.assertEqual(pick_language(["zh-Hans-CN"]), "zh_CN")
        self.assertEqual(pick_language(["fi-FI", "fr-FR"]), "fr")
        self.assertEqual(pick_language(["fi-FI"]), "en")
        self.assertEqual(pick_language([]), "en")

    def test_codes_are_found_in_any_spelling(self):
        import strings
        self.assertEqual(strings.canonical("pt_br"), "pt_BR")
        self.assertEqual(strings.canonical("zh-tw"), "zh_TW")
        self.assertIsNone(strings.canonical("xx"))
        try:
            strings.set_language("xx")
            self.assertEqual(strings.LANGUAGE, "en")
            strings.set_language("system", ["ar-EG"])
            self.assertTrue(strings.right_to_left())
        finally:
            strings.set_language("en")


class KinshipTests(unittest.TestCase):
    def words(self, a, b, language="en"):
        from kinship import describe
        from sample import sample_tree
        return describe(sample_tree(), a, b, language)[0]

    def test_close_relatives(self):
        cases = {("ivana", "luka"): "father", ("ivana", "marko"): "brother",
                 ("ivana", "ante"): "grandfather (father's side)", ("ivana", "stipe"): "grandfather (mother's side)",
                 ("ivana", "tomo"): "first cousin (father's side)", ("ivana", "zvonko"): "uncle (mother's side)",
                 ("ante", "ivana"): "granddaughter", ("luka", "tomo"): "nephew"}
        for (a, b), want in cases.items():
            self.assertEqual(self.words(a, b), want, (a, b))

    def test_in_laws_and_strangers(self):
        self.assertEqual(self.words("mara", "luka"), "husband")
        self.assertEqual(self.words("mara", "ante"), "father-in-law")
        self.assertEqual(self.words("ana", "luka"), "brother-in-law")
        self.assertEqual(self.words("ivana", "ana"), "aunt by marriage")
        self.assertEqual(self.words("stipe", "ante"), "not related through the recorded links")

    def test_croatian_terms(self):
        cases = {("ivana", "josip"): "stric (očeva strana)", ("ivana", "zvonko"): "ujak (majčina strana)",
                 ("ivana", "tomo"): "bratić (očeva strana)", ("mara", "ante"): "svekar",
                 ("ivana", "ana"): "strina", ("ivana", "ante"): "djed (očeva strana)"}
        for (a, b), want in cases.items():
            self.assertEqual(self.words(a, b, "hr"), want, (a, b))

    def test_other_languages_spell_the_relation_out_step_by_step(self):
        from kinship import describe
        from sample import sample_tree
        term = lambda key: key[4:]  # noqa: E731 - "kin_father" -> "father"
        cases = {("ivana", "luka"): "father", ("ivana", "marko"): "brother",
                 ("ivana", "ante"): "father › father", ("ivana", "tomo"): "father › brother › son",
                 ("ivana", "ana"): "father › brother › wife", ("mara", "ante"): "husband › father",
                 ("ante", "ivana"): "son › daughter", ("stipe", "ante"): "none"}
        for (a, b), want in cases.items():
            self.assertEqual(describe(sample_tree(), a, b, "de", term)[0], want, (a, b))

    def test_cousins_removed_and_half_siblings(self):
        from kinship import describe
        from model import Family, Person, Tree
        people = {k: Person(k, given=k, sex="M") for k in ("gp", "a", "b", "a1", "b1", "a2", "dad", "mum1", "mum2", "x", "y")}
        families = {
            "f1": Family("f1", ["gp"], "married", [{"person": "a", "link": "birth"}, {"person": "b", "link": "birth"}]),
            "f2": Family("f2", ["a"], "married", [{"person": "a1", "link": "birth"}]),
            "f3": Family("f3", ["b"], "married", [{"person": "b1", "link": "birth"}]),
            "f4": Family("f4", ["a1"], "married", [{"person": "a2", "link": "birth"}]),
            "f5": Family("f5", ["dad", "mum1"], "married", [{"person": "x", "link": "birth"}]),
            "f6": Family("f6", ["dad", "mum2"], "married", [{"person": "y", "link": "birth"}]),
        }
        tree = Tree(people, families)
        self.assertEqual(describe(tree, "b1", "a2")[0], "first cousin once removed (father's side)")
        self.assertEqual(describe(tree, "x", "y")[0], "half-brother")
