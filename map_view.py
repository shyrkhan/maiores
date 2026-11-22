"""A map widget: OpenStreetMap pictures (tiles) with markers for places, drawn by this
program rather than a web browser, so it stays small and works where a browser engine
doesn't exist.

It follows the OpenStreetMap tile usage policy (operations.osmfoundation.org):
- only the tiles in view are requested, never areas ahead of time or for offline use;
- requests go through Qt's disk cache, which honours the server's caching headers;
- the program names itself in the User-Agent (no personal details), over HTTPS;
- "© OpenStreetMap contributors" is always shown on the map, linking to the licence.
Without a tile source (no consent, no network, tests) the markers sit on a plain grid.
"""
import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

TILE = 256
MIN_ZOOM, MAX_ZOOM = 2, 18
ATTRIBUTION = "© OpenStreetMap contributors"
COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
DEFAULT_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = b"MaioresDesktop/1.4 (desktop genealogy program)"


def to_pixel(lat, lon, zoom):
    """Web Mercator: degrees to pixels on the whole-world map at this zoom."""
    lat = max(-85.0511, min(85.0511, lat))
    scale = TILE * 2 ** zoom
    x = (lon + 180.0) / 360.0 * scale
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * scale
    return x, y


def to_degrees(x, y, zoom):
    scale = TILE * 2 ** zoom
    lon = x / scale * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / scale))))
    return lat, lon


def _shortest_way_round(points):
    """The points with longitudes shifted by 360 where that brings them together: 179 E and
    179 W are 2 degrees apart across the 180th meridian, not 358 the other way."""
    lons = sorted({lon % 360.0 for _lat, lon in points})
    if len(lons) < 2:
        return list(points)
    gaps = [(lons[(i + 1) % len(lons)] - lons[i]) % 360.0 for i in range(len(lons))]
    widest = max(range(len(lons)), key=lambda i: gaps[i])
    start = lons[(widest + 1) % len(lons)]  # The span starts after the widest empty stretch.
    return [(lat, start + (lon % 360.0 - start) % 360.0) for lat, lon in points]


_MANAGERS = {}


def network(cache_folder=None):
    """One network manager for the whole program run (per cache), never freed while a
    request is out: a manager freed with requests pending crashes Qt."""
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache
    key = str(cache_folder or "")
    if key not in _MANAGERS:
        manager = QNetworkAccessManager()
        if cache_folder:
            cache = QNetworkDiskCache(manager)
            cache.setCacheDirectory(key)
            cache.setMaximumCacheSize(300 * 1024 * 1024)
            manager.setCache(cache)
        _MANAGERS[key] = manager
    return _MANAGERS[key]


class TileSource:
    """Loads tiles over the network through a disk cache. `ready(z, x, y, pixmap)` is called
    as each arrives. Created only after the user agreed to load map pictures."""

    def __init__(self, cache_folder, ready, url=DEFAULT_TILE_URL):
        self.url, self.ready, self.pending = url, ready, {}
        self.manager = network(cache_folder)
        self.stopped = False

    @staticmethod
    def available():
        from PySide6.QtNetwork import QSslSocket
        return QSslSocket.supportsSsl()

    def want(self, z, x, y):
        key = (z, x, y)
        if key in self.pending or self.stopped:
            return
        from PySide6.QtNetwork import QNetworkRequest
        request = QNetworkRequest(QUrl(self.url.format(z=z, x=x, y=y)))
        request.setRawHeader(b"User-Agent", USER_AGENT)
        request.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute,
                             QNetworkRequest.CacheLoadControl.PreferCache)
        reply = self.manager.get(request)
        self.pending[key] = reply
        reply.finished.connect(lambda key=key, reply=reply: self._finished(key, reply))

    def stop(self):
        """The map is closing: answers still on their way go nowhere."""
        self.stopped = True
        for reply in list(self.pending.values()):
            reply.abort()

    def forget_others(self, wanted):
        """Tiles that scrolled out of view before arriving are not needed any more."""
        for key, reply in list(self.pending.items()):
            if key not in wanted:
                reply.abort()

    def _finished(self, key, reply):
        from PySide6.QtNetwork import QNetworkReply
        self.pending.pop(key, None)
        if not self.stopped and reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self.ready(*key, pixmap)
        reply.deleteLater()


class MapView(QWidget):
    """Markers: list of dicts {"lat", "lon", "label", "count", "key"}; `path` is a list of
    (lat, lon) drawn as a line (one person's life, place to place). Emits marker_clicked(key)
    and point_clicked(lat, lon) for setting a place's position by clicking."""

    marker_clicked = Signal(str)
    point_clicked = Signal(float, float)

    def __init__(self, source_factory=None):
        super().__init__()
        self.zoom, self.centre = 6, (44.5, 16.0)
        self.markers, self.path, self.selected = [], [], None
        self.tiles = {}
        self.source = source_factory(self._tile_ready) if source_factory else None
        self.message = ""
        self.picking = False
        self._drag = None
        self.setMinimumSize(QSize(480, 360))
        self.setMouseTracking(True)

    def sizeHint(self):
        return QSize(820, 600)

    # Where things are on screen.
    def _origin(self):
        cx, cy = to_pixel(*self.centre, self.zoom)
        return cx - self.width() / 2, cy - self.height() / 2

    def screen_point(self, lat, lon):
        """The map repeats east-west: a point is drawn in the copy nearest the centre, so
        places either side of the 180th meridian sit side by side."""
        x, y = to_pixel(lat, lon, self.zoom)
        ox, oy = self._origin()
        world = TILE * 2 ** self.zoom
        cx = ox + self.width() / 2
        x += round((cx - x) / world) * world
        return QPointF(x - ox, y - oy)

    def degrees_at(self, point):
        ox, oy = self._origin()
        return to_degrees(ox + point.x(), oy + point.y(), self.zoom)

    def fit(self, points):
        """Centre and zoom so every point shows."""
        if not points:
            return
        points = _shortest_way_round(points)
        for zoom in range(MAX_ZOOM - 4, MIN_ZOOM - 1, -1):
            xs, ys = zip(*(to_pixel(lat, lon, zoom) for lat, lon in points))
            if max(xs) - min(xs) < self.width() * 0.8 and max(ys) - min(ys) < self.height() * 0.8:
                break
        self.zoom = zoom
        lat, lon = to_degrees((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, zoom)
        self.centre = (lat, (lon + 180.0) % 360.0 - 180.0)
        self.update()

    def visible_tiles(self):
        ox, oy = self._origin()
        count = 2 ** self.zoom
        first_x, first_y = int(ox // TILE), int(oy // TILE)
        last_x, last_y = int((ox + self.width()) // TILE), int((oy + self.height()) // TILE)
        return [(self.zoom, x % count, y, x, y) for x in range(first_x, last_x + 1)
                for y in range(max(0, first_y), min(count - 1, last_y) + 1)]

    def _tile_ready(self, z, x, y, pixmap):
        self.tiles[(z, x, y)] = pixmap
        if len(self.tiles) > 400:  # Only what is on screen and nearby stays in memory.
            for key in list(self.tiles)[:100]:
                del self.tiles[key]
        self.update()

    # Drawing.
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#dfe6ec"))
        ox, oy = self._origin()
        wanted = set()
        for z, wrapped_x, y, x, _y in self.visible_tiles():
            key = (z, wrapped_x, y)
            wanted.add(key)
            target = QRectF(x * TILE - ox, y * TILE - oy, TILE, TILE)
            if key in self.tiles:
                painter.drawPixmap(target.toRect(), self.tiles[key])
            else:
                painter.setPen(QPen(QColor("#c4ccd4"), 1))
                painter.drawRect(target)
                if self.source is not None:
                    self.source.want(*key)
        if self.source is not None:
            self.source.forget_others(wanted)
        self._paint_path(painter)
        self._paint_markers(painter)
        self._paint_attribution(painter)
        if self.message:
            painter.setPen(QColor("#40464d"))
            painter.drawText(self.rect().adjusted(12, 10, -12, -10),
                             Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                             self.message)

    def _paint_path(self, painter):
        if len(self.path) < 2:
            return
        line = QPainterPath(self.screen_point(*self.path[0]))
        for lat, lon in self.path[1:]:
            line.lineTo(self.screen_point(lat, lon))
        painter.setPen(QPen(QColor("#d9822b"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(line)

    def _paint_markers(self, painter):
        font = QFont()
        font.setPointSizeF(8.5)
        painter.setFont(font)
        for marker in self.markers:
            point = self.screen_point(marker["lat"], marker["lon"])
            chosen = marker["key"] == self.selected
            radius = 6 + min(8, marker.get("count", 1))
            painter.setPen(QPen(QColor("white"), 2))
            painter.setBrush(QColor("#e0a020" if chosen else "#2f6fd1"))
            painter.drawEllipse(point, radius, radius)
            if chosen or self.zoom >= 9:
                painter.setPen(QColor("#1d1f22"))
                painter.drawText(point + QPointF(radius + 3, 4), marker["label"])

    def _attribution_rect(self):
        return QRectF(self.width() - 210, self.height() - 20, 206, 18)

    def _paint_attribution(self, painter):
        box = self._attribution_rect()
        painter.fillRect(box, QColor(255, 255, 255, 210))
        painter.setPen(QColor("#2f6fd1"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, ATTRIBUTION)

    # Moving around.
    def marker_at(self, point):
        for marker in reversed(self.markers):
            radius = 6 + min(8, marker.get("count", 1)) + 3
            if (self.screen_point(marker["lat"], marker["lon"]) - point).manhattanLength() <= radius * 1.4:
                return marker
        return None

    def mousePressEvent(self, event):
        point = event.position()
        if self._attribution_rect().contains(point):
            QDesktopServices.openUrl(QUrl(COPYRIGHT_URL))
            return
        self._drag = (point, point, to_pixel(*self.centre, self.zoom))

    def mouseMoveEvent(self, event):
        if self._drag is None:
            marker = self.marker_at(event.position())
            self.setToolTip(marker["label"] if marker else "")
            return
        start, _last, (cx, cy) = self._drag
        moved = event.position() - start
        self._drag = (start, event.position(), (cx, cy))
        self.centre = to_degrees(cx - moved.x(), cy - moved.y(), self.zoom)
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag is None:
            return
        start = self._drag[0]
        self._drag = None
        if (event.position() - start).manhattanLength() > 4:
            return  # A drag, not a click.
        if self.picking:
            self.point_clicked.emit(*self.degrees_at(event.position()))
            return
        marker = self.marker_at(event.position())
        if marker is not None:
            self.selected = marker["key"]
            self.marker_clicked.emit(marker["key"])
            self.update()

    def wheelEvent(self, event):
        step = 1 if event.angleDelta().y() > 0 else -1
        self.zoom_at(event.position(), step)

    def zoom_at(self, point, step):
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom + step))
        if zoom == self.zoom:
            return
        anchor = self.degrees_at(point)
        self.zoom = zoom
        ax, ay = to_pixel(*anchor, zoom)  # The spot under the mouse stays under the mouse.
        self.centre = to_degrees(ax - point.x() + self.width() / 2, ay - point.y() + self.height() / 2, zoom)
        self.update()
