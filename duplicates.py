"""Finding people recorded twice in one tree. No interface code here.

The same scoring as combining trees (combine.person_score: names, other names,
surnames, sex, years), plus the family around each pair. Only people sharing a first
name are compared, so a big tree is still quick. Some pairs look alike but must not
be merged, and the reason is shown instead: partners, or one the ancestor of the
other. Brothers or sisters with the same name and the same parents are often a child
who died young and the next one named after them, so that pair scores low and says so.
"""
from dataclasses import dataclass, field

from combine import _first_names, person_score
from model import TreeIndex, not_duplicates, parse_date

SHOW_FROM = 2.0


@dataclass
class Candidate:
    a: str
    b: str
    score: float
    reasons: list = field(default_factory=list)  # Text keys: why they look like one person.
    blocked: str = ""  # A text key when merging would be refused.


def _year(event):
    parsed = parse_date((event or {}).get("date", ""))
    return parsed.year if parsed else None


def _relatives_of(index, person_id):
    parents = [p for f, link in index.parent_families(person_id) if link == "birth" for p in f.partners]
    partners, children = [], []
    for family in index.families_of(person_id):
        partners += [p for p in family.partners if p != person_id]
        children += family.child_ids
    return {"parent": parents, "partner": partners, "child": children}


def _ancestors(parents_of, person_id):
    found, stack = set(), [person_id]
    while stack:
        for parent in parents_of.get(stack.pop(), ()):
            if parent not in found:
                found.add(parent)
                stack.append(parent)
    return found


def _pair_reasons(tree, a, b, relatives):
    first, second = tree.people[a], tree.people[b]
    reasons, bonus = ["dup_same_name"], 0.0
    for event, key in (("birth", "dup_same_birth"), ("death", "dup_same_death")):
        if _year(getattr(first, event)) and _year(getattr(first, event)) == _year(getattr(second, event)):
            reasons.append(key)
    for role, key in (("parent", "dup_same_parents"), ("partner", "dup_same_partner"), ("child", "dup_same_children")):
        shared = set(relatives[a][role]) & set(relatives[b][role])
        if shared:
            reasons.append(key)
            bonus += 1.5
        else:
            # Recorded twice in two branches: the relatives are themselves look-alikes.
            alike = any(person_score(tree.people[x], tree.people[y]) is not None
                        for x in relatives[a][role][:6] for y in relatives[b][role][:6] if x != y)
            if alike:
                if "dup_similar_family" not in reasons:
                    reasons.append("dup_similar_family")
                bonus += 1.0
    return reasons, bonus


def _richness(tree, person_id, relatives):
    """How much a record knows; the fuller one is offered first, as the one to keep."""
    person = tree.people[person_id]
    known = [person.given, person.surname, person.birth_surname, person.sex, person.photo, person.notes,
             (person.birth or {}).get("date"), (person.birth or {}).get("place"), (person.death or {}).get("date")]
    return sum(1 for value in known if value) + sum(len(v) for v in relatives[person_id].values()) \
        + len(person.extra.get("events") or []) + len(person.extra.get("documents") or [])


def _close_pairs(members, years):
    """Pairs in one first-name group that could be one person by their birth years:
    within two years of each other, or one of them without a known year."""
    dated = sorted((m for m in members if years.get(m)), key=lambda m: years[m])
    undated = [m for m in members if not years.get(m)]
    for i, a in enumerate(dated):
        for b in dated[i + 1:]:
            if years[b] - years[a] > 2:
                break
            yield a, b
    for i, a in enumerate(undated):
        for b in undated[i + 1:] + dated:
            yield a, b


def find_duplicates(tree):
    """Pairs of people who may be one person, most likely first."""
    marked = {tuple(pair) for pair in not_duplicates(tree)}
    index = TreeIndex(tree)
    groups, years = {}, {}
    for person in tree.people.values():
        if person.extra.get("hidden"):
            continue  # Only a surname is left of them: everyone with that surname would match.
        years[person.id] = _year(person.birth)
        for name in _first_names(person):
            groups.setdefault(name, []).append(person.id)
    relatives, parents_of = {}, {}
    for family in tree.families.values():
        for child in family.child_ids:
            parents_of.setdefault(child, []).extend(family.partners)
    seen, found = set(), []
    for members in groups.values():
        for a, b in _close_pairs(members, years):
            pair = tuple(sorted((a, b)))
            if a == b or pair in seen or pair in marked:
                continue
            seen.add(pair)
            score = person_score(tree.people[pair[0]], tree.people[pair[1]])
            if score is None:
                continue
            for person_id in pair:
                if person_id not in relatives:
                    relatives[person_id] = _relatives_of(index, person_id)
            reasons, bonus = _pair_reasons(tree, pair[0], pair[1], relatives)
            score += bonus
            if "dup_same_parents" in reasons and not (years.get(a) and years.get(b)):
                score = min(score, SHOW_FROM)  # Maybe a child named after one who died.
                reasons.append("dup_maybe_siblings")
            if score < SHOW_FROM:
                continue
            blocked = ""
            if pair[1] in relatives[pair[0]]["partner"]:
                blocked = "dup_blocked_partners"
            elif pair[0] in _ancestors(parents_of, pair[1]) or pair[1] in _ancestors(parents_of, pair[0]):
                blocked = "dup_blocked_ancestor"
            first, second = sorted(pair, key=lambda pid: -_richness(tree, pid, relatives))
            found.append(Candidate(first, second, score, reasons, blocked))
    return sorted(found, key=lambda c: (-c.score, c.a, c.b))
