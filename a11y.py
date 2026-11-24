"""Names for screen readers, given to every window as it opens: a field in a form takes
its label's text, a field with only grey example text takes that, and a list or table
the window's title. Done in one place, so a new window can't be forgotten."""
import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QComboBox, QDialog, QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
    QSlider, QTextEdit, QWidget,
)

FIELDS = (QLineEdit, QComboBox, QAbstractSpinBox, QPlainTextEdit, QTextEdit, QAbstractItemView, QSlider)


def _clean(text):
    return text.replace("&", "").strip().rstrip(":：").strip()


def name_fields(window):
    for form in window.findChildren(QFormLayout):
        for row in range(form.rowCount()):
            label = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            label = label.widget() if label is not None else None
            field = field.widget() if field is not None else None
            if isinstance(label, QLabel) and isinstance(field, QWidget) and _clean(label.text()):
                for widget in [field] + field.findChildren(QWidget):
                    if isinstance(widget, FIELDS) and not widget.accessibleName():
                        widget.setAccessibleName(_clean(label.text()))
    for widget in window.findChildren(QWidget):
        if not isinstance(widget, FIELDS) or widget.accessibleName():
            continue
        buddy_of = next((label for label in window.findChildren(QLabel) if label.buddy() is widget), None)
        if buddy_of is not None and _clean(buddy_of.text()):
            widget.setAccessibleName(_clean(buddy_of.text()))
        elif isinstance(widget, QLineEdit) and widget.placeholderText():
            widget.setAccessibleName(_clean(widget.placeholderText()))
        elif isinstance(widget, (QPlainTextEdit, QTextEdit)) and widget.placeholderText():
            widget.setAccessibleName(_clean(widget.placeholderText()))
        elif isinstance(widget, QAbstractItemView) and window.windowTitle():
            widget.setAccessibleName(_clean(window.windowTitle()))


def form_tab_order(window):
    """Tab goes down a form's rows as they are seen, whatever order the fields were made in."""
    from PySide6.QtCore import Qt
    for form in window.findChildren(QFormLayout):
        chain = []
        for row in range(form.rowCount()):
            for role in (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole,
                         QFormLayout.ItemRole.SpanningRole):
                item = form.itemAt(row, role)
                widget = item.widget() if item is not None else None
                if widget is None and item is not None and item.layout() is not None:
                    layout = item.layout()
                    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
                else:
                    widgets = [widget]
                for found in widgets:
                    if found is None:
                        continue
                    for candidate in [found] + found.findChildren(QWidget):
                        if candidate.focusPolicy() & Qt.FocusPolicy.TabFocus and candidate not in chain:
                            chain.append(candidate)
        for first, second in zip(chain, chain[1:]):
            if first.window() is second.window():  # A field's own pop-up list is no stop.
                QWidget.setTabOrder(first, second)


# On a Mac, Enter in a list starts editing instead of opening the item, as it does elsewhere.
ENTER_OPENS = sys.platform == "darwin"


def _enter_opens(view, event):
    if (event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter) or event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            or view.window().windowType() == Qt.WindowType.Popup  # A pop-up's own Enter chooses.
            or view.state() == QAbstractItemView.State.EditingState):
        return
    index = view.currentIndex()
    if index.isValid() and not index.flags() & Qt.ItemFlag.ItemIsEditable:
        view.activated.emit(index)


class _Namer(QObject):
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QDialog):
            name_fields(watched)
            form_tab_order(watched)
        elif ENTER_OPENS and event.type() == QEvent.Type.KeyPress and isinstance(watched, QAbstractItemView):
            _enter_opens(watched, event)
        return False


_namer = None


def install(app):
    """Once per program: every dialog shown from then on is named."""
    global _namer
    if _namer is None and app is not None:
        _namer = _Namer()
        app.installEventFilter(_namer)
