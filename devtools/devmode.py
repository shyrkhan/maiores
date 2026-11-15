"""Developer mode: watch and drive the running program.

    python app.py --dev [TREE]

Adds, only when asked for:
  * a Developer panel at the bottom: live state, the checks from checks.py after
    every change (the status bar turns red on a failure), and a log of actions;
  * a Developer menu with an overlay (Ctrl+Shift+O) that draws each card's box,
    its ID, the family head and the line ends, so layout problems are visible;
  * a local remote control, used by tools/devctl.py, so a developer can ask the
    running program for its state, run checks, take screenshots, select people
    and run actions while it is open. Only the same user on the same computer
    can connect.

The release builds leave this file out, so `--dev` does nothing there.
"""
import datetime
import getpass
import json
import time
import traceback
from pathlib import Path

import shiboken6

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeySequence, QPen
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import (
    QDockWidget,
    QGraphicsItem,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QTabWidget,
)

from canvas import LinesItem
from devtools.checks import FAIL, failures, fit_problems, run_checks

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "dev-output"
LOG_LIMIT = 500


def server_name():
    return f"maiores-dev-{getpass.getuser()}"


class OverlayItem(QGraphicsItem):
    """Card boxes, IDs, the family head and line ends, drawn over the tree."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setZValue(50)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.area = QRectF()
        for item in window.person_items.values():
            self.area = self.area.united(item.sceneBoundingRect())
        self.area = self.area.adjusted(-80, -80, 80, 80)

    def boundingRect(self):
        return self.area

    def shape(self):
        from PySide6.QtGui import QPainterPath
        return QPainterPath()  # Never catches clicks.

    def paint(self, painter, option, widget=None):
        w = self.window
        painter.setFont(QFont("monospace", 9))
        for pid, item in w.person_items.items():
            box = item.mapRectToScene(item.shape().boundingRect())
            colour = QColor("#ffcc33") if pid == w.house else QColor("#ff66cc")
            painter.setPen(QPen(colour, 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(box)
            label = pid[-6:] + ("  HEAD" if pid == w.house else "") + ("" if item.blood else "  in-law")
            painter.drawText(box.topLeft() + QPointF(3, -4), label)
            painter.drawText(box.bottomLeft() + QPointF(3, 12), f"{box.x():.0f}, {box.y():.0f}")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#33ddff"))
        scene = self.scene()
        for item in scene.items() if scene else []:
            if isinstance(item, LinesItem):
                path = item.path
                for index in range(path.elementCount()):
                    element = path.elementAt(index)
                    painter.drawEllipse(QPointF(element.x, element.y), 2.5, 2.5)


class DevMode:
    def __init__(self, window, serve=True):
        self.window = window
        self.overlay_on = False
        self.overlay = None
        self.log_lines = []
        self.last_problems = []
        self.check_timer = QTimer(window)
        self.check_timer.setSingleShot(True)
        self.check_timer.setInterval(0)
        self.check_timer.timeout.connect(self.check_now)
        self._build_dock()
        self._build_menu()
        self._wrap()
        self.server = self._serve() if serve else None
        window.setWindowTitle(window.windowTitle() + "  [developer mode]")
        self.log("developer mode on")
        self.schedule()

    # The panel.
    def _build_dock(self):
        w = self.window
        self.state_text = QPlainTextEdit(readOnly=True)
        self.state_text.setFont(QFont("monospace", 9))
        self.checks_list = QListWidget()
        self.log_text = QPlainTextEdit(readOnly=True)
        self.log_text.setFont(QFont("monospace", 9))
        tabs = QTabWidget()
        tabs.addTab(self.checks_list, "Checks")
        tabs.addTab(self.state_text, "State")
        tabs.addTab(self.log_text, "Log")
        self.dock = QDockWidget("Developer", w)
        self.dock.setObjectName("developer_dock")
        self.dock.setWidget(tabs)
        w.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock)
        QTimer.singleShot(0, lambda: w.resizeDocks([self.dock], [170], Qt.Orientation.Vertical))
        self.badge = QLabel()
        w.statusBar().addPermanentWidget(self.badge)

    def _build_menu(self):
        w = self.window
        menu = w.menuBar().addMenu("&Developer")

        def add(text, handler, shortcut=None):
            action = menu.addAction(text)
            action.triggered.connect(lambda _checked=False: handler())
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            return action

        add("Run checks now", self.check_now, "Ctrl+Shift+K")
        add("Check that Fit centres the tree", self.check_fit)
        self.overlay_action = add("Show layout overlay", self.toggle_overlay, "Ctrl+Shift+O")
        self.overlay_action.setCheckable(True)
        add("Save screenshot", lambda: self.log(f"screenshot {self.screenshot()}"), "Ctrl+Shift+S")
        add("Show or hide this panel", lambda: self.dock.setVisible(not self.dock.isVisible()))

    # Watching what happens.
    def _wrap(self):
        w = self
        window = self.window
        real_refresh, real_select, real_run = window.refresh, window.select, window.run_action

        def refresh(*args, **kwargs):
            result = real_refresh(*args, **kwargs)
            w._redraw_overlay()
            w.schedule()
            return result

        def select(person_id):
            result = real_select(person_id)
            w.log(f"select {w.name(person_id)}")
            w.schedule()
            return result

        def run_action(key, person_id):
            w.log(f"action {key} on {w.name(person_id)}")
            started = time.monotonic()
            try:
                return real_run(key, person_id)
            finally:
                w.log(f"  done in {(time.monotonic() - started) * 1000:.0f} ms")
                w.schedule()

        window.refresh, window.select, window.run_action = refresh, select, run_action
        window.view.on_add = run_action  # The view kept the original when it was made.
        window.statusBar().messageChanged.connect(lambda text: text and self.log(f"status: {text}"))

    def name(self, person_id):
        tree = self.window.tree
        if tree is None or person_id not in tree.people:
            return str(person_id)
        return f"{tree.people[person_id].display_name} ({person_id[-6:]})"

    def log(self, text):
        line = f"{datetime.datetime.now():%H:%M:%S} {text}"
        self.log_lines.append(line)
        del self.log_lines[:-LOG_LIMIT]
        self.log_text.appendPlainText(line)

    def schedule(self):
        self.check_timer.start()  # After the current change has finished.

    def state(self):
        w = self.window
        tree = w.tree
        view = w.view
        centre = view.mapToScene(view.viewport().rect().center())
        return {
            "folder": str(w.folder) if w.folder else None,
            "editable": w.editable,
            "people": len(tree.people) if tree else 0,
            "families": len(tree.families) if tree else 0,
            "house": self.name(w.house),
            "selected": self.name(w.selected),
            "on_screen": len(w.person_items),
            "add_buttons": [b.key for b in w.add_button_items],
            "back_stack": [self.name(entry[0]) for entry in w.nav_history],
            "chart": w.chart,
            "collapsed": [self.name(p) for p in w.collapsed],
            "undo": len(w.history.undo_stack),
            "redo": len(w.history.redo_stack),
            "zoom": round(view.zoom_level(), 3),
            "view_centre": [round(centre.x()), round(centre.y())],
            "page": w.pages.currentIndex(),
            "save_error": w.save_error,
        }

    def check_now(self):
        try:
            problems = run_checks(self.window)
        except Exception:
            self.log("checks crashed:\n" + traceback.format_exc())
            return []
        new = [str(p) for p in failures(problems)]
        if new and new != [str(p) for p in failures(self.last_problems)]:
            for line in new:
                self.log(f"CHECK FAILED {line}")
        self.last_problems = problems
        self.checks_list.clear()
        if not problems:
            self.checks_list.addItem("All checks pass.")
        for problem in problems:
            item = QListWidgetItem(str(problem))
            item.setForeground(QColor("#ff9c8f" if problem.severity == FAIL else "#e6c06a"))
            self.checks_list.addItem(item)
        failed = len(failures(problems))
        self.badge.setText(f" checks: {failed} FAILED " if failed else " checks OK ")
        self.badge.setStyleSheet("background:#a33;color:white" if failed else "color:#8fd18f")
        self.state_text.setPlainText(json.dumps(self.state(), indent=2, ensure_ascii=False))
        return problems

    def check_fit(self):
        self.window.view.fit_tree()
        problems = fit_problems(self.window)
        self.log("fit: " + (", ".join(map(str, problems)) or "centred"))
        return problems

    # Seeing the layout.
    def toggle_overlay(self, on=None):
        self.overlay_on = (not self.overlay_on) if on is None else bool(on)
        self.overlay_action.setChecked(self.overlay_on)
        self._redraw_overlay()

    def _redraw_overlay(self):
        scene = self.window.view.scene()
        # A rebuilt tree deletes the old picture, and the overlay with it.
        if self.overlay is not None and shiboken6.isValid(self.overlay) and self.overlay.scene():
            self.overlay.scene().removeItem(self.overlay)
        self.overlay = None
        if self.overlay_on and scene is not None and self.window.person_items:
            self.overlay = OverlayItem(self.window)
            scene.addItem(self.overlay)

    def screenshot(self, path=None):
        OUTPUT.mkdir(exist_ok=True)
        path = Path(path) if path else OUTPUT / f"dev-{datetime.datetime.now():%Y%m%d-%H%M%S}.png"
        self.window.grab().save(str(path))
        return str(path)

    # The remote control.
    def _serve(self):
        server = QLocalServer(self.window)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(server_name())
        if not server.listen(server_name()):
            self.log(f"remote control unavailable: {server.errorString()}")
            return None
        server.newConnection.connect(lambda: self._accept(server))
        self.log(f"remote control listening as {server_name()}")
        return server

    def _accept(self, server):
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            buffer = bytearray()

            def readable(socket=socket, buffer=buffer):
                buffer.extend(bytes(socket.readAll()))
                while b"\n" in buffer:
                    line, _, rest = bytes(buffer).partition(b"\n")
                    buffer[:] = rest
                    reply = self.handle(line)
                    socket.write(json.dumps(reply, ensure_ascii=False).encode() + b"\n")
                    socket.flush()

            socket.readyRead.connect(readable)
            socket.disconnected.connect(socket.deleteLater)

    def find_person(self, text):
        tree = self.window.tree
        if tree is None or not text:
            return None
        if text in tree.people:
            return text
        for pid, person in tree.people.items():
            if pid.endswith(text) or text.lower() in person.display_name.lower():
                return pid
        return None

    def handle(self, line):
        try:
            request = json.loads(line)
            command = request.get("cmd")
            self.log(f"remote: {command} {request.get('arg', '')}".rstrip())
            return {"ok": True, "result": self._command(command, request.get("arg"))}
        except Exception as error:
            return {"ok": False, "error": f"{type(error).__name__}: {error}"}

    def _command(self, command, arg):
        w = self.window
        if command == "state":
            return self.state()
        if command == "checks":
            return [str(p) for p in self.check_now()]
        if command == "people":
            return [
                {"id": pid, "name": w.tree.people[pid].display_name,
                 "x": round(item.x()), "y": round(item.y()), "selected": pid == w.selected}
                for pid, item in w.person_items.items()
            ]
        if command == "screenshot":
            return self.screenshot(arg)
        if command == "select":
            pid = self.find_person(arg)
            if pid is None:
                raise ValueError(f"nobody matches {arg!r}")
            w.go_to_person(pid)
            return self.name(pid)
        if command == "action":
            key, _, who = (arg or "").partition(" ")
            pid = self.find_person(who) if who else w.selected
            w.run_action(key, pid)  # Opens its dialog; replies once it is closed.
            return self.state()
        if command == "fit":
            return [str(p) for p in self.check_fit()]
        if command == "overlay":
            self.toggle_overlay(arg not in ("off", "0", "false"))
            return self.overlay_on
        if command in ("undo", "redo", "go_back"):
            getattr(w, command)()
            return self.state()
        if command == "log":
            return self.log_lines[-int(arg or 40):]
        raise ValueError(
            "unknown command; try state, checks, people, screenshot [PATH], select NAME, "
            "action KEY [NAME], fit, overlay on|off, undo, redo, go_back, log [N]"
        )


def install(window, serve=True):
    window.dev_mode = DevMode(window, serve)
    return window.dev_mode
