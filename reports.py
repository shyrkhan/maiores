"""Reports to print or send: a family group sheet, an ancestor book and a descendant
book, as one HTML document that becomes a PDF (or an OpenDocument text file).

Each person is a numbered entry of labelled lines ("Born: 1921, Trogir [3]") built from
the interface's own words, not sentences: sentences can't be made correctly in all the
program's languages from pieces (Croatian alone changes nouns by case and gender).
Sources become numbered notes at the end, followed by an index of names and of places.

Ancestor books number people the usual way (Ahnentafel): you are 1, a person's father
is twice their number, the mother twice plus one. When cousins married, the same
ancestor is reached twice; they get one entry and "see no. N" the second time.
The caller passes a tree already made safe for sharing (privacy.shareable).
"""
import datetime
import html
from pathlib import Path

from model import (
    date_label, fact_details, family_marriage, parse_date, person_events, person_names, person_story, tree_sources,
)
from strings import collation_key, t


def _e(text):
    return html.escape(str(text))


class _Book:
    def __init__(self, tree, notes=True, sources=True):
        self.tree, self.with_notes, self.with_sources = tree, notes, sources
        self.sources = tree_sources(tree)
        self.citations = []  # Numbered source notes, in order of first use.
        self.cited = {}  # (source id, page, quality) -> note number: two sources are never one note.
        self.numbers = {}  # person id -> entry number.
        self.places = {}  # place -> entry numbers.

    def cite(self, fact):
        if not self.with_sources:
            return ""
        marks = []
        for citation in fact_details(fact).get("citations", []):
            key = (citation["source"], citation.get("page", ""), citation.get("quality", ""))
            if key not in self.cited:
                self.citations.append(self._source_text(*key))
                self.cited[key] = len(self.citations)
            marks.append(str(self.cited[key]))
        return f" <sup>[{', '.join(marks)}]</sup>" if marks else ""

    def _source_text(self, source_id, page, quality):
        """Title, author and archive, so two registers of the same name can be told apart."""
        source = self.sources.get(source_id, {})
        parts = [source.get("title") or t("source_untitled")]
        parts += [source[key] for key in ("author", "repository") if source.get(key)]
        if page:
            parts.append(page)
        text = ", ".join(parts)
        return f"{text} ({t('quality_' + quality)})" if quality else text

    def name(self, person_id):
        person = self.tree.people.get(person_id)
        if person is None:
            return ""
        number = self.numbers.get(person_id)
        text = _e(person.full_name)
        return f"{text} ({_e(t('report_no', n=number))})" if number else text

    def _place(self, place):
        if place:
            self.places.setdefault(place, set()).add(self.current)
        return place

    def fact_line(self, label, fact, extra=""):
        if not fact:
            return ""
        parts = [part for part in (date_label(fact.get("date", "")) if fact.get("date") else "",
                                   self._place(fact.get("place", "")), fact.get("text", ""), extra) if part]
        people = [f"{_e(t('role_' + p['role']))} {self.name(p['person']) if p.get('person') in self.tree.people else _e(p.get('name', ''))}"
                  for p in fact_details(fact).get("people", [])]
        if not parts and not people and not fact_details(fact).get("citations"):
            return ""
        line = f"<b>{_e(label)}:</b> {_e(', '.join(parts))}{self.cite(fact)}"
        if people:
            line += f"<br>&nbsp;&nbsp;{_e(t('panel_people_present'))}: {'; '.join(people)}"
        return line

    def entry(self, person_id, number, heading_level=3):
        """One person: number, name, years, then every recorded fact as a labelled line."""
        person = self.tree.people[person_id]
        self.current = number
        years = person.years_label()
        title = f"{_e(t('report_no', n=number))} &nbsp; {_e(person.full_name)}" + (f" &nbsp; ({_e(years)})" if years else "")
        lines = [self.fact_line(t("fact_birth"), person.birth),
                 *[self.fact_line(t(f"event_{e['type']}"), e) for e in person_events(person) if e["type"] == "baptism"],
                 self.fact_line(t("fact_death"), person.death),
                 *[self.fact_line(t(f"event_{e['type']}"), e) for e in person_events(person) if e["type"] != "baptism"]]
        for family in self.tree.families_of(person_id):
            partner = next((p for p in family.partners if p != person_id and p in self.tree.people), None)
            marriage = family_marriage(family)
            if partner is not None:
                label = t("fact_marriage") if family.relationship in ("married", "divorced") else t("panel_partners")
                details = self.fact_line(label, marriage)  # "Married: 1975, Split [2]" and witnesses.
                rest = details.partition("</b> ")[2].strip()
                ended = f"; {_e(t('rel_divorced'))}" if family.relationship == "divorced" else ""
                lines.append(f"<b>{_e(label)}:</b> {self.name(partner)}" + (f", {rest}" if rest else "") + ended)
        names = person_names(person)
        if names:
            lines.append(f"<b>{_e(t('field_other_names'))}:</b> " + "; ".join(
                f"{_e((n['given'] + ' ' + n['surname']).strip())} ({_e(t('name_type_' + n['type']))}){self.cite(n)}"
                for n in names))
        body = "<br>".join(line for line in lines if line)
        notes = f"<p style='margin-left:12px'><i>{_e(person.notes).replace(chr(10), '<br>')}</i></p>" \
            if self.with_notes and person.notes else ""
        story = person_story(person)
        if self.with_notes and story:  # A life story reads as paragraphs, as it was written.
            notes += "".join(f"<p>{_e(paragraph).replace(chr(10), '<br>')}</p>"
                             for paragraph in story.split("\n\n") if paragraph.strip())
        return f"<h{heading_level}>{title}</h{heading_level}><p>{body}</p>{notes}"

    def see(self, number, earlier):
        return f"<h3>{_e(t('report_no', n=number))}</h3><p>{_e(t('report_see', n=earlier))}</p>"

    @staticmethod
    def _index_name(person):
        """"Surname, Given" as indexes have it; one part alone without the comma, and
        someone with no name at all as the entry above calls them."""
        if person.surname and person.given:
            return f"{person.surname}, {person.given}"
        return person.surname or person.given or person.display_name

    def endings(self):
        parts = []
        if self.citations:
            items = "".join(f"<li>{_e(text)}</li>" for text in self.citations)
            parts.append(f"<h2>{_e(t('field_sources'))}</h2><ol>{items}</ol>")
        people = sorted(self.numbers, key=lambda p: (collation_key(self.tree.people[p].surname),
                                                     collation_key(self.tree.people[p].given)))
        if people:
            rows = "".join(f"<tr><td>{_e(self._index_name(self.tree.people[p]))}</td>"
                           f"<td>{self.numbers[p]}</td></tr>" for p in people)
            parts.append(f"<h2>{_e(t('report_index_names'))}</h2><table cellpadding='2'>{rows}</table>")
        if self.places:
            rows = "".join(f"<tr><td>{_e(place)}</td><td>{', '.join(str(n) for n in sorted(numbers))}</td></tr>"
                           for place, numbers in sorted(self.places.items(), key=lambda item: collation_key(item[0])))
            parts.append(f"<h2>{_e(t('report_index_places'))}</h2><table cellpadding='2'>{rows}</table>")
        return "".join(parts)


def _parents(tree, person_id):
    """(father, mother) of someone's birth family; with unknown sexes, in the order recorded."""
    family = next((f for f, link in tree.parent_families(person_id) if link == "birth"), None)
    partners = [p for p in (family.partners if family else []) if p in tree.people]
    father = next((p for p in partners if tree.people[p].sex == "M"), None)
    mother = next((p for p in partners if tree.people[p].sex == "F" and p != father), None)
    for p in partners:
        if p not in (father, mother):
            if father is None:
                father = p
            elif mother is None:
                mother = p
    return father, mother


MARK_NAME = "maiores-mark"  # The footer mark, as the PDF and .odt writers know it.


def _page(title, subtitle, body):
    import branding
    made = t("report_made", date=datetime.date.today().strftime("%d.%m.%Y"))
    mark = branding.small_icon_uri()
    logo = f"<img src='{mark}' width='14' height='14' alt=''> " if mark else ""
    import strings
    direction = "rtl" if strings.right_to_left() else "ltr"  # Arabic reads from the right.
    if direction == "rtl":  # The index tables too: from the right edge, first column on the right.
        body = body.replace("<table ", "<table align='right' dir='rtl' ")
    return (f"<html lang='{_e(strings.LANGUAGE)}' dir='{direction}'><head><meta charset='utf-8'>"
            f"<title>{_e(title)}</title></head><body dir='{direction}'>"
            f"<h1>{_e(title)}</h1><p>{_e(subtitle)}</p>{body}<p><small>{logo}{_e(made)}</small></p></body></html>")


def ancestor_book(tree, root_id, generations=6, notes=True, sources=True):
    with tree.looking():
        return _ancestor_book(tree, root_id, generations, notes, sources)


def _ancestor_book(tree, root_id, generations, notes, sources):
    book = _Book(tree, notes, sources)
    order, queue, first_seen = [], [(root_id, 1)], {}
    while queue:
        person_id, number = queue.pop(0)
        if number.bit_length() > generations:
            continue
        order.append((person_id, number))
        if person_id in first_seen:
            continue  # The same ancestor through a second line: listed once.
        first_seen[person_id] = number
        father, mother = _parents(tree, person_id)
        for parent, child_number in ((father, 2 * number), (mother, 2 * number + 1)):
            if parent is not None:
                queue.append((parent, child_number))
    order.sort(key=lambda item: item[1])
    book.numbers = dict(first_seen)
    body, generation = [], 0
    for person_id, number in order:
        if number.bit_length() != generation:
            generation = number.bit_length()
            body.append(f"<h2>{_e(t('report_generation', n=generation))}</h2>")
        if first_seen[person_id] != number:
            body.append(book.see(number, first_seen[person_id]))
        else:
            body.append(book.entry(person_id, number))
    title = t("report_ancestors_title", name=tree.people[root_id].display_name)
    return _page(title, t("report_ancestors_intro"), "".join(body) + book.endings())


def descendant_book(tree, root_id, generations=6, notes=True, sources=True):
    with tree.looking():  # One index for the whole book, not one per person listed.
        return _descendant_book(tree, root_id, generations, notes, sources)


def _descendant_book(tree, root_id, generations, notes, sources):
    book = _Book(tree, notes, sources)
    order, depth = [root_id], {root_id: 1}
    index = 0
    while index < len(order):
        person_id = order[index]
        index += 1
        if depth[person_id] >= generations:
            continue
        for child in _children(tree, person_id):
            if child not in depth:
                depth[child] = depth[person_id] + 1
                order.append(child)
    book.numbers = {person_id: number for number, person_id in enumerate(order, 1)}
    body, generation = [], 0
    for person_id in order:
        if depth[person_id] != generation:
            generation = depth[person_id]
            body.append(f"<h2>{_e(t('report_generation', n=generation))}</h2>")
        body.append(book.entry(person_id, book.numbers[person_id]))
        children = [c for c in _children(tree, person_id) if c in book.numbers]
        if children:
            items = "".join(f"<li>{book.name(c)}</li>" for c in children)
            body.append(f"<p><b>{_e(t('panel_children'))}:</b></p><ul>{items}</ul>")
    title = t("report_descendants_title", name=tree.people[root_id].display_name)
    return _page(title, t("report_descendants_intro"), "".join(body) + book.endings())


def _born(tree, person_id):
    """A sort key in birth order: the parsed date ("about 1870" before "1900"), never the
    stored text, which sorts "abt 1870" after "1900". Undated children come last."""
    parsed = parse_date(tree.people[person_id].birth_date)
    if parsed is None:
        return (1, 0, 0, 0)
    return (0, parsed.year, parsed.month or 0, parsed.day or 0)


def _children(tree, person_id):
    children = []
    for family in tree.families_of(person_id):
        children += [c for c in family.child_ids if c in tree.people and c not in children]
    return sorted(children, key=lambda c: (_born(tree, c), collation_key(tree.people[c].given)))


def family_sheet(tree, person_id, notes=True, sources=True):
    """Someone with each partner and their children: the classic family group sheet."""
    book = _Book(tree, notes, sources)
    number = 1
    body = []
    families = tree.families_of(person_id) or []
    people = [person_id]
    for family in families:
        people += [p for p in family.partners if p != person_id and p in tree.people]
        people += [c for c in family.child_ids if c in tree.people]
    father, mother = _parents(tree, person_id)
    for person in [person_id, *people[1:]]:
        if person not in book.numbers:
            book.numbers[person] = number
            number += 1
    body.append(book.entry(person_id, book.numbers[person_id], 2))
    parents = [book.name(p) or _e(tree.people[p].display_name) for p in (father, mother) if p]
    if parents:
        body.append(f"<p><b>{_e(t('panel_parents'))}:</b> {' &amp; '.join(parents)}</p>")
    for family in families:
        partner = next((p for p in family.partners if p != person_id and p in tree.people), None)
        if partner is not None:
            body.append(book.entry(partner, book.numbers[partner], 2))
        children = [c for c in family.child_ids if c in tree.people]
        if children:
            body.append(f"<h3>{_e(t('panel_children'))}</h3>")
            for child in sorted(children, key=lambda c: (_born(tree, c), collation_key(tree.people[c].given))):
                body.append(book.entry(child, book.numbers[child], 4))
    title = t("report_family_title", name=tree.people[person_id].display_name)
    return _page(title, "", "".join(body) + book.endings())


def write_document(page_html, path):
    """A PDF, or an OpenDocument text (.odt) to keep editing in a word processor."""
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument, QTextDocumentWriter
    import branding
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QImage
    document = QTextDocument()
    mark = branding.small_icon_uri()
    if mark and mark in page_html:  # The writers do not read data: addresses; hand them the picture.
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(MARK_NAME),
                             QImage(str(branding.SMALL_ICON)))
        page_html = page_html.replace(mark, MARK_NAME)
    if " dir='rtl'" in page_html[:400]:
        # Every paragraph right to left, as the page says: the writers take the document's
        # default, not the page's attribute.
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QTextOption
        option = QTextOption()
        option.setTextDirection(Qt.LayoutDirection.RightToLeft)
        document.setDefaultTextOption(option)
    document.setHtml(page_html)
    if " dir='rtl'" in page_html[:400]:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QTextCursor
        cursor = QTextCursor(document)
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = cursor.blockFormat()
        block_format.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        cursor.mergeBlockFormat(block_format)
    path = Path(path)
    from storage import check_written, temp_beside
    temp = temp_beside(path)
    try:
        if path.suffix.lower() == ".odt":
            writer = QTextDocumentWriter(str(temp), b"odf")
            if not writer.write(document):
                raise OSError(writer.device().errorString() if writer.device() else str(path))
            del writer
        else:
            writer = QPdfWriter(str(temp))
            writer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                             QMarginsF(18, 18, 18, 18), QPageLayout.Unit.Millimeter))
            writer.setTitle(document.metaInformation(QTextDocument.MetaInformation.DocumentTitle))
            document.print_(writer)
            del writer  # Closes the file before it is renamed (Windows needs that).
        check_written(temp)  # A full disk leaves a cut-off file and no error.
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return document


def odt_supported():
    from PySide6.QtGui import QTextDocumentWriter
    # Qt names it "ODF" in capitals: compared without case, or ODT is never offered.
    return b"odf" in [bytes(f).lower() for f in QTextDocumentWriter.supportedDocumentFormats()]
