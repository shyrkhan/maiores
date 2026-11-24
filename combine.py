"""Combining a relative's tree with yours. No interface code here.

1. suggest_matches: which of their people are already in your tree. Names and dates
   give a first guess; then the family around each person decides, because two
   people called Ivan Radić with no dates are told apart by who their parents,
   partners and children are.
2. differences: what the two records of one person say differently.
3. combine: their people go in as new records, then each matched pair is merged
   with edits.merge_people, oldest generation first. That way every rule a merge
   already follows (no loops, no person with two sets of birth parents, couples
   not related) holds here too, and a refusal names the pair that caused it.
"""
import json
from dataclasses import dataclass, field

import edits
from model import (
    Family, Person, clean_citations, face_links, files_of, fold_text, new_id, not_duplicates, parse_date,
    fact_places, person_documents, person_names, place_records, remap_people, stored_facts, tree_sources,
)
from strings import t

SURE, LIKELY, POSSIBLE = "sure", "likely", "possible"
ACCEPT_FROM = 3.0  # Suggestions scoring at least this are ticked; weaker ones start as "add as new".


class CombineError(Exception):
    """A matched pair can't be joined. `theirs` and `mine` name the two people."""

    def __init__(self, theirs, mine, message):
        super().__init__(message)
        self.theirs, self.mine = theirs, mine


@dataclass
class Suggestion:
    theirs: str
    mine: str | None
    score: float = 0.0
    alternatives: list = field(default_factory=list)  # Other people of yours worth offering, best first.
    accepted: bool = False  # Strong and clear enough to be ticked; otherwise only offered.

    @property
    def confidence(self):
        if self.mine is None:
            return ""
        if not self.accepted:
            return POSSIBLE
        return SURE if self.score >= 5 else LIKELY


def _year(event):
    parsed = parse_date((event or {}).get("date", ""))
    return parsed.year if parsed else None


def _first_name(person):
    return fold_text(person.given.strip()).split(" ")[0] if person.given.strip() else ""


def _first_names(person):
    """The main first name and those of other names ("Joannes" for Ivan)."""
    names = {_first_name(person)} | {fold_text(n["given"]).split(" ")[0] for n in person_names(person) if n["given"]}
    return {name for name in names if name}


def _surnames(person):
    names = [person.surname, person.birth_surname] + [n["surname"] for n in person_names(person)]
    return {fold_text(name.strip()) for name in names if name.strip()}


def person_score(a, b):
    """How alike two records look on their own, or None when they can't be the same person.
    `b` may be someone a shared copy hid: only surname and sex are left, so the family decides."""
    if b.extra.get("hidden"):
        if (a.sex and b.sex and a.sex != b.sex) or (b.surname and _surnames(a) and not _surnames(a) & _surnames(b)):
            return None
        return 1.0 if _surnames(a) & _surnames(b) else 0.5
    if not _first_names(a) & _first_names(b):
        return None
    if a.sex and b.sex and a.sex != b.sex:
        return None
    mine_names, their_names = _surnames(a), _surnames(b)
    # A different surname doesn't rule anyone out: married names change, and one tree
    # may know only the birth surname. It just counts for less; the family decides.
    differ = bool(mine_names and their_names and not mine_names & their_names)
    score = 1.0 + (1.0 if mine_names & their_names else -0.5 if differ else 0.0)
    if fold_text(a.given.strip()) == fold_text(b.given.strip()) and " " in a.given.strip():
        score += 0.5  # Both middle names agree.
    for event, exact, close in (("birth", 3.0, 1.5), ("death", 2.0, 1.0)):
        first, second = _year(getattr(a, event)), _year(getattr(b, event))
        if first and second:
            if abs(first - second) > 2:
                return None
            score += exact if first == second else close
    if (a.living == "yes" and (b.death or b.living == "no")) or (b.living == "yes" and (a.death or a.living == "no")):
        return None
    return score


def _relatives(tree, person_id):
    """{role: [ids]} for parents, partners and children."""
    parents = [p for f, link in tree.parent_families(person_id) if link == "birth" for p in f.partners]
    partners, children = [], []
    for family in tree.families_of(person_id):
        partners += [p for p in family.partners if p != person_id]
        children += family.child_ids
    return {"parent": parents, "partner": partners, "child": children}


def _clear(totals, their_id, my_id, score, assigned, taken):
    """A match is only made by itself when nothing else open comes close: two hidden
    brothers who look the same are left for you to choose, not guessed."""
    rivals = [s for m, s in totals[their_id].items() if m != my_id and m not in taken]
    rivals += [options[my_id] for t, options in totals.items()
               if t != their_id and t not in assigned and my_id in options]
    return all(score - rival >= 1.0 for rival in rivals)


def suggest_matches(mine, theirs):
    """For each of their people, the best person of yours and how sure that is."""
    candidates = {}
    for their_id, their_person in theirs.people.items():
        for my_id, my_person in mine.people.items():
            score = person_score(my_person, their_person)
            if score is not None:
                candidates.setdefault(their_id, {})[my_id] = score
    with theirs.looking(), mine.looking():  # One index each, not one per person (18 s on 5,000).
        their_relatives = {p: _relatives(theirs, p) for p in theirs.people}
        my_relatives = {p: _relatives(mine, p) for p in mine.people}

    def family_bonus(their_id, my_id, assigned):
        """Relatives of theirs that look like (or were matched to) relatives of mine in the same role."""
        bonus = 0.0
        for role, their_list in their_relatives[their_id].items():
            mine_list = set(my_relatives[my_id][role])
            for relative in their_list:
                if assigned.get(relative) in mine_list:
                    bonus += 2.0
                elif mine_list & set(candidates.get(relative, {})):
                    bonus += 1.0
        return min(bonus, 6.0)

    assigned = {}
    totals = {}
    for _round in range(3):  # Matches found in one round strengthen their relatives' in the next.
        totals = {their_id: {my_id: base + family_bonus(their_id, my_id, assigned)
                             for my_id, base in options.items()}
                  for their_id, options in candidates.items()}
        pairs = sorted(((score, their_id, my_id) for their_id, options in totals.items()
                        for my_id, score in options.items()), reverse=True)
        assigned, taken = {}, set()
        for score, their_id, my_id in pairs:  # One of theirs to one of yours, best first.
            if their_id not in assigned and my_id not in taken and score >= ACCEPT_FROM \
                    and _clear(totals, their_id, my_id, score, assigned, taken):
                assigned[their_id] = my_id
                taken.add(my_id)

    suggestions, offered = [], set(assigned.values())
    for their_id in theirs.people:
        options = sorted(totals.get(their_id, {}).items(), key=lambda item: -item[1])
        best = assigned.get(their_id)
        if best is None:  # A weaker suggestion, still never someone already offered to another.
            best = next((m for m, _s in options if m not in offered), None)
            offered.add(best)
        score = totals.get(their_id, {}).get(best, 0.0) if best else 0.0
        suggestions.append(Suggestion(their_id, best, score, [m for m, _s in options if m != best],
                                      accepted=assigned.get(their_id) is not None))
    return suggestions


FIELDS = (  # (key, label key); the key reads and writes one detail of a Person.
    ("given", "field_given"), ("surname", "field_surname"), ("birth_surname", "field_birth_surname"),
    ("sex", "field_sex"), ("birth.date", "panel_born"), ("birth.place", "field_birth_place"),
    ("death.date", "panel_died"), ("death.place", "field_death_place"),
)


def _get(person, key):
    if "." in key:
        event, part = key.split(".")
        return (getattr(person, event) or {}).get(part, "")
    return getattr(person, key)


def _set(person, key, value):
    if "." in key:
        event, part = key.split(".")
        current = dict(getattr(person, event) or {"date": "", "place": ""})
        current[part] = value
        setattr(person, event, current)
    else:
        setattr(person, key, value)


def differences(mine_person, their_person):
    """[(key, label key, your value, their value)] where both say something and it differs."""
    found = []
    for key, label in FIELDS:
        mine_value, their_value = _get(mine_person, key), _get(their_person, key)
        # "Radic" against "Radić" is the same thing typed without accents: nothing to choose.
        if mine_value and their_value and fold_text(mine_value.strip()) != fold_text(their_value.strip()):
            found.append((key, label, mine_value, their_value))
    return found


def _generation(tree, person_id, seen=None):
    """How many generations of ancestors are recorded above someone: parents merge first."""
    seen = seen or set()
    if person_id in seen:
        return 0
    seen.add(person_id)
    parents = [p for f, _link in tree.parent_families(person_id) for p in f.partners]
    return 1 + max((_generation(tree, p, seen) for p in parents), default=-1)


@dataclass
class Result:
    tree: object
    added: int
    joined: int


def _take_theirs(my_person, their_copy, keys):
    """Their version where it was chosen. Only for details that still differ from the
    person they are matched to now: a choice made against an earlier match must not
    overwrite the right one. Swapped, not overwritten: theirs becomes yours, and yours goes
    to the other side, so the merge keeps it in the notes or as another name."""
    differing = {key for key, _label, _m, _t in differences(my_person, their_copy)}
    for key in keys:
        if key in differing:
            mine_value = _get(my_person, key)
            _set(my_person, key, _get(their_copy, key))
            _set(their_copy, key, mine_value)


def combine(mine, theirs, matches, take_theirs=None, copy_photo=None, copy_documents=None, copy_raw=None):
    """Your tree with theirs added. `matches`: {their id: your id} for people who are the
    same; `take_theirs`: {their id: {field keys}} where their version wins; `copy_photo(their
    id, their stored path)` gives a photo path in your tree's media folder, or "";
    `copy_documents(their id, their documents)` gives the documents with files in yours;
    `copy_raw(their stored path)` copies a DNA raw data file into yours, giving its path or "".
    Without them, no file of theirs is referred to from your tree. Raises
    CombineError naming the pair if a match would make the tree contradict itself."""
    take_theirs = take_theirs or {}
    if len(set(matches.values())) != len(matches):
        raise ValueError("two of their people matched to one of yours")
    trial = edits.copy_tree(mine)
    new_ids = {their_id: new_id("p") for their_id in theirs.people}
    theirs = _with_mine_ids(theirs, trial, new_ids)
    for their_id, person in theirs.people.items():
        data = person.to_dict()
        copy = Person.from_dict(new_ids[their_id], data)
        copy.photo = (copy_photo(their_id, person.photo) or "") if copy_photo else ""
        documents = copy_documents(their_id, person_documents(person)) if copy_documents else []
        copy.extra.pop("documents", None)
        if documents:
            copy.extra["documents"] = documents
        _bring_raw_files(copy, copy_raw)
        trial.people[copy.id] = copy
    for family in theirs.families.values():
        partners = [new_ids[p] for p in family.partners if p in new_ids]
        children = [{**c, "person": new_ids[c["person"]]} for c in family.children if c["person"] in new_ids]
        copy = Family(new_id("f"), partners, family.relationship, children, dict(family.extra))
        trial.families[copy.id] = copy

    mine_faces = set(face_links(mine))
    _bring_faces_and_marks(trial, theirs)
    order = sorted(matches.items(), key=lambda pair: (_generation(mine, pair[1]), pair[1]))
    # Merged without checking the whole tree each time (two checks per person: minutes on
    # a big tree); checked once at the end. Only if that finds a problem are the merges
    # done again one by one with checks, to name the pair that caused it.
    before = {(issue.code, issue.detail) for issue in edits.validate(trial)}
    quick = edits.copy_tree(trial)
    try:
        for their_id, my_id in order:
            _take_theirs(quick.people[my_id], quick.people[new_ids[their_id]], take_theirs.get(their_id, ()))
            edits.merge_people(quick, my_id, new_ids[their_id], check=False)
        clean = not [i for i in edits.validate(quick) if (i.code, i.detail) not in before]
    except edits.EditError:
        clean = False
    if clean:
        trial = quick
        order = []
    for their_id, my_id in order:
        _take_theirs(trial.people[my_id], trial.people[new_ids[their_id]], take_theirs.get(their_id, ()))
        try:
            edits.merge_people(trial, my_id, new_ids[their_id])
        except edits.EditError as error:
            raise CombineError(theirs.people[their_id].display_name, mine.people[my_id].display_name,
                               str(error)) from error
    # Merged one person at a time, an event of theirs still named the next person by their
    # new id, so it didn't look like yours yet; now that everyone is merged it is the same.
    for my_id in set(matches.values()):
        person = trial.people.get(my_id)
        for key in ("events", "names", "tasks"):
            items = person.extra.get(key) if person is not None else None
            if isinstance(items, list):
                person.extra[key] = [item for n, item in enumerate(items) if item not in items[:n]]
    _drop_faces_of_missing_files(trial, mine_faces)
    return Result(trial, len(theirs.people) - len(matches), len(matches))


def _source_key(source):
    return tuple(fold_text(source.get(field) or "").strip() for field in ("title", "author", "repository"))


def _content_key(record):
    return json.dumps({k: v for k, v in record.items() if v}, sort_keys=True, ensure_ascii=False) \
        if isinstance(record, dict) else ""


def _with_mine_ids(theirs, trial, new_ids):
    """A copy of their tree whose facts cite sources in `trial` and point at the new ids of
    their people. Their sources come across; one with the same title, author and archive
    as yours is yours. Two registers of one title from different archives stay two."""
    theirs = edits.copy_tree(theirs)
    mine_sources = trial.extra.setdefault("sources", {})
    by_key = {_source_key(source): source_id for source_id, source in tree_sources(trial).items()}
    raw = theirs.extra.get("sources") if isinstance(theirs.extra.get("sources"), dict) else {}
    # A source with no title is the same as one of yours only when it says exactly the same.
    by_content = {_content_key(record): source_id for source_id, record in mine_sources.items()
                  if isinstance(record, dict)}
    source_map = {}
    for source_id, source in tree_sources(theirs).items():
        key = _source_key(source)
        record = raw.get(source_id, source)
        if isinstance(mine_sources.get(source_id), dict) and _content_key(mine_sources[source_id]) == _content_key(record):
            source_map[source_id] = source_id  # Your own source, come back in a copy of your tree.
        elif key[0] and key in by_key:
            source_map[source_id] = by_key[key]
            # The same source: what theirs says and yours doesn't (a note, the publication,
            # an abbreviation) fills the gaps of yours.
            mine = mine_sources.get(by_key[key])
            if isinstance(mine, dict) and isinstance(record, dict):
                for name, value in record.items():
                    if value and not mine.get(name):
                        mine[name] = value
        elif not key[0] and _content_key(record) in by_content:
            source_map[source_id] = by_content[_content_key(record)]
        else:
            source_map[source_id] = new_id("s")
            # The whole record, with what the window doesn't show (publication, abbreviation).
            mine_sources[source_map[source_id]] = {k: v for k, v in raw.get(source_id, source).items() if v}
            if key[0]:
                by_key[key] = source_map[source_id]
    if not mine_sources:
        trial.extra.pop("sources", None)
    for _owner, _kind, fact in stored_facts(theirs):
        if "citations" in fact:
            cited = [{**c, "source": source_map[c["source"]]} for c in clean_citations(fact["citations"])
                     if c["source"] in source_map]
            fact.pop("citations")
            if cited:
                fact["citations"] = cited
    remap_people(theirs, new_ids, keep_unknown=False)
    _bring_places(theirs, trial)
    return theirs


def _bring_places(theirs, trial):
    """Their place records into yours. A place spelled alike (accents aside) is yours: their
    facts take your spelling; your details win and theirs fill the gaps."""
    mine = place_records(trial)
    by_fold = {fold_text(name): name for name in list(mine) + list(fact_places(trial))}
    renames = {}
    mine_names = set(mine) | set(fact_places(trial))
    for name in list(place_records(theirs)) + list(fact_places(theirs)):
        # Respelled only when you don't have it as they wrote it: a tree holding both
        # "trogir" and "Trogir" keeps each where it was.
        if name not in mine_names and fold_text(name) in by_fold and by_fold[fold_text(name)] != name:
            renames[name] = by_fold[fold_text(name)]
    for _owner, _kind, fact in stored_facts(theirs):
        if fact.get("place") in renames:
            fact["place"] = renames[fact["place"]]
    for name, record in place_records(theirs).items():
        name = renames.get(name, name)
        if record.get("parent"):
            record = {**record, "parent": renames.get(record["parent"], record["parent"])}
        target = mine.get(name, {})
        merged = {**record, **target}
        old = target.get("old_names", []) + [o for o in record.get("old_names", []) if o not in target.get("old_names", [])]
        if old:
            merged["old_names"] = old
        mine[name] = merged
    if mine:
        trial.extra["places"] = mine


def _bring_raw_files(person, copy_raw):
    """A DNA raw file is referred to only once it is in your tree's folder: a test whose
    file couldn't be copied keeps its matches and segments, not a path to nowhere."""
    dna = person.extra.get("dna")
    if not isinstance(dna, dict) or not isinstance(dna.get("tests"), list):
        return
    for test in dna["tests"]:
        raw = test.get("raw") if isinstance(test, dict) else None
        if not isinstance(raw, dict):
            continue
        stored = (copy_raw(raw.get("file", "")) or "") if copy_raw else ""
        if stored:
            test["raw"] = {**raw, "file": stored}
        else:
            test.pop("raw")


def missing_records(tree):
    """What a combined tree refers to but doesn't hold: [source ids cited but missing].
    Checked before a combined tree replaces yours, so success is never reported over a gap."""
    sources = tree_sources(tree)
    missing = []
    for _owner, _kind, fact in stored_facts(tree):
        for citation in clean_citations(fact.get("citations")):
            if citation["source"] not in sources and citation["source"] not in missing:
                missing.append(citation["source"])
    return missing


def _bring_faces_and_marks(trial, theirs):
    """Their faces and not-duplicate marks, already pointing at the new ids, added to
    yours before the merges (which then re-point them like everything else)."""
    faces = face_links(trial)
    for path, items in face_links(theirs).items():
        faces[path] = faces.get(path, []) + [item for item in items if item not in faces.get(path, [])]
    if faces:
        trial.extra["faces"] = faces
    pairs = not_duplicates(trial) + [p for p in not_duplicates(theirs) if p not in not_duplicates(trial)]
    if pairs:
        trial.extra["not_duplicates"] = pairs


def _drop_faces_of_missing_files(trial, before):
    """Faces of their pictures that didn't come across (no copy function, or refused)."""
    referenced = {path for person in trial.people.values() for path in files_of(person)}
    faces = {path: items for path, items in face_links(trial).items() if path in referenced or path in before}
    trial.extra.pop("faces", None)
    if faces:
        trial.extra["faces"] = faces


def describe_result(result):
    return t("combine_done", added=result.added, joined=result.joined)
