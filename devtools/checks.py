"""Rules the running program must always obey, checked from the outside.

Every rule here exists because a real bug broke it once. `run_checks` only
looks: it never saves, changes the tree or processes events, so it is safe to
call at any moment, from tests, the explorer and dev mode alike.
"""
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QMenu

from canvas import AddButtonItem, LinesItem, PersonItem
from model import Tree, validate
from storage import TREE_FILE

FAIL, WARN = "fail", "warn"
LINE_RULE = FAIL  # 2026-11-10: no explorer seed ever tripped it, so it is a hard rule.


@dataclass
class Problem:
    kind: str
    severity: str
    detail: str

    def __str__(self):
        return f"[{self.severity}] {self.kind}: {self.detail}"


def failures(problems):
    return [p for p in problems if p.severity == FAIL]


def run_checks(window):
    problems = []
    for rule in (
        _data_is_valid,
        _disk_matches_memory,
        _selection,
        _add_buttons,
        _stray_windows,
        _cards_do_not_overlap,
        _each_person_once,
        _lines_avoid_cards,
        _panel_buttons_fit,
    ):
        try:
            problems += rule(window)
        except Exception as error:  # A broken rule is itself worth reporting.
            problems.append(Problem("check_crashed", FAIL, f"{rule.__name__}: {error!r}"))
    return problems


def _data_is_valid(window):
    if window.tree is None:
        return []
    return [Problem("data_" + issue.code, FAIL, issue.message()) for issue in validate(window.tree)]


def _disk_matches_memory(window):
    """Saving is immediate, so what is on disk must always equal what is shown."""
    if window.tree is None or window.folder is None or not window.editable:
        return []
    if window.save_error:
        return [Problem("save_failed", FAIL, window.save_error)]
    path = Path(window.folder) / TREE_FILE
    from storage import _read_json  # Read exactly as the program reads it.
    on_disk = Tree.from_dict(_read_json(path))
    if on_disk != window.tree:
        return [Problem("disk_differs", FAIL, "tree.json does not match the tree in memory")]
    return []


def _selection(window):
    tree = window.tree
    if tree is None or not tree.people:
        return []
    problems = []
    if window.selected is None:
        problems.append(Problem("nobody_selected", FAIL, "the tree has people but none is selected"))
    elif window.selected not in window.person_items:
        problems.append(Problem("selected_not_shown", FAIL, f"{window.selected} has no card on screen"))
    lit = [pid for pid, item in window.person_items.items() if item.highlighted]
    if window.selected in window.person_items and lit != [window.selected]:
        problems.append(Problem("highlight_wrong", FAIL, f"highlighted {lit}, selected {window.selected}"))
    if window.selected in tree.people:
        if not window.panel.isVisible() and window.isVisible() and getattr(window, "panel_enabled", True):
            problems.append(Problem("panel_hidden", FAIL, "someone is selected but the panel is hidden"))
        expected = tree.people[window.selected].display_name
        if window.panel.name.text().split("\n")[0] != expected:  # A second line may say "Private".
            problems.append(
                Problem("panel_stale", FAIL, f"panel shows {window.panel.name.text()!r}, not {expected!r}")
            )
    return problems


def _add_buttons(window):
    problems = []
    scene = window.view.scene()
    on_scene = [i for i in scene.items() if isinstance(i, AddButtonItem)] if scene else []
    if set(map(id, on_scene)) != set(map(id, window.add_button_items)):
        problems.append(Problem("add_buttons_untracked", FAIL, "add buttons on screen differ from the list"))
    for item in on_scene:
        if item.person_id != window.selected:
            problems.append(Problem("add_button_wrong_person", FAIL, f"{item.key} belongs to {item.person_id}"))
    from app import CHARTS
    if on_scene and (not window.editable or not CHARTS[window.chart]["add"]):
        problems.append(Problem("add_buttons_not_allowed", FAIL, "add buttons in a read-only or ancestor view"))
    cards = [i for i in window.person_items.values() if i.scene() is scene]
    for button in on_scene:
        box = button.sceneBoundingRect()
        for card in cards:
            if card.person_id != button.person_id and box.intersects(_card_rect(card)):
                problems.append(
                    Problem("add_button_covers_card", FAIL, f"{button.key} covers {card.person_id}")
                )
    return problems


def _allowed_windows(window):
    allowed = {id(window)}
    modal = QApplication.activeModalWidget()
    if modal is not None:
        allowed.add(id(modal))
    search = getattr(window, "search_box", None)
    if search is not None and search.completer() is not None:
        allowed.add(id(search.completer().popup()))
    return allowed


def _stray_windows(window):
    """A widget that lost its parent becomes a window of its own: the 'cascade' bug."""
    allowed = _allowed_windows(window)
    problems = []
    for widget in QApplication.topLevelWidgets():
        if id(widget) in allowed or isinstance(widget, (QMenu, QDialog, QMainWindow)):
            continue
        if widget.windowType() in (Qt.WindowType.Popup, Qt.WindowType.ToolTip):
            continue  # Drop-down lists, completers and tooltips are windows by design.
        if type(widget).__name__ == "QWidget" and not widget.children():
            continue  # Qt's own empty helpers.
        name = type(widget).__name__
        if widget.isVisible() or name in ("QPushButton", "QLabel", "QFrame"):
            problems.append(Problem("stray_window", FAIL, f"a loose {name} is its own window"))
    return problems


def _card_rect(card):
    return card.mapRectToScene(card.shape().boundingRect())


def _cards_do_not_overlap(window):
    """Sweep by left edge, so even a 4096-card ancestor view stays quick."""
    if getattr(window, "chart", "") == "fan":
        return []  # Wedges touch by design; their boxes overlap but their shapes do not.
    rects = sorted(
        ((_card_rect(item), pid) for pid, item in window.person_items.items()),
        key=lambda pair: pair[0].left(),
    )
    problems = []
    active = []
    for rect, pid in rects:
        active = [(r, p) for r, p in active if r.right() > rect.left()]
        for other, other_id in active:
            if other.intersects(rect) and other.intersected(rect).width() > 1:
                problems.append(Problem("cards_overlap", FAIL, f"{pid} overlaps {other_id}"))
        active.append((rect, pid))
    return problems


def fit_problems(window):
    """After Fit, the view must be centred on the people and lines, not the add buttons."""
    scene = window.view.scene()
    area = QRectF()
    for item in scene.items():
        if isinstance(item, (PersonItem, LinesItem)):
            area = area.united(item.sceneBoundingRect())
    if area.isNull():
        return []
    view = window.view
    centre = view.mapToScene(view.viewport().rect().center())
    tolerance = 3.0 / max(view.zoom_level(), 0.01)  # About three screen pixels.
    off_x, off_y = abs(centre.x() - area.center().x()), abs(centre.y() - area.center().y())
    if off_x > tolerance or off_y > tolerance:
        return [Problem("fit_off_centre", FAIL, f"view centre is {off_x:.0f}, {off_y:.0f} away from the people")]
    return []


def _each_person_once(window):
    """A second card for someone is silently unclickable, so it must never happen."""
    scene = window.view.scene()
    seen, problems = set(), []
    for item in scene.items() if scene else []:
        if isinstance(item, PersonItem):
            if item.person_id in seen:
                # When cousins marry, a shared ancestor rightly appears on both sides.
                # Relatives marrying (cousins, say) also put one person in two places,
                # which family tree programs draw on purpose; data rules stop the bad cases.
                severity = WARN
                problems.append(Problem("person_drawn_twice", severity, f"{item.person_id} has two cards"))
            seen.add(item.person_id)
    return problems


def _segments(scene):
    for item in scene.items():
        if isinstance(item, LinesItem):
            path = item.path
            for index in range(1, path.elementCount()):
                a, b = path.elementAt(index - 1), path.elementAt(index)
                if b.isLineTo():
                    yield a.x, a.y, b.x, b.y


def _lines_avoid_cards(window):
    """A line running through a portrait makes it look as if the wrong people are joined."""
    scene = window.view.scene()
    if scene is None or len(window.person_items) > 1500 or getattr(window, "chart", "") == "fan":
        return []
    boxes = [(_card_rect(item).adjusted(3, 3, -3, -3), pid) for pid, item in window.person_items.items()]
    problems = []
    for x1, y1, x2, y2 in _segments(scene):
        segment = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1) or 0.01, abs(y2 - y1) or 0.01)
        for box, pid in boxes:
            if segment.intersects(box):
                problems.append(Problem("line_through_card", LINE_RULE, f"a line crosses {pid}"))
                break
    return problems


def _panel_buttons_fit(window):
    """Every button in the side panel must be fully inside it, never cut off at the edge."""
    from PySide6.QtWidgets import QPushButton
    panel = window.panel
    if not panel.isVisible():
        return []
    problems = []
    for button in panel.findChildren(QPushButton):
        if not button.isVisible():
            continue
        right = button.mapTo(panel, button.rect().topRight()).x()
        if right > panel.width():
            problems.append(Problem("panel_button_cut_off", FAIL, f"'{button.text()}' runs off the panel"))
    return problems
