"""Reading and writing GEDCOM 5.5.1, the format genealogy programs exchange.

Everything standard GEDCOM cannot express goes in tags starting with _FT_, which
other programs ignore, so a file we wrote comes back the same. Files from other
programs are read as far as possible: what cannot be used is kept in the person's
notes or counted in the report, and never silently thrown away.

No interface code here. Photos are returned as paths for the caller to import.
"""
import datetime
import glob
import re
import urllib.parse
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from model import (
    DOCUMENT_KINDS, Family, Person, Tree, as_list, fact_details, family_marriage, new_id, parse_date, person_documents, person_events,
    person_names, person_story, place_records, stored_facts, tree_sources,
)

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
MAX_LINE_VALUE = 200
_LINE = re.compile(r"^\s*(\d{1,2})\s+(?:(@[^@]+@)\s+)?([A-Za-z0-9_]+)(?: (.*))?$")
_NAME = re.compile(r"^([^/]*)(?:/([^/]*)/?)?(.*)$")
_ABOUT = ("ABT", "EST", "CAL", "ABOUT", "CIRCA", "CA")
_LIVING_LIMIT_YEARS = 100


class GedcomError(Exception):
    """The file cannot be used at all."""


# Writing.
def _gedcom_single(parsed):
    """[ABT|BEF|AFT] [@#DJULIAN@] [day] [MON] year, a double-dated year as 1708/09."""
    parts = []
    prefix = {"abt": "ABT", "bef": "BEF", "aft": "AFT"}.get(parsed.qualifier)
    if prefix:
        parts.append(prefix)
    if parsed.calendar == "julian":
        parts.append("@#DJULIAN@")
    if parsed.day is not None:
        parts.append(str(parsed.day))
    if parsed.month is not None:
        parts.append(MONTHS[parsed.month - 1])
    parts.append(f"{parsed.year - 1:04d}/{parsed.year % 100:02d}" if parsed.dual else f"{parsed.year:04d}")
    return " ".join(parts)


def date_to_gedcom(stored):
    parsed = parse_date(stored)
    if parsed is None:
        return stored
    if parsed.end_year is not None and parsed.end is not None:
        start = _gedcom_single(replace(parsed, end=None, end_year=None))
        return f"BET {start} AND {_gedcom_single(parsed.end)}"
    if parsed.end_year is not None:
        return f"BET {parsed.year:04d} AND {parsed.end_year:04d}"
    if parsed.qualifier == "from":
        start = _gedcom_single(replace(parsed, qualifier=None, end=None))
        return f"FROM {start} TO {_gedcom_single(parsed.end)}" if parsed.end else f"FROM {start}"
    if parsed.qualifier == "to":
        return f"TO {_gedcom_single(replace(parsed, qualifier=None))}"
    return _gedcom_single(parsed)


def _date_value(stored):
    """A DATE line's value. Our own dates go as written (the @#DJULIAN@ calendar escape must
    keep its single @); text that isn't a date is made safe like any other value."""
    return date_to_gedcom(stored) if parse_date(stored) else _safe_value(stored)


def _safe_value(text):
    """GEDCOM lines must not begin a value with @ unless it is a reference."""
    return text.replace("@", "@@")


def _long_text(level, tag, text, lines):
    """Write text that may contain new lines or be longer than one line allows."""
    first = True
    for part in re.split(r"\r\n|\r|\n", text):
        chunks = [part[i : i + MAX_LINE_VALUE] for i in range(0, len(part), MAX_LINE_VALUE)] or [""]
        for number, chunk in enumerate(chunks):
            value = _safe_value(chunk)
            if first:
                lines.append(f"{level} {tag} {value}" if value else f"{level} {tag}")
                first = False
            elif number == 0:
                lines.append(f"{level + 1} CONT {value}" if value else f"{level + 1} CONT")
            else:
                lines.append(f"{level + 1} CONC {value}")


# Sources: 0 @S1@ SOUR records, cited as 2 SOUR @S1@ / 3 PAGE / 3 QUAY.
QUALITY_TO_QUAY = {"original": "3", "copy": "2", "family": "1"}
QUAY_TO_QUALITY = {"3": "original", "2": "copy", "1": "family", "0": "family"}
# The people at an event. GEDCOM 5.5.1 allows ASSO only on a person's own record, so a
# godfather is written there with the fact named in _FT_FACT; marriage witnesses go under
# MARR, the place GEDCOM 7 gives them. Someone known only by name uses _FT_ROLE + NAME.
ROLE_WORDS = {"godfather": "Godfather", "godmother": "Godmother", "godparent": "Godparent", "witness": "Witness",
              "priest": "Priest", "informant": "Informant", "midwife": "Midwife", "other": "Other"}
NAME_TYPE_WORDS = {"birth": "birth", "married": "married", "nickname": "aka", "latin": "aka", "other": "aka"}


class _Out:
    """What the writer needs to refer to: people's and sources' pointers."""

    def __init__(self, tree, people):
        self.people = people
        self.sources = {sid: f"@S{n}@" for n, sid in enumerate(tree_sources(tree), 1)}
        self.places = place_records(tree)
        self.tree = tree


def _coordinate(value, positive, negative):
    """43.5167 -> N43.5167, the form GEDCOM uses: at least four decimals, and up to six
    when the place was given that exactly (a house, not just the village)."""
    digits = f"{abs(value):.6f}".rstrip("0")
    digits = digits if len(digits.split(".")[1]) >= 4 else f"{abs(value):.4f}"
    return f"{positive if value >= 0 else negative}{digits}"


def _place_lines(place, lines, out):
    lines.append(f"2 PLAC {_safe_value(place)}")
    record = out.places.get(place, {}) if out else {}
    found = (record["lat"], record["lon"]) if "lat" in record else None  # Its own, never borrowed from above.
    if found:
        lines.append("3 MAP")
        lines.append(f"4 LATI {_coordinate(found[0], 'N', 'S')}")
        lines.append(f"4 LONG {_coordinate(found[1], 'E', 'W')}")


def _citations(fact, level, lines, out):
    for citation in fact_details(fact).get("citations", []):
        pointer = out.sources.get(citation["source"]) if out else None
        if pointer is None:
            continue
        lines.append(f"{level} SOUR {pointer}")
        if citation.get("page"):
            _long_text(level + 1, "PAGE", citation["page"], lines)
        if citation.get("quality") in QUALITY_TO_QUAY:
            lines.append(f"{level + 1} QUAY {QUALITY_TO_QUAY[citation['quality']]}")
        if citation.get("document"):
            lines.append(f"{level + 1} _FT_DOC {_safe_value(citation['document'])}")
        if citation.get("text"):
            lines.append(f"{level + 1} DATA")
            _long_text(level + 2, "TEXT", citation["text"], lines)


def _role_lines(entry, level, lines, out, fact_name=None):
    pointer = out.people.get(entry.get("person")) if out and entry.get("person") else None
    if pointer:
        lines.append(f"{level} ASSO {pointer}")
        lines.append(f"{level + 1} RELA {ROLE_WORDS[entry['role']]}")
        lines.append(f"{level + 1} _FT_ROLE {entry['role']}")
    else:
        lines.append(f"{level} _FT_ROLE {entry['role']}")
        lines.append(f"{level + 1} NAME {_safe_value(entry.get('name', ''))}")
    if fact_name:
        lines.append(f"{level + 1} _FT_FACT {fact_name}")


def _event(tag, event, lines, always=False, value="", out=None):
    event = event or {}
    date, place = event.get("date", ""), event.get("place", "")
    if not date and not place and not fact_details(event) and not value:
        if always:
            lines.append(f"1 {tag} Y")
        return
    lines.append(f"1 {tag} {_safe_value(value)}".rstrip())
    _event_details(event, lines, out)


def _event_details(event, lines, out=None, roles_here=False):
    date, place = event.get("date", ""), event.get("place", "")
    if date:
        lines.append(f"2 DATE {_date_value(date)}")
    if place:
        _place_lines(place, lines, out)
    extras = fact_details(event)
    for key, tag in (("age", "AGE"), ("cause", "CAUS"), ("address", "ADDR")):
        if extras.get(key):
            _long_text(2, tag, extras[key], lines)
    _citations(event, 2, lines, out)
    if roles_here:
        for entry in fact_details(event).get("people", []):
            _role_lines(entry, 2, lines, out)


# Life events: the tag each type uses, and whether its details go on the tag line.
EVENT_TAGS = {"occupation": ("OCCU", True), "religion": ("RELI", True), "education": ("EDUC", True),
              "residence": ("RESI", False), "baptism": ("BAPM", False), "burial": ("BURI", False),
              "emigration": ("EMIG", False), "rank": ("TITL", True), "nationality": ("NATI", True),
              "immigration": ("IMMI", False), "naturalisation": ("NATU", False), "census": ("CENS", False),
              "confirmation": ("CONF", False), "first_communion": ("FCOM", False), "ordination": ("ORDN", False),
              "graduation": ("GRAD", False), "retirement": ("RETI", False), "will": ("WILL", False),
              "probate": ("PROB", False), "cremation": ("CREM", False), "adoption": ("ADOP", False),
              "property": ("PROP", True), "description": ("DSCR", True)}
# Tags whose details go on the tag line when written under their own tag (kept as "other").
INLINE_TAGS = {"CAST", "IDNO", "SSN", "NCHI", "NMR", "FACT"}
EVEN_TYPES = {"military": "Military service", "other": "Other"}


def _life_events(person, lines, out=None):
    # Long text goes on CONC/CONT lines: other programs refuse a line over 255 characters.
    for event in person_events(person):
        kind, text = event["type"], event["text"]
        own = event.get("tag")
        placed = event.get("text_on")  # Where the text stood in the file it came from.
        if own and (own in READ_TAGS or own.startswith("_")):
            # The tag it came as (CHR, BARM, IDNO...): written back the same way.
            inline = own in INLINE_TAGS or EVENT_TAGS.get(READ_TAGS.get(own, ""), ("", False))[1]
            inline = placed == "line" if placed in ("line", "note") else inline
            _long_text(1, own, text if inline else "", lines)
            if text and not inline:
                _long_text(2, "NOTE", text, lines)
        elif kind in EVENT_TAGS:
            tag, inline = EVENT_TAGS[kind]
            inline = placed == "line" if placed in ("line", "note") else inline
            _long_text(1, tag, text if inline else "", lines)
            if text and not inline:
                _long_text(2, "NOTE", text, lines)
        else:
            _long_text(1, "EVEN", text if placed != "note" else "", lines)
            lines.append(f"2 TYPE {_safe_value(event.get('label') or EVEN_TYPES.get(kind, 'Other'))}")
            if text and placed == "note":
                _long_text(2, "NOTE", text, lines)
        _event_details(event, lines, out)
        if event.get("ref"):
            lines.append(f"2 _FT_REF {event['ref']}")  # Only to place kept lines; taken out again.


def _name_lines(person, lines):
    given = _safe_value(person.given)
    first_surname = person.birth_surname or person.surname

    written = person.extra.get("name_as_written")
    unchanged = isinstance(written, dict) and isinstance(written.get("value"), str) and \
        (written.get("given"), written.get("surname"), written.get("birth_surname")) == \
        (person.given, person.surname, person.birth_surname)

    def add(surname, kind=None):
        surname = _safe_value(surname)
        if unchanged and kind is None:
            lines.append(f"1 NAME {_safe_value(written['value'])}")
            return  # Its GIVN and SURN, as written, are among the kept lines.
        lines.append(f"1 NAME {given} /{surname}/".strip())
        if kind:
            lines.append(f"2 TYPE {kind}")
        if given:
            lines.append(f"2 GIVN {given}")
        if surname:
            lines.append(f"2 SURN {surname}")

    add(first_surname)
    if person.birth_surname and person.surname and person.surname != person.birth_surname:
        add(person.surname, "married")


def _other_names(person, lines, out):
    for item in person_names(person):
        written = item.get("written")
        if written:
            lines.append(f"1 NAME {_safe_value(written)}")
        else:
            lines.append(f"1 NAME {_safe_value(item['given'])} /{_safe_value(item['surname'])}/".strip())
        lines.append(f"2 TYPE {_safe_value(item.get('label') or NAME_TYPE_WORDS[item['type']])}")
        lines.append(f"2 _FT_TYPE {item['type']}")  # Marks it as another name, never the main one.
        if item["given"] and not written:
            lines.append(f"2 GIVN {_safe_value(item['given'])}")
        if item["surname"] and not written:
            lines.append(f"2 SURN {_safe_value(item['surname'])}")
        if item["date"]:
            lines.append(f"2 DATE {_date_value(item['date'])}")
        _citations(item, 2, lines, out)


def _person_roles(person, lines, out):
    """The people at this person's own facts, on the person's record (see ROLE_WORDS)."""
    facts = [("BIRT", person.birth), ("DEAT", person.death)]
    facts += [(f"EVEN:{n}", event) for n, event in enumerate(person_events(person))]
    for name, fact in facts:
        for entry in fact_details(fact).get("people", []):
            _role_lines(entry, 1, lines, out, name)


def _partner_roles(family, tree):
    """GEDCOM has one HUSB and one WIFE. Use sex where it decides, listed order otherwise."""
    partners = [p for p in family.partners if p in tree.people][:2]
    if len(partners) == 2 and tree.people[partners[0]].sex == "F" and tree.people[partners[1]].sex != "F":
        partners.reverse()
    if len(partners) == 1 and tree.people[partners[0]].sex == "F":
        return [("WIFE", partners[0])]
    return list(zip(("HUSB", "WIFE"), partners))


def _without(notes, text):
    """The notes with one whole paragraph equal to `text` taken out, or None if it isn't there."""
    if not text:
        return None
    if notes == text:
        return ""
    if notes.startswith(text + "\n"):
        return notes[len(text) + 1:]
    if notes.endswith("\n" + text):
        return notes[:-len(text) - 1]
    if "\n" + text + "\n" in notes:
        return notes.replace("\n" + text + "\n", "\n", 1)
    return None


class _Resolver:
    """Turns kept tokens (@ft:p:<id>@) into this file's pointers; None when what they
    pointed at is gone (someone deleted since), so that line is left out."""

    def __init__(self, people, families, out, kept_records):
        self.people, self.families, self.out = people, families, out
        # A record a shared copy left at home is an empty list: pointing at it writes nothing.
        self.kept = {str(n): f"@K{n}@" for n, record in enumerate(kept_records, 1) if record}

    def __call__(self, text):
        missing = False

        def swap(match):
            nonlocal missing
            kind, key = match[1], match[2]
            found = {"p": self.people, "f": self.families, "s": self.out.sources, "r": self.kept}.get(kind, {}).get(key)
            if found is None:
                missing = True
                return ""
            return found
        result = re.sub(r"@ft:([pfsrx]):([^@]+)@", swap, text)
        return None if missing else result


def _with_kept(chunk, kept, resolve, whole=False):
    """A record as written here, with the lines kept from another program's file put back
    in their places (see _leftovers). `whole`: the kept lines are a record of their own."""
    if not isinstance(kept, list) or not kept or not all(isinstance(line, str) for line in kept):
        return chunk
    if whole:
        root = _Node("")
        base = 0
    else:
        parsed, _bad = _parse_lines("\n".join(chunk))
        if len(parsed) != 1:
            return chunk
        root, base = parsed[0], 1
    path = {base - 1: root}
    skip_below = None
    seen_keys = {}
    for line in kept:
        wrapper = line.startswith("~")
        match = re.match(r"^(\d{1,2}) (.*)$", line[1:] if wrapper else line)
        if not match:
            continue
        level = int(match[1])
        if skip_below is not None:
            if level > skip_below:
                continue
            skip_below = None
        parent = path.get(level - 1)
        if parent is None:
            continue
        if wrapper:
            tag, _, number = match[2].partition("#")
            number, _, key = number.partition("=")
            same = [c for c in parent.children if c.tag == tag]
            number = int(number) if number.isdigit() else 1
            node = same[number - 1] if len(same) >= number else None
            if key.startswith(_REF):
                # A life event, found by the reference it carries through every edit; one
                # deleted since takes its details with it, never onto the next event.
                found = [c for c in same if any(g.tag == "_FT_REF" and g.value == key[len(_REF):] for g in c.children)]
                if not found:
                    skip_below = level
                    continue
                node = found[0]
            elif key:
                wanted = resolve(key)
                if wanted is None:
                    skip_below = level  # The family or source it was about is gone: its details too.
                    continue
                found = [c for c in same if " ".join(c.value.split()) == " ".join(wanted.split())]
                taken = seen_keys.setdefault((id(parent), tag, key), 0)
                seen_keys[(id(parent), tag, key)] += 1
                if found:
                    # Two citations of one source (two sources merged since): the one in
                    # its old place if that still fits, else the next of them in turn.
                    node = node if node in found else found[min(taken, len(found) - 1)]
                elif tag != "NAME":  # A citation or family link removed since: its details go with it.
                    skip_below = level
                    continue
            if node is None:
                node = _Node(tag)
                parent.children.append(node)
        else:
            text = resolve(match[2])
            parts = _LINE.match(f"{level} {text}") if text is not None else None
            if parts is None:
                skip_below = level  # What it pointed at is gone: leave it and its details out.
                continue
            node = _Node(parts[3].upper(), parts[4] or "", parts[2])
            if node.tag in _SINGLE_TAGS and any(c.tag == node.tag for c in parent.children):
                skip_below = level  # A quality set here since replaces the one kept from the file.
                continue
            parent.children.append(node)
        path = {k: v for k, v in path.items() if k < level}
        path[level] = node
    out = []
    for node in (root.children if whole else [root]):
        _raw_lines(node, 0, out)
    return out


def write_gedcom(tree, path, photo_path=None, today=None):
    """The file's text. photo_path maps a stored photo to the path to record, or None."""
    today = today or datetime.date.today()
    people = {pid: f"@I{n}@" for n, pid in enumerate(tree.people, 1)}
    families = {
        fid: f"@F{n}@"
        for n, (fid, family) in enumerate(tree.families.items(), 1)
        if any(p in people for p in family.partners + family.child_ids)
    }

    lines = [
        "0 HEAD",
        "1 SOUR Maiores",
        "2 NAME Maiores",
        "1 SUBM @SUBM@",
        "1 GEDC",
        "2 VERS 5.5.1",
        "2 FORM LINEAGE-LINKED",
        "1 CHAR UTF-8",
        f"1 DATE {today.day} {MONTHS[today.month - 1]} {today.year}",
        "0 @SUBM@ SUBM",
        "1 NAME Maiores",
    ]

    out = _Out(tree, people)
    # Each person's own families, in the tree's order: looking through every family for
    # every person took over two minutes on 34,000 people.
    own_families = {}
    for fid, family in tree.families.items():
        if fid in families:
            for member in dict.fromkeys([c["person"] for c in family.children] + list(family.partners)):
                own_families.setdefault(member, []).append((fid, family))
    kept = [lines_ for lines_ in as_list(tree.extra.get("gedcom_records")) if isinstance(lines_, list)]
    resolve = _Resolver(people, families, out, kept)
    for pid, person in tree.people.items():
        start = len(lines)
        lines.append(f"0 {people[pid]} INDI")
        _name_lines(person, lines)
        _other_names(person, lines, out)
        lines.append(f"1 SEX {person.sex if person.sex in ('M', 'F') else 'U'}")
        if person.sex == "X":
            lines.append("1 _FT_SEX X")
        _event("BIRT", person.birth, lines, out=out, value=str((person.birth or {}).get("text") or ""))
        _event("DEAT", person.death, lines, always=person.living == "no", out=out,
               value=str((person.death or {}).get("text") or ""))
        _life_events(person, lines, out)
        _person_roles(person, lines, out)
        if person.living != "no":
            lines.append(f"1 _FT_LIVING {person.living}")
        if person.extra.get("hidden"):
            lines.append("1 _FT_HIDDEN Y")  # Left out of a shared copy; see privacy.py.
        if person.extra.get("private"):
            lines.append("1 RESN confidential")  # The standard mark other programs respect too.
        if person.photo and photo_path is not None:
            recorded = photo_path(person.photo)
            if recorded:
                lines.append("1 OBJE")
                lines.append(f"2 FILE {_safe_value(recorded)}")
                lines.append("3 FORM jpg")
                kept_title = person.extra.get("photo_title")
                if isinstance(kept_title, dict) and kept_title.get("file") == person.photo:  # Only while it is that picture.
                    if kept_title.get("title"):
                        lines.append(f"2 TITL {_safe_value(kept_title['title'])}")
                    if isinstance(kept_title.get("ref"), str) and kept_title["ref"]:
                        lines.append(f"2 _FT_REF {kept_title['ref']}")
        for document in person_documents(person) if photo_path is not None else ():
            recorded = photo_path(document["file"])
            if recorded:
                lines.append("1 OBJE")
                lines.append(f"2 FILE {_safe_value(recorded)}")
                lines.append(f"3 FORM {Path(recorded).suffix.lstrip('.').lower() or 'file'}")
                if document["title"]:
                    lines.append(f"2 TITL {_safe_value(document['title'])}")
                lines.append("2 _FT_DOC Y")  # A document, not the portrait, when read back.
                if document["kind"] != "other":
                    lines.append(f"2 _FT_DOC_KIND {document['kind']}")
                if document["date"]:
                    lines.append(f"2 _FT_DOC_DATE {_safe_value(document['date'])}")
                if document.get("ref"):
                    lines.append(f"2 _FT_REF {document['ref']}")  # Its kept lines find it by this.
        for fid, family in own_families.get(pid, ()):
            for child in family.children:
                if child["person"] == pid:
                    lines.append(f"1 FAMC {families[fid]}")
                    link = child.get("link", "unknown")
                    if link == "unknown":
                        lines.append("2 _FT_LINK unknown")
                    else:
                        pedi = {"birth": "birth", "adopted": "adopted", "foster": "foster"}.get(link, "birth")
                        lines.append(f"2 PEDI {pedi}")
            if pid in family.partners:
                lines.append(f"1 FAMS {families[fid]}")
        notes = person.notes
        for ref in as_list(person.extra.get("shared_notes")):
            # A note shared with others in the file it came from: pointed to again, as long
            # as its text is still there word for word (else it simply stays in the notes).
            if not (isinstance(ref, dict) and isinstance(ref.get("text"), str) and isinstance(ref.get("note"), str)):
                continue
            pointer = resolve(ref["note"])
            rest = _without(notes, ref["text"]) if pointer else None
            if rest is not None:
                notes = rest
                lines.append(f"1 NOTE {pointer}")
        for part in [p for p in as_list(person.extra.get("note_parts")) if isinstance(p, str)]:
            rest = _without(notes, part)  # Each of their separate notes, while still there.
            if rest is not None and part:
                _long_text(1, "NOTE", part, lines)
                notes = rest
        if notes:
            _long_text(1, "NOTE", notes, lines)
        if person_story(person):
            _long_text(1, "_FT_STORY", person_story(person), lines)
        lines[start:] = _with_kept(lines[start:], person.extra.get("gedcom"), resolve)

    for fid, family in tree.families.items():
        if fid not in families:
            continue
        start = len(lines)
        lines.append(f"0 {families[fid]} FAM")
        for role, partner in _partner_roles(family, tree):
            lines.append(f"1 {role} {people[partner]}")
        for child in family.children:
            if child["person"] in people:
                lines.append(f"1 CHIL {people[child['person']]}")
        marriage = family_marriage(family)
        stored = family.extra.get("marriage") if isinstance(family.extra.get("marriage"), dict) else {}
        said = _safe_value(str(stored.get("text") or "")) if isinstance(stored.get("text"), str) else ""
        if family.relationship in ("married", "divorced") or any(marriage.values()) or said:
            if any(marriage.values()) or said:
                lines.append(f"1 MARR {said}".rstrip())
                _event_details(marriage, lines, out, roles_here=True)
            else:
                lines.append("1 MARR Y")
        if family.relationship == "divorced":
            lines.append("1 DIV Y")
        if family.relationship == "partners":
            lines.append("1 _FT_REL partners")
        lines[start:] = _with_kept(lines[start:], family.extra.get("gedcom"), resolve)

    repositories = {}
    stored_sources = tree.extra.get("sources") if isinstance(tree.extra.get("sources"), dict) else {}
    for sid, source in tree_sources(tree).items():
        start = len(lines)
        lines.append(f"0 {out.sources[sid]} SOUR")
        if source["title"]:
            _long_text(1, "TITL", source["title"], lines)
        if source["author"]:
            lines.append(f"1 AUTH {_safe_value(source['author'])}")
        if source["repository"]:
            pointer = repositories.setdefault(source["repository"], f"@R{len(repositories) + 1}@")
            lines.append(f"1 REPO {pointer}")
        if source["note"]:
            _long_text(1, "NOTE", source["note"], lines)
        lines[start:] = _with_kept(lines[start:], (stored_sources.get(sid) or {}).get("gedcom"), resolve)
    kept_repositories = tree.extra.get("gedcom_repositories")
    kept_repositories = kept_repositories if isinstance(kept_repositories, dict) else {}
    for name in kept_repositories:
        if isinstance(name, str) and name:
            repositories.setdefault(name, f"@R{len(repositories) + 1}@")  # Archives no source cites.
    for name, pointer in repositories.items():
        start = len(lines)
        lines.append(f"0 {pointer} REPO")
        lines.append(f"1 NAME {_safe_value(name)}")
        lines[start:] = _with_kept(lines[start:], kept_repositories.get(name), resolve)
    # Whole records kept from another program's file: notes, pictures, the submitter...
    for record in kept:
        lines.extend(_with_kept([], record, resolve, whole=True))

    lines.append("0 TRLR")
    lines = [line for line in lines if not line.startswith("2 _FT_REF ")]
    return "\n".join(lines) + "\n"


# Reading.
@dataclass
class _Node:
    """One line of the file and the lines under it. `used` is set when the importer reads
    it; whatever is never read is kept as written (see _leftovers), so nothing is lost."""
    tag: str
    value: str = ""
    pointer: str | None = None
    children: list = field(default_factory=list)
    used: bool = field(default=False, compare=False, repr=False)
    ref: str = field(default="", compare=False, repr=False)  # A life event's reference.
    fact: dict | None = field(default=None, compare=False, repr=False)  # The life event read from it.

    def first(self, tag):
        node = next((c for c in self.children if c.tag == tag), None)
        if node is not None:
            node.used = True
        return node

    def peek(self, tag):
        """Like first, but only looking: the line is still kept as written."""
        return next((c for c in self.children if c.tag == tag), None)

    def all(self, tag):
        nodes = [c for c in self.children if c.tag == tag]
        for node in nodes:
            node.used = True
        return nodes

    def text_of(self, tag):
        node = self.first(tag)
        return node.full_text() if node else ""

    def full_text(self):
        text = self.value
        for child in self.children:
            if child.tag == "CONT":
                child.used = True
                text += "\n" + child.value
            elif child.tag == "CONC":
                child.used = True
                text += child.value
        return text.replace("@@", "@")


# Keeping what the importer does not read. A record's unread lines are stored as text,
# level 1 being the record's own children. A line starting with "~" is not data but the
# way there: "~1 BIRT#2" means "inside the second BIRT", so an unread "3 TIME 10:30" under
# a read DATE goes back under that DATE when the file is written again.
# A reference: @I12@, no spaces, and not part of an escaped "@@" in text.
_POINTER = re.compile(r"(?<!@)@(?![#@])[^@\s]+@(?!@)")


def _raw_lines(node, level, out):
    pointer = f"{node.pointer} " if node.pointer else ""
    value = f" {node.value}" if node.value else ""
    out.append(f"{level} {pointer}{node.tag}{value}")
    for child in node.children:
        _raw_lines(child, level + 1, out)


_KEYED_TAGS = {"NAME", "FAMC", "FAMS", "SOUR"}
_SINGLE_TAGS = {"QUAY"}
_REF = "ref:"  # A life event's own reference (event["ref"]), written as "2 _FT_REF <ref>".


def _leftovers(node, level=1):
    out, seen = [], {}
    for child in node.children:
        if not child.used:
            _raw_lines(child, level, out)
            continue
        # Counted among the read ones only: those are what this program writes again, in order.
        seen[child.tag] = seen.get(child.tag, 0) + 1
        below = _leftovers(child, level + 1)
        if below:
            # Names and family links may be written in another order than the file had them:
            # the way there also says which one by its value, so the lines find it again.
            key = f"={child.value.strip()}" if child.tag in _KEYED_TAGS and child.value.strip() else ""
            if child.ref:
                key = f"={_REF}{child.ref}"
            out.append(f"~{level} {child.tag}#{seen[child.tag]}{key}")
            out.extend(below)
    return out


def _token_pointers(lines, tokens):
    """File pointers (@I12@) become tokens naming what they point at in the tree
    (@ft:p:<person id>@), so they can be written with the new file's pointers later.
    A pointer to something not kept becomes a token that writes nothing."""
    def swap(match):
        pointer = match[0]
        if pointer == "@VOID@":
            return pointer
        return tokens.get(pointer) or f"@ft:x:{pointer.strip('@')}@"
    return [_POINTER.sub(swap, line) for line in lines]


@dataclass
class ImportResult:
    tree: Tree
    photos: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    documents: dict = field(default_factory=dict)  # person id: [(file path, title, kind or "", date)]


def decode_gedcom(data):
    """GEDCOM files come in many encodings. Returns (text, warning or None)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), None
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace"), None
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        pass
    head = data[:2000].decode("latin-1").upper()
    if "ANSEL" in head:
        return data.decode("latin-1"), "encoding_ansel"
    # Old Croatian programs wrote Windows-1250, which is what "ANSI" means here.
    return data.decode("cp1250", errors="replace"), "encoding_guess"


def _parse_lines(text):
    """Turn lines into a tree of records. Returns (records, number of bad lines)."""
    records = []
    stack = []
    bad = 0
    for raw in re.split(r"\r\n|\r|\n", text):
        if not raw.strip():
            continue
        match = _LINE.match(raw)
        if not match:
            # Some programs break long notes without a CONT, so keep the text.
            if stack and stack[-1][1].tag in ("NOTE", "CONT", "CONC"):
                stack[-1][1].value += " " + raw.strip()
            else:
                bad += 1
            continue
        level = int(match[1])
        node = _Node(match[3].upper(), match[4] or "", match[2])
        while stack and stack[-1][0] >= level:
            stack.pop()
        if level == 0:
            records.append(node)
        elif stack:
            stack[-1][1].children.append(node)
        else:
            bad += 1
            continue
        stack.append((level, node))
    return records, bad


_CALENDAR_ESCAPES = {"@#DJULIAN@": "julian", "JULIAN": "julian", "@#DGREGORIAN@": "", "GREGORIAN": ""}


def _single_from_gedcom(value, qualifier_allowed=True):
    """'ABT @#DJULIAN@ 10 FEB 1708/09' and the like, in stored form, or None."""
    words = value.upper().split()
    qualifier = None
    if qualifier_allowed and words and words[0].rstrip(".") in _ABOUT + ("BEF", "BEFORE", "AFT", "AFTER"):
        first = words.pop(0).rstrip(".")
        qualifier = "abt" if first in _ABOUT else "bef" if first.startswith("BEF") else "aft"
    calendar_name = ""
    if words and words[0] in _CALENDAR_ESCAPES:
        calendar_name = _CALENDAR_ESCAPES[words.pop(0)]
    elif words and words[0].startswith("@#D"):
        return None  # Hebrew, French Republican and other calendars: kept in the notes instead.
    match = re.match(r"^(?:(\d{1,2})\s+)?(?:([A-Z]{3})\s+)?(\d{1,4})(?:/(\d{1,2}))?$", " ".join(words))
    if not match or (match[1] and not match[2]) or (match[2] and match[2] not in MONTHS):
        return None
    year = f"{int(match[3]):04d}"  # Years before 1000 too: the Middle Ages, royal lines.
    if match[4]:
        year = f"{year}/{(int(match[3]) + 1) % 100:02d}"
        if int(match[4]) != (int(match[3]) + 1) % (10 if len(match[4]) == 1 else 100) or int(match[3]) < 1000:
            return None
    stored = year
    if match[2]:
        stored += f"-{MONTHS.index(match[2]) + 1:02d}"
        if match[1]:
            stored += f"-{int(match[1]):02d}"
    if qualifier:
        stored = f"{qualifier} {stored}"
    if calendar_name:
        stored += " julian"
    return stored if parse_date(stored) else None


_EXACT_SIDE = re.compile(r"^[0-9]{4}(?:-[0-9]{2}){0,2}$")


def date_from_gedcom(text, period=False):
    """Returns the stored form, or None if it cannot be understood. With `period` (a
    residence, a job), FROM ... TO ... is kept as a period; elsewhere it becomes a range."""
    value = " ".join(text.replace("@@", "@").strip().upper().split())
    if not value:
        return ""
    match = re.match(r"^FROM\s+(.+?)(?:\s+TO\s+(.+))?$", value) or re.match(r"^()TO\s+(.+)$", value)
    if match and period:
        start = _single_from_gedcom(match[1], False) if match[1] else None
        end = _single_from_gedcom(match[2], False) if match[2] else None
        if (match[1] and start is None) or (match[2] and end is None):
            return None
        stored = f"from {start} to {end}" if start and end else f"from {start}" if start else f"to {end}"
        return stored if parse_date(stored) else None
    match = re.match(r"^(?:BET|FROM)\s+(.+?)\s+(?:AND|TO)\s+(.+)$", value)
    if match:
        start, end = _single_from_gedcom(match[1], False), _single_from_gedcom(match[2], False)
        if start is None or end is None:
            return None
        if re.fullmatch(r"\d{1,2}", match[1]) and re.search(r"[A-Z]{3}", match[2]):
            return None  # "BET 12 AND 19 AUG 1295" means days, not the year 12.
        # Kept exactly ("BET 12 MAY 1880 AND MAY 1880"), or not at all: a range that can't
        # be held as written (an "about" end, the old calendar, the end before the start)
        # goes to the notes and its line back out unchanged, never cut to its years.
        exact = f"{start}/{end}"
        if _EXACT_SIDE.match(start) and _EXACT_SIDE.match(end) and parse_date(exact):
            return exact
        return None
    if value.startswith("FROM ") or value.startswith("TO "):
        return _single_from_gedcom(value.split(" ", 1)[1], False)  # One end of a period, elsewhere.
    return _single_from_gedcom(value)


def _clean_lines(text):
    """Spaces tidied within each line, but the lines kept: a note, a page reference or a
    cause written over two lines in the file stays on two lines."""
    return "\n".join(_clean_name_part(line) for line in text.replace("@@", "@").split("\n")).strip("\n")


def _clean_name_part(text):
    return " ".join(text.replace("@@", "@").split())


def _names(record):
    """Returns (given, current surname, birth surname). Names written as other names
    (_FT_TYPE) are never the main one."""
    nodes = [node for node in record.all("NAME") if not node.text_of("_FT_TYPE")]
    if not nodes:
        return "", "", ""

    def parts(node):
        match = _NAME.match(node.full_text().replace("\n", " "))
        given = _clean_name_part(match[1] or "")
        surname = _clean_name_part(match[2] or "")
        suffix = _clean_name_part(match[3] or "")
        given = _clean_name_part(node.text_of("GIVN")) or given
        surname = _clean_name_part(node.text_of("SURN")) or surname
        if suffix:
            given = f"{given} {suffix}".strip()
        return given, surname

    given, surname = parts(nodes[0])
    # MyHeritage and Family Tree Maker put the married surname inside the name: _MARNM.
    married = _clean_name_part(nodes[0].peek("_MARNM").value if nodes[0].peek("_MARNM") else "")
    if married and married != surname:
        return given, married, surname
    for node in nodes[1:]:
        kind = node.text_of("TYPE").lower()
        if kind == "married":
            married_given, married = parts(node)
            # The married form of this very name ("Mary Ann" married Jones). A married name
            # with other given names ("Mary /Jones/") stays one of their other names, as
            # written: taken as the surname, it would be written back as "Mary Ann /Jones/",
            # a name the file never had.
            same_given = not married_given or _clean_name_part(married_given).casefold() == given.casefold()
            if married and married != surname and same_given:
                return given, married, surname
        if kind in ("birth", "maiden") and nodes[0].text_of("TYPE").lower() == "married":
            _, born = parts(node)  # The married name first, the birth name after it.
            if born and born != surname:
                return given, surname, born
    return given, surname, ""


_DMS = re.compile(r"^([NSEW])?\s*(-?\d+(?:\.\d+)?)(?:[°\s:]+(\d+(?:\.\d+)?)(?:['′\s:]+(\d+(?:\.\d+)?)[\"″]?)?['′]?)?\s*([NSEW])?$")


def _degrees(text):
    """N43.5167, S12.5, 43.5167, -12.5, and the degrees-and-minutes some programs write
    (N47°04', 47°04'30"N) as a number; None when not one."""
    text = text.strip().upper().replace(",", ".")
    match = _DMS.match(text)
    if not text or match is None or (match[1] and match[5]):
        return None
    value = float(match[2])
    minutes, seconds = float(match[3] or 0), float(match[4] or 0)
    if minutes >= 60 or seconds >= 60 or ((match[3] or match[4]) and "." in match[2]):
        return None
    value = abs(value) + minutes / 60 + seconds / 3600 if (match[3] or match[4]) else value
    if match[3] and match[2].startswith("-"):
        value = -value
    return -value if (match[1] or match[5]) in ("S", "W") else value


class _Sources:
    """Source records of the file, made into the tree's sources as they are first cited.
    A source written in place (2 SOUR Parish book) becomes a source with that title."""

    def __init__(self, records, tree):
        self.records = {r.pointer: r for r in records if r.tag == "SOUR" and r.pointer}
        self.repositories = {r.pointer: _clean_name_part(r.text_of("NAME")) for r in records
                             if r.tag == "REPO" and r.pointer}
        self.tree, self.ids, self.titles = tree, {}, {}

    def _add(self, key, source):
        if key not in self.ids:
            self.ids[key] = new_id("s")
            self.tree.extra.setdefault("sources", {})[self.ids[key]] = {k: v for k, v in source.items() if v}
        return self.ids[key]

    def _record(self, pointer):
        record = self.records.get(pointer)
        if record is None:
            return None
        repository = record.first("REPO")
        where = ""
        if repository is not None:
            where = self.repositories.get(repository.value.strip()) or _clean_name_part(repository.text_of("NAME")
                                                                                         or repository.value)
        title = _clean_lines(record.text_of("TITL") or record.value) or pointer.strip("@")
        return self._add(pointer, {"title": title, "author": _clean_name_part(record.text_of("AUTH")),
                                   "repository": where, "note": _written_note(record).strip()})

    def place(self, node):
        """A PLAC line's place, keeping MAP coordinates (N43.5167 / E16.2500) as a place record."""
        name = _clean_name_part(node.text_of("PLAC"))
        plac = node.first("PLAC")
        point = plac.first("MAP") if plac is not None else None
        if name and point is not None:
            lat, lon = _degrees(point.text_of("LATI")), _degrees(point.text_of("LONG"))
            places = self.tree.extra.setdefault("places", {})
            known = places.get(name, {})
            if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
                if "lat" not in known:  # The first coordinates given for a place are its own.
                    places.setdefault(name, {}).update({"lat": lat, "lon": lon})
            else:
                # Coordinates we cannot read: kept as written, so they go back out unchanged.
                for node in (point, point.peek("LATI"), point.peek("LONG")):
                    if node is not None:
                        node.used = False
            if not places:
                self.tree.extra.pop("places")
        return name

    def cite(self, node):
        citations = []
        for source in node.all("SOUR"):
            value = source.value.strip()
            if value.startswith("@") and value.endswith("@"):
                source_id = self._record(value)
            else:
                title = _clean_name_part(source.full_text())
                source_id = self._add(("title", title), {"title": title}) if title else None
            if source_id is None:
                source.used = False  # Points at nothing in the file: kept as written.
                continue
            entry = {"source": source_id}
            if source.text_of("PAGE"):
                entry["page"] = _clean_lines(source.text_of("PAGE"))
            quay = source.peek("QUAY")
            if quay is not None:
                quality = QUAY_TO_QUALITY.get(quay.value.strip())
                if quality and QUALITY_TO_QUAY.get(quality) == quay.value.strip():
                    quay.used = True
                    entry["quality"] = quality
                # Otherwise ("0", "unreliable") the line is kept exactly as written.
            if source.text_of("_FT_DOC"):
                entry["document"] = source.text_of("_FT_DOC").strip()
            data = source.peek("DATA")
            if data is not None and data.peek("TEXT") is not None:
                data.used = True
                entry["text"] = data.text_of("TEXT").strip()
            if entry not in citations:
                citations.append(entry)
            else:
                source.used = False  # The same citation again (another record link): kept as written.
        return citations


def _role(node):
    """The role of an ASSO or _FT_ROLE line: our own word, or guessed from RELA / ROLE."""
    own = node.value.strip() if node.tag == "_FT_ROLE" else node.text_of("_FT_ROLE").strip()
    if own in ROLE_WORDS:
        rela = node.peek("RELA")
        if rela is not None and rela.value.strip() == ROLE_WORDS[own]:
            rela.used = True  # Our own word for it, written again with the role.
        return own
    words = f"{node.text_of('RELA')} {node.text_of('ROLE')}".lower()
    # "Godparent" says neither: it stays a godparent, whatever the person's sex.
    for role, keys in (("godparent", ("godparent", "godp")), ("godmother", ("godmother", "kuma")),
                       ("godfather", ("godfather", "kum", "sponsor")),
                       ("witness", ("witn", "svjedo")), ("priest", ("priest", "clergy", "officiat", "župnik")),
                       ("informant", ("inform",)), ("midwife", ("midwife", "babica"))):
        if any(key in words for key in keys):
            return role
    for tag in ("RELA", "ROLE"):  # "Neighbour" has no role of ours: keep the word as written.
        if node.peek(tag) is not None and node.peek(tag).value.strip() != ROLE_WORDS["other"]:
            node.peek(tag).used = False
    return "other"


def _people_at(node):
    """The people listed under an event (GEDCOM 7 places them there), as role entries with
    file pointers still in "person"; they are turned into ids once everyone is read."""
    found = []
    for child in node.children:
        if child.tag == "ASSO" and child.value.strip().startswith("@"):
            child.used = True
            found.append({"person": child.value.strip(), "role": _role(child)})
        elif child.tag == "_FT_ROLE" and child.text_of("NAME"):
            child.used = True
            found.append({"name": _clean_name_part(child.text_of("NAME")), "role": _role(child)})
    return found


def _details(node, notes, label, sources, period=False):
    raw_date = node.text_of("DATE")
    stored = date_from_gedcom(raw_date, period)
    if stored is None:
        # Not a date we can hold (510 BC, "between the 12th and 19th"): shown in the notes,
        # and the line itself kept as written so it goes back out unchanged.
        notes.append(f"{label}: {raw_date}")
        node.peek("DATE").used = False
        stored = ""
    event = {"date": stored, "place": sources.place(node) if sources is not None else _clean_name_part(node.text_of("PLAC"))}
    citations = sources.cite(node) if sources is not None else []
    if citations:
        event["citations"] = citations
    people = _people_at(node)
    if people:
        event["people"] = people
    for key, tag in (("age", "AGE"), ("cause", "CAUS"), ("address", "ADDR")):
        text = _clean_lines(node.text_of(tag))
        if text:
            event[key] = text
    return event


def _event_from(record, tag, notes, label, sources=None):
    node = record.first(tag)
    if node is None:
        return None
    details = _details(node, notes, label, sources)
    if tag == "BIRT" and not node.value.strip() and not node.children:
        node.used = False  # "1 BIRT" and nothing more: written back as it was.
    if node.value.strip() and node.value.strip().upper() != "Y":
        details["text"] = _clean_name_part(node.full_text())  # Some programs write the place here.
    return details


def _other_names_from(record, sources, main_given, main_surnames):
    """NAME lines beyond the main name (and its married form): other names."""
    found = []
    for number, node in enumerate(record.all("NAME")):
        own_type = node.text_of("_FT_TYPE").strip()
        if not own_type and number == 0:
            continue
        match = _NAME.match(node.full_text().replace("\n", " "))
        given = _clean_name_part(node.text_of("GIVN")) or _clean_name_part(match[1] or "")
        surname = _clean_name_part(node.text_of("SURN")) or _clean_name_part(match[2] or "")
        if not own_type and (given, surname) in {(main_given, s) for s in main_surnames}:
            if number > 0 and node.peek("TYPE") is None:
                node.used = False  # The very same name again: not ours to keep, so kept as written.
            elif node.peek("TYPE") is not None:
                node.peek("TYPE").used = True  # Its "married" is written again with that name.
            continue  # The married or birth form of the main name, already stored.
        if not given and not surname:
            node.used = False
            continue
        word = node.text_of("TYPE").strip()
        kind = own_type if own_type in NAME_TYPE_WORDS else (
            "married" if "married" in word.lower() else "birth" if word.lower() in ("birth", "maiden", "birthname")
            else "other")
        if node.peek("NICK") is not None and not own_type:  # The nickname itself kept as written.
            kind = "nickname"
        entry = {"given": given, "surname": surname, "type": kind}
        if word and word != NAME_TYPE_WORDS[kind]:
            entry["label"] = word  # "MarriedName", "Also known as": written back in the same words.
        as_written = node.full_text().strip()
        if " ".join(as_written.split()) != f"{given} /{surname}/".strip():
            entry["written"] = as_written
            for part in ("GIVN", "SURN"):
                if node.peek(part) is not None:
                    node.peek(part).used = False
        date = date_from_gedcom(node.text_of("DATE"))
        if date:
            entry["date"] = date
        citations = sources.cite(node)
        if citations:
            entry["citations"] = citations
        found.append(entry)
    return found


def _person_roles_from(record, person, events):
    """ASSO and _FT_ROLE lines on a person's own record, put on the fact they name
    (_FT_FACT), or for another program's file on the baptism, else the birth."""
    for node in record.children:
        if node.tag == "ASSO" and node.value.strip().startswith("@"):
            entry = {"person": node.value.strip(), "role": _role(node)}
        elif node.tag == "_FT_ROLE" and node.text_of("NAME"):
            entry = {"name": _clean_name_part(node.text_of("NAME")), "role": _role(node)}
        else:
            continue
        node.used = True
        where = node.text_of("_FT_FACT").strip()
        if where.startswith("EVEN:") and where[5:].isdigit() and int(where[5:]) < len(events):
            fact = events[int(where[5:])]
        elif where == "DEAT" and person.death is not None:
            fact = person.death
        elif not where and any(e["type"] == "baptism" for e in events):
            fact = next(e for e in events if e["type"] == "baptism")
        else:
            if person.birth is None:
                person.birth = {"date": "", "place": ""}
            fact = person.birth
        fact.setdefault("people", []).append(entry)


def _resolve_people(tree, person_ids):
    """File pointers in role entries become person ids; a pointer to nobody is dropped."""
    for _owner, _kind, fact in stored_facts(tree):
        if not isinstance(fact.get("people"), list):
            continue
        kept = []
        for entry in fact["people"]:
            if "person" in entry:
                if entry["person"] not in person_ids:
                    continue
                entry = {**entry, "person": person_ids[entry["person"]]}
            if entry not in kept:
                kept.append(entry)
        if kept:
            fact["people"] = kept
        else:
            fact.pop("people")


READ_TAGS = {"OCCU": "occupation", "RELI": "religion", "EDUC": "education", "RESI": "residence",
             "BAPM": "baptism", "CHR": "baptism", "CHRA": "baptism", "BURI": "burial", "EMIG": "emigration",
             "TITL": "rank", "NATI": "nationality", "IMMI": "immigration", "NATU": "naturalisation",
             "CENS": "census", "CONF": "confirmation", "FCOM": "first_communion", "ORDN": "ordination",
             "GRAD": "graduation", "RETI": "retirement", "WILL": "will", "PROB": "probate",
             "CREM": "cremation", "ADOP": "adoption", "PROP": "property", "DSCR": "description",
             # No type of ours: kept as "other", with their own tag for writing them back.
             "BARM": "other", "BASM": "other", "BLES": "other", "CAST": "other", "IDNO": "other",
             "SSN": "other", "NCHI": "other", "NMR": "other", "FACT": "other"}


def _events_from(record, notes, sources):
    events = []
    for node in record.children:
        if node.tag in READ_TAGS:
            kind = READ_TAGS[node.tag]
        elif node.tag == "EVEN":
            kind = "military" if "milit" in node.text_of("TYPE").lower() else "other"
        else:
            continue
        node.used = True
        details = _details(node, notes, kind.capitalize() + " date as written", sources, period=True)
        if node.tag != "EVEN" and EVENT_TAGS.get(kind, ("EVEN",))[0] != node.tag:
            details["tag"] = node.tag  # CHR rather than BAPM, a bar mitzvah, an ID number...
        if node.tag in ("BARM", "BASM", "BLES", "CAST", "IDNO", "SSN", "NCHI", "NMR", "FACT") \
                and node.peek("TYPE") is not None:
            node.peek("TYPE").used = False  # Written back as it was; the tag says what it is.
        text = node.full_text().strip() or _written_note(node)  # With its CONC/CONT lines.
        if text:
            details["text_on"] = "line" if node.full_text().strip() else "note"
        if node.tag == "EVEN":
            # What kind of event, in the file's own words ("Familie", "Funktion").
            label = _clean_name_part(node.text_of("TYPE"))
            if label and label != EVEN_TYPES.get(kind):
                details["label"] = label
        event = {"type": kind, "date": details["date"]}
        for key, value in (("place", details["place"]), ("text", _clean_lines(text))):
            if value:
                event[key] = value
        event.update({k: details[k] for k in ("citations", "people", "age", "cause", "address", "tag", "label",
                                              "text_on") if k in details})
        node.fact = event  # Given a reference later if lines under it are kept (_keep_the_rest).
        events.append(event)
    return events


def _written_note(node):
    """The first note written out under this line. A pointer to a shared note (NOTE @N2@)
    is not text: it stays unread, so it is kept as written and goes back out pointing at
    the same note, instead of becoming the words "@N2@"."""
    for child in node.children:
        if child.tag == "NOTE" and not _POINTER.fullmatch(child.value.strip()):
            child.used = True
            return child.full_text()
    return ""


def _note_text(record, shared_notes, refs=None):
    """The record's notes as text. `refs` collects (pointer, text) for shared notes, so the
    note can be written as the same shared record again (see _shared_note_lines)."""
    refs = [] if refs is None else refs
    texts = []
    for node in record.all("NOTE"):
        value = node.value.strip()
        if value.startswith("@") and value.endswith("@"):
            shared = shared_notes.get(value)
            if shared is not None:
                shared.used = True
                texts.append(shared.full_text())
                refs.append((value, shared.full_text()))
        else:
            text = node.full_text()
            if text:
                texts.append(text)
    return texts


def _living_status(record, birth, today):
    explicit = record.text_of("_FT_LIVING")
    if explicit in ("yes", "unknown"):
        return explicit
    if record.first("DEAT") is not None:
        return "no"
    parsed = parse_date((birth or {}).get("date", ""))
    if parsed is None or parsed.qualifier == "aft":
        return "unknown"  # "After 1910" could be any time since: never a death asserted.
    # A range counts from its latest year: "between 1910 and 1940" may be 86 today.
    if today.year - (parsed.end_year or parsed.year) > _LIVING_LIMIT_YEARS:
        return "no"
    return "unknown" if parsed.end_year else "yes"


PICTURE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


def _media_file(base_folder, value):
    """The file a FILE line names, if it is inside the GEDCOM's own folder and there.
    GEDCOM 7 writes FILE as a URL, so "my%20photo.jpg" is tried decoded too."""
    if not value or _is_web_link(value):
        return None
    if re.match(r"^[A-Za-z]:/|^file://|^//", value, re.IGNORECASE) or Path(value).is_absolute():
        # Where it was on the other person's computer ("C:/Users/Ana/Pictures/b.jpg"): never
        # read from there, but found by its name beside the GEDCOM, or in a folder there,
        # as the message about missing photos advises.
        name = urllib.parse.unquote(value.rsplit("/", 1)[-1])
        root = base_folder.resolve()
        for candidate in [base_folder / name] + sorted(base_folder.glob(f"*/{glob.escape(name)}")):
            resolved = candidate.resolve()
            if name and resolved.is_relative_to(root) and resolved.is_file():
                return resolved
        return None
    for candidate in dict.fromkeys((value, urllib.parse.unquote(value))):
        resolved = (base_folder / candidate).resolve()
        if resolved.is_relative_to(base_folder.resolve()) and resolved.is_file():
            return resolved
    return None


def _is_web_link(value):
    """A web address or an e-mail address: never a file that could have been beside the GEDCOM."""
    return bool(re.match(r"^(https?|ftp|mailto):", value, re.IGNORECASE)) or (
        "@" in value and "/" not in value and "." in value.split("@")[-1])


def _media_references(record, base_folder, shared_objects):
    """Files the record points to, only those inside the GEDCOM's own folder: the picture
    marked as the main one (_PRIM Y, or the one _PHOTO points to), else the first picture,
    is the portrait; the rest are documents.

    Returns (photo path or None, [(document path, title, kind, date)], files mentioned but
    not found or not inside the folder). A file not copied in keeps its line, so it goes
    back out as it came.
    """
    missing, found = 0, []  # found: (path, title, kind, date, main, a document by choice)
    main_pointer = record.peek("_PHOTO").value.strip() if record.peek("_PHOTO") else ""
    if main_pointer:
        record.peek("_PHOTO").used = True
    for node in record.all("OBJE"):
        source = shared_objects.get(node.value.strip(), node)
        title = source.text_of("TITL")
        document = bool(source.text_of("_FT_DOC"))
        kind, date = source.text_of("_FT_DOC_KIND"), source.text_of("_FT_DOC_DATE")
        main = source.text_of("_PRIM").upper().startswith("Y") or (main_pointer and node.value.strip() == main_pointer)
        if source.peek("FORM") is not None:
            source.first("FORM")  # GEDCOM 5.5's place for it: written again, under FILE.
        if source.peek("_CUTOUT") is not None:
            source.peek("_CUTOUT").used = False  # Kept as written: not ours to say.
        copied = left = 0
        for file_node in source.all("FILE"):
            value = file_node.value.replace("@@", "@").replace("\\", "/").strip()
            if file_node.peek("FORM") is not None:
                file_node.first("FORM")  # Written again with the file.
            resolved = _media_file(base_folder, value)
            if resolved is None:
                file_node.used = False  # Kept as written: a web link, a missing file.
                left += 1
                if value and not _is_web_link(value):
                    missing += 1
                continue
            copied += 1
            if source is node and not node.ref:
                # Lines kept under this picture follow it by this reference, wherever it is
                # written: the portrait goes first, whatever its place in the file was.
                node.ref = uuid.uuid4().hex[:10]
            found.append((resolved, title or file_node.text_of("TITL"), kind if kind in DOCUMENT_KINDS else "",
                          date, main, document, node.ref if source is node else ""))
        if not copied:
            node.used = False  # Nothing copied in: keep the line as it was.
            if source is not node:
                source.used = False
        elif source is not node:
            # A shared record: copied files are ours now; if some of its files were not,
            # the whole record is kept too, so none of them is lost.
            source.used = not left
            node.used = not left
    pictures = [entry for entry in found if entry[0].suffix.lower() in PICTURE_TYPES and not entry[5]]
    portrait = next((entry for entry in pictures if entry[4]), pictures[0] if pictures else None)
    documents = [entry[:4] + (entry[6],) for entry in found if entry is not portrait]
    if portrait is not None and (portrait[1] or portrait[6]) and record.tag == "INDI":
        # "Ana in 1950", and where its kept lines belong: kept with the portrait.
        _portrait_titles[id(record)] = (portrait[1], portrait[6])
    return (portrait[0] if portrait else None), documents, missing


_portrait_titles = {}  # Record -> the portrait's title, while one file is read.


def _fact_media(node, base_folder, shared_objects, documents, owners):
    """The files on a fact or a family, as documents of `owners`. Returns how many named
    files were not found."""
    photo, found, missing = _media_references(node, base_folder, shared_objects)
    found = ([(photo, "", "", "")] if photo else []) + found
    for obje in node.children:
        # A date or note under a picture on an event can't go with the document (it is
        # written with the person, not the event): the picture's lines are kept as written
        # too, so nothing of them is lost.
        if obje.tag == "OBJE" and any(c.tag not in ("FILE", "TITL", "FORM") for c in obje.children):
            obje.used = False
    for owner in owners:
        known = {entry[0] for entry in documents.get(owner, [])}
        documents.setdefault(owner, []).extend(entry for entry in found if entry[0] not in known)
        if not documents[owner]:
            del documents[owner]
    return missing


def _ftm_link(child_node, link):
    """Family Tree Maker and Ancestry say how a child belongs to each parent (_FREL for the
    father, _MREL for the mother): Natural, Adopted, Foster, Step... We keep one link per
    child and family, so an adoption by either parent makes it "adopted", and a step or
    unknown relation makes it "unknown". The lines themselves are kept too, as written."""
    words = {(child_node.peek(tag).value if child_node.peek(tag) else "").strip().lower()
             for tag in ("_FREL", "_MREL")} - {"", "natural", "birth", "biological"}
    if not words:
        return link
    if "adopted" in words:
        return "adopted"
    if "foster" in words:
        return "foster"
    return "unknown"


def _keep_the_rest(records, tree, sources, person_ids, family_ids, note_refs=None):
    """Everything the importer did not read, kept as written (see _leftovers): with each
    person, family, source and repository, and whole records nobody pointed to."""
    head = records[0]
    program = _clean_name_part(head.peek("SOUR").peek("NAME").value if head.peek("SOUR") and
                               head.peek("SOUR").peek("NAME") else (head.peek("SOUR").value if head.peek("SOUR") else ""))
    if program:
        tree.extra["gedcom_from"] = program
    for pointer in sources.records:
        sources._record(pointer)  # Sources nobody cited are sources too.
    for record in records:
        if record.tag == "INDI" and record.pointer in person_ids:
            me = person_ids[record.pointer]
            for node in record.children:
                if node.tag not in ("FAMS", "FAMC"):
                    continue
                family = tree.families.get(family_ids.get(node.value.strip(), ""))
                member = family is not None and (
                    me in family.partners if node.tag == "FAMS" else me in family.child_ids)
                if not member:
                    node.used = False  # A link the family itself does not have: kept as written.
    owners = {}  # Record -> where its leftovers go.
    for record in records:
        if record.tag == "INDI" and record.pointer in person_ids:
            owners[id(record)] = tree.people[person_ids[record.pointer]].extra
        elif record.tag == "FAM" and record.pointer in family_ids:
            owners[id(record)] = tree.families[family_ids[record.pointer]].extra
        elif record.tag == "SOUR" and record.pointer in sources.ids:
            owners[id(record)] = tree.extra["sources"][sources.ids[record.pointer]]
    for record in records:
        if record.tag == "INDI" and id(record) in owners:
            for child in record.children:
                if child.fact is not None and _leftovers(child, 2):
                    # Lines kept under a life event follow it by this reference, not by its
                    # place in the list: deleting the event before must not hand them on.
                    child.ref = child.fact["ref"] = uuid.uuid4().hex[:10]
    kept_lines = {}
    for record in records:
        if id(record) in owners:
            lines = _leftovers(record)
            if lines:
                kept_lines[id(record)] = lines
    repositories = {}
    for record in records:
        if record.tag == "REPO" and record.pointer:
            name = sources.repositories.get(record.pointer)
            lines = _leftovers(record)
            if name:  # Every archive, even one no source points to yet: it is written back too.
                repositories[name] = lines
    # Whole records: what no person, family or source used, and what the kept lines point to.
    pointed = {m[0] for lines in [*kept_lines.values(), *repositories.values()] for line in lines
               for m in _POINTER.finditer(line)}
    pointed |= {pointer for refs in (note_refs or {}).values() for pointer, _text in refs}
    # The header and the submitter say who made the file: written fresh by whoever writes it next.
    whole = [r for r in records[1:] if r.tag not in ("TRLR", "INDI", "SOUR", "REPO", "SUBM", "SUBN")
             and (not r.used or r.pointer in pointed) and not (r.tag == "FAM" and r.pointer in family_ids)]
    tokens = {pointer: f"@ft:p:{pid}@" for pointer, pid in person_ids.items()}
    tokens.update({pointer: f"@ft:f:{fid}@" for pointer, fid in family_ids.items()})
    tokens.update({pointer: f"@ft:s:{sid}@" for pointer, sid in sources.ids.items() if isinstance(pointer, str)})
    tokens.update({r.pointer: f"@ft:r:{n}@" for n, r in enumerate(whole, 1) if r.pointer})
    for record in records:
        if id(record) in kept_lines:
            owners[id(record)]["gedcom"] = _token_pointers(kept_lines[id(record)], tokens)
    for pointer, refs in (note_refs or {}).items():
        if pointer in person_ids:
            tree.people[person_ids[pointer]].extra["shared_notes"] = [
                {"note": tokens[p], "text": text} for p, text in refs if p in tokens]
    if repositories:
        tree.extra["gedcom_repositories"] = {name: _token_pointers(lines, tokens)
                                            for name, lines in repositories.items()}
    if whole:
        found = []
        for record in whole:
            lines = []
            _raw_lines(record, 0, lines)
            found.append(_token_pointers(lines, tokens))
        tree.extra["gedcom_records"] = found


def read_gedcom(path, today=None):
    """Read a GEDCOM file into a new tree."""
    today = today or datetime.date.today()
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise GedcomError(str(error)) from error
    text, encoding_warning = decode_gedcom(data)
    records, bad_lines = _parse_lines(text)
    if not records or records[0].tag != "HEAD":
        raise GedcomError("not_gedcom")
    for number, record in enumerate(records):
        if record.tag in ("INDI", "FAM") and not record.pointer:
            record.pointer = f"@ft-unnamed-{number}@"  # Nobody can point at it, but it is someone.

    warnings = []
    if encoding_warning:
        warnings.append((encoding_warning, 1))
    if bad_lines:
        warnings.append(("bad_lines", bad_lines))

    shared_notes = {r.pointer: r for r in records if r.tag == "NOTE" and r.pointer}
    shared_objects = {r.pointer: r for r in records if r.tag == "OBJE" and r.pointer}
    tree = Tree()
    sources = _Sources(records, tree)
    photos, documents = {}, {}
    person_ids = {}
    note_refs = {}  # Person pointer -> [(shared note pointer, its text)].
    odd_dates = 0
    skipped_photos = 0

    for record in records:
        if record.tag != "INDI" or not record.pointer:
            continue
        given, surname, birth_surname = _names(record)
        notes = []
        birth = _event_from(record, "BIRT", notes, "Birth date as written", sources)
        death = _event_from(record, "DEAT", notes, "Death date as written", sources)
        events = _events_from(record, notes, sources)
        odd_dates += len(notes)
        own_sex, file_sex = record.text_of("_FT_SEX"), record.text_of("SEX")  # Both read: we write both.
        sex = own_sex or file_sex.upper()[:1]
        person = Person(
            new_id("p"),
            given=given,
            surname=surname,
            birth_surname=birth_surname,
            sex=sex if sex in ("M", "F", "X") else "",
            birth=birth,
            living=_living_status(record, birth, today),
        )
        if person.living == "no":
            person.death = death or {"date": "", "place": ""}
        refs = []
        written = _note_text(record, shared_notes, refs)
        if refs:
            note_refs[record.pointer] = refs
        own_notes = [n.full_text() for n in record.children if n.tag == "NOTE" and not n.value.strip().startswith("@")]
        if len(own_notes) > 1:
            person.extra["note_parts"] = own_notes  # Written back as separate notes while unchanged.
        # A file we wrote already carries those date notes: do not add them twice.
        person.notes = "\n".join(written + [n for n in notes if not any(n in w for w in written)])
        _person_roles_from(record, person, events)
        if events:
            person.extra["events"] = events
        names = _other_names_from(record, sources, given, {surname, birth_surname})
        if names:
            person.extra["names"] = names
        story = record.first("_FT_STORY")
        if story is not None and story.full_text().strip():
            person.extra["story"] = story.full_text().strip()
        if record.text_of("_FT_HIDDEN"):
            person.extra["hidden"] = True
        restriction = record.first("RESN")
        if restriction is not None:  # Another program's "confidential" or "privacy" is our private mark.
            words = {w.strip().lower() for w in restriction.value.split(",")}
            if words & {"confidential", "privacy"}:
                person.extra["private"] = True
            if words - {"confidential", "privacy"}:
                restriction.used = False  # "locked" and the like: kept as written.
        main_name = next((n for n in record.children if n.tag == "NAME" and not n.peek("_FT_TYPE")), None)
        if main_name is not None:
            ours = f"{given} /{birth_surname or surname}/".strip()
            if " ".join(main_name.full_text().split()) != ours:
                # "FERDINAND Karl von /Neapel und Sizilien/ II": written back just so, until edited.
                person.extra["name_as_written"] = {"value": main_name.full_text().strip(), "given": given,
                                                   "surname": surname, "birth_surname": birth_surname}
                for part in ("GIVN", "SURN"):  # Their own pieces go back too, not ours.
                    if main_name.peek(part) is not None:
                        main_name.peek(part).used = False
        tree.people[person.id] = person
        person_ids[record.pointer] = person.id
        photo, found_documents, missing = _media_references(record, path.parent, shared_objects)
        if photo:
            photos[person.id] = photo
            title, ref = _portrait_titles.pop(id(record), ("", ""))
            if title or ref:  # Its file is set once copied in.
                person.extra["photo_title"] = {k: v for k, v in (("title", title), ("ref", ref)) if v}
        if found_documents:
            documents[person.id] = found_documents
        skipped_photos += missing  # Each file, even when another of the same person was found.
        # Pictures and scans on one of their facts (a baptism record on the baptism): theirs
        # too, among their documents; a picture there is no portrait.
        for node in record.children:
            if node.tag != "OBJE" and node.peek("OBJE") is not None:
                skipped_photos += _fact_media(node, path.parent, shared_objects, documents, [person.id])
    if odd_dates:
        warnings.append(("odd_dates", odd_dates))

    links, explicit = {}, set()
    for record in records:
        if record.tag != "INDI" or record.pointer not in person_ids:
            continue
        record.all("FAMS")  # Written again from the families themselves.
        for node in record.all("FAMC"):
            if node.first("_FT_LINK"):
                link = "unknown"
            else:
                pedi = node.text_of("PEDI").lower()
                link = pedi if pedi in ("birth", "adopted", "foster") else ("unknown" if pedi else "birth")
                if link == "unknown":
                    # "step", "sealing", 7.0's OTHER with its PHRASE: none of ours, so the
                    # line is kept as written and goes back out as it came.
                    node.peek("PEDI").used = False
            links[(person_ids[record.pointer], node.value.strip())] = link
            if node.peek("PEDI") is not None or node.peek("_FT_LINK") is not None:
                explicit.add((person_ids[record.pointer], node.value.strip()))

    broken = 0
    extra_partners = 0
    family_ids = {}
    for record in records:
        if record.tag != "FAM":
            continue
        family = Family(new_id("f"))
        record.used = True
        for tag in ("HUSB", "WIFE"):
            for node in record.all(tag):
                person = person_ids.get(node.value.strip())
                if person is None:
                    broken += 1
                elif person in family.partners:
                    node.used = False  # Husband and wife the same person: the second line kept.
                elif person not in family.partners:
                    if len(family.partners) == 2:
                        extra_partners += 1
                    else:
                        family.partners.append(person)
        for node in record.all("CHIL"):
            person = person_ids.get(node.value.strip())
            if person is None:
                broken += 1
            elif person in family.partners or person in family.child_ids:
                broken += 1
            else:
                link = links.get((person, record.pointer), "birth")
                if (person, record.pointer) not in explicit:
                    link = _ftm_link(node, link)
                family.children.append({"person": person, "link": link})
        if record.text_of("_FT_REL") == "partners":
            family.relationship = "partners"
        elif record.first("DIV") is not None:
            family.relationship = "divorced"
        elif record.first("MARR") is not None:
            family.relationship = "married"
        marr = record.first("MARR")
        if marr is not None:
            details = _details(marr, [], "Marriage", sources)
            if marr.value.strip() and marr.value.strip().upper() != "Y":
                details["text"] = _clean_name_part(marr.full_text())  # "illegitim", a church...
            marriage = {k: v for k, v in details.items() if v}
            if marriage:
                family.extra["marriage"] = marriage
        if family.partners or family.child_ids:
            tree.families[family.id] = family
            if record.pointer:
                family_ids[record.pointer] = family.id
            # A wedding photo or certificate on the family, or on its marriage: both partners'.
            for node in [record] + [n for n in record.children if n.tag != "OBJE" and n.peek("OBJE") is not None]:
                if node.peek("OBJE") is not None and family.partners:
                    skipped_photos += _fact_media(node, path.parent, shared_objects, documents, family.partners)
        else:
            record.used = False  # Nobody in it is in the file: kept as written, with its details.
    if skipped_photos:
        warnings.append(("photos_skipped", skipped_photos))
    _resolve_people(tree, person_ids)
    _keep_the_rest(records, tree, sources, person_ids, family_ids, note_refs)
    if broken:
        warnings.append(("broken_links", broken))
    if extra_partners:
        warnings.append(("extra_partners", extra_partners))

    return ImportResult(tree, photos, warnings, documents)
