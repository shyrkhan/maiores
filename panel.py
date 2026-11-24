"""The side panel: everything about the selected person, and what you can do to them."""
import html
import re

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import house_layout as hl
import canvas
from canvas import clear_layout, paint_portrait
import datetime

from dialogs import event_summary
from facts_dialogs import FactContext, citation_text, name_text
from model import (
    date_input_text, date_warnings, fact_details, family_marriage, kept_details, person_documents, person_events,
    person_names,
    person_story, person_tasks, photos_of, roles_of,
)
from strings import t
import theme

PANEL_WIDTH = 300
PREVIEW_W = 132

# Which panel section an action belongs in. Anything not listed goes in the middle.
ADD_KEYS = ("add_father", "add_mother", "add_partner", "add_child", "add_sibling", "add_extra_parent", "connect")
RISKY_KEYS = ("merge", "remove_parents", "remove_partner", "delete")


def _place_text(date, place):
    shown = date_input_text(date)
    return ", ".join(part for part in (shown, place) if part)



_LONG_RUN = re.compile(r"[^\s<>&;\"'=]{40,}")


def _breakable(text):
    """A long unbroken run (a web address in the notes, say) may break anywhere: the
    panel wraps at spaces only, and such a line would push its buttons out of sight."""
    return _LONG_RUN.sub(lambda m: "\u200b".join(m[0][i:i + 20] for i in range(0, len(m[0]), 20)), text)

class PersonPanel(QFrame):
    def __init__(self, on_person_link, on_action):
        super().__init__()
        self.on_person_link = on_person_link
        self.on_action = on_action
        self.links = []
        self.current = None
        self.photo_links = []
        self.button_pool = {}  # Action key -> its button, reused for every person.
        self.today = datetime.date.today()
        self.setFixedWidth(PANEL_WIDTH)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self.portrait = QLabel()
        self.portrait.setAccessibleName(t("field_photo"))
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.name = QLabel()
        self.name.setWordWrap(True)
        self.name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        font = self.name.font()
        font.setPointSizeF(font.pointSizeF() * 1.3)
        font.setBold(True)
        self.name.setFont(font)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.RichText)
        self.details.linkActivated.connect(self._link_clicked)
        # Tab reaches each link (a parent, a document, "Photos with"), Enter follows it, and
        # a screen reader reads the text, not only a picture of it.
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse
                                             | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
                                             | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.details.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.details.setAccessibleName(t("menu_person").replace("&", ""))
        self.add_heading = QLabel(t("panel_add_heading"))
        self.add_heading.setWordWrap(True)  # Russian at large text is wider than the panel.
        heading_font = self.add_heading.font()
        heading_font.setBold(True)
        self.add_heading.setFont(heading_font)
        self.add_buttons = QGridLayout()
        self.add_buttons.setSpacing(4)
        self.buttons = QGridLayout()
        self.buttons.setSpacing(4)
        self.risky_buttons = QGridLayout()
        self.risky_buttons.setSpacing(4)
        self.divider = QFrame()
        self.divider.setFrameShape(QFrame.Shape.HLine)
        self.divider.setStyleSheet(f"color: {theme.hex('divider')};")

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(self.portrait)
        layout.addWidget(self.name)
        layout.addSpacing(6)
        layout.addWidget(self.add_heading)
        layout.addLayout(self.add_buttons)
        layout.addSpacing(6)
        layout.addWidget(self.details)
        layout.addLayout(self.buttons)
        layout.addStretch(1)
        layout.addWidget(self.divider)
        layout.addLayout(self.risky_buttons)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _button_clicked(self):
        button = self.sender()
        if button is not None and self.current is not None:
            self.on_action(button.property("action_key"), self.current)

    def _link_clicked(self, target):
        if target.startswith("photo"):
            self.on_action(f"open_file:{self.photo_links[int(target[5:])]}", self.current)
            return
        if target.startswith("doc"):
            self.on_action(f"open_document:{target[3:]}", self.current)
            return
        if target == "dna":
            self.on_action("dna", self.current)
            return
        self.on_person_link(self.links[int(target)])

    def _person_link(self, tree, person_id):
        self.links.append(person_id)
        name = html.escape(tree.people[person_id].display_name)
        return f'<a href="{len(self.links) - 1}" style="color:{theme.hex('highlight')}">{name}</a>'

    def _dna_details(self, tree, person):
        """The person's DNA tests, and the DNA they share with testers in the tree."""
        import dna
        from dna_dialog import relation_name
        lines = []
        for test in dna.tests_of(person):
            label = " · ".join(x for x in (test["company"], t(f"dna_kind_{test['kind']}"), test["haplogroup"]) if x)
            lines.append(html.escape(f"{label}: {t('dna_match_count', count=len(test['matches']))}"))
        everyone = tree.held("dna_matches", lambda: dna.all_matches(tree))
        for tester, _test, match in everyone:
            if match["person"] != person.id or tester not in tree.people or match["cm"] is None:
                continue
            status, relation, figures = dna.check(tree, tester, match)
            text = t("dna_panel_shared", cm=match["cm"])
            if status in ("fits", "low", "high"):
                text += " " + t(f"dna_check_{status}", relation=relation_name(relation.up, relation.down, relation.half),
                                low=figures[1], high=figures[2])
            elif status == "unrelated":
                text += " " + t("dna_check_unrelated")
            colour = theme.hex("warn") if status in ("low", "high", "unrelated") else theme.hex("text")
            lines.append(f"{self._person_link(tree, tester)}: <span style='color:{colour}'>{html.escape(text)}</span>")
        if not lines:
            return []
        link = f'<a href="dna" style="color:{theme.hex("highlight")}">{html.escape(t("dna_open"))}</a>'
        return [f"<p><b>{html.escape(t('panel_dna'))}</b><br>{'<br>'.join(lines)}<br>{link}</p>"]

    def _fact_details(self, tree, person):
        """Other names, the people at this person's events, where the person appears in
        other records, and the sources of everything."""
        context = FactContext(tree)
        facts = [(t("fact_birth"), person.birth), (t("fact_death"), person.death)]
        facts += [(t(f"event_{e['type']}"), e) for e in person_events(person)]
        for family in tree.families_of(person.id):
            marriage = family_marriage(family)
            if fact_details(marriage):
                facts.append((t("fact_marriage"), marriage))
        parts, sources, present = [], [], []
        names = person_names(person)
        if names:
            lines = "<br>".join(html.escape(name_text(n)) for n in names)
            parts.append(f"<p><b>{html.escape(t('field_other_names'))}</b><br>{lines}</p>")
        for label, fact in facts:
            details = fact_details(fact)
            for entry in details.get("people", []):
                who = (self._person_link(tree, entry["person"]) if entry.get("person") in tree.people
                       else html.escape(context.person_name(entry)))
                present.append(f"{html.escape(label)}: {html.escape(t('role_' + entry['role']))} {who}")
            for citation in details.get("citations", []):
                sources.append(f"{html.escape(label)}: {html.escape(citation_text(context, citation))}")
        for name in names:
            for citation in name.get("citations", []):
                sources.append(f"{html.escape(t('field_other_names'))}: {html.escape(citation_text(context, citation))}")
        if present:
            parts.append(f"<p><b>{html.escape(t('panel_people_present'))}</b><br>{'<br>'.join(present)}</p>")
        elsewhere = []
        for role, owner, kind, _fact in roles_of(tree, person.id):
            if owner in tree.people:
                what = t("fact_" + kind) if kind in ("birth", "death") else t(f"event_{kind}")
                elsewhere.append(html.escape(t("panel_role_in", role=t("role_" + role), what=what)) + " "
                                 + self._person_link(tree, owner))
            elif owner in tree.families:
                partners = [p for p in tree.families[owner].partners if p in tree.people]
                links = " & ".join(self._person_link(tree, p) for p in partners)
                elsewhere.append(html.escape(t("panel_role_in", role=t("role_" + role), what=t("fact_marriage")))
                                 + " " + links)
        if elsewhere:
            parts.append(f"<p><b>{html.escape(t('panel_roles_elsewhere'))}</b><br>{'<br>'.join(elsewhere)}</p>")
        self.photo_links = []
        pictures = []
        for path, title in photos_of(tree, person.id):
            self.photo_links.append(path)
            label = html.escape(title or t("doc_kind_photo"))
            pictures.append(f'<a href="photo{len(self.photo_links) - 1}" style="color:{theme.hex('highlight')}">{label}</a>')
        if pictures:
            parts.append(f"<p><b>{html.escape(t('panel_photos_with'))}</b><br>{'<br>'.join(pictures)}</p>")
        if sources:
            parts.append(f"<p><b>{html.escape(t('field_sources'))}</b><br>{'<br>'.join(sources)}</p>")
        return parts

    def _people_rows(self, tree, heading, people, notes=None):
        names = []
        for person_id in people:
            if person_id in tree.people:
                self.links.append(person_id)
                name = html.escape(tree.people[person_id].display_name)
                note = f" <span style='color:{theme.hex("soft")}'>{html.escape(notes[person_id])}</span>" if notes and person_id in notes else ""
                names.append(f'<a href="{len(self.links) - 1}" style="color:{theme.hex('highlight')}">{name}</a>{note}')
        shown = "<br>".join(names) if names else f"<i>{html.escape(t('panel_none'))}</i>"
        return f"<p><b>{html.escape(heading)}</b><br>{shown}</p>"

    def show_person(self, tree, person_id, pixmap, actions, relation=""):
        person = tree.people[person_id]
        self.links = []
        self.current = person_id
        private = person.extra.get("private")
        self.name.setText(f"{person.display_name}\n{t('panel_private_person')}" if private else person.display_name)

        height = round(PREVIEW_W * hl.PORTRAIT_H / hl.PORTRAIT_W)
        ratio = self.devicePixelRatioF()  # Stays sharp on high-resolution screens.
        image = QPixmap(QSize(round(PREVIEW_W * ratio), round(height * ratio)))
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)  # Rounded corners show the panel behind.
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        letters = [w[0] for w in (person.given.split()[:1] + person.surname.split()[:1]) if w]
        paint_portrait(
            painter, QRectF(0, 0, PREVIEW_W, height), pixmap, person.living == "no",
            "".join(letters).upper() or "?", canvas.DECOR.tints.get(person.id), 10.0,
        )
        painter.end()
        self.portrait.setPixmap(image)

        rows = []
        if relation:
            rows.append((relation, ""))
        if person.birth_surname and person.birth_surname != person.surname:
            rows.append((t("panel_birth_surname"), person.birth_surname))
        born = _place_text(person.birth_date, (person.birth or {}).get("place", ""))
        if born:
            rows.append((t("panel_born"), born))
        died = _place_text(person.death_date, (person.death or {}).get("place", ""))
        cause = fact_details(person.death).get("cause") if person.death else ""
        if cause:
            died = ", ".join(x for x in (died, t("fact_cause", cause=cause)) if x)
        if died:
            rows.append((t("panel_died"), died))
        elif person.living == "no":
            rows.append((t("panel_deceased"), ""))
        parts = [
            f"<p><b>{html.escape(key)}</b>"
            + (f"<br>{html.escape(value)}" if value else "")
            + "</p>"
            for key, value in rows
        ]

        family = tree.birth_family_of(person_id)
        parents = family.partners if family else []
        siblings = [c for c in family.child_ids if c != person_id] if family else []
        partners, children, married = [], [], {}
        for own in tree.families_of(person_id):
            for p in own.partners:
                if p != person_id:
                    partners.append(p)
                    marriage = family_marriage(own)
                    when = ", ".join(x for x in (date_input_text(marriage["date"]), marriage["place"]) if x)
                    if when:
                        married[p] = t("panel_married", when=when)
            children.extend(own.child_ids)
        parts.append(self._people_rows(tree, t("panel_parents"), parents))
        for other, kind in tree.parent_families(person_id):
            if other is not family and kind in ("adopted", "foster"):
                heading = t("panel_extra_parents", kind=t(f"panel_kind_{kind}"))
                parts.append(self._people_rows(tree, heading, other.partners))
        parts.append(self._people_rows(tree, t("panel_partners"), partners, married))
        parts.append(self._people_rows(tree, t("panel_children"), children))
        if siblings:
            parts.append(self._people_rows(tree, t("panel_siblings"), siblings))
        events = person_events(person)
        if events:
            lines = "<br>".join(html.escape(event_summary(e)) for e in events)
            parts.append(f"<p><b>{html.escape(t('field_events'))}</b><br>{lines}</p>")
        parts += self._fact_details(tree, person)
        parts += self._dna_details(tree, person)
        kept = kept_details(tree, person.extra.get("gedcom"))
        if kept:
            heading = t("panel_other_details", program=str(tree.extra.get("gedcom_from") or "GEDCOM"))
            items = "<br>".join(html.escape(line) for line in kept)
            parts.append(f'<p><b>{html.escape(heading)}</b><br><span style="color:{theme.hex("soft")}">'
                         f'{items}</span></p>')
        warnings = date_warnings(tree, person_id, self.today)
        if warnings:
            items = "<br>".join(html.escape(w) for w in warnings)
            parts.append(f'<p style="color:{theme.hex('warn')}"><b>{html.escape(t("panel_check_dates"))}</b><br>{items}</p>')
        documents = person_documents(person)
        if documents:
            lines = []
            for index, document in enumerate(documents):
                label = document["title"] or t(f"doc_kind_{document['kind']}")
                extra = ", ".join(x for x in (document["date"], t("documents_private_mark") if document["private"] else "")
                                  if x)
                note = f" <span style='color:{theme.hex("soft")}'>{html.escape(extra)}</span>" if extra else ""
                lines.append(f'<a href="doc{index}" style="color:{theme.hex('highlight')}">{html.escape(label)}</a>{note}')
            parts.append(f"<p><b>{html.escape(t('panel_documents'))}</b><br>{'<br>'.join(lines)}</p>")
        story = person_story(person)
        if story:
            shown = story if len(story) <= 600 else story[:600].rsplit(" ", 1)[0] + " ..."
            heading = t("panel_story_private") if person.extra.get("story_private") else t("panel_story")
            parts.append(f"<p><b>{html.escape(heading)}</b><br>{html.escape(shown).replace(chr(10), '<br>')}</p>")
        tasks = [task for task in person_tasks(person) if not task["done"]]
        if tasks:
            items = "<br>".join("\u2610 " + html.escape(task["text"]) for task in tasks)
            parts.append(f"<p><b>{html.escape(t('panel_tasks'))}</b><br>{items}</p>")
        if person.notes:
            notes = html.escape(person.notes).replace("\n", "<br>")
            heading = t("panel_notes_private") if person.extra.get("notes_private") else t("panel_notes")
            parts.append(f"<p><b>{html.escape(heading)}</b><br>{notes}</p>")
        self.details.setText(_breakable("".join(parts)))

        for grid in (self.add_buttons, self.buttons, self.risky_buttons):
            clear_layout(grid, keep_widgets=True)  # The buttons are reused for the next person.
        counts = {}
        places = {}  # Grid -> (row, column) of the next free cell.
        full = self.width() - 24 if self.width() > 100 else PANEL_WIDTH - 24
        for key, label, enabled in actions:
            if key in ADD_KEYS:
                grid = self.add_buttons
            elif key in RISKY_KEYS:
                grid = self.risky_buttons
            else:
                grid = self.buttons
            index = counts.get(id(grid), 0)
            counts[id(grid)] = index + 1
            # One button per action, made once and reused: making new ones on every redraw
            # left a little memory behind each time (PySide keeps part of a deleted button).
            button = self.button_pool.get(key)
            if button is None:
                button = QPushButton()
                # Share the panel's width; a long label must never push the column off screen.
                button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                button.setMinimumWidth(40)
                button.setObjectName(f"action_{key}")
                button.setProperty("action_key", key)
                button.clicked.connect(self._button_clicked)
                self.button_pool[key] = button
            button.setToolTip(label)
            button.setEnabled(enabled)
            # A label too long for half the panel (German, large text) gets a whole row; one
            # too long even for that is shortened with "…", whole in its tooltip.
            metrics = button.fontMetrics()
            needed = metrics.horizontalAdvance(label.replace("&", "")) + 24
            row, column = places.get(id(grid), (0, 0))
            if needed > full / 2 - 4:
                if column:
                    row, column = row + 1, 0
                button.setText(label if needed <= full else metrics.elidedText(label, Qt.TextElideMode.ElideRight, full - 24))
                grid.addWidget(button, row, 0, 1, 2)
                places[id(grid)] = (row + 1, 0)
            else:
                button.setText(label)
                grid.addWidget(button, row, column)
                places[id(grid)] = (row + 1, 0) if column else (row, 1)
            button.show()
        # Tab in the order they are seen: the add buttons at the top first, the risky last.
        shown = sorted((b for b in self.button_pool.values() if b.isVisibleTo(self) and self.isAncestorOf(b)),
                       key=lambda b: (0 if b.property("action_key") in ADD_KEYS else
                                      2 if b.property("action_key") in RISKY_KEYS else 1,
                                      [k for k, _l, _e in actions].index(b.property("action_key"))
                                      if b.property("action_key") in [k for k, _l, _e in actions] else 0))
        for first, second in zip(shown, shown[1:]):
            if first.window() is second.window():
                QWidget.setTabOrder(first, second)
        has_add = any(key in ADD_KEYS for key, _label, _enabled in actions)
        has_risky = any(key in RISKY_KEYS for key, _label, _enabled in actions)
        self.add_heading.setVisible(has_add)
        self.divider.setVisible(has_risky)
