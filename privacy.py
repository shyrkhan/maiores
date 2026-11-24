"""What leaves the computer. Your own view always shows everything; these rules only
apply to copies made for other people: GEDCOM exports, map pins and shared trees.

- Items marked private (a document, someone's notes, a whole person) stay out.
- Living people, if chosen, are reduced to their surname and sex. A person counts as
  living unless the tree says otherwise: when in doubt, hide. Someone with no death
  recorded who could have been born less than LIVING_YEARS ago (the latest date a range
  allows, to the day), or whose birth is unknown or open-ended ("after 1910"), is
  treated as living.
- A hidden person is marked with the "hidden" flag (never with translated words), so
  when a shared copy comes back through combining, they are recognised as hidden.
"""
import re

from edits import copy_tree
from model import (
    as_list, cited_sources, face_links, fact_places, files_of, parse_date, person_documents, place_chain, place_records,
    stored_facts,
)

LIVING_YEARS = 100


def counts_as_living(person, today):
    if person.living == "yes":
        return True
    if person.living == "no" or person.death is not None:
        return False
    born = parse_date(person.birth_date)
    if born is None or born.qualifier in ("aft", "from"):
        return True  # Unknown, or "after 1910": no latest year, so it could be recent.
    # The latest the birth could be: the end of a range ("between 1920 and 1930"), and the
    # day itself, so protection lasts until the 100th birthday, not the start of that year.
    year = born.end_year or born.year
    if born.end is not None:  # Between two exact dates: the later one.
        month, day = born.end.month or 12, born.end.day or 31
    elif born.end_year:
        month, day = 12, 31
    else:
        month, day = born.month or 12, born.day or 31
    age = today.year - year - ((today.month, today.day) < (month, day))
    return age < LIVING_YEARS


def is_hidden(person):
    return bool(person.extra.get("hidden"))


def _hide(person):
    person.given = ""
    person.birth_surname = ""
    person.birth = person.death = None
    person.living = "yes"
    person.photo = ""
    person.notes = ""
    person.extra = {"hidden": True}


_RECORD_TOKEN = re.compile(r"@ft:r:(\d+)@")
_NOTE_POINTER = re.compile(r"^1 S?NOTE @ft:r:\d+@$")


def _keep_pointed_records(shared):
    """Whole records kept from another program's file go only where something shared
    points at them: a note on someone's birth or marriage, say. Loose notes and the
    submitter's name and address are about no one shared, so they stay home. A record
    left at home becomes an empty entry, so the others keep their numbers."""
    records = [r if isinstance(r, list) else [] for r in as_list(shared.extra.get("gedcom_records"))]
    shared.extra.pop("gedcom_records", None)
    if not records:
        return
    from model import kept_line_lists
    holders = kept_line_lists(shared)  # People, families, sources and archives: shapes checked there.
    holders += [[ref.get("note") for ref in as_list(person.extra.get("shared_notes")) if isinstance(ref, dict)]
                for person in shared.people.values()]
    wanted = set()
    waiting = [line for lines in holders for line in as_list(lines) if isinstance(line, str)]
    while waiting:
        for number in _RECORD_TOKEN.findall(waiting.pop()):
            index = int(number) - 1
            if 0 <= index < len(records) and index not in wanted:
                wanted.add(index)
                waiting.extend(line for line in records[index] if isinstance(line, str))
    if wanted:
        shared.extra["gedcom_records"] = [record if n in wanted else [] for n, record in enumerate(records)]


def shareable(tree, today, hide_living=True):
    """A copy of the tree with private items removed and, if chosen, living people hidden."""
    shared = copy_tree(tree)
    hidden = set()
    for person in shared.people.values():
        if person.extra.get("private") or (hide_living and counts_as_living(person, today)):
            _hide(person)
            hidden.add(person.id)
            continue
        if person.extra.get("notes_private"):
            person.notes = ""
            person.extra.pop("note_parts", None)  # The same notes, remembered piece by piece.
            person.extra.pop("shared_notes", None)
            if isinstance(person.extra.get("gedcom"), list):  # And the shared notes they point at.
                person.extra["gedcom"] = [line for line in person.extra["gedcom"]
                                          if not (isinstance(line, str) and _NOTE_POINTER.match(line))]
        person.extra.pop("tasks", None)  # Research to-do is your own working list.
        person.extra.pop("dna", None)  # DNA tests and matches: about living people, never shared.
        if person.extra.pop("story_private", None):
            person.extra.pop("story", None)
        documents = [d for d in person_documents(person) if not d["private"]]
        person.extra.pop("documents", None)
        person.extra.pop("notes_private", None)
        if documents:
            person.extra["documents"] = [{k: v for k, v in d.items() if k != "private"} for d in documents]
    for family in shared.families.values():
        if hidden & set(family.partners):
            family.extra.pop("marriage", None)  # When and where a living couple married.
            family.extra.pop("gedcom", None)  # And what another program's file said about them.
    # A citation may point at a scan; it goes only if that scan is shared too. Sources no
    # longer cited stay home: a title like "Hospital record of Luka" says enough by itself.
    shared_files = {path for person in shared.people.values() for path in files_of(person)}
    for _owner, _kind, fact in stored_facts(shared):
        for citation in as_list(fact.get("citations")):
            if isinstance(citation, dict) and citation.get("document") not in shared_files:
                citation.pop("document", None)
    faces = {}
    for path, items in face_links(shared).items():
        if path in shared_files:  # A face is only shared with its picture,
            # and never names someone hidden: neither the link nor a name typed on the face.
            kept = [{k: v for k, v in item.items() if k not in ("person", "name")} if item.get("person") in hidden
                    else item for item in items]
            faces[path] = kept
    shared.extra.pop("faces", None)
    if faces:
        shared.extra["faces"] = faces
    shared.extra.pop("not_duplicates", None)  # Your own housekeeping; says who is in the tree.
    _keep_pointed_records(shared)
    # Only places a shared fact still names, and the places they lie in: a hidden living
    # person's address must not stay behind as a place record with coordinates.
    records = place_records(shared)
    needed = set()
    for place in fact_places(shared):
        needed.update(place_chain(shared, place, records))
    places = {name: record for name, record in records.items() if name in needed}
    shared.extra.pop("places", None)
    if places:
        shared.extra["places"] = places
    cited = cited_sources(shared)
    raw_sources = shared.extra.get("sources")
    sources = {k: v for k, v in (raw_sources.items() if isinstance(raw_sources, dict) else ()) if k in cited}
    shared.extra.pop("sources", None)
    if sources:
        shared.extra["sources"] = sources
    return shared
