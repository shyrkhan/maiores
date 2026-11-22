"""Every change to the family data. No interface code here.

Each function checks first and only then changes the tree, so a refused edit
leaves everything as it was. Valid input keeps validate(tree) free of problems.
"""
import copy

from model import (
    as_list,
    CHILD_LINKS,
    EVENT_TYPES,
    NAME_TYPES,
    SOURCE_FIELDS,
    person_names,
    RELATIONSHIPS,
    Family,
    Person,
    Tree,
    couples_related_by_descent,
    face_links,
    fact_details,
    fold_text,
    is_period,
    new_id,
    normalize_date_input,
    parse_date,
    place_chain,
    place_records,
    remap_people,
    stored_facts,
    validate,
)
from strings import t

UNDO_LIMIT = 200
PERSON_TEXT_FIELDS = ("given", "surname", "birth_surname", "sex", "notes")


class EditError(ValueError):
    """The edit is not possible. The message is meant for the user."""


def clean_fields(values):
    """Turn form values into stored fields, or raise EditError with the reason."""
    fields = {key: values.get(key, "").strip() for key in PERSON_TEXT_FIELDS}
    fields["notes"] = values.get("notes", "").rstrip()

    birth = normalize_date_input(values.get("birth_date", ""))
    death = normalize_date_input(values.get("death_date", ""))
    if is_period(birth) or is_period(death):
        raise EditError(t("error_period_not_here"))
    if birth is None:
        raise EditError(t("error_birth_date"))
    if death is None:
        raise EditError(t("error_death_date"))

    living = values.get("living", "unknown")
    birth_place = values.get("birth_place", "").strip()
    death_place = values.get("death_place", "").strip()
    has_death = bool(death or death_place)
    if has_death and living == "yes":
        living = "no"
    if living == "yes":
        death_event = None
    elif has_death or living == "no":
        death_event = {"date": death, "place": death_place}
    else:
        death_event = None
    if has_death and living == "unknown":
        living = "no"

    parsed_birth, parsed_death = parse_date(birth), parse_date(death)
    if parsed_birth and parsed_death:
        if (parsed_death.end_year or parsed_death.year) < parsed_birth.year:
            raise EditError(t("error_death_before_birth"))

    fields["birth"] = {"date": birth, "place": birth_place} if birth or birth_place else None
    fields["death"] = death_event
    # Where each date came from (citations of sources) and who else was there
    # (godparents at a baptism, the person who reported a death).
    for key in ("birth", "death"):
        details = fact_details({"citations": values.get(f"{key}_citations"), "people": values.get(f"{key}_people")})
        if details and (key == "birth" or fields["death"] is not None):  # Never a death made up from a citation.
            fields[key] = {**(fields[key] or {"date": "", "place": ""}), **details}
    fields["living"] = living
    return fields


def make_person(values):
    person = Person(new_id("p"), **clean_fields(values))
    _store_events(person, clean_events(values.get("events")))
    _store_list(person, "names", clean_names(values.get("names")))
    _store_flags(person, values)
    return person


def clean_events(events):
    """Life events as entered, in stored form; raises EditError for a date not understood."""
    clean = []
    for event in events or []:
        if event.get("type") not in EVENT_TYPES:
            raise EditError(t("error_bad_choice"))
        date = normalize_date_input(event.get("date", ""))
        if date is None:
            raise EditError(t("error_event_date", what=t(f"event_{event['type']}")))
        entry = {"type": event["type"], "date": date}
        for key in ("place", "text"):
            if event.get(key, "").strip():
                entry[key] = event[key].strip()
        clean.append({**entry, **fact_details(event)})
    return clean


def clean_names(names):
    """Other names as entered; raises EditError for a date not understood."""
    clean = []
    for item in names or []:
        given, surname = item.get("given", "").strip(), item.get("surname", "").strip()
        if not given and not surname:
            continue
        date = normalize_date_input(item.get("date", ""))
        if date is None:
            raise EditError(t("error_event_date", what=t("field_other_names")))
        entry = {"given": given, "surname": surname,
                 "type": item.get("type") if item.get("type") in NAME_TYPES else "other"}
        if date:
            entry["date"] = date
        clean.append({**entry, **fact_details(item)})
    return clean


# What a birth, death or marriage can carry from another program's file, which the
# editing windows do not show: kept through an edit (see FACT_EXTRAS in model.py).
CARRIED = ("age", "address", "cause", "label", "tag", "text", "text_on")


def _carry(old, new):
    if isinstance(old, dict) and isinstance(new, dict):
        new.update({k: old[k] for k in CARRIED if k in old and k not in new})
    return new


def update_person(tree, person_id, values):
    fields = clean_fields(values)
    person = _person(tree, person_id)
    old_birth = person.birth
    if fields.get("birth") is None and isinstance(old_birth, dict) and not old_birth.get("date") \
            and not old_birth.get("place"):
        # A birth recorded without a date or place ("1 BIRT" from another program, or one
        # known only by an address): nothing was cleared, so the record stays.
        fields["birth"] = {"date": "", "place": ""}
    for key in ("birth", "death"):
        _carry(getattr(person, key), fields.get(key))
    for key, value in fields.items():
        setattr(person, key, value)
    if "events" in values:
        _store_events(person, clean_events(values["events"]))
    if "names" in values:
        _store_list(person, "names", _carry_written(person_names(person), clean_names(values["names"])))
    _store_flags(person, values)


def _carry_written(before, after):
    """An other name exactly as another program wrote it ("Elena /Case/ Jr.") stays with
    that name while its parts and type are unchanged; editing the name lets it go."""
    written = {}  # Names alike in every part ("Elena Case Jr." and "Elena Case III") keep their order.
    for name in before:
        written.setdefault((name["given"], name["surname"], name["type"]), []).append(name.get("written", ""))
    for name in after:
        queue = written.get((name["given"], name["surname"], name["type"]))
        if queue:
            kept = queue.pop(0)
            if kept and "written" not in name:
                name["written"] = kept
    return after


def _store_list(person, key, items):
    if items:
        person.extra[key] = items
    else:
        person.extra.pop(key, None)


def _store_flags(person, values):
    """Private marks: kept in extra, and only when set, so older files stay unchanged."""
    for flag in ("private", "notes_private"):
        if flag in values:
            if values[flag]:
                person.extra[flag] = True
            else:
                person.extra.pop(flag, None)


def _store_events(person, events):
    if events:
        person.extra["events"] = events
    else:
        person.extra.pop("events", None)


def set_marriage(tree, family_id, date="", place="", citations=None, people=None):
    """A couple's marriage date and place, its citations and witnesses; all empty clears it."""
    family = tree.families.get(family_id)
    if family is None:
        raise EditError(t("error_bad_choice"))
    stored = normalize_date_input(date)
    if is_period(stored):
        raise EditError(t("error_period_not_here"))
    if stored is None:
        raise EditError(t("error_event_date", what=t("field_marriage")))
    marriage = {k: v for k, v in (("date", stored), ("place", place.strip())) if v}
    marriage.update(fact_details({"citations": citations, "people": people}))
    _carry(family.extra.get("marriage"), marriage)
    if marriage:
        family.extra["marriage"] = marriage
    else:
        family.extra.pop("marriage", None)


def set_dna(tree, changes):
    """{person id: [test]}: each person's DNA tests as the DNA window left them."""
    import dna
    for person_id, tests in changes.items():
        if person_id in tree.people:
            dna.store_tests(tree.people[person_id], [t for t in map(dna.clean_test, tests) if t])


def _person(tree, person_id):
    if person_id not in tree.people:
        raise EditError(t("error_person_missing"))
    return tree.people[person_id]


def _check_link(link):
    if link not in CHILD_LINKS:
        raise EditError(t("error_bad_choice"))


def _new_family(tree, partners, relationship="unknown"):
    family = Family(new_id("f"), list(partners), relationship, [])
    tree.families[family.id] = family
    return family


def add_first_person(tree, person):
    if tree.people:
        raise EditError(t("error_tree_not_empty"))
    tree.people[person.id] = person


def open_single_parent_families(tree, person_id):
    """Families where this person is the only partner, so a slot is free."""
    return [f for f in tree.families_of(person_id) if f.partners == [person_id]]


def add_partner(tree, person_id, partner, relationship="married", family_id=None, new_family=False):
    """Add a partner. A single free slot is filled, so existing children get both parents."""
    _person(tree, person_id)
    if relationship not in RELATIONSHIPS:
        raise EditError(t("error_bad_choice"))
    open_families = open_single_parent_families(tree, person_id)
    target = None
    if family_id is not None:
        target = next((f for f in open_families if f.id == family_id), None)
        if target is None:
            raise EditError(t("error_bad_choice"))
    elif not new_family and open_families:
        if len(open_families) > 1:
            raise EditError(t("error_choose_family"))
        target = open_families[0]

    tree.people[partner.id] = partner
    if target is None:
        _new_family(tree, [person_id, partner.id], relationship)
    else:
        target.partners.append(partner.id)
        target.relationship = relationship


def add_child(tree, person_id, child, link="birth", family_id=None, new_family=False):
    """Add a child to one of this person's families, creating one if needed."""
    _person(tree, person_id)
    _check_link(link)
    families = tree.families_of(person_id)
    if family_id is not None:
        target = next((f for f in families if f.id == family_id), None)
        if target is None:
            raise EditError(t("error_bad_choice"))
    elif new_family or not families:
        target = None
    elif len(families) == 1:
        target = families[0]
    else:
        raise EditError(t("error_choose_family"))

    tree.people[child.id] = child
    if target is None:
        target = _new_family(tree, [person_id])
    target.children.append({"person": child.id, "link": link})


def add_sibling(tree, person_id, sibling, link="birth"):
    _person(tree, person_id)
    _check_link(link)
    family = _main_family(tree, person_id)
    tree.people[sibling.id] = sibling
    if family is None:
        # Parents not known yet: brothers and sisters share a family with no parents in it.
        # Adding a parent later makes them the parent of all of them.
        family = _new_family(tree, [])
        family.children.append({"person": person_id, "link": "birth"})
    family.children.append({"person": sibling.id, "link": link})


EXTRA_LINKS = ("adopted", "foster")  # Parents someone can have besides their birth parents.


def _main_family(tree, person_id):
    """The birth (or unknown-link) parents' family; adoptive and foster ones are extra."""
    for family, link in tree.parent_families(person_id):
        if link not in EXTRA_LINKS:
            return family
    return None


def _extra_family(tree, person_id, link):
    """A family of this kind (adoptive, foster) with room for another parent."""
    for family, kind in tree.parent_families(person_id):
        if kind == link and len(family.partners) < 2:
            return family
    return None


def add_parent(tree, person_id, parent, link="birth"):
    _person(tree, person_id)
    _check_link(link)
    if link in EXTRA_LINKS:
        # Adoptive and foster parents are a family of their own, beside the birth parents.
        family = _extra_family(tree, person_id, link)
        tree.people[parent.id] = parent
        if family is None:
            family = _new_family(tree, [parent.id])
            family.children.append({"person": person_id, "link": link})
        else:
            family.partners.append(parent.id)
        return
    family = _main_family(tree, person_id)
    if family is not None and len(family.partners) >= 2:
        raise EditError(t("error_two_parents", child=_name(tree, person_id), parents=_names(tree, family.partners)))
    tree.people[parent.id] = parent
    if family is None:
        family = _new_family(tree, [parent.id])
        family.children.append({"person": person_id, "link": link})
    else:
        family.partners.append(parent.id)


def can_add_parent(tree, person_id):
    family = _main_family(tree, person_id)
    return family is None or len(family.partners) < 2


def can_add_sibling(tree, person_id):
    return person_id in tree.people  # With or without known parents.


def is_ancestor(tree, ancestor_id, person_id):
    """True if ancestor_id is a parent, grandparent and so on of person_id."""
    parents_of = {}
    for family in tree.families.values():
        for child in family.child_ids:
            parents_of.setdefault(child, []).append(family)
    seen = set()
    stack = [person_id]
    while stack:
        current = stack.pop()
        for family in parents_of.get(current, ()):
            for parent in family.partners:
                if parent == ancestor_id:
                    return True
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
    return False


def _name(tree, person_id):
    return tree.people[person_id].display_name if person_id in tree.people else "?"


def _names(tree, ids):
    return " and ".join(_name(tree, p) for p in ids)


def _refuse_loop(tree, older, younger):
    if older == younger:
        raise EditError(t("error_link_self"))
    if is_ancestor(tree, younger, older):
        raise EditError(t("error_link_loop", child=_name(tree, younger), parent=_name(tree, older)))
    # Nor may someone become the child of their own partner, or of a partner's ancestor.
    for family in tree.families_of(younger):
        for partner in family.partners:
            if partner == younger:
                continue
            if partner == older:
                raise EditError(t("error_link_partner_child", child=_name(tree, younger), parent=_name(tree, older)))
            if is_ancestor(tree, partner, older) or is_ancestor(tree, older, partner):
                raise EditError(t("error_link_makes_couple_related", a=_name(tree, younger), b=_name(tree, partner)))


def _keeps_couples_unrelated(link):
    """Refuse a link that would make an existing couple ancestor and descendant.

    A new parent link can do that through a long chain of families, so the
    link is made and checked as a whole, and undone if it fails.
    """
    def checked(tree, *args, **kwargs):
        before = set(couples_related_by_descent(tree))
        saved = copy_tree(tree)
        link(tree, *args, **kwargs)
        new = set(couples_related_by_descent(tree)) - before
        if new:
            first = sorted(new)[0]
            couple = next(f.partners for f in tree.families.values()
                          if len(f.partners) == 2 and f.partners[0] == first)
            tree.people, tree.families = saved.people, saved.families
            raise EditError(t("error_link_makes_couple_related", a=_name(tree, couple[0]), b=_name(tree, couple[1])))
    checked.__name__, checked.__doc__ = link.__name__, link.__doc__
    return checked


def _refuse_second_parents(tree, child_id, link="birth"):
    if link in EXTRA_LINKS:
        return  # Adoptive and foster parents come in addition to birth parents.
    family = _main_family(tree, child_id)
    if family is not None and family.partners:
        raise EditError(t("error_link_has_parents", child=_name(tree, child_id),
                          parents=_names(tree, family.partners)))


def unlink_from_parents(tree, child_id, family_id=None):
    """Take someone out of one of their parents' families. Nobody is deleted."""
    _person(tree, child_id)
    families = [f for f, _kind in tree.parent_families(child_id)]
    family = next((f for f in families if f.id == family_id), None) if family_id else (
        families[0] if families else None)
    if family is None:
        raise EditError(t("error_sibling_needs_parent", name=_name(tree, child_id)))
    family.children = [c for c in family.children if c["person"] != child_id]
    lone_parent = not family.children and len(family.partners) < 2
    lone_child = not family.partners and len(family.children) < 2
    if lone_parent or lone_child:
        del tree.families[family.id]  # Nobody left for this family to connect.


def unlink_partner(tree, person_id, partner_id):
    """End a recorded partnership. Children stay with person_id; nobody is deleted."""
    family = next((f for f in tree.families_of(person_id) if partner_id in f.partners), None)
    if family is None:
        raise EditError(t("error_bad_choice"))
    family.partners = [p for p in family.partners if p != partner_id]
    if not family.children:
        del tree.families[family.id]
        return
    # The family stays for the children, but the marriage, the kind of relationship and
    # what another program's file said about the couple were theirs: a partner added later
    # must not inherit them. Undo brings them back with the partner.
    family.relationship = "unknown"
    family.extra.pop("marriage", None)
    family.extra.pop("gedcom", None)


def link_partner(tree, person_id, other_id, relationship="married"):
    """Record two people already in the tree as partners."""
    _person(tree, person_id)
    _person(tree, other_id)
    if person_id == other_id:
        raise EditError(t("error_link_self"))
    if relationship not in RELATIONSHIPS:
        raise EditError(t("error_bad_choice"))
    if any(other_id in f.partners for f in tree.families_of(person_id)):
        raise EditError(t("error_already_partner", a=_name(tree, person_id), b=_name(tree, other_id)))
    for older, younger in ((person_id, other_id), (other_id, person_id)):
        if is_ancestor(tree, older, younger):
            raise EditError(t("error_link_parent_partner", a=_name(tree, older), b=_name(tree, younger)))
    own = tree.birth_family_of(person_id)
    if own is not None and own is tree.birth_family_of(other_id):
        raise EditError(t("error_link_sibling_partner", a=_name(tree, person_id), b=_name(tree, other_id)))
    _new_family(tree, [person_id, other_id], relationship)


@_keeps_couples_unrelated
def link_child(tree, parent_id, child_id, link="birth", family_id=None, new_family=False):
    """Record someone already in the tree as a child of this person."""
    _person(tree, parent_id)
    _person(tree, child_id)
    _check_link(link)
    if any(child_id in f.child_ids for f in tree.families_of(parent_id)):
        raise EditError(t("error_already_child", child=_name(tree, child_id), parent=_name(tree, parent_id)))
    own = _main_family(tree, child_id)
    if link not in EXTRA_LINKS and own is not None and not own.partners:
        # Brothers and sisters whose parents were not known: this parent becomes theirs.
        _refuse_loop(tree, parent_id, child_id)
        for sibling in own.child_ids:
            _refuse_loop(tree, parent_id, sibling)
        own.partners.append(parent_id)
        return
    # Existing parents are the simplest reason, so they are reported first.
    _refuse_second_parents(tree, child_id, link)
    _refuse_loop(tree, parent_id, child_id)
    families = tree.families_of(parent_id)
    if family_id is not None:
        target = next((f for f in families if f.id == family_id), None)
        if target is None:
            raise EditError(t("error_bad_choice"))
    elif new_family or not families:
        target = None
    elif len(families) == 1:
        target = families[0]
    else:
        raise EditError(t("error_choose_family"))
    if target is not None:
        # The child also gains this family's other parent.
        for partner in target.partners:
            _refuse_loop(tree, partner, child_id)
    if target is None:
        target = _new_family(tree, [parent_id])
    target.children.append({"person": child_id, "link": link})


@_keeps_couples_unrelated
def link_parent(tree, child_id, parent_id, link="birth"):
    """Record someone already in the tree as a parent of this person."""
    _person(tree, child_id)
    _person(tree, parent_id)
    _check_link(link)
    if any(parent_id in f.partners for f, _kind in tree.parent_families(child_id)):
        raise EditError(t("error_already_parent", child=_name(tree, child_id), parent=_name(tree, parent_id)))
    family = _extra_family(tree, child_id, link) if link in EXTRA_LINKS else _main_family(tree, child_id)
    if link in EXTRA_LINKS and family is None:
        _refuse_loop(tree, parent_id, child_id)
        family = _new_family(tree, [parent_id])
        family.children.append({"person": child_id, "link": link})
        return
    _refuse_loop(tree, parent_id, child_id)
    if family is None:
        family = _new_family(tree, [parent_id])
        family.children.append({"person": child_id, "link": link})
        return
    if len(family.partners) >= 2:
        raise EditError(t("error_two_parents", child=_name(tree, child_id), parents=_names(tree, family.partners)))
    # The new parent also becomes the existing parent's partner, so they must not be related.
    for partner in family.partners:
        for older, younger in ((partner, parent_id), (parent_id, partner)):
            if is_ancestor(tree, older, younger):
                raise EditError(t("error_link_makes_couple_related", a=_name(tree, parent_id), b=_name(tree, partner)))
        own = tree.birth_family_of(partner)
        if own is not None and own is tree.birth_family_of(parent_id):
            raise EditError(t("error_link_sibling_partner", a=_name(tree, parent_id), b=_name(tree, partner)))
    # The new parent becomes the parent of everyone in this family, not just this child.
    for sibling in family.child_ids:
        _refuse_loop(tree, parent_id, sibling)
    family.partners.append(parent_id)


def possible_duplicates(tree, values, exclude=()):
    """People already in the tree who might be the one about to be added."""
    given = fold_text(values.get("given", "").strip())
    surname = fold_text(values.get("surname", "").strip())
    if not given:
        return []
    born = parse_date(normalize_date_input(values.get("birth_date", "")) or "")
    found = []
    for person in tree.people.values():
        if person.id in exclude or fold_text(person.given.strip()) != given:
            continue
        names = {fold_text(person.surname.strip()), fold_text(person.birth_surname.strip())}
        if surname and person.surname and surname not in names:
            continue
        theirs = parse_date(person.birth_date or "")
        if born and theirs and abs(born.year - theirs.year) > 2:
            continue
        found.append(person.id)
    return found


@_keeps_couples_unrelated
def link_sibling(tree, person_id, other_id, link="birth"):
    """Record someone already in the tree as a brother or sister of this person."""
    _person(tree, person_id)
    _person(tree, other_id)
    _check_link(link)
    if person_id == other_id:
        raise EditError(t("error_link_self"))
    family = _main_family(tree, person_id)
    # Already together in any parents' family, birth, adoptive or other, counts as already siblings.
    if any(other_id in f.child_ids for f, _kind in tree.parent_families(person_id)):
        raise EditError(t("error_already_sibling", a=_name(tree, person_id), b=_name(tree, other_id)))
    if family is None:
        theirs = _main_family(tree, other_id)
        if theirs is not None:
            # Only the other one has a family: this person joins it.
            if person_id in theirs.partners:
                raise EditError(t("error_sibling_is_parent", other=_name(tree, person_id),
                                  person=_name(tree, other_id)))
            for parent in theirs.partners:
                _refuse_loop(tree, parent, person_id)
            theirs.children.append({"person": person_id, "link": link})
            return
        family = _new_family(tree, [])  # Neither has parents yet: a family with none.
        family.children.append({"person": person_id, "link": "birth"})
    if other_id in family.partners:
        raise EditError(t("error_sibling_is_parent", other=_name(tree, other_id), person=_name(tree, person_id)))
    _refuse_second_parents(tree, other_id, link)
    theirs = _main_family(tree, other_id)
    if theirs is not None and theirs is not family and not theirs.partners and link not in EXTRA_LINKS:
        # They already stand with brothers and sisters whose parents are not known: the
        # whole group joins, each keeping their own link. Adding just them left them with
        # two birth families (found by the explorer).
        for parent in family.partners:
            for child in theirs.child_ids:
                _refuse_loop(tree, parent, child)
        for child in theirs.children:
            if child["person"] not in family.child_ids and child["person"] not in family.partners:
                family.children.append(dict(child))
        del tree.families[theirs.id]
        return
    for parent in family.partners:
        _refuse_loop(tree, parent, other_id)
    family.children.append({"person": other_id, "link": link})


def describe_change(before, after):
    """A few words for what an edit did, shown as "Undo add Ana Šimić"."""
    added = [after.people[p].display_name for p in after.people if p not in before.people]
    removed = [before.people[p].display_name for p in before.people if p not in after.people]
    if added and not removed:
        return t("change_add", names=", ".join(added))
    if removed and not added:
        if any(p in after.people and before.people[p] != after.people[p] for p in before.people):
            return t("change_merge", names=", ".join(removed))
        return t("change_delete", names=", ".join(removed))
    edited = [after.people[p].display_name for p in after.people
              if p in before.people and before.people[p] != after.people[p]]
    if edited and before.families == after.families:
        return t("change_edit", names=", ".join(edited[:2]) + (" ..." if len(edited) > 2 else ""))
    touched = []
    for family_id in set(before.families) | set(after.families):
        old, new = before.families.get(family_id), after.families.get(family_id)
        if old != new:
            for family in (old, new):
                if family is not None:
                    touched += [p for p in family.partners + family.child_ids if p not in touched]
    names = [after.people[p].display_name for p in touched if p in after.people][:3]
    return t("change_links", names=", ".join(names)) if names else t("change_other")


def _union(first, second):
    """Two lists of dicts as one, without repeats, in order."""
    together = list(as_list(first))
    for item in as_list(second):
        if item not in together:
            together.append(item)
    return together


def _merge_details(keep, remove):
    """Fill gaps in keep from remove. Differing dates and places are kept in the notes;
    a different name becomes one of keep's other names; citations, the people at events,
    life events, other names and documents are combined."""
    if remove.extra.get("hidden"):
        return  # A person a shared copy hid carries no details, only guesses ("living").
    extras = []

    def compare(label, kept, other):
        if other and kept != other:
            extras.append(f"{label}: {other}")

    for field_name in ("given", "surname", "birth_surname", "sex", "photo"):
        if not getattr(keep, field_name):
            setattr(keep, field_name, getattr(remove, field_name))
    names = _union(keep.extra.get("names"), remove.extra.get("names"))
    other_name = {"given": remove.given, "surname": remove.surname, "type": "other"}
    known = [fold_text(f"{n.get('given', '')} {n.get('surname', '')}") for n in names]
    if (remove.given or remove.surname) and fold_text(remove.display_name) != fold_text(keep.display_name) \
            and fold_text(f"{remove.given} {remove.surname}") not in known:  # "Radic" for "Radić" is no news.
        names.append(other_name)
    for name, label in (("birth", t("panel_born")), ("death", t("panel_died"))):
        kept_event, other_event = getattr(keep, name) or {}, getattr(remove, name) or {}
        if not kept_event and not other_event and getattr(keep, name) is None and getattr(remove, name) is None:
            continue
        merged = {"date": kept_event.get("date", ""), "place": kept_event.get("place", "")}
        for part in ("date", "place"):
            kept_value, other_value = kept_event.get(part, ""), other_event.get(part, "")
            if not kept_value and other_value:
                merged[part] = other_value
            else:
                compare(label, kept_value, other_value)
        for key in ("citations", "people"):
            together = _union(kept_event.get(key), other_event.get(key))
            if together:
                merged[key] = together
        for key in CARRIED:  # Cause, age... from another program's file: kept's first.
            if key in kept_event or key in other_event:
                merged[key] = kept_event.get(key, other_event.get(key))
        setattr(keep, name, merged)
    # DNA tests and lines kept from another program's file belong to the one person now.
    tests = [t for t in as_list((keep.extra.get("dna") or {}).get("tests"))] + \
        [t for t in as_list((remove.extra.get("dna") or {}).get("tests"))]
    if tests:
        keep.extra["dna"] = {"tests": tests}
    kept_lines = as_list(keep.extra.get("gedcom")) + as_list(remove.extra.get("gedcom"))
    if kept_lines:
        keep.extra["gedcom"] = kept_lines
    if keep.living == "unknown":
        keep.living = remove.living
    if keep.death is not None or remove.living == "no":
        keep.living = "no"
    if keep.living == "no" and keep.death is None:
        keep.death = {"date": "", "place": ""}
    notes = [keep.notes, remove.notes if remove.notes != keep.notes else ""] + extras
    keep.notes = "\n".join(part for part in notes if part)
    events = _union(keep.extra.get("events"), remove.extra.get("events"))
    tasks = _union(keep.extra.get("tasks"), remove.extra.get("tasks"))
    stories = [s for s in (keep.extra.get("story"), remove.extra.get("story")) if isinstance(s, str) and s.strip()]
    story = "\n\n".join(dict.fromkeys(stories))  # Both written down, once each.
    documents = [dict(d) if isinstance(d, dict) else d for d in as_list(keep.extra.get("documents"))]
    for document in as_list(remove.extra.get("documents")):
        if not isinstance(document, dict):
            continue
        same = next((d for d in documents if isinstance(d, dict) and d.get("file") == document.get("file")), None)
        if same is None:
            documents.append(document)
        elif document.get("private"):
            same["private"] = True  # One of them kept it private: whoever is kept, it stays private.
    # A hidden person from a shared copy says nothing new, and must not hide the one kept.
    keep.extra = {**{k: v for k, v in remove.extra.items() if k != "hidden"}, **keep.extra}
    if story:
        keep.extra["story"] = story
    for key, items in (("events", events), ("documents", documents), ("names", names), ("tasks", tasks)):
        if items:
            keep.extra[key] = items
        else:
            keep.extra.pop(key, None)


def set_sources(tree, sources, merged=None, removed=()):
    """The tree's source records as edited in the Sources window. `merged` maps a source
    that turned out to be the same book to the one kept: its citations move across."""
    merged = merged or {}
    for _owner, _kind, fact in stored_facts(tree):
        if not isinstance(fact.get("citations"), list):
            continue
        moved = []
        for citation in fact["citations"]:
            if not isinstance(citation, dict) or citation.get("source") in removed:
                continue
            citation = {**citation, "source": merged.get(citation.get("source"), citation.get("source"))}
            if citation not in moved:
                moved.append(citation)
        if moved:
            fact["citations"] = moved
        else:
            fact.pop("citations")
    # The window edits only the fields it shows; what else a record holds (a publication
    # or abbreviation from another program's file) stays with it.
    before = tree.extra.get("sources") if isinstance(tree.extra.get("sources"), dict) else {}
    kept = {}
    for key, source in sources.items():
        if key in removed:
            continue
        old = before.get(key) if isinstance(before.get(key), dict) else {}
        record = {f: v for f, v in old.items() if f not in SOURCE_FIELDS}
        record.update({f: v for f, v in source.items() if v})
        kept[key] = record
    if kept:
        tree.extra["sources"] = kept
    else:
        tree.extra.pop("sources", None)


def add_sources(tree, sources):
    """Sources made while editing someone, stored with that person."""
    stored = tree.extra.setdefault("sources", {})
    for source_id, source in sources.items():
        stored[source_id] = {f: v for f, v in source.items() if v}
    if not stored:
        tree.extra.pop("sources", None)


def _store_places(tree, records):
    if records:
        tree.extra["places"] = records
    else:
        tree.extra.pop("places", None)


def set_place(tree, name, record):
    """A place's details. Refused if it would lie inside itself (a loop of places)."""
    name = name.strip()
    if not name:
        raise EditError(t("error_bad_choice"))
    records = place_records(tree)
    record = {k: v for k, v in record.items() if v not in ("", None, [])}
    if record.get("parent") and name in place_chain(tree, record["parent"], {**records, name: record}):
        raise EditError(t("error_place_loop", place=name, parent=record["parent"]))
    records[name] = record
    tree.extra["places"] = records
    _store_places(tree, place_records(tree))


def rename_place(tree, old, new):
    """Call a place something else everywhere: in every fact, as every other place's
    parent, and as the record itself. Renaming onto an existing place merges the two:
    the one renamed onto keeps its details, the other fills its gaps."""
    new = new.strip()
    if not new or new == old:
        return
    for _owner, _kind, fact in stored_facts(tree):
        if fact.get("place") == old:
            fact["place"] = new
    records = place_records(tree)
    moved = records.pop(old, None)
    if moved is not None:
        target = records.get(new, {})
        merged = {**moved, **target}
        merged["old_names"] = _union(target.get("old_names"), moved.get("old_names"))
        if not merged["old_names"]:
            merged.pop("old_names")
        records[new] = merged
    for record in records.values():
        if record.get("parent") == old:
            record["parent"] = new
    if records.get(new, {}).get("parent") == new:
        records[new].pop("parent")
    _store_places(tree, records)


def remove_place(tree, name):
    """Forget a place's details. Facts keep the place text; places inside it lose their parent."""
    records = place_records(tree)
    records.pop(name, None)
    for record in records.values():
        if record.get("parent") == name:
            record.pop("parent")
    _store_places(tree, records)


def set_tasks(tree, person_id, tasks):
    person = _person(tree, person_id)
    cleaned = [{"text": item["text"].strip(), "done": bool(item.get("done")),
                **({"note": item["note"].strip()} if item.get("note", "").strip() else {})}
               for item in tasks if item.get("text", "").strip()]
    _store_list(person, "tasks", cleaned)


def set_story(tree, person_id, story, private=False):
    person = _person(tree, person_id)
    if story.strip():
        person.extra["story"] = story.rstrip()
    else:
        person.extra.pop("story", None)
    if private and story.strip():
        person.extra["story_private"] = True
    else:
        person.extra.pop("story_private", None)


def set_faces(tree, stored, faces):
    """The faces marked in one picture (see model.face_links)."""
    tree.extra.setdefault("faces", {})[stored] = faces
    cleaned = face_links(tree)
    tree.extra.pop("faces", None)
    if cleaned:
        tree.extra["faces"] = cleaned


def mark_not_duplicate(tree, a, b):
    """Two people the duplicate finder suggested, confirmed to be different."""
    _person(tree, a)
    _person(tree, b)
    pairs = [list(p) for p in as_list(tree.extra.get("not_duplicates")) if isinstance(p, list)]
    if sorted([a, b]) not in [sorted(p) for p in pairs]:
        pairs.append(sorted([a, b]))
    tree.extra["not_duplicates"] = pairs


def replace_person_references(tree, old_id, new_id=None, name=""):
    """Point every reference to someone (people at events, faces, not-duplicate marks) at
    someone else (a merge), or, with no new_id, keep only their written name (a delete)."""
    remap_people(tree, {old_id: new_id}, {old_id: name})


def _combine_same_couples(tree):
    """After a merge, two families can have the same two partners. Make them one."""
    seen = {}
    for family_id, family in list(tree.families.items()):
        if len(family.partners) != 2:
            continue
        key = frozenset(family.partners)
        if key not in seen:
            seen[key] = family
            continue
        first = seen[key]
        first.children.extend(family.children)
        if first.relationship == "unknown":
            first.relationship = family.relationship
        _combine_family_details(first, family)
        del tree.families[family_id]


def _combine_family_details(first, second):
    """What the second record of a couple knew comes along: its marriage fills what the
    first doesn't say (citations and witnesses of both are kept), and its other lines from
    another program's file are kept too."""
    theirs = second.extra.get("marriage")
    if isinstance(theirs, dict):
        mine = first.extra.get("marriage") if isinstance(first.extra.get("marriage"), dict) else {}
        merged = {**theirs, **{k: v for k, v in mine.items() if v not in ("", None, [])}}
        for key in ("citations", "people"):
            items = list(as_list(mine.get(key))) + [i for i in as_list(theirs.get(key)) if i not in as_list(mine.get(key))]
            if items:
                merged[key] = items
        first.extra["marriage"] = merged
    for key, value in second.extra.items():
        if key == "marriage":
            continue
        if key not in first.extra:
            first.extra[key] = value
        elif isinstance(first.extra[key], list) and isinstance(value, list):
            first.extra[key] = first.extra[key] + [v for v in value if v not in first.extra[key]]


def _fold_partial_families(tree):
    """A child recorded with one parent in one family and with both parents in another
    (one tree knew only the father) is in the second family only. Other children of the
    one-parent family stay where they are: their other parent is still unknown."""
    changed = True
    while changed:
        changed = False
        for child_id in {c["person"] for f in tree.families.values() for c in f.children}:
            entries = [(f, c.get("link", "birth")) for f in tree.families.values()
                       for c in f.children if c["person"] == child_id]
            for small, link in entries:
                twin = next((f for f, other_link in entries if f is not small and other_link == link
                             and len(small.partners) < 2 and set(small.partners) == set(f.partners)), None)
                if twin is not None:  # The same one parent (or no parent) twice: one family.
                    order = list(tree.families)
                    keep, drop = (twin, small) if order.index(twin.id) < order.index(small.id) else (small, twin)
                    keep.children = _unique_children(keep.children + drop.children)
                    keep.extra = {**drop.extra, **keep.extra}  # The first (yours) wins; gaps filled.
                    del tree.families[drop.id]
                    changed = True
                    break
                bigger = next((f for f, other_link in entries if f is not small and other_link == link
                               and set(small.partners) <= set(f.partners)
                               and len(small.partners) < len(f.partners)), None)
                if bigger is None:
                    continue
                small.children = [c for c in small.children if c["person"] != child_id]
                keeps_parent_link = bool(small.partners and small.children)
                if not (keeps_parent_link or len(small.partners) == 2 or len(small.children) >= 2):
                    del tree.families[small.id]
                changed = True
                break
            if changed:
                break


def _unique_children(children):
    """One entry per child, preferring a birth link if the two entries differ."""
    best = {}
    for child in children:
        current = best.get(child["person"])
        if current is None or (current.get("link") != "birth" and child.get("link") == "birth"):
            best[child["person"]] = child
    return list(best.values())


def merge_people(tree, keep_id, remove_id):
    """Treat two records as one person. Refused if it would make the data contradict itself."""
    keep = _person(tree, keep_id)
    _person(tree, remove_id)
    if keep_id == remove_id:
        raise EditError(t("error_link_self"))
    if any(remove_id in f.partners for f in tree.families_of(keep_id)):
        raise EditError(t("error_merge_partners"))
    if is_ancestor(tree, keep_id, remove_id) or is_ancestor(tree, remove_id, keep_id):
        raise EditError(t("error_merge_ancestor"))

    trial = copy_tree(tree)
    _merge_details(trial.people[keep_id], trial.people[remove_id])
    del trial.people[remove_id]
    replace_person_references(trial, remove_id, keep_id)
    for family in trial.families.values():
        family.partners = [keep_id if p == remove_id else p for p in family.partners]
        family.children = [
            {**c, "person": keep_id} if c["person"] == remove_id else c for c in family.children
        ]
    _combine_same_couples(trial)
    for family in trial.families.values():
        family.children = _unique_children(family.children)
    _fold_partial_families(trial)

    before = {(issue.code, issue.detail) for issue in validate(tree)}
    new_problems = [i for i in validate(trial) if (i.code, i.detail) not in before]
    if any(i.code == "two_birth_families" for i in new_problems):
        raise EditError(t("error_merge_two_families"))
    if new_problems:
        raise EditError(t("error_merge_conflict", problem=new_problems[0].message()))
    tree.people = trial.people
    tree.families = trial.families
    tree.extra = trial.extra  # Faces and not-duplicate marks were re-pointed there too.
    return keep


def set_relationship(tree, family_id, relationship):
    if family_id not in tree.families or relationship not in RELATIONSHIPS:
        raise EditError(t("error_bad_choice"))
    tree.families[family_id].relationship = relationship


def set_child_link(tree, person_id, link):
    _check_link(link)
    family = tree.birth_family_of(person_id)
    if family is None:
        raise EditError(t("error_bad_choice"))
    for child in family.children:
        if child["person"] == person_id:
            child["link"] = link


def make_head(tree, person_id, partner_id):
    """List person_id first in their family with partner_id, so they head the view."""
    _person(tree, person_id)
    for family in tree.families_of(person_id):
        if partner_id in family.partners:
            family.partners.remove(person_id)
            family.partners.insert(0, person_id)


def delete_person(tree, person_id):
    """Remove someone, and any family that no longer connects anybody."""
    name = _person(tree, person_id).display_name
    del tree.people[person_id]
    replace_person_references(tree, person_id, name=name)  # A godparent stays, as a written name.
    for family_id, family in list(tree.families.items()):
        family.partners = [p for p in family.partners if p != person_id]
        family.children = [c for c in family.children if c["person"] != person_id]
        connected = len(family.partners) + len(family.children)
        keeps_parent_link = bool(family.partners and family.children)
        keeps_couple = len(family.partners) == 2
        keeps_siblings = len(family.children) >= 2
        if connected == 0 or not (keeps_parent_link or keeps_couple or keeps_siblings):
            del tree.families[family_id]


def copy_tree(tree):
    return Tree.from_dict(copy.deepcopy(tree.to_dict()))


def _pack(tree):
    """A whole tree as compressed bytes: family data shrinks many times over."""
    import json
    import zlib
    return zlib.compress(json.dumps(tree.to_dict(), ensure_ascii=False).encode("utf-8"), 6)


def _unpack(data):
    import json
    import zlib
    return Tree.from_dict(json.loads(zlib.decompress(data).decode("utf-8")))


class _Stack(list):
    """Holds packed snapshots but hands out trees, so callers never see the packing."""

    def append(self, tree):
        super().append(_pack(tree))

    def pop(self, index=-1):
        return _unpack(super().pop(index))

    def __getitem__(self, index):
        item = super().__getitem__(index)
        return [_unpack(x) for x in item] if isinstance(index, slice) else _unpack(item)

    def __iter__(self):
        return (_unpack(x) for x in super().__iter__())


class History:
    """Undo and redo by whole snapshots, which cannot drift out of step with the data.

    Snapshots are kept compressed: a 6,000-person tree is about a megabyte as
    objects, and 200 undo steps of that would otherwise fill memory.
    """

    def __init__(self, limit=UNDO_LIMIT):
        self.limit = limit
        self.undo_stack = _Stack()
        self.redo_stack = _Stack()
        self.undo_labels = []  # What each step did, in step with the stacks.
        self.redo_labels = []

    def push(self, snapshot, label=""):
        self.undo_stack.append(snapshot)
        self.undo_labels.append(label)
        del self.undo_stack[: -self.limit]
        del self.undo_labels[: -self.limit]
        self.redo_stack.clear()
        self.redo_labels.clear()

    def next_undo(self):
        return self.undo_labels[-1] if self.undo_labels else ""

    def next_redo(self):
        return self.redo_labels[-1] if self.redo_labels else ""

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo(self, current):
        previous = self.undo_stack.pop()
        self.redo_stack.append(current)
        self.redo_labels.append(self.undo_labels.pop() if self.undo_labels else "")
        return previous

    def redo(self, current):
        following = self.redo_stack.pop()
        self.undo_stack.append(current)
        self.undo_labels.append(self.redo_labels.pop() if self.redo_labels else "")
        return following

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.undo_labels.clear()
        self.redo_labels.clear()
