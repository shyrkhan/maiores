"""How two people are related, from the recorded links. No interface code here.

The relation is worked out by blood first: the nearest shared ancestor, and how
many generations each person is below them. That gives parent, sibling, aunt,
cousin, "once removed" and so on. If there is no blood link, one marriage is
allowed on either side, which covers husband, father-in-law, sister-in-law,
"the wife of your uncle" and "your wife's cousin". The words come from
strings.py, so each language can use its own kinship terms.
"""
from collections import deque
from dataclasses import dataclass, field

from model import TreeIndex

MAX_DEPTH = 40


@dataclass
class Relation:
    """B as seen from A. `up`: generations from A to the shared ancestor; `down`: from there to B."""
    kind: str  # "self", "blood", "partner", "partner_of_blood", "blood_of_partner", "none"
    up: int = 0
    down: int = 0
    half: bool = False  # Siblings (or their lines) sharing only one parent.
    side: str = ""  # "father" or "mother": which of A's parents the link goes through.
    sex: str = ""  # B's sex, for gendered words.
    via: str = ""  # The partner a marriage link goes through.
    inner: "Relation | None" = None  # The blood relation on the far side of a marriage.
    path: list = field(default_factory=list)  # People from A to B, for highlighting.


def _parents(index, tree, person_id):
    family = index.birth_family_of(person_id)
    return [p for p in (family.partners if family else []) if p in tree.people]


def _ancestors(index, tree, start):
    """Every ancestor with its distance and the path down to `start`."""
    found = {start: (0, [start])}
    waiting = deque([start])
    while waiting:
        current = waiting.popleft()
        depth, path = found[current]
        if depth >= MAX_DEPTH:
            continue
        for parent in _parents(index, tree, current):
            if parent not in found:
                found[parent] = (depth + 1, [parent] + path)
                waiting.append(parent)
    return found


def blood_relation(tree, a, b, index=None):
    """The blood relation of B to A, or None when no shared ancestor is recorded."""
    index = index or TreeIndex(tree)
    if a == b:
        return Relation("self", path=[a])
    mine, theirs = _ancestors(index, tree, a), _ancestors(index, tree, b)
    shared = [p for p in mine if p in theirs]
    if not shared:
        return None
    best = min(shared, key=lambda p: (mine[p][0] + theirs[p][0], mine[p][0]))
    up, down = mine[best][0], theirs[best][0]
    path = list(reversed(mine[best][1])) + theirs[best][1][1:]
    # Half relations: the nearest shared couple contributes only one person.
    half = False
    if up >= 1 and down >= 1:
        a_line = mine[best][1][1] if len(mine[best][1]) > 1 else a
        b_line = theirs[best][1][1] if len(theirs[best][1]) > 1 else b
        half = set(_parents(index, tree, a_line)) != set(_parents(index, tree, b_line))
    side = ""
    if up >= 1:
        first_parent = path[1]
        parent_sex = tree.people[first_parent].sex
        side = "father" if parent_sex == "M" else "mother" if parent_sex == "F" else ""
    return Relation("blood", up, down, half, side, tree.people[b].sex, path=path)


def relationship(tree, a, b):
    """The closest recorded relation of B to A."""
    index = TreeIndex(tree)
    blood = blood_relation(tree, a, b, index)
    if blood is not None:
        return blood
    sex = tree.people[b].sex
    partners_of = lambda person: [p for f in index.families_of(person) for p in f.partners  # noqa: E731
                                  if p != person and p in tree.people]
    if b in partners_of(a):
        return Relation("partner", sex=sex, path=[a, b])
    # B married to one of A's blood relatives: "the wife of your uncle".
    for partner in partners_of(b):
        inner = blood_relation(tree, a, partner, index)
        if inner is not None and inner.kind == "blood":
            return Relation("partner_of_blood", sex=sex, via=partner, inner=inner, path=inner.path + [b])
    # B a blood relative of A's partner: "your wife's cousin".
    for partner in partners_of(a):
        inner = blood_relation(tree, partner, b, index)
        if inner is not None and inner.kind == "blood":
            return Relation("blood_of_partner", sex=sex, via=partner, inner=inner, path=[a] + inner.path)
    return Relation("none", sex=sex)


# Words. English builds "great-" chains; Croatian has its own terms for close
# relatives and describes the distant ones by generation ("u 2. koljenu").

def _pick(sex, male, female, other):
    return male if sex == "M" else female if sex == "F" else other


def _ordinal(n):
    return {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}.get(n, f"{n}th")


def _times(n):
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def _en_blood(r):
    up, down, sex = r.up, r.down, r.sex
    half = "half-" if r.half else ""
    if up == 0:
        base = _pick(sex, "son", "daughter", "child") if down == 1 else _pick(sex, "grandson", "granddaughter", "grandchild")
        return base if down <= 2 else "great-" * (down - 2) + base
    if down == 0:
        base = _pick(sex, "father", "mother", "parent") if up == 1 else _pick(sex, "grandfather", "grandmother", "grandparent")
        return base if up <= 2 else "great-" * (up - 2) + base
    if up == 1 and down == 1:
        return half + _pick(sex, "brother", "sister", "sibling")
    if up == 1:
        base = _pick(sex, "nephew", "niece", "nephew or niece")
        return half + ("grand" if down == 3 else "great-" * (down - 3) + "grand" if down > 3 else "") + base
    if down == 1:
        base = _pick(sex, "uncle", "aunt", "uncle or aunt")
        return half + "great-" * (up - 2) + base
    degree, removed = min(up, down) - 1, abs(up - down)
    text = f"{_ordinal(degree)} cousin"
    return text + (f" {_times(removed)} removed" if removed else "")


def _en(r, tree, a):
    if r.kind == "self":
        return "the same person"
    if r.kind == "none":
        return "not related through the recorded links"
    if r.kind == "partner":
        return _pick(r.sex, "husband", "wife", "partner")
    if r.kind == "blood":
        return _en_blood(r)
    inner = r.inner
    if r.kind == "partner_of_blood":
        if (inner.up, inner.down) == (0, 1):
            return _pick(r.sex, "son-in-law", "daughter-in-law", "child's partner")
        if (inner.up, inner.down) == (1, 0):
            return _pick(r.sex, "stepfather", "stepmother", "step-parent")
        if (inner.up, inner.down) == (1, 1):
            return _pick(r.sex, "brother-in-law", "sister-in-law", "sibling-in-law")
        if (inner.up, inner.down) == (2, 1) and r.sex in ("M", "F"):
            return _pick(r.sex, "uncle by marriage", "aunt by marriage", "")
        whose = tree.people[r.via].display_name
        return f"{_pick(r.sex, 'husband', 'wife', 'partner')} of {whose}, {_en_blood(inner)}"
    partner = tree.people[r.via]
    if (inner.up, inner.down) == (1, 0):
        return _pick(r.sex, "father-in-law", "mother-in-law", "parent-in-law")
    if (inner.up, inner.down) == (1, 1):
        return _pick(r.sex, "brother-in-law", "sister-in-law", "sibling-in-law")
    if (inner.up, inner.down) == (0, 1):
        return _pick(r.sex, "stepson", "stepdaughter", "stepchild")
    return f"{_pick(partner.sex, 'husband', 'wife', 'partner')}'s {_en_blood(inner)}"


def _hr_up(n, genitive=False):
    """Ancestor n generations up: djed, pradjed, prapradjed..."""
    if genitive:
        return "roditelja" if n == 1 else "pra" * (n - 2) + "djeda ili " + "pra" * (n - 2) + "bake"
    return None


def _hr_blood(r):
    up, down, sex = r.up, r.down, r.sex
    if up == 0:
        if down == 1:
            return _pick(sex, "sin", "kći", "dijete")
        return "pra" * (down - 2) + _pick(sex, "unuk", "unuka", "unuk/unuka")
    if down == 0:
        if up == 1:
            return _pick(sex, "otac", "majka", "roditelj")
        return "pra" * (up - 2) + _pick(sex, "djed", "baka", "djed/baka")
    if up == 1 and down == 1:
        return ("polu" if r.half else "") + _pick(sex, "brat", "sestra", "brat/sestra")
    if up == 1:
        if down == 2:
            return _pick(sex, "nećak", "nećakinja", "nećak/nećakinja")
        return "pra" * (down - 3) + _pick(sex, "unuk", "unuka", "unuk/unuka") + " brata ili sestre"
    if down == 1:
        if up == 2:
            if sex == "F":
                return "teta"
            if sex == "M":
                return "stric" if r.side == "father" else "ujak" if r.side == "mother" else "stric/ujak"
            return "brat/sestra roditelja"
        return _pick(sex, "brat", "sestra", "brat/sestra") + " " + _hr_up(up - 1, genitive=True)
    degree, removed = min(up, down) - 1, abs(up - down)
    if degree == 1:
        text = _pick(sex, "bratić", "sestrična", "bratić/sestrična")
    else:
        text = _pick(sex, "brat", "sestra", "brat/sestra") + f" u {degree}. koljenu"
    if removed:
        text += f", {removed} " + ("generacija" if removed >= 5 else "generacije" if removed >= 2 else "generacija") + " razlike"
    return text


def _hr(r, tree, a):
    if r.kind == "self":
        return "ista osoba"
    if r.kind == "none":
        return "nema zapisane rodbinske veze"
    if r.kind == "partner":
        return _pick(r.sex, "muž", "žena", "partner")
    if r.kind == "blood":
        return _hr_blood(r)
    inner = r.inner
    if r.kind == "partner_of_blood":
        if (inner.up, inner.down) == (0, 1):
            return _pick(r.sex, "zet", "snaha", "partner djeteta")
        if (inner.up, inner.down) == (1, 0):
            return _pick(r.sex, "očuh", "maćeha", "partner roditelja")
        if (inner.up, inner.down) == (1, 1):
            return _pick(r.sex, "šogor", "šogorica", "šogor/šogorica")
        if (inner.up, inner.down) == (2, 1):
            blood_sex = tree.people[r.via].sex
            if r.sex == "F" and blood_sex == "M":  # The wife of a father's or mother's brother.
                return "strina" if inner.side == "father" else "ujna" if inner.side == "mother" else "strina/ujna"
            if r.sex == "M" and blood_sex == "F":  # The husband of an aunt.
                return "tetak"
        whose = tree.people[r.via].display_name
        return f"{_pick(r.sex, 'muž', 'žena', 'partner')} od {whose} ({_hr_blood(inner)})"
    me = tree.people[a].sex
    if (inner.up, inner.down) == (1, 0):
        if me == "F":
            return _pick(r.sex, "svekar", "svekrva", "roditelj partnera")
        if me == "M":
            return _pick(r.sex, "punac", "punica", "roditelj partnera")
        return "roditelj partnera"
    if (inner.up, inner.down) == (1, 1):
        return _pick(r.sex, "šogor", "šogorica", "šogor/šogorica")
    if (inner.up, inner.down) == (0, 1):
        return _pick(r.sex, "pastorak", "pastorka", "pastorak/pastorka")
    return f"{_hr_blood(inner)} partnera"


# Every other language: kinship words are full of grammar and customs (Chinese and
# Korean say which side and who is older), so rather than guess a term, the relation
# is spelled out one step at a time with plain words: "father › mother › brother".

def _blood_steps(tree, r, path):
    steps = [("parent", path[i]) for i in range(1, r.up + 1)]
    steps += [("child", path[i]) for i in range(r.up + 1, len(path))]
    if r.up and r.down:  # Up to a parent and straight down again is a brother or sister.
        steps[r.up - 1:r.up + 1] = [("sibling", path[r.up + 1])]
    return steps


def steps(tree, r):
    """B's relation as (kind, person) steps from A: kind is parent, child, sibling or partner."""
    if r.kind == "partner":
        return [("partner", r.path[-1])]
    if r.kind == "blood":
        return _blood_steps(tree, r, r.path)
    if r.kind == "partner_of_blood":
        return _blood_steps(tree, r.inner, r.inner.path) + [("partner", r.path[-1])]
    if r.kind == "blood_of_partner":
        return [("partner", r.via)] + _blood_steps(tree, r.inner, r.inner.path)
    return []


def spelled_out(tree, r, term):
    """'father › mother › brother'. `term(key)` gives the word for keys like kin_father."""
    if r.kind == "self":
        return term("kin_self")
    if r.kind == "none":
        return term("kin_none")
    gendered = {"parent": ("father", "mother", "parent"), "child": ("son", "daughter", "child"),
                "sibling": ("brother", "sister", "sibling"), "partner": ("husband", "wife", "partner")}
    words = [term("kin_" + _pick(tree.people[person].sex, *gendered[kind])) for kind, person in steps(tree, r)]
    return " › ".join(words)


def describe(tree, a, b, language="en", term=None):
    """B's relation to A in a few words, with the side of the family when it matters.
    Languages other than English and Croatian need `term` (see spelled_out)."""
    r = relationship(tree, a, b)
    if language not in ("en", "hr") and term is not None:
        return spelled_out(tree, r, term), r
    words = (_hr if language == "hr" else _en)(r, tree, a)
    if r.kind == "blood" and r.up >= 2 and r.side:
        if language == "hr":
            words += " (očeva strana)" if r.side == "father" else " (majčina strana)"
        else:
            words += " (father's side)" if r.side == "father" else " (mother's side)"
    return words, r
