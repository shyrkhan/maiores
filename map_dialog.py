"""The Map window: where things happened, one marker per place; one person's life drawn
place to place in date order; and giving positions to places that have none, by clicking
on the map or by searching a place name online (only when asked, see PlaceSearch).
`operations` replays the position changes on the tree, like the Places window."""
import json
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout,
)

import edits
from map_view import USER_AGENT, MapView
from model import all_facts, date_input_text, fold_text, parse_date, place_coordinates, place_records
from screen import fit_to_screen
from strings import collation_key, t

DEFAULT_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
SHOW = ("all", "birth", "death", "marriage", "other")


class PlaceSearch:
    """Coordinates for a place name from OpenStreetMap's Nominatim, following its usage
    policy: only when the user presses Search (never while typing), at most one request a
    second, answers cached on disk, the program named in the User-Agent."""

    def __init__(self, cache_file, url=DEFAULT_SEARCH_URL):
        from map_view import network
        self.url, self.cache_file = url, Path(cache_file)
        self.manager = network()
        self.waiting, self.busy, self.stopped = [], False, False
        try:
            self.cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}

    def search(self, text, answer):
        """answer([(label, lat, lon), ...]) once known."""
        key = fold_text(text.strip())
        if key in self.cache:
            answer([tuple(hit) for hit in self.cache[key]])
            return
        self.waiting.append((key, text.strip(), answer))
        self._next()

    last_sent = 0.0  # For the whole program: one search a second, however many windows.

    def _next(self):
        if self.busy or not self.waiting or self.stopped:
            return
        import time
        wait = PlaceSearch.last_sent + 1.1 - time.monotonic()
        if wait > 0:
            QTimer.singleShot(int(wait * 1000) + 10, self._next)
            return
        PlaceSearch.last_sent = time.monotonic()
        from PySide6.QtCore import QUrlQuery
        from PySide6.QtNetwork import QNetworkRequest
        key, text, answer = self.waiting.pop(0)
        url = QUrl(self.url)
        query = QUrlQuery()
        for name, value in (("q", text), ("format", "jsonv2"), ("limit", "5")):
            query.addQueryItem(name, value)
        url.setQuery(query)
        request = QNetworkRequest(url)
        request.setRawHeader(b"User-Agent", USER_AGENT)
        self.busy = True
        reply = self.manager.get(request)
        reply.finished.connect(lambda: self._done(reply, key, answer))

    def stop(self):
        """The window is closing: queued searches are dropped and a late answer goes nowhere."""
        self.stopped = True
        self.waiting.clear()

    def _done(self, reply, key, answer):
        from PySide6.QtNetwork import QNetworkReply
        if self.stopped:
            reply.deleteLater()
            return
        hits = []
        if reply.error() == QNetworkReply.NetworkError.NoError:
            try:
                for item in json.loads(bytes(reply.readAll()).decode("utf-8")):
                    hits.append((item.get("display_name", ""), float(item["lat"]), float(item["lon"])))
            except (ValueError, KeyError, TypeError):
                hits = []
            self.cache[key] = hits
            try:
                self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                self.cache_file.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        reply.deleteLater()
        answer(hits)
        self.busy = False
        self._next()


class MapDialog(QDialog):
    def __init__(self, parent, tree, focus=None, source_factory=None, search_factory=None, offline_reason=""):
        super().__init__(parent)
        self.setWindowTitle(t("map_window_title"))
        fit_to_screen(self, 1180, 760)
        self.tree, self.focus, self.chosen = tree, focus, None
        self.work = edits.copy_tree(tree)
        self.operations, self.search, self.hits = [], None, []
        self.search_factory = search_factory  # Asks before the first search, then gives a PlaceSearch.
        self.view = MapView(source_factory)
        self.view.message = offline_reason
        self.view.marker_clicked.connect(self._marker_clicked)
        self.view.point_clicked.connect(self._point_clicked)
        self.show_kind = QComboBox()
        for kind in SHOW:
            self.show_kind.addItem(t(f"map_show_{kind}"), kind)
        self.show_kind.currentIndexChanged.connect(lambda _i: self.refresh())
        name = tree.people[focus].display_name if focus in tree.people else ""
        self.only_focus = QCheckBox(t("map_only_life", name=name))
        self.only_focus.setEnabled(bool(name))
        self.only_focus.toggled.connect(lambda _on: self.refresh(fit=True))
        self.events = QListWidget()
        self.events.itemActivated.connect(self._go)
        self.missing_label = QLabel()
        self.missing_label.setWordWrap(True)
        self.missing = QListWidget()
        self.missing.currentRowChanged.connect(lambda _row: self._missing_chosen())
        self.pick = QPushButton(t("map_pick"))
        self.pick.setCheckable(True)
        self.pick.toggled.connect(self._picking)
        self.find = QPushButton(t("map_search"))
        self.find.clicked.connect(self.search_online)
        self.find.setEnabled(search_factory is not None)
        self.find.setToolTip("" if search_factory is not None else t("map_search_off"))
        self.results = QComboBox()
        self.results.setVisible(False)
        self.use_result = QPushButton(t("map_use_result"))
        self.use_result.setVisible(False)
        self.use_result.clicked.connect(self._use_result)
        side = QVBoxLayout()
        side.addWidget(QLabel(t("map_show")))
        side.addWidget(self.show_kind)
        side.addWidget(self.only_focus)
        side.addWidget(QLabel(t("map_here")))
        side.addWidget(self.events, 2)
        side.addWidget(self.missing_label)
        side.addWidget(self.missing, 1)
        place_row = QHBoxLayout()
        place_row.addWidget(self.pick)
        place_row.addWidget(self.find)
        side.addLayout(place_row)
        side.addWidget(self.results)
        side.addWidget(self.use_result)
        body = QHBoxLayout()
        body.addWidget(self.view, 3)
        body.addLayout(side, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)
        self.refresh(fit=True)

    def rows(self):
        kind = self.show_kind.currentData()
        rows = [r for r in all_facts(self.work) if r.place]
        if self.only_focus.isChecked():
            rows = [r for r in rows if self.focus in (r.person_id, r.with_id)]
        if kind == "other":
            return [r for r in rows if r.kind not in ("birth", "death", "marriage")]
        return [r for r in rows if kind == "all" or r.kind == kind]

    def refresh(self, fit=False):
        records = place_records(self.work)
        by_place, missing = {}, []
        for row in self.rows():
            by_place.setdefault(row.place, []).append(row)
        markers = []
        for place, rows in by_place.items():
            where = place_coordinates(self.work, place, records)
            if where is None:
                missing.append(place)
                continue
            markers.append({"lat": where[0], "lon": where[1], "label": place, "count": len(rows), "key": place})
        self.by_place = by_place
        self.view.markers = markers
        self.view.path = self._life_path(records) if self.only_focus.isChecked() else []
        # The list beside the map follows the filter too: only the events still shown.
        if self.view.selected in by_place:
            self._marker_clicked(self.view.selected)
        else:
            self.view.selected = None
            self.events.clear()
        if fit:
            self.view.fit([(m["lat"], m["lon"]) for m in markers])
        self.view.update()
        self.missing_places = sorted(missing, key=collation_key)
        self.missing.clear()
        self.missing.addItems(self.missing_places)
        self.missing_label.setText(t("map_missing", count=len(self.missing_places)))
        self._missing_chosen()

    def _life_path(self, records):
        """One person's places in date order: where they were born, lived, married, died."""
        dated = []
        for row in self.rows():
            parsed = parse_date(row.date)
            where = place_coordinates(self.work, row.place, records)
            if parsed and where:
                dated.append(((parsed.year, parsed.month or 0, parsed.day or 0), where))
        points = [where for _when, where in sorted(dated)]
        return [p for n, p in enumerate(points) if n == 0 or p != points[n - 1]]

    def _marker_clicked(self, place):
        from dialogs import fact_label
        self.events.clear()
        for row in sorted(self.by_place.get(place, []), key=lambda r: (r.date or "9999", r.kind)):
            item = QListWidgetItem(f"{date_input_text(row.date) or '?'}   {fact_label(self.tree, row)}")
            item.setData(Qt.ItemDataRole.UserRole, row.person_id)
            self.events.addItem(item)

    def current_missing(self):
        row = self.missing.currentRow()
        return self.missing_places[row] if 0 <= row < len(self.missing_places) else None

    def _missing_chosen(self):
        chosen = self.current_missing() is not None
        self.pick.setEnabled(chosen)
        self.find.setEnabled(chosen and self.search_factory is not None)
        self.results.setVisible(False)
        self.use_result.setVisible(False)
        if not chosen and self.pick.isChecked():
            self.pick.setChecked(False)

    def _picking(self, on):
        self.view.picking = on
        self.view.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    def set_position(self, place, lat, lon):
        record = {**place_records(self.work).get(place, {}), "lat": round(lat, 5), "lon": round(lon, 5)}
        edits.set_place(self.work, place, record)
        self.operations.append(("set", place, record))
        self.pick.setChecked(False)
        self.refresh()

    def _point_clicked(self, lat, lon):
        place = self.current_missing()
        if place is not None:
            self.set_position(place, lat, lon)

    def search_online(self):
        place = self.current_missing()
        if place is None or self.search_factory is None:
            return
        if self.search is None:
            self.search = self.search_factory()
            if self.search is None:  # Not allowed: nothing is sent.
                return
        self.find.setEnabled(False)
        self.search.search(place, lambda hits, place=place: self._found(place, hits))

    def _found(self, place, hits):
        self.find.setEnabled(self.current_missing() is not None and self.search_factory is not None)
        if place != self.current_missing():
            return
        self.hits = hits
        self.results.clear()
        if not hits:
            self.results.addItem(t("map_search_nothing"))
        for label, lat, lon in hits:
            self.results.addItem(f"{label}  ({lat:.4f}, {lon:.4f})")
        self.results.setVisible(True)
        self.use_result.setVisible(bool(hits))

    def _use_result(self):
        place, row = self.current_missing(), self.results.currentIndex()
        if place is not None and 0 <= row < len(self.hits):
            _label, lat, lon = self.hits[row]
            self.set_position(place, lat, lon)

    def _go(self, item):
        self.chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def done(self, result):
        """Closing with requests still out: stop them before the window's parts go away."""
        if self.view.source is not None:
            self.view.source.stop()
        if self.search is not None:
            self.search.stop()
        super().done(result)
