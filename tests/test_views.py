"""Lifelines, the gallery and the statistics page."""
import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import views_dialogs as views  # noqa: E402
from sample import sample_tree  # noqa: E402

TODAY = datetime.date(2026, 11, 14)


class LifelineTests(unittest.TestCase):
    def test_rows_run_from_birth_to_death_or_today(self):
        tree = sample_tree()
        rows = {row[0]: row for row in views.lifeline_rows(tree, list(tree.people), TODAY)}
        self.assertEqual(rows["luka"][2:], (1949, 2017, False))
        living = next(row for row in rows.values() if tree.people[row[0]].living == "yes")
        self.assertEqual(living[3], 2026)
        births = [row[2] for row in views.lifeline_rows(tree, list(tree.people), TODAY)]
        self.assertEqual(births, sorted(births))

    def test_ancestors_and_descendants(self):
        tree = sample_tree()
        self.assertEqual(set(views.related(tree, "ivana", "ancestors")) >= {"ivana", "luka", "ante"}, True)
        self.assertIn("ivana", views.related(tree, "ante", "descendants"))
        self.assertNotIn("ante", views.related(tree, "ivana", "descendants"))

    def test_the_window_draws_and_goes_to_a_person(self):
        dialog = views.LifelinesDialog(None, sample_tree(), "ivana", TODAY)
        bars = [item for item in dialog.view.scene().items() if item.data(0)]
        self.assertTrue(bars)
        dialog.who.setCurrentIndex(dialog.who.findData("ancestors"))
        self.assertLess(len(dialog.rows()), len(sample_tree().people))
        dialog._go("luka")
        self.assertEqual(dialog.chosen, "luka")
        dialog.deleteLater()


class GalleryTests(unittest.TestCase):
    def test_portraits_and_document_pictures_are_shown(self):
        tree = sample_tree()
        tree.people["luka"].photo = "media/luka.jpg"
        tree.people["ante"].extra["documents"] = [{"file": "media/docs/group.jpg", "title": "Wedding"},
                                                  {"file": "media/docs/letter.pdf", "title": "Letter"}]
        picture = QPixmap(40, 50)
        picture.fill(QColor("#888888"))
        dialog = views.GalleryDialog(None, tree, lambda stored: picture)
        self.assertEqual(dialog.list.count(), 2)  # The portrait and the picture; not the PDF.
        dialog.with_documents.setChecked(False)
        self.assertEqual(dialog.list.count(), 1)
        dialog.deleteLater()


class StatisticsTests(unittest.TestCase):
    def test_numbers_for_the_charts(self):
        numbers = views.statistics(sample_tree(), TODAY)
        self.assertEqual(numbers["people"], 16)
        self.assertEqual(numbers["surnames"][0][0], "Šimić")
        self.assertTrue(all(decade % 10 == 0 for decade, _n in numbers["births_per_decade"]))
        dialog = views.StatisticsDialog(None, sample_tree(), TODAY, "summary")
        self.assertEqual(dialog.tabs.count(), 5)
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
