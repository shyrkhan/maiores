"""What leaves the computer. Your own view always shows everything; these rules only
apply to copies made for other people: GEDCOM exports, map pins and shared trees.

- Items marked private (a document, someone's notes, a whole person) stay out.
- Living people, if chosen, are reduced to their surname and sex. A person counts as
  living unless the tree says otherwise: when in doubt, hide. Someone with no death
  recorded who was born less than LIVING_YEARS ago, or whose birth is unknown, is
  treated as living.
- A hidden person is marked with the "hidden" flag (never with translated words), so
  when a shared copy comes back through combining, they are recognised as hidden.
"""
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
    return born is None or today.year - born.year < LIVING_YEARS


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
            kept = [{k: v for k, v in item.items() if not (k == "person" and v in hidden)} for item in items]
            faces[path] = kept  # and never names someone hidden.
    shared.extra.pop("faces", None)
    if faces:
        shared.extra["faces"] = faces
    shared.extra.pop("not_duplicates", None)  # Your own housekeeping; says who is in the tree.
    # Whole records kept from another program's file: loose notes, and the submitter's name
    # and address. Not about anyone shared in particular, so they stay home.
    shared.extra.pop("gedcom_records", None)
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
    sources = {k: v for k, v in (shared.extra.get("sources") or {}).items() if k in cited}
    shared.extra.pop("sources", None)
    if sources:
        shared.extra["sources"] = sources
    return shared
