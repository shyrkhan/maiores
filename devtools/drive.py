"""Driving the running program like a person would: its windows, widgets, menus,
clicks and keys. Used by the remote control in developer mode (devmode.py), and
through it by tools/maiores-mcp.

Widgets are named by a selector:
    ""                the window in front (an open dialog, else the main window)
    "@12"             a number from the last `widgets` listing
    "name:objName"    an objectName
    "class:QLineEdit" the first widget of that class (add "#2" for the second)
    "text:Save"       a button, label, tab or field whose text contains this
    "Save"            the same as text:

Clicks, keys and menu entries are delivered after the reply, so an action that
opens a dialog does not hold the answer back; look again after a short wait.
"""
import base64

import shiboken6

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QSlider,
    QSpinBox,
    QTabBar,
    QTabWidget,
    QTextEdit,
    QWidget,
)

BUTTONS = {"left": Qt.MouseButton.LeftButton, "right": Qt.MouseButton.RightButton,
           "middle": Qt.MouseButton.MiddleButton}


def _plain(text):
    return (text or "").replace("&&", "\0").replace("&", "").replace("\0", "&")


def widget_text(widget):
    if isinstance(widget, QAbstractButton):
        return _plain(widget.text()) or widget.toolTip()
    if isinstance(widget, QLabel):
        return widget.text()
    if isinstance(widget, QLineEdit):
        return widget.text()
    if isinstance(widget, QComboBox):
        return widget.currentText()
    if isinstance(widget, (QPlainTextEdit, QTextEdit)):
        return widget.toPlainText()[:300]
    if isinstance(widget, QGroupBox):
        return widget.title()
    if isinstance(widget, (QSpinBox, QSlider)):
        return str(widget.value())
    if isinstance(widget, QTabBar):
        return " | ".join(widget.tabText(i) for i in range(widget.count()))
    if widget.isWindow():
        return widget.windowTitle()
    return ""


def describe(widget):
    out = {"class": type(widget).__name__}
    if widget.objectName():
        out["name"] = widget.objectName()
    text = widget_text(widget)
    if text:
        out["text"] = text if len(text) <= 200 else text[:200] + "…"
    if isinstance(widget, QLineEdit) and widget.placeholderText():
        out["placeholder"] = widget.placeholderText()
    if widget.toolTip() and widget.toolTip() != text:
        out["tooltip"] = widget.toolTip()[:200]
    if not widget.isEnabled():
        out["disabled"] = True
    if isinstance(widget, (QCheckBox,)) or (isinstance(widget, QAbstractButton) and widget.isCheckable()):
        out["checked"] = widget.isChecked()
    if isinstance(widget, QComboBox):
        out["items"] = [widget.itemText(i) for i in range(min(widget.count(), 60))]
    if isinstance(widget, QTabWidget):
        out["tabs"] = [widget.tabText(i) + (" [current]" if i == widget.currentIndex() else "")
                       for i in range(widget.count())]
    if isinstance(widget, QAbstractItemView) and widget.model() is not None:
        model = widget.model()
        rows = []
        for row in range(min(model.rowCount(), 40)):
            rows.append(" | ".join(str(model.index(row, col).data() or "")
                                   for col in range(min(model.columnCount(), 8))))
        out["rows"] = rows
        out["row_count"] = model.rowCount()
    geometry = widget.geometry()
    out["rect"] = [geometry.x(), geometry.y(), geometry.width(), geometry.height()]
    return out


class Driver:
    def __init__(self, window):
        self.window = window
        self.numbered = {}

    # Which window, which widget.
    def windows(self):
        out = []
        for widget in QApplication.topLevelWidgets():
            if widget.isVisible():
                entry = {"class": type(widget).__name__, "title": widget.windowTitle() or widget_text(widget),
                         "modal": widget.isModal()}
                if isinstance(widget, QMenu):
                    entry["entries"] = [_plain(a.text()) for a in widget.actions() if a.text()]
                out.append(entry)
        return out

    def front(self):
        popup = QApplication.activePopupWidget()
        if popup is not None:
            return popup
        modal = QApplication.activeModalWidget()
        if modal is not None:
            return modal
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                return widget
        return self.window

    def find(self, selector, within=None):
        root = within or self.front()
        selector = (selector or "").strip()
        if not selector:
            return root
        if selector.startswith("@"):
            widget = self.numbered.get(int(selector[1:]))
            if widget is None or not shiboken6.isValid(widget):
                raise ValueError(f"{selector} is gone; list the widgets again")
            return widget
        nth = 1
        if "#" in selector and selector.rsplit("#", 1)[1].isdigit():
            selector, count = selector.rsplit("#", 1)
            nth = int(count)
        kind, _, value = selector.partition(":")
        if kind not in ("name", "class", "text"):
            kind, value = "text", selector
        found = []
        for widget in [root, *root.findChildren(QWidget)]:
                if not widget.isVisible():
                    continue
                if kind == "name" and widget.objectName() == value:
                    found.append(widget)
                elif kind == "class" and type(widget).__name__ == value:
                    found.append(widget)
                elif kind == "text" and value.lower() in widget_text(widget).lower() and not widget.isWindow():
                    found.append(widget)
        if kind == "text":
            # A button with that text beats the label that happens to mention it.
            found.sort(key=lambda w: (not isinstance(w, QAbstractButton),
                                      _plain(widget_text(w)).lower() != value.lower()))
        if len(found) < nth:
            raise ValueError(f"no visible widget matches {selector!r} in {type(root).__name__}")
        return found[nth - 1]

    def widgets(self, selector="", depth=6, limit=250):
        root = self.find(selector)
        self.numbered = {}
        lines = []

        def walk(widget, level):
            if len(lines) >= limit or not widget.isVisible():
                return
            info = describe(widget)
            text = widget_text(widget)
            interesting = (text or widget.objectName() or isinstance(
                widget, (QAbstractButton, QLineEdit, QComboBox, QAbstractItemView, QTabBar, QSlider, QSpinBox)))
            if interesting or level == 0:
                number = len(self.numbered)
                self.numbered[number] = widget
                label = info["class"] + (f" name={info['name']}" if "name" in info else "")
                if text:
                    label += f" {text[:80]!r}"
                for flag in ("disabled", "checked"):
                    if flag in info:
                        label += f" {flag}={info[flag]}"
                lines.append(f"{'  ' * level}@{number} {label}")
                level += 1
            if level > depth:
                return
            for child in widget.children():
                if isinstance(child, QWidget) and not child.isWindow():
                    walk(child, level)

        walk(root, 0)
        return "\n".join(lines)

    # Pictures.
    def picture(self, selector=""):
        widget = self.find(selector)
        image = widget.grab()
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return {"png": base64.b64encode(bytes(data)).decode(), "width": image.width(), "height": image.height(),
                "of": type(widget).__name__ + (f" {widget.windowTitle()!r}" if widget.isWindow() else "")}

    # Input, delivered after the reply.
    @staticmethod
    def later(job):
        QTimer.singleShot(0, job)

    def click(self, selector, button="left", double=False, x=None, y=None):
        widget = self.find(selector)
        point = QPoint(x, y) if x is not None and y is not None else widget.rect().center()
        which = BUTTONS[button or "left"]

        def go():
            if double:
                QTest.mouseDClick(widget, which, Qt.KeyboardModifier.NoModifier, point)
            elif which == Qt.MouseButton.LeftButton and isinstance(widget, QAbstractButton) and x is None:
                widget.click()
            else:
                QTest.mouseClick(widget, which, Qt.KeyboardModifier.NoModifier, point)
        self.later(go)
        return f"clicking {describe(widget)['class']} {widget_text(widget)[:60]!r}"

    def key(self, keys, selector=""):
        widget = self.find(selector) if selector else (QApplication.focusWidget() or self.front())
        sequence = QKeySequence(keys)
        if sequence.isEmpty():
            raise ValueError(f"cannot read the keys {keys!r}")

        def go():
            for i in range(sequence.count()):
                combo = sequence[i]
                QTest.keyClick(widget, combo.key(), combo.keyboardModifiers())
        self.later(go)
        return f"pressing {sequence.toString()} on {type(widget).__name__}"

    def type(self, text, selector=""):
        widget = self.find(selector) if selector else (QApplication.focusWidget() or self.front())
        self.later(lambda: QTest.keyClicks(widget, text))
        return f"typing {len(text)} characters into {type(widget).__name__}"

    def set_value(self, selector, value):
        """Fill a field directly: a line edit, text box, combo, spin box, slider or check box."""
        widget = self.find(selector)
        if isinstance(widget, QLineEdit):
            widget.setText(value)
        elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
            widget.setPlainText(value)
        elif isinstance(widget, QComboBox):
            index = widget.findText(value, Qt.MatchFlag.MatchFixedString)  # "Male" must not pick "Female".
            if index < 0:
                index = widget.findText(value, Qt.MatchFlag.MatchContains)
            if index < 0:
                raise ValueError(f"{value!r} is not in that list")
            widget.setCurrentIndex(index)
        elif isinstance(widget, (QSpinBox, QSlider)):
            widget.setValue(int(value))
        elif isinstance(widget, QAbstractButton) and widget.isCheckable():
            widget.setChecked(value.lower() in ("1", "yes", "true", "on"))
        else:
            raise ValueError(f"cannot set a value on {type(widget).__name__}")
        return describe(widget)

    def menu(self, path):
        """'File/Export/GEDCOM…' from the menu bar, or an entry of the menu that is open."""
        parts = [p.strip().lower() for p in path.split("/") if p.strip()]
        popup = QApplication.activePopupWidget()
        if isinstance(popup, QMenu):
            actions = popup.actions()
        else:
            actions = self.window.menuBar().actions()
        trail = []
        for i, part in enumerate(parts):
            match = next((a for a in actions if _plain(a.text()).lower().rstrip("…. ") == part.rstrip("…. ")), None)
            match = match or next((a for a in actions if part in _plain(a.text()).lower()), None)
            if match is None:
                names = [_plain(a.text()) for a in actions if a.text()]
                raise ValueError(f"no entry {part!r} after {trail or 'the start'}; there is {names}")
            trail.append(_plain(match.text()))
            if i < len(parts) - 1:
                if match.menu() is None:
                    raise ValueError(f"{trail[-1]!r} has no submenu")
                match.menu().aboutToShow.emit()
                actions = match.menu().actions()
            else:
                if match.menu() is not None:
                    match.menu().aboutToShow.emit()  # Menus filled as they open (Person, Recent).
                    return {"entries": [_plain(a.text()) for a in match.menu().actions() if a.text()]}
                if not match.isEnabled():
                    raise ValueError(f"{trail[-1]!r} is disabled now")

                def go(action=match, popup=popup):
                    if isinstance(popup, QMenu):
                        popup.close()
                    action.trigger()
                self.later(go)
        return "running " + " / ".join(trail)

    def close_front(self, accept=False):
        widget = self.front()
        if widget is self.window:
            return "nothing open in front of the main window"
        if isinstance(widget, QDialog):
            self.later(widget.accept if accept else widget.reject)
        else:
            self.later(widget.close)
        return f"closing {type(widget).__name__} {widget.windowTitle()!r}"

    def click_person(self, pid, button="left", double=False):
        """Click a card on the tree, as a mouse would."""
        item = self.window.person_items.get(pid)
        if item is None:
            raise ValueError("that person is not on screen; select them first")
        view = self.window.view
        view.ensureVisible(item, 40, 40)
        point = view.mapFromScene(item.sceneBoundingRect().center())
        which = BUTTONS[button or "left"]
        viewport = view.viewport()

        def go():
            if double:
                QTest.mouseDClick(viewport, which, Qt.KeyboardModifier.NoModifier, point)
            elif which == Qt.MouseButton.RightButton:
                # A context menu comes from the event, not from the press.
                from PySide6.QtGui import QContextMenuEvent
                QApplication.sendEvent(viewport, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point,
                                                                   viewport.mapToGlobal(point)))
            else:
                QTest.mouseClick(viewport, which, Qt.KeyboardModifier.NoModifier, point)
        self.later(go)
        return f"{'double-' if double else ''}{button or 'left'} click on {pid} at {point.x()},{point.y()}"
