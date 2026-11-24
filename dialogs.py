"""The form for adding or editing a person, and the find-a-person box."""
import copy
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from edits import EditError, clean_fields
from model import (
    EVENT_TYPES, date_input_text, date_sort_key, fact_details, fold_text, is_period, normalize_date_input,
    person_documents,
    person_events, person_names,
)
from facts_dialogs import FactContext, FactDetails, NamesDialog
from photos import STORED_H, STORED_W, default_crop
from screen import fit_hint, fit_to_screen, scrolling
from strings import collation_key, t
import theme

SEX_OPTIONS = [("", "sex_unknown"), ("F", "sex_female"), ("M", "sex_male"), ("X", "sex_other")]
LIVING_OPTIONS = [("yes", "living_yes"), ("no", "living_no"), ("unknown", "living_unknown")]
RELATIONSHIP_OPTIONS = [
    ("married", "rel_married"),
    ("partners", "rel_partners"),
    ("divorced", "rel_divorced"),
    ("unknown", "rel_unknown"),
]
LINK_OPTIONS = [
    ("birth", "link_birth"),
    ("adopted", "link_adopted"),
    ("foster", "link_foster"),
    ("unknown", "link_unknown"),
]


def _combo(options, current):
    box = QComboBox()
    for value, key in options:
        box.addItem(t(key), value)
    index = box.findData(current)
    box.setCurrentIndex(index if index >= 0 else 0)
    return box


class PersonDialog(QDialog):
    """Enter someone's details. Save stays off until the dates make sense.

    `relationships` is a list of (family id, partner name, current value[, marriage]),
    and `link` is the current child link, or None when it does not apply.
    """

    def __init__(self, parent, title, initial=None, link=None, relationships=(), another=False, context=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.add_another = False
        self.photo_source = None
        data = initial or {}
        self.context = context or FactContext()
        self.known_sources = set(self.context.sources)

        form = QFormLayout()
        self.given = QLineEdit(data.get("given", ""))
        self.surname = QLineEdit(data.get("surname", ""))
        self.birth_surname = QLineEdit(data.get("birth_surname", ""))
        self.sex = _combo(SEX_OPTIONS, data.get("sex", ""))
        self.birth_date = QLineEdit(date_input_text(data.get("birth_date", "")))
        fit_hint(self.birth_date, t("date_hint"))
        self.birth_place = QLineEdit(data.get("birth_place", ""))
        self.status = _combo(LIVING_OPTIONS, data.get("living", "yes"))
        self.death_date = QLineEdit(date_input_text(data.get("death_date", "")))
        fit_hint(self.death_date, t("date_hint"))
        self.death_place = QLineEdit(data.get("death_place", ""))
        self.birth_details = FactDetails(self.context, {"citations": data.get("birth_citations"),
                                                         "people": data.get("birth_people")}, t("fact_birth"))
        self.death_details = FactDetails(self.context, {"citations": data.get("death_citations"),
                                                         "people": data.get("death_people")}, t("fact_death"))
        self.names = [dict(n) for n in data.get("names", [])]
        self.names_button = QPushButton()
        self.names_button.setObjectName("other_names")
        self.names_button.clicked.connect(self.edit_names)
        self._label_names()
        self.events = [dict(e) for e in data.get("events", [])]
        self.notes = QPlainTextEdit(data.get("notes", ""))
        self.notes.setFixedHeight(80)
        self.notes.setTabChangesFocus(True)

        form.addRow(t("field_given"), self.given)
        form.addRow(t("field_surname"), self.surname)
        form.addRow(t("field_sex"), self.sex)
        form.addRow(t("field_birth_surname"), self.birth_surname)
        names_row = QWidget()
        names_layout = QHBoxLayout(names_row)
        names_layout.setContentsMargins(0, 0, 0, 0)
        names_layout.addWidget(self.names_button)
        names_layout.addStretch(1)
        form.addRow(t("field_other_names"), names_row)
        form.addRow(t("field_birth_date"), self.birth_date)
        form.addRow(t("field_birth_place"), self.birth_place)
        form.addRow("", self.birth_details)
        form.addRow(t("field_status"), self.status)
        form.addRow(t("field_death_date"), self.death_date)
        form.addRow(t("field_death_place"), self.death_place)
        form.addRow("", self.death_details)

        self.link = None
        if link is not None:
            self.link = _combo(LINK_OPTIONS, link)
            form.addRow(t("field_link"), self.link)
        self.relationships = {}
        self.marriages = {}
        for row in relationships:
            family_id, partner, current = row[:3]
            marriage = row[3] if len(row) > 3 else None
            box = _combo(RELATIONSHIP_OPTIONS, current)
            label = t("field_relationship_with", name=partner) if partner else t("field_relationship")
            form.addRow(label, box)
            self.relationships[family_id] = box
            if marriage is not None:
                # When and where the couple married, next to the relationship itself.
                line = QWidget()
                inner = QHBoxLayout(line)
                inner.setContentsMargins(0, 0, 0, 0)
                date = QLineEdit(date_input_text(marriage.get("date", "")))
                date.setPlaceholderText(t("field_marriage_date"))
                place = QLineEdit(marriage.get("place", ""))
                place.setPlaceholderText(t("field_marriage_place"))
                inner.addWidget(date, 1)
                inner.addWidget(place, 2)
                form.addRow(t("field_marriage"), line)
                details = FactDetails(self.context, marriage, t("fact_marriage"))
                form.addRow("", details)
                date.textChanged.connect(self._refresh)
                self.marriages[family_id] = (date, place, details)
        events_box = QWidget()
        events_layout = QVBoxLayout(events_box)
        events_layout.setContentsMargins(0, 0, 0, 0)
        self.events_list = QListWidget()
        self.events_list.setFixedHeight(84)
        self.events_list.itemActivated.connect(lambda _item: self._edit_event())
        buttons_row = QHBoxLayout()
        for key, handler in (("event_add", self._add_event), ("event_edit", self._edit_event),
                             ("event_remove", self._remove_event)):
            button = QPushButton(t(key))
            button.setObjectName(key)
            button.clicked.connect(lambda _checked=False, h=handler: h())
            buttons_row.addWidget(button)
        events_layout.addWidget(self.events_list)
        events_layout.addLayout(buttons_row)
        form.addRow(t("field_events"), events_box)
        self._show_events()

        photo_row = QWidget()
        photo_layout = QHBoxLayout(photo_row)
        photo_layout.setContentsMargins(0, 0, 0, 0)
        self.photo_button = QPushButton(t("photo_choose"))
        self.photo_button.clicked.connect(self._choose_photo)
        self.photo_label = QLabel(t("photo_none"))
        photo_layout.addWidget(self.photo_button)
        photo_layout.addWidget(self.photo_label, 1)
        form.addRow(t("field_photo"), photo_row)
        form.addRow(t("field_notes"), self.notes)
        self.notes_private = QCheckBox(t("field_notes_private"))
        self.notes_private.setChecked(bool(data.get("notes_private")))
        self.private = QCheckBox(t("field_private_person"))
        self.private.setChecked(bool(data.get("private")))
        for box in (self.notes_private, self.private):
            box.setToolTip(t("field_private_tip"))
        form.addRow("", self.notes_private)
        form.addRow("", self.private)

        self.problem = QLabel()
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet(f"color: {theme.hex('error')};")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.another_button = None
        if another:
            # For entering a row of children or siblings without going back each time.
            self.another_button = self.buttons.addButton(
                t("save_add_another"), QDialogButtonBox.ButtonRole.ActionRole
            )
            self.another_button.clicked.connect(self._save_and_again)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setDefault(True)

        # The form scrolls on a short screen, so Save and Cancel always stay in sight.
        fields = QWidget()
        fields.setLayout(form)
        form.setContentsMargins(0, 0, 0, 0)
        scroller = QScrollArea()
        scroller.setObjectName("person_fields")
        scroller.setWidget(fields)
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bar = scroller.verticalScrollBar().sizeHint().width()
        scroller.setMinimumWidth(fields.sizeHint().width() + bar)
        layout = QVBoxLayout(self)
        layout.addWidget(scroller, 1)
        layout.addWidget(self.problem)
        layout.addWidget(self.buttons)
        wanted = fields.sizeHint().height() + self.buttons.sizeHint().height() + 3 * layout.spacing() + 24
        fit_to_screen(self, fields.sizeHint().width() + bar + 24, wanted)

        self.status.currentIndexChanged.connect(self._refresh)
        for field in (self.birth_date, self.death_date):
            field.textChanged.connect(self._refresh)
        self._refresh()
        self.given.setFocus()
        # Enter saves. Any other button ("Other names", "Add event") would otherwise become
        # the default as soon as it was focused once, or by being first in the window.
        save = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(button is save)
        save.setDefault(True)
        # What OK with nothing changed would give (a copy: events and names are edited in place).
        self.shown = copy.deepcopy(self.values())

    def ask_event(self, event):
        dialog = EventDialog(self, event, self.context)
        return dialog.values() if dialog.exec() else None

    def _label_names(self):
        self.names_button.setText(t("button_other_names", count=len(self.names)))

    def ask_names(self):
        dialog = NamesDialog(self, self.context, self.names)
        return dialog.values() if dialog.exec() else None

    def edit_names(self):
        chosen = self.ask_names()
        if chosen is not None:
            self.names = chosen
            self._label_names()

    def _show_events(self):
        self.events_list.clear()
        for event in self.events:
            self.events_list.addItem(event_summary(event))

    def _add_event(self):
        event = self.ask_event({"type": "occupation"})
        if event is not None:
            self.events.append(event)
            self._show_events()

    def _edit_event(self):
        row = self.events_list.currentRow()
        if 0 <= row < len(self.events):
            event = self.ask_event(self.events[row])
            if event is not None:
                self.events[row] = event
                self._show_events()

    def _remove_event(self):
        row = self.events_list.currentRow()
        if 0 <= row < len(self.events):
            del self.events[row]
            self._show_events()

    def _choose_photo(self):
        path, _ = QFileDialog.getOpenFileName(self, t("photo_dialog"), str(Path.home()), t("photo_filter"))
        if path:
            self.set_photo_source(path)

    def set_photo_source(self, path):
        self.photo_source = path
        self.photo_label.setText(Path(path).name)

    def _refresh(self):
        living = self.status.currentData() == "yes"
        self.death_date.setEnabled(not living or bool(self.death_date.text()))
        self.death_place.setEnabled(not living)
        message = ""
        try:
            values = self.values()
            clean_fields(values)
            for date, _place, _details in self.marriages.values():
                if normalize_date_input(date.text()) is None:
                    raise EditError(t("error_event_date", what=t("field_marriage")))
                if is_period(normalize_date_input(date.text())):
                    raise EditError(t("error_period_not_here"))
        except EditError as error:
            message = str(error)
            typed = (self.birth_date.text(), self.death_date.text())
            if any(normalize_date_input(text) is None for text in typed):
                message = f"{message} {t('date_try', hint=t('date_hint'))}"
        self.problem.setText(message)
        self.problem.setVisible(bool(message))
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(not message)
        if self.another_button is not None:
            self.another_button.setEnabled(not message)

    def _save_and_again(self):
        self.add_another = True
        self.accept()

    def values(self):
        """What was entered, in the form edits.clean_fields expects."""
        values = {
            "given": self.given.text(),
            "surname": self.surname.text(),
            "birth_surname": self.birth_surname.text(),
            "sex": self.sex.currentData(),
            "birth_date": self.birth_date.text(),
            "birth_place": self.birth_place.text(),
            "living": self.status.currentData(),
            "death_date": self.death_date.text(),
            "death_place": self.death_place.text(),
            "notes": self.notes.toPlainText(),
            "notes_private": self.notes_private.isChecked(),
            "private": self.private.isChecked(),
            "photo_source": self.photo_source,
            "relationships": {key: box.currentData() for key, box in self.relationships.items()},
            "birth_citations": self.birth_details.citations,
            "birth_people": self.birth_details.people,
            "death_citations": self.death_details.citations,
            "death_people": self.death_details.people,
            "events": [dict(e) for e in self.events],
            "names": [dict(n) for n in self.names],
            "marriages": {key: {"date": d.text(), "place": p.text(), **details.values()}
                          for key, (d, p, details) in self.marriages.items()},
            "new_sources": {k: v for k, v in self.context.sources.items() if k not in self.known_sources},
        }
        if self.link is not None:
            values["link"] = self.link.currentData()
        if self.add_another:
            values["add_another"] = True
        if getattr(self, "shown", None) is not None and values == self.shown:
            # Nothing changed: OK must not rewrite what the window doesn't show (a hand-edited
            # file's odd shapes, details from another program) or add an undo step.
            values["unchanged"] = True
        return values


def person_to_values(person):
    return {
        "given": person.given,
        "surname": person.surname,
        "birth_surname": person.birth_surname,
        "sex": person.sex,
        "birth_date": person.birth_date,
        "birth_place": (person.birth or {}).get("place", ""),
        "living": person.living,
        "death_date": person.death_date,
        "death_place": (person.death or {}).get("place", ""),
        "notes": person.notes,
        "notes_private": bool(person.extra.get("notes_private")),
        "private": bool(person.extra.get("private")),
        "birth_citations": fact_details(person.birth).get("citations", []),
        "birth_people": fact_details(person.birth).get("people", []),
        "death_citations": fact_details(person.death).get("citations", []),
        "death_people": fact_details(person.death).get("people", []),
        "events": [{**e, "date": date_input_text(e["date"])} for e in person_events(person)],
        "names": [{**n, "date": date_input_text(n["date"])} for n in person_names(person)],
        "documents": person_documents(person),  # For pointing a citation at a scan.
    }


def matching_people(tree, query):
    """People matching every typed word, sorted by surname and then given name."""
    words = fold_text(query).split()
    found = []
    for person in tree.people.values():
        others = " ".join(f"{n['given']} {n['surname']}" for n in person_names(person))
        haystack = fold_text(f"{person.given} {person.surname} {person.birth_surname} {others}")
        if all(word in haystack for word in words):
            found.append(person)
    return sorted(found, key=lambda p: (collation_key(p.surname), collation_key(p.given), p.id))


class FindDialog(QDialog):
    def __init__(self, parent, tree, today, title=None, exclude=()):
        super().__init__(parent)
        self.tree = tree
        self.today = today
        self.exclude = set(exclude)
        self.chosen = None
        self.setWindowTitle(title or t("find_title"))
        fit_to_screen(self, 420, 480)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("find_placeholder"))
        self.results = QListWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.results)
        self.search.textChanged.connect(self._refresh)
        self.search.returnPressed.connect(self._choose_current)
        self.results.itemActivated.connect(self._choose_item)
        self._refresh()
        self.search.setFocus()

    def _refresh(self):
        self.results.clear()
        for person in matching_people(self.tree, self.search.text()):
            if person.id in self.exclude:
                continue
            label = person.display_name
            detail = person.age_label(self.today)
            item = QListWidgetItem(f"{label}   ({detail})" if detail else label)
            item.setData(Qt.ItemDataRole.UserRole, person.id)
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)

    def _choose_current(self):
        item = self.results.currentItem()
        if item is not None:
            self._choose_item(item)

    def _choose_item(self, item):
        self.chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()


class CropArea(QWidget):
    """Shows the picture with the portrait shape on top. Drag to move, wheel to resize."""

    MAX_SIDE = 620
    MIN_CROP = 40

    def __init__(self, image):
        super().__init__()
        self.image = image
        self.crop = default_crop(image)
        self.scale_factor = min(1.0, self.MAX_SIDE / max(image.width(), image.height()))
        self.setFixedSize(
            QSize(
                max(1, round(image.width() * self.scale_factor)),
                max(1, round(image.height() * self.scale_factor)),
            )
        )
        self._drag_from = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def largest_width(self):
        return min(self.image.width(), round(self.image.height() * STORED_W / STORED_H))

    def smallest_width(self):
        return min(self.MIN_CROP, self.largest_width())

    def set_crop_width(self, width):
        """Resize around the current centre, staying inside the picture."""
        width = max(self.smallest_width(), min(self.largest_width(), width))
        height = round(width * STORED_H / STORED_W)
        centre = self.crop.center()
        self._place(QRect(centre.x() - width // 2, centre.y() - height // 2, width, height))

    def _place(self, rect):
        rect.moveLeft(max(0, min(rect.left(), self.image.width() - rect.width())))
        rect.moveTop(max(0, min(rect.top(), self.image.height() - rect.height())))
        self.crop = rect
        self.update()

    def move_crop(self, dx, dy):
        self._place(self.crop.translated(dx, dy))

    def _on_screen(self):
        factor = self.scale_factor
        return QRectF(
            self.crop.x() * factor,
            self.crop.y() * factor,
            self.crop.width() * factor,
            self.crop.height() * factor,
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRectF(self.rect()), self.image)
        shown = self._on_screen()
        shade = QColor(0, 0, 0, 150)
        whole = QRectF(self.rect())
        painter.fillRect(QRectF(0, 0, whole.width(), shown.top()), shade)
        painter.fillRect(QRectF(0, shown.bottom(), whole.width(), whole.height() - shown.bottom()), shade)
        painter.fillRect(QRectF(0, shown.top(), shown.left(), shown.height()), shade)
        painter.fillRect(QRectF(shown.right(), shown.top(), whole.width() - shown.right(), shown.height()), shade)
        painter.setPen(QPen(theme.colour("highlight"), 2))
        painter.drawRect(shown)
        painter.end()

    def mousePressEvent(self, event):
        self._drag_from = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_from is None:
            return
        point = event.position().toPoint()
        delta = (point - self._drag_from) / self.scale_factor
        self.move_crop(delta.x(), delta.y())
        self._drag_from = point

    def mouseReleaseEvent(self, event):
        self._drag_from = None

    def wheelEvent(self, event):
        factor = 0.92 if event.angleDelta().y() > 0 else 1.09
        self.set_crop_width(round(self.crop.width() * factor))
        event.accept()


class CropDialog(QDialog):
    def __init__(self, parent, image):
        super().__init__(parent)
        self.setWindowTitle(t("crop_title"))
        self.area = CropArea(image)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(self.area.smallest_width(), self.area.largest_width())
        self.slider.setValue(self.area.crop.width())
        self.slider.valueChanged.connect(self.area.set_crop_width)
        hint = QLabel(t("crop_hint"))
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.area, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(hint)
        layout.addWidget(self.slider)
        layout.addWidget(buttons)


class PreferencesDialog(QDialog):
    """Personal settings, kept per user on this computer, never inside a tree."""

    def __init__(self, parent, values):
        super().__init__(parent)
        import house_layout as hl
        self.setWindowTitle(t("menu_preferences").replace("&", "").replace("...", ""))
        self.setMinimumWidth(420)
        form = QFormLayout()
        self.style = QComboBox()
        for style in hl.STYLES:
            self.style.addItem(t(f"style_{style}"), style)
        self.style.setCurrentIndex(max(0, self.style.findData(values["card_style"])))
        self.detail = QComboBox()
        self.detail.addItem(t("pref_detail_age"), "age")
        self.detail.addItem(t("pref_detail_years"), "years")
        self.detail.setCurrentIndex(max(0, self.detail.findData(values["detail"])))
        self.generations = QSpinBox()
        self.generations.setRange(1, hl.MAX_ANCESTOR_GENERATIONS)
        self.generations.setValue(values["generations_up"])
        self.reopen = QCheckBox(t("pref_reopen"))
        self.reopen.setChecked(values["reopen_last"])
        from strings import LANGUAGES, SYSTEM
        self.language = QComboBox()
        self.language.addItem(t("pref_language_system"), SYSTEM)
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(values.get("language", SYSTEM))))
        self.language.setToolTip(t("pref_language_note"))
        form.addRow(t("pref_card_style"), self.style)
        form.addRow(t("pref_detail"), self.detail)
        form.addRow(t("pref_generations"), self.generations)
        form.addRow("", self.reopen)
        form.addRow(t("pref_language"), self.language)
        self.theme = QComboBox()
        for name in theme.THEMES:
            self.theme.addItem(t(f"theme_{name}"), name)
        self.theme.setCurrentIndex(max(0, self.theme.findData(values.get("theme", "dark"))))
        form.insertRow(0, t("pref_theme"), self.theme)

        def choice(options, current):
            box = QComboBox()
            for value in options:
                box.addItem(t(value[1]), value[0])
            box.setCurrentIndex(max(0, box.findData(current)))
            return box

        self.placeholder = choice((("initials", "placeholder_initials"), ("silhouette", "placeholder_silhouette")),
                                  values.get("placeholder", "initials"))
        self.lines = choice((("square", "lines_square"), ("rounded", "lines_rounded"), ("curved", "lines_curved")),
                            values.get("lines", "rounded"))
        self.colours = choice((("plain", "colours_plain"), ("side", "colours_side"), ("surname", "colours_surname")),
                              values.get("colours", "plain"))
        self.toolbar = choice((("icons", "toolbar_icons"), ("both", "toolbar_both"), ("text", "toolbar_text")),
                              values.get("toolbar", "icons"))
        self.surnames = choice((("both", "surnames_both"), ("birth", "surnames_birth"), ("current", "surnames_current")),
                               values.get("surnames", "both"))
        self.motion = QCheckBox(t("pref_motion"))
        self.motion.setChecked(values.get("motion", True))
        self.mark_deceased = QCheckBox(t("pref_mark_deceased"))
        self.mark_deceased.setChecked(bool(values.get("mark_deceased")))
        self.shadows = QCheckBox(t("pref_shadows"))
        self.shadows.setChecked(bool(values.get("shadows", True)))
        for row, (label, widget) in enumerate(((t("pref_placeholder"), self.placeholder), (t("pref_lines"), self.lines),
                                               (t("pref_colours"), self.colours), ("", self.mark_deceased),
                                               ("", self.shadows), (t("pref_toolbar"), self.toolbar), ("", self.motion),
                                               (t("pref_surnames"), self.surnames)), start=2):
            form.insertRow(row, label, widget)
        self.show_tour = QCheckBox(t("pref_show_tour"))
        self.show_tour.setChecked(bool(values.get("show_tour", True)))
        form.addRow(t("pref_tour"), self.show_tour)
        self.map_tiles = QCheckBox(t("pref_map_tiles"))
        self.map_tiles.setChecked(bool(values.get("map_tiles")))
        self.map_search = QCheckBox(t("pref_map_search"))
        self.map_search.setChecked(bool(values.get("map_search")))
        for box in (self.map_tiles, self.map_search):
            box.setToolTip(t("pref_map_tip"))
        form.addRow(t("pref_map"), self.map_tiles)
        form.addRow("", self.map_search)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        area = scrolling(form)
        wanted = area.widget().sizeHint()  # Measured once the form sits in its page.
        layout.addWidget(area, 1)
        layout.addWidget(buttons)
        bar = area.verticalScrollBar().sizeHint().width()
        fit_to_screen(self, wanted.width() + bar + 32, wanted.height() + buttons.sizeHint().height() + 48)

    def values(self):
        return {
            "card_style": self.style.currentData(),
            "detail": self.detail.currentData(),
            "generations_up": self.generations.value(),
            "reopen_last": self.reopen.isChecked(),
            "language": self.language.currentData(),
            "show_tour": self.show_tour.isChecked(),
            "theme": self.theme.currentData(),
            "placeholder": self.placeholder.currentData(),
            "toolbar": self.toolbar.currentData(),
            "motion": self.motion.isChecked(),
            "surnames": self.surnames.currentData(),
            "lines": self.lines.currentData(),
            "colours": self.colours.currentData(),
            "mark_deceased": self.mark_deceased.isChecked(),
            "shadows": self.shadows.isChecked(),
            "map_tiles": self.map_tiles.isChecked(),
            "map_search": self.map_search.isChecked(),
        }


def event_summary(event):
    """One line for a life event: 'Occupation: carpenter, 1950, Split'."""
    extras = fact_details(event)
    parts = [event.get("text", ""), date_input_text(normalize_date_input(event.get("date", "")) or ""),
             event.get("place", ""), extras.get("address", ""),
             t("fact_age", age=extras["age"]) if extras.get("age") else "",
             t("fact_cause", cause=extras["cause"]) if extras.get("cause") else ""]
    detail = ", ".join(p for p in parts if p)
    label = t(f"event_{event.get('type', 'other')}")
    if extras.get("label") and event.get("type") in ("other", "military"):
        label = extras["label"]  # The other program's own word: "Familie", "Funktion".
    return f"{label}: {detail}" if detail else label


class EventDialog(QDialog):
    """One life event: what, when, where, and where you learned it."""

    def __init__(self, parent, event, context=None):
        super().__init__(parent)
        self.original = dict(event or {})
        self.setWindowTitle(t("event_title"))
        self.setMinimumWidth(420)
        form = QFormLayout()
        self.kind = QComboBox()
        for kind in EVENT_TYPES:
            self.kind.addItem(t(f"event_{kind}"), kind)
        self.kind.setCurrentIndex(max(0, self.kind.findData(event.get("type", "occupation"))))
        self.text = QLineEdit(event.get("text", ""))
        self.text.setPlaceholderText(t("event_text_hint"))
        self.date = QLineEdit(event.get("date", ""))  # Already in the form people type.
        self.date.setPlaceholderText(t("event_date_hint"))
        self.place = QLineEdit(event.get("place", ""))
        self.details = FactDetails(context or FactContext(), event, t("event_title"))
        form.addRow(t("event_kind"), self.kind)
        form.addRow(t("event_text"), self.text)
        form.addRow(t("event_date"), self.date)
        form.addRow(t("event_place"), self.place)
        form.addRow("", self.details)
        self.problem = QLabel()
        self.problem.setStyleSheet(f"color: {theme.hex('error')};")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.problem)
        layout.addWidget(self.buttons)
        self.date.textChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        bad = normalize_date_input(self.date.text()) is None
        self.problem.setText(t("date_try", hint=t("event_date_hint")) if bad else "")
        self.problem.setVisible(bad)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not bad)

    def values(self):
        kind = self.kind.currentData()
        # What it carries from another program's file and this window does not show
        # (age, cause, address, its own tag...) stays, unless it became another kind of event.
        carried = {k: v for k, v in fact_details(self.original).items() if k not in ("citations", "people")}
        if kind != self.original.get("type"):
            carried.pop("tag", None)
            carried.pop("label", None)
        return {**carried, "type": kind, "text": self.text.text().strip(),
                "date": self.date.text().strip(), "place": self.place.text().strip(), **self.details.values()}


def fact_label(tree, row):
    """'Born: Luka Šimić' or 'Married: Luka Šimić and Mara Šimić'."""
    name = tree.people[row.person_id].display_name if row.person_id in tree.people else "?"
    if row.kind == "marriage" and row.with_id in tree.people:
        name = t("names_and", a=name, b=tree.people[row.with_id].display_name)
    kind = t(f"fact_{row.kind}") if row.kind in ("birth", "death", "marriage") else t(f"event_{row.kind}")
    text = f"{kind}: {name}"
    return f"{text} ({row.text})" if row.text else text


class PlacesDialog(QDialog):
    """Every place in the tree and what happened there (double-click goes to the person),
    and the selected place's details: the place it lies in, kind, coordinates, old names.
    Edits are tried on a copy as you make them; `operations` replays them on the tree."""

    def __init__(self, parent, tree, rows=None):
        super().__init__(parent)
        from edits import copy_tree
        from places_dialog import PlaceEditor
        self.setWindowTitle(t("places_title"))
        fit_to_screen(self, 980, 620)
        self.tree, self.chosen = tree, None
        self.work = copy_tree(tree)
        self.operations = []
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(t("places_filter"))
        self.places = QListWidget()
        self.events = QListWidget()
        self.editor = PlaceEditor()
        self.editor.saved.connect(self._saved)
        self.editor.forgotten.connect(self._forgotten)
        right = QVBoxLayout()
        right.addWidget(self.editor)
        right.addWidget(QLabel(t("places_what_happened")))
        right.addWidget(self.events, 1)
        split = QHBoxLayout()
        split.addWidget(self.places, 2)
        split.addLayout(right, 3)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.filter)
        layout.addLayout(split, 1)
        layout.addWidget(buttons)
        self.filter.textChanged.connect(lambda _text: self._fill_places())
        self.places.currentRowChanged.connect(self._show_place)
        self.events.itemActivated.connect(self._go)
        self._fill_places()

    def _collect(self):
        from model import all_facts, place_records
        self.by_place = {}
        for row in all_facts(self.work):
            if row.place:
                self.by_place.setdefault(row.place, []).append(row)
        self.records = place_records(self.work)
        for name in self.records:
            self.by_place.setdefault(name, [])

    def _fill_places(self, select=None):
        self._collect()
        words = fold_text(self.filter.text()).split()
        self.shown = [p for p in sorted(self.by_place, key=lambda p: (-len(self.by_place[p]), collation_key(p)))
                      if all(w in fold_text(p) for w in words)]
        self.places.blockSignals(True)
        self.places.clear()
        for place in self.shown:
            marks = " \u2316" if "lat" in self.records.get(place, {}) else ""  # Has coordinates.
            self.places.addItem(f"{place}  ({len(self.by_place[place])}){marks}")
        self.places.blockSignals(False)
        if self.shown:
            row = self.shown.index(select) if select in self.shown else 0
            self.places.setCurrentRow(row)
            self._show_place(row)
        else:
            self.events.clear()
            self.editor.show_place(None, None, [])

    def _show_place(self, row):
        self.events.clear()
        if not 0 <= row < len(self.shown):
            return
        place = self.shown[row]
        self.editor.show_place(place, self.records.get(place), list(self.by_place))
        facts = sorted(self.by_place[place], key=lambda f: date_sort_key(f.date, f.kind))
        for fact in facts:
            item = QListWidgetItem(f"{date_input_text(fact.date) or '?'}   {fact_label(self.tree, fact)}")
            item.setData(Qt.ItemDataRole.UserRole, fact.person_id)
            self.events.addItem(item)

    def _saved(self, old, new, record):
        import edits
        from edits import copy_tree
        from model import place_records
        # Worked on a copy: a save that is refused must leave nothing behind, not even
        # the rename that ran before the refusal.
        trial = copy_tree(self.work)
        try:
            records = place_records(trial)
            if new != old and new in records:
                # Renamed onto a place already known: the two are merged, and the one renamed
                # onto keeps its details. The form showed the renamed place, so only what the
                # person changed in it counts, on top of the merged record.
                before = records.get(old, {})
                changed = {k: v for k, v in record.items() if v not in ("", None, []) and v != before.get(k)}
                edits.rename_place(trial, old, new)
                merged = place_records(trial).get(new, {})
                record = {**merged, **changed}
                if merged.get("old_names") or changed.get("old_names"):
                    names = list(merged.get("old_names", []))
                    record["old_names"] = names + [n for n in changed.get("old_names", []) if n not in names]
            elif new != old:
                edits.rename_place(trial, old, new)
            edits.set_place(trial, new, record)
        except edits.EditError as error:
            self.editor.problem.setText(str(error))
            return
        self.work = trial
        if new != old:
            self.operations.append(("rename", old, new))
        self.operations.append(("set", new, record))
        self._fill_places(new)

    def _forgotten(self, name):
        import edits
        edits.remove_place(self.work, name)
        self.operations.append(("forget", name))
        self._fill_places(name)

    def _go(self, item):
        self.chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()


class TimelineDialog(QDialog):
    """The family's dated events in order. Double-click goes to the person."""

    def __init__(self, parent, tree, rows, year_of):
        super().__init__(parent)
        self.setWindowTitle(t("timeline_title"))
        fit_to_screen(self, 720, 560)
        self.tree, self.chosen = tree, None
        # By the real date: "about 1921" belongs in 1921, not after all plain years.
        self.rows = sorted((r for r in rows if year_of(r) is not None), key=lambda r: date_sort_key(r.date, r.kind))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(t("timeline_filter"))
        self.list = QListWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.filter)
        layout.addWidget(self.list)
        self.filter.textChanged.connect(self._fill)
        self.list.itemActivated.connect(self._go)
        self._fill()

    def _fill(self):
        words = fold_text(self.filter.text()).split()
        self.list.clear()
        for row in self.rows:
            line = f"{date_input_text(row.date):>12}   {fact_label(self.tree, row)}"
            if row.place:
                line += f"  -  {row.place}"
            if all(w in fold_text(line) for w in words):
                item = QListWidgetItem(line)
                item.setData(Qt.ItemDataRole.UserRole, row.person_id)
                self.list.addItem(item)

    def _go(self, item):
        self.chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
