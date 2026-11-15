"""The map: projection, markers, one person's life as a line, giving places a position,
and the rule that nothing goes over the network without the person agreeing."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from map_dialog import MapDialog  # noqa: E402
from map_view import MapView, to_degrees, to_pixel  # noqa: E402
from model import place_records  # noqa: E402
from test_sources import parish_tree  # noqa: E402


def travelling_tree():
    """Davor born in Trogir, lived in Zagreb, died in Split; Seget has no position yet."""
    tree = parish_tree()
    tree.people["davor"].extra["events"] = [{"type": "residence", "date": "1980", "place": "Zagreb"},
                                            {"type": "occupation", "date": "1975", "place": "Seget", "text": "x"}]
    tree.people["davor"].living = "no"
    tree.people["davor"].death = {"date": "2010", "place": "Split"}
    tree.extra["places"].update({"Zagreb": {"lat": 45.815, "lon": 15.98}, "Split": {"lat": 43.508, "lon": 16.44}})
    return tree


class FakeSource:
    """Stands in for OpenStreetMap: answers every tile at once with a plain picture."""

    def __init__(self, ready):
        self.ready, self.asked = ready, []

    def want(self, z, x, y):
        self.asked.append((z, x, y))
        pixmap = QPixmap(256, 256)
        pixmap.fill(QColor("#cde"))
        self.ready(z, x, y, pixmap)

    def forget_others(self, wanted):
        pass


class ProjectionTests(unittest.TestCase):
    def test_degrees_and_pixels_go_back_and_forth(self):
        for lat, lon in ((43.5167, 16.25), (-33.9, 151.2), (0, 0), (60.1, -45.3)):
            back = to_degrees(*to_pixel(lat, lon, 12), 12)
            self.assertAlmostEqual(back[0], lat, places=6)
            self.assertAlmostEqual(back[1], lon, places=6)

    def test_only_the_tiles_in_view_are_asked_for(self):
        sources = []
        view = MapView(lambda ready: sources.append(FakeSource(ready)) or sources[-1])
        view.resize(600, 400)
        view.grab()
        asked = set(sources[0].asked)
        self.assertEqual(asked, {key[:3] for key in view.visible_tiles()})
        self.assertLessEqual(len(asked), 12)  # A 600 x 400 view needs at most 4 x 3 tiles.


class MapWindowTests(unittest.TestCase):
    def test_markers_and_places_without_a_position(self):
        dialog = MapDialog(None, travelling_tree(), "davor")
        labels = {m["label"] for m in dialog.view.markers}
        self.assertEqual(labels, {"Trogir", "Zagreb", "Split"})
        self.assertEqual(dialog.missing_places, ["Seget"])
        dialog.deleteLater()

    def test_one_life_is_drawn_place_to_place_in_date_order(self):
        dialog = MapDialog(None, travelling_tree(), "davor")
        dialog.only_focus.setChecked(True)
        self.assertEqual(dialog.view.path, [(43.5167, 16.25), (45.815, 15.98), (43.508, 16.44)])
        dialog.deleteLater()

    def test_clicking_the_map_gives_a_place_its_position(self):
        tree = travelling_tree()
        dialog = MapDialog(None, tree, "davor")
        dialog.resize(1000, 700)
        dialog.missing.setCurrentRow(0)
        dialog.pick.setChecked(True)
        dialog.view.point_clicked.emit(43.53, 16.24)
        self.assertEqual(dialog.missing_places, [])
        self.assertEqual(dialog.operations, [("set", "Seget", {"lat": 43.53, "lon": 16.24})])
        self.assertNotIn("Seget", place_records(tree))  # The tree itself changes only after OK.
        dialog.deleteLater()

    def test_a_search_result_can_be_used(self):
        class FakeSearch:
            def search(self, text, answer):
                answer([(f"{text}, Hrvatska", 43.53, 16.24)])

        dialog = MapDialog(None, travelling_tree(), "davor", search_factory=FakeSearch)
        dialog.missing.setCurrentRow(0)
        dialog.search_online()
        self.assertTrue(dialog.use_result.isVisibleTo(dialog))
        dialog.use_result.click()
        self.assertEqual(dialog.operations[-1][1], "Seget")
        dialog.deleteLater()

    def test_a_refused_search_sends_nothing(self):
        dialog = MapDialog(None, travelling_tree(), "davor", search_factory=lambda: None)
        dialog.missing.setCurrentRow(0)
        dialog.search_online()
        self.assertIsNone(dialog.search)
        self.assertEqual(dialog.operations, [])
        dialog.deleteLater()

    def test_without_a_tile_source_the_markers_sit_on_a_grid(self):
        dialog = MapDialog(None, travelling_tree(), offline_reason="Map pictures are off.")
        dialog.resize(900, 600)
        image = dialog.view.grab()
        self.assertFalse(image.isNull())
        self.assertEqual(dialog.view.message, "Map pictures are off.")
        marker = dialog.view.markers[0]
        point = dialog.view.screen_point(marker["lat"], marker["lon"])
        self.assertIs(dialog.view.marker_at(point + QPointF(2, 1)), marker)
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
