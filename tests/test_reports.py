"""Reports, books and the wall poster."""
import datetime
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

import privacy  # noqa: E402
import reports  # noqa: E402
from model import Family, Person, Tree  # noqa: E402
from sample import sample_tree  # noqa: E402

app = QApplication.instance() or QApplication([])
TODAY = datetime.date(2026, 11, 13)


def text_of(page_html):
    from PySide6.QtGui import QTextDocument
    document = QTextDocument()
    document.setHtml(page_html)
    return document.toPlainText()


def pdf_pages(path):
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", Path(path).read_bytes()))


def cousins_married():
    """Two cousins married: their child reaches grandpa Ante through both parents."""
    p = {k: Person(k, given=k.capitalize(), surname="Šimić", sex=s, living="no", death={"date": "", "place": ""})
         for k, s in (("ante", "M"), ("mara", "F"), ("luka", "M"), ("ana", "F"), ("ivo", "M"), ("eva", "F"),
                      ("kid", "M"), ("x", "F"), ("y", "M"))}
    f = {"f0": Family("f0", ["ante", "mara"], "married", [{"person": "luka", "link": "birth"},
                                                          {"person": "ana", "link": "birth"}]),
         "f1": Family("f1", ["luka", "x"], "married", [{"person": "ivo", "link": "birth"}]),
         "f2": Family("f2", ["y", "ana"], "married", [{"person": "eva", "link": "birth"}]),
         "f3": Family("f3", ["ivo", "eva"], "married", [{"person": "kid", "link": "birth"}])}
    return Tree(p, f)


class BookTests(unittest.TestCase):
    def test_an_ancestor_book_numbers_the_usual_way_and_lists_shared_ancestors_once(self):
        text = text_of(reports.ancestor_book(cousins_married(), "kid", 6))
        for line in ("No. 1", "Kid Šimić", "No. 2", "Ivo Šimić", "No. 3", "Eva Šimić", "No. 4", "Luka Šimić",
                     "Index of names"):
            self.assertIn(line, text)
        # Ante is Ivo's grandfather (no. 8) and Eva's (no. 12): one entry, then "see no. 8".
        self.assertIn("No. 8", text)
        self.assertIn("The same person as no. 8", text)
        self.assertEqual(text.count("Ante Šimić"), 2)  # The entry and the index line... once each.

    def test_a_descendant_book_lists_children_under_their_parents(self):
        text = text_of(reports.descendant_book(sample_tree(), "ante", 3))
        self.assertIn("Descendants of Ante Šimić", text)
        self.assertIn("Generation 3", text)
        self.assertRegex(text, r"Children:\s*\n?.*Luka Šimić \(No\. \d+\)")

    def test_sources_become_numbered_notes_and_places_an_index(self):
        tree = sample_tree()
        tree.extra["sources"] = {"s1": {"title": "Parish book of Trogir"}}
        tree.people["ante"].birth = {"date": "1921", "place": "Trogir", "citations": [{"source": "s1", "page": "p. 4"}]}
        text = text_of(reports.family_sheet(tree, "ante"))
        self.assertIn("[1]", text)
        self.assertIn("Parish book of Trogir, p. 4", text)
        self.assertIn("Index of places", text)
        self.assertIn("Trogir", text.split("Index of places")[1])
        quiet = text_of(reports.family_sheet(tree, "ante", notes=False, sources=False))
        self.assertNotIn("Parish book", quiet)

    def test_a_shared_report_never_shows_living_people(self):
        tree = sample_tree()
        living = [p for p in tree.people.values() if privacy.counts_as_living(p, TODAY)]
        text = text_of(reports.descendant_book(privacy.shareable(tree, TODAY), "ante", 4))
        for person in living:
            self.assertNotIn(person.display_name, text)

    def test_the_document_becomes_a_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "book.pdf"
            reports.write_document(reports.descendant_book(sample_tree(), "ante", 4), path)
            self.assertGreaterEqual(pdf_pages(path), 1)
            self.assertEqual([p.name for p in Path(folder).iterdir()], ["book.pdf"])  # No temporary file left.

    @unittest.skipUnless(reports.odt_supported(), "this Qt has no OpenDocument writer")
    def test_the_document_becomes_an_odt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "book.odt"
            reports.write_document(reports.family_sheet(sample_tree(), "ante"), path)
            self.assertEqual(path.read_bytes()[:2], b"PK")


class PosterTests(unittest.TestCase):
    def scene(self):
        from canvas import INK_PRINT
        from exports import prepared_scene
        from house_layout import layout_family
        tree = sample_tree()
        return prepared_scene(tree, layout_family(tree, "ante"), TODAY, lambda person: None, INK_PRINT)

    def test_tiles_cover_the_chart_and_one_sheet_is_one_page(self):
        import poster
        scene, area = self.scene()
        with tempfile.TemporaryDirectory() as folder:
            one = Path(folder) / "one.pdf"
            self.assertEqual(poster.write_poster(scene, area, one, "A1", 1), 1)
            self.assertEqual(pdf_pages(one), 1)
            tiles = Path(folder) / "tiles.pdf"
            _orientation, rows, columns = poster.plan(area, "A4", 3)
            count = poster.write_poster(scene, area, tiles, "A4", 3, lambda r, c: f"Row {r}, column {c}")
            self.assertEqual((count, columns), (rows * columns, 3))
            self.assertEqual(pdf_pages(tiles), count)
            self.assertLess(tiles.stat().st_size, 20_000_000)  # Vectors, not one giant picture.


if __name__ == "__main__":
    unittest.main()
