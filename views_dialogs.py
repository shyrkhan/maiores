"""Other ways to look at the family: lifelines across the years with history alongside,
a gallery of everyone's pictures, and statistics drawn as charts."""
import collections
import datetime

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
    QGraphicsView, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QScrollArea, QTabWidget, QVBoxLayout,
    QWidget,
)

import theme
from model import fold_text, parse_date, person_documents
from strings import t

# History shown behind the lifelines: (first year, last year, text key). Wars and the
# states the family's places belonged to; the user can switch them off.
# States, drawn as a strip along the top, one after another:
STATES = [(1867, 1918, "history_austria_hungary"), (1918, 1941, "history_yugoslavia_kingdom"),
          (1945, 1991, "history_yugoslavia"), (1991, 9999, "history_croatia")]
# Events, drawn as shaded bands behind the lives:
EVENTS = [(1914, 1918, "history_ww1"), (1918, 1920, "history_flu"), (1939, 1945, "history_ww2"),
          (1991, 1995, "history_homeland_war")]
HISTORY = STATES + EVENTS
ROW, BAR, NAME_W, YEAR_W = 26, 14, 210, 7.0


def _year(event):
    parsed = parse_date((event or {}).get("date", ""))
    return parsed.year if parsed else None


def _close(parent, layout):
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(parent.reject)
    layout.addWidget(buttons)


# Lifelines.

def lifeline_rows(tree, people, today):
    """[(person id, name, born, died or None, open-ended)] sorted by birth."""
    rows = []
    for person_id in people:
        person = tree.people[person_id]
        born = _year(person.birth)
        if born is None:
            continue
        died = _year(person.death)
        if died is None and person.living == "yes":
            rows.append((person_id, person.display_name, born, today.year, False))
        elif died is None:
            rows.append((person_id, person.display_name, born, None, True))
        else:
            rows.append((person_id, person.display_name, born, max(died, born), False))
    return sorted(rows, key=lambda row: (row[2], fold_text(row[1])))


def related(tree, start, kind):
    """Everyone, or the ancestors or descendants of `start` (with `start` itself)."""
    if kind == "all" or start not in tree.people:
        return list(tree.people)
    found, waiting = [], [start]
    while waiting:
        person = waiting.pop(0)
        if person in found:
            continue
        found.append(person)
        if kind == "ancestors":
            for family, link in tree.parent_families(person):
                waiting += [p for p in family.partners if p in tree.people]
        else:
            for family in tree.families_of(person):
                waiting += [c for c in family.child_ids if c in tree.people]
    return found


class LifelinesView(QGraphicsView):
    def __init__(self, on_person):
        super().__init__()
        self.on_person = on_person
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(theme.colour("background"))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def draw(self, rows, history, today):
        scene = QGraphicsScene(self)
        self.setScene(scene)
        if not rows:
            scene.addText(t("lifelines_empty")).setDefaultTextColor(theme.colour("soft"))
            return
        first = min(row[2] for row in rows) // 10 * 10
        last = max(max(row[3] or row[2] + 30, row[2]) for row in rows)
        last = (min(last, today.year) + 9) // 10 * 10
        x = lambda year: NAME_W + (year - first) * YEAR_W  # noqa: E731
        height = len(rows) * ROW + 90
        soft, line, text = theme.colour("soft"), theme.colour("divider"), theme.colour("text")
        if history:
            small = QFont()
            small.setPointSizeF(8)
            for number, (start, end, key) in enumerate(STATES):  # One strip of states along the top.
                if end < first or start > last:
                    continue
                left, right = x(max(start, first)), x(min(end, last))
                strip = QGraphicsRectItem(QRectF(left, 28, right - left - 2, 16))
                shade = QColor(theme.colour("highlight"))
                shade.setAlpha(45 if number % 2 else 25)
                strip.setBrush(shade)
                strip.setPen(QPen(Qt.PenStyle.NoPen))
                strip.setToolTip(f"{t(key)}: {start}\u2013{'' if end == 9999 else end}")
                scene.addItem(strip)
                label = QGraphicsSimpleTextItem(t(key))
                label.setFont(small)
                label.setBrush(text)
                if label.boundingRect().width() < right - left - 6:
                    label.setPos(left + 4, 29)
                    scene.addItem(label)
            for number, (start, end, key) in enumerate(EVENTS):  # Wars and the flu behind the lives.
                if end <= first or start >= last:  # Only ones that show as a band.
                    continue
                left, right = x(max(start, first)), x(min(end, last))
                band = QGraphicsRectItem(QRectF(left, 48, max(2, right - left), height - 48))
                shade = QColor(theme.colour("path"))
                shade.setAlpha(45)
                band.setBrush(shade)
                band.setPen(QPen(Qt.PenStyle.NoPen))
                band.setToolTip(f"{t(key)}: {start}\u2013{end}")
                scene.addItem(band)
                label = QGraphicsSimpleTextItem(t(key))
                label.setFont(small)
                label.setBrush(soft)
                label.setPos(left + 2, 48 + (number % 2) * 11)  # Staggered: neighbours don't collide.
                scene.addItem(label)
        for decade in range(first, last + 1, 10):
            scene.addLine(x(decade), 24, x(decade), height, QPen(line, 1))
            mark = QGraphicsSimpleTextItem(str(decade))
            mark.setBrush(soft)
            mark.setPos(x(decade) - 14, 4)
            scene.addItem(mark)
        for number, (person_id, name, born, died, open_ended) in enumerate(rows):
            top = 80 + number * ROW
            label = QGraphicsSimpleTextItem(name)
            label.setBrush(text)
            label.setPos(8, top - 2)
            scene.addItem(label)
            end = died if died is not None else born + 25
            bar = QGraphicsRectItem(QRectF(x(born), top, max(YEAR_W, (end - born) * YEAR_W), BAR))
            colour = theme.colour("highlight")
            if open_ended:
                colour.setAlpha(110)  # How it ended isn't known: a fainter bar that fades out.
            bar.setBrush(colour)
            bar.setPen(QPen(Qt.PenStyle.NoPen))
            bar.setToolTip(f"{name}: {born}–{died if died is not None else '?'}")
            bar.setData(0, person_id)
            bar.setCursor(Qt.CursorShape.PointingHandCursor)
            scene.addItem(bar)
            label.setData(0, person_id)
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-10, -10, 20, 20))

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None and item.data(0):
            self.on_person(item.data(0))
            return
        super().mouseDoubleClickEvent(event)


class LifelinesDialog(QDialog):
    def __init__(self, parent, tree, selected, today=None):
        super().__init__(parent)
        self.setWindowTitle(t("lifelines_title"))
        self.resize(1100, 720)
        self.tree, self.selected, self.today = tree, selected, today or datetime.date.today()
        self.chosen = None
        self.who = QComboBox()
        name = tree.people[selected].display_name if selected in tree.people else ""
        for kind, key in (("all", "lifelines_everyone"), ("ancestors", "lifelines_ancestors"),
                          ("descendants", "lifelines_descendants")):
            self.who.addItem(t(key, name=name), kind)
        self.history = QCheckBox(t("lifelines_history"))
        self.history.setChecked(True)
        self.view = LifelinesView(self._go)
        hint = QLabel(t("lifelines_hint"))
        hint.setStyleSheet(f"color: {theme.hex('soft')};")
        top = QHBoxLayout()
        top.addWidget(self.who)
        top.addWidget(self.history)
        top.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.view, 1)
        layout.addWidget(hint)
        _close(self, layout)
        self.who.currentIndexChanged.connect(lambda _i: self.draw())
        self.history.toggled.connect(lambda _on: self.draw())
        self.draw()

    def rows(self):
        return lifeline_rows(self.tree, related(self.tree, self.selected, self.who.currentData()), self.today)

    def draw(self):
        self.view.draw(self.rows(), self.history.isChecked(), self.today)

    def _go(self, person_id):
        self.chosen = person_id
        self.accept()


# Gallery.

class GalleryDialog(QDialog):
    """Everyone's portrait, and the pictures among their documents. Double-click goes to them."""

    def __init__(self, parent, tree, picture_for, documents_too=True):
        super().__init__(parent)
        self.setWindowTitle(t("gallery_title"))
        self.resize(960, 700)
        self.tree, self.picture_for, self.chosen = tree, picture_for, None
        self.with_documents = QCheckBox(t("gallery_documents"))
        self.with_documents.setChecked(documents_too)
        self.with_documents.toggled.connect(lambda _on: self.fill())
        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(QSize(150, 180))
        self.list.setGridSize(QSize(176, 230))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(self._go)
        self.empty = QLabel(t("gallery_empty"))
        self.empty.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.with_documents)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.empty)
        _close(self, layout)
        self.fill()

    def entries(self):
        """[(person id, caption, stored file)] portraits first, then document pictures."""
        found = []
        people = sorted(self.tree.people.values(), key=lambda p: (fold_text(p.surname), fold_text(p.given)))
        for person in people:
            if person.photo:
                found.append((person.id, person.display_name, person.photo))
        if self.with_documents.isChecked():
            from documents import is_image
            for person in people:
                for document in person_documents(person):
                    if is_image(document["file"]):
                        found.append((person.id, f"{person.display_name}\n{document['title']}", document["file"]))
        return found

    def fill(self):
        self.list.clear()
        for person_id, caption, stored in self.entries():
            pixmap = self.picture_for(stored)
            if pixmap is None or pixmap.isNull():
                continue
            thumb = pixmap.scaled(150, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            item = QListWidgetItem(QIcon(thumb), caption)
            item.setData(Qt.ItemDataRole.UserRole, person_id)
            item.setToolTip(caption)
            self.list.addItem(item)
        self.empty.setVisible(self.list.count() == 0)

    def _go(self, item):
        self.chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()


# Statistics.

def statistics(tree, today=None):
    """Numbers for the statistics page."""
    today = today or datetime.date.today()
    people = list(tree.people.values())
    births = [_year(p.birth) for p in people if _year(p.birth)]
    decades = collections.Counter(year // 10 * 10 for year in births)
    lifespans = collections.defaultdict(list)
    for person in people:
        born, died = _year(person.birth), _year(person.death)
        if born and died and died >= born:
            lifespans[born // 100 * 100].append(died - born)
    surnames = collections.Counter((p.birth_surname or p.surname).strip() for p in people
                                   if (p.birth_surname or p.surname).strip())
    given = collections.Counter(p.given.split()[0] for p in people if p.given.strip() and not p.extra.get("hidden"))
    return {
        "people": len(people), "living": sum(1 for p in people if p.living == "yes"),
        "deceased": sum(1 for p in people if p.living == "no"), "families": len(tree.families),
        "births_per_decade": sorted(decades.items()),
        "lifespan_by_century": sorted((century, round(sum(v) / len(v))) for century, v in lifespans.items()),
        "surnames": surnames.most_common(12), "given": given.most_common(12),
        "oldest": min(births) if births else None,
    }


class BarChart(QWidget):
    """A plain bar chart: (label, value) pairs, horizontal bars, values printed at the end."""

    def __init__(self, pairs):
        super().__init__()
        self.pairs = pairs
        self.setMinimumHeight(max(60, len(pairs) * 24 + 10))

    def sizeHint(self):
        return QSize(520, max(60, len(self.pairs) * 24 + 10))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.pairs:
            painter.setPen(theme.colour("soft"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, t("statistics_none"))
            return
        biggest = max(value for _label, value in self.pairs) or 1
        label_w = 120
        usable = max(40, self.width() - label_w - 60)
        for number, (label, value) in enumerate(self.pairs):
            top = 5 + number * 24
            painter.setPen(theme.colour("text"))
            painter.drawText(QRectF(0, top, label_w - 8, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             str(label))
            width = usable * value / biggest
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.colour("highlight"))
            painter.drawRoundedRect(QRectF(label_w, top + 3, max(2, width), 14), 4, 4)
            painter.setPen(theme.colour("soft"))
            painter.drawText(QRectF(label_w + width + 6, top, 60, 20), Qt.AlignmentFlag.AlignVCenter, str(value))


class StatisticsDialog(QDialog):
    def __init__(self, parent, tree, today=None, summary=""):
        super().__init__(parent)
        self.setWindowTitle(t("statistics_title"))
        self.resize(720, 640)
        numbers = statistics(tree, today)
        tabs = QTabWidget()
        overview = QLabel(summary)
        overview.setWordWrap(True)
        overview.setAlignment(Qt.AlignmentFlag.AlignTop)
        tabs.addTab(overview, t("statistics_overview"))
        for key, pairs in (("statistics_births", [(f"{d}\u2013{d + 9}", n) for d, n in numbers["births_per_decade"]]),
                           ("statistics_lifespan", [(f"{c}–{c + 99}", years)
                                                    for c, years in numbers["lifespan_by_century"]]),
                           ("statistics_surnames", numbers["surnames"]),
                           ("statistics_given", numbers["given"])):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(BarChart(pairs))
            tabs.addTab(scroll, t(key))
        layout = QVBoxLayout(self)
        layout.addWidget(tabs, 1)
        _close(self, layout)
        self.tabs = tabs

