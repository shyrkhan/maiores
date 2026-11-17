"""The family data: people, families, incomplete dates and data checks.

No interface code here. Fields this version does not recognise are kept and
written back, so a future version's data survives being opened by this one.
"""
import calendar
import contextlib
import re
import unicodedata
import uuid
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath, PureWindowsPath

from strings import t

# Which surname names show: "both" (the current one, with "rođ. X" beside it where the
# birth surname differs), "birth" or "current". Set from Preferences.
SURNAMES = "both"

# 2 (version 1.1): sources are records cited from facts, facts can list the people who
# were there (godparents, witnesses), people can have other names. 1.0 refuses these
# files rather than quietly dropping what it doesn't know when saving.
FORMAT_VERSION = 2
LIVING_VALUES = {"yes", "no", "unknown"}
CHILD_LINKS = {"birth", "adopted", "foster", "unknown"}
RELATIONSHIPS = {"married", "partners", "divorced", "unknown"}



class TreeFormatError(ValueError):
    """The data has the wrong structure and cannot be trusted as a tree."""


def as_list(value):
    """A list read from a file, or [] when the file has something else there."""
    return value if isinstance(value, list) else []


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4()}"


@dataclass(frozen=True)
class ParsedDate:
    """One stored date. `year` is the year for calculations: for a double-dated year
    written 1708/09 (the year changed in March then) it is the new-style 1709.
    `qualifier`: abt, bef, aft, or for periods from / to; `end` is a period's end date.
    `end_year` is the end of a "between" range (stored 1880/1885)."""
    year: int
    month: int | None = None
    day: int | None = None
    qualifier: str | None = None
    end_year: int | None = None
    calendar: str = ""  # "julian" for dates written in the old calendar.
    dual: bool = False
    end: "ParsedDate | None" = None

    def key(self):
        """For sorting: the start of the date."""
        return (self.year, self.month or 0, self.day or 0)


# Stored dates, one spelling each (so two copies of a date always compare equal):
#   1921   1921-05   1921-05-14   abt 1921   bef 1900   aft 1900   1880/1885 (between)
#   1708/09-02-10 (double-dated year)   1708-02-10 julian   abt 1708 julian
#   from 1950   to 1960   from 1950 to 1960   from 1700 julian to 1710 julian (periods)
_CORE = re.compile(r"^([0-9]{4})(?:/([0-9]{2}))?(?:-([0-9]{2})(?:-([0-9]{2}))?)?$")
_RANGE_DATE = re.compile(r"^([0-9]{4})/([0-9]{4})$")  # Stored dates use 0-9 only, never other scripts' digits.


def _days_in(year, month, julian):
    if julian and month == 2:
        return 29 if year % 4 == 0 else 28  # The old calendar: every fourth year, no exceptions.
    return calendar.monthrange(year, month)[1]


def _parse_single(text):
    """'[abt|bef|aft ]YYYY[/YY][-MM[-DD]][ julian]', or None."""
    qualifier = None
    head, _space, rest = text.partition(" ")
    if head in ("abt", "bef", "aft") and rest:
        qualifier, text = head, rest
    julian = text.endswith(" julian")
    if julian:
        text = text[:-len(" julian")]
    match = _CORE.match(text)
    if not match:
        return None
    year = int(match[1])
    dual = match[2] is not None
    if dual:
        if int(match[2]) != (year + 1) % 100:
            return None  # 1708/09 only: the second year is always the next one.
        year += 1
    month = int(match[3]) if match[3] else None
    day = int(match[4]) if match[4] else None
    if year < 1 or (month is not None and not 1 <= month <= 12):
        return None
    if day is not None and not 1 <= day <= _days_in(year - (1 if dual else 0), month, julian):
        return None
    return ParsedDate(year, month, day, qualifier, calendar="julian" if julian else "", dual=dual)


def parse_date(text):
    """Return a ParsedDate, or None if the text is empty or not understood."""
    if not text:
        return None
    match = _RANGE_DATE.match(text)
    if match:
        start, end = int(match[1]), int(match[2])
        return ParsedDate(start, end_year=end) if start <= end else None
    if text.startswith("from "):
        first, separator, second = text[5:].partition(" to ")
        start = _parse_single(first)
        end = _parse_single(second) if separator else None
        if start is None or start.qualifier or (separator and (end is None or end.qualifier)):
            return None
        if end is not None and end.key() < start.key():
            return None
        return ParsedDate(start.year, start.month, start.day, "from", calendar=start.calendar, dual=start.dual,
                          end=end)
    if text.startswith("to "):
        end = _parse_single(text[3:])
        if end is None or end.qualifier:
            return None
        return ParsedDate(end.year, end.month, end.day, "to", calendar=end.calendar, dual=end.dual)
    return _parse_single(text)


def is_period(stored):
    parsed = parse_date(stored)
    return parsed is not None and parsed.qualifier in ("from", "to")


_ABOUT_WORDS = ("about", "abt", "circa", "ca.", "ca", "c.", "c", "cca.", "cca", "oko", "~")
_BEFORE_WORDS = ("before", "bef", "prije")
_AFTER_WORDS = ("after", "aft", "poslije", "nakon")
_JULIAN_WORDS = ("julian", "(julian)", "jul.", "(jul.)", "o.s.", "(o.s.)", "os", "old style", "(old style)")
_FROM_WORDS = ("from", "od")
_TO_WORDS = ("to", "until", "till", "do")
_DOTTED_FULL = re.compile(r"^(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4}(?:/\d{1,2})?)$")
_DOTTED_MONTH = re.compile(r"^(\d{1,2})\s*\.\s*(\d{4}(?:/\d{1,2})?)$")
_ANY_RANGE = re.compile(r"^(\d{4})\s*[-/–]\s*(\d{4})$")
_DUAL_YEAR = re.compile(r"^(\d{4})/(\d{1,2})")


def _templates(key, *names):
    """Every language's text for `key` split around its placeholders, lower case."""
    import strings
    found = set()
    for table in strings.STRINGS.values():
        template = table.get(key, "")
        if all("{" + name + "}" in template for name in names):
            pattern = re.escape(template.lower())
            for name in names:
                pattern = pattern.replace(re.escape("{" + name + "}"), f"(?P<{name}>.+?)")
            found.add(pattern)
    return [re.compile(f"^{p}$") for p in sorted(found, key=len, reverse=True)]


def _qualifier_words():
    """(before the date, after the date, stored qualifier) for every language's
    date_word_* text, so 'environ 1921', '1921頃' and '约1921年' all read back."""
    import strings
    found = set()
    for table in strings.STRINGS.values():
        for key, stored in (("date_word_about", "abt"), ("date_word_before", "bef"), ("date_word_after", "aft")):
            template = table.get(key, "")
            if "{date}" in template:
                before, after = template.lower().split("{date}", 1)
                if before.strip() or after.strip():
                    found.add((before.strip(), after.strip(), stored))
    # Longest first, so "vor dem" wins over "vor".
    return sorted(found, key=lambda item: -len(item[0]) - len(item[1]))


def _translated_qualifier(value):
    for before, after, stored in _qualifier_words():
        if value.startswith(before) and value.endswith(after) and len(value) > len(before) + len(after):
            inner = value[len(before):len(value) - len(after)].strip(" .")
            if inner[:1].isdigit() and inner[-1:].isdigit():
                return stored, inner
    return None, value


def _strip_julian(value):
    """(value without the calendar word, whether it was there)."""
    for pattern in _templates("date_word_julian", "date"):
        match = pattern.match(value)
        if match:
            return match["date"].strip(), True
    for word in _JULIAN_WORDS:
        if value.endswith(" " + word):
            return value[:-len(word) - 1].strip(), True
    return value, False


def _dual_core(value):
    """'1708/9' or '1708/09' as stored '1708/09'; anything else unchanged."""
    match = _DUAL_YEAR.match(value)
    if match and len(match[2]) <= 2 and not _ANY_RANGE.match(value):
        year = int(match[1])
        if int(match[2]) == (year + 1) % (10 if len(match[2]) == 1 else 100):
            return f"{year}/{(year + 1) % 100:02d}" + value[match.end():]
    return value


def _normalize_single(value):
    """One date as typed (no period words), in stored form, or None."""
    value = value.strip().rstrip(".").strip()
    value, julian = _strip_julian(value)
    value = value.rstrip(".").strip()
    qualifier = None
    for words, stored in ((_ABOUT_WORDS, "abt"), (_BEFORE_WORDS, "bef"), (_AFTER_WORDS, "aft")):
        for word in words:
            if value.startswith(word) and value[len(word):][:1] in (" ", ".") + tuple("0123456789"):
                qualifier = stored
                value = value[len(word):].strip(" .")
                break
        if qualifier:
            break
    if qualifier is None:
        qualifier, value = _translated_qualifier(value)
    match = _DOTTED_FULL.match(value)
    if match:
        value = f"{_dual_core(match[3])}-{int(match[2]):02d}-{int(match[1]):02d}"
    else:
        match = _DOTTED_MONTH.match(value)
        if match:
            value = f"{_dual_core(match[2])}-{int(match[1]):02d}"
        else:
            value = _dual_core(value)
    stored = f"{qualifier} {value}" if qualifier else value
    if julian:
        stored += " julian"
    return stored if _parse_single(stored) else None


def _period_parts(value):
    """(start text or None, end text or None) when the value is a period, else None."""
    for pattern in _templates("date_word_period", "start", "end"):
        match = pattern.match(value)
        if match:
            return match["start"], match["end"]
    for pattern in _templates("date_word_from", "date"):
        match = pattern.match(value)
        if match:
            return match["date"], None
    for pattern in _templates("date_word_to", "date"):
        match = pattern.match(value)
        if match:
            return None, match["date"]
    words = value.split(" ", 1)
    if len(words) == 2 and words[0] in _FROM_WORDS:
        for joiner in _TO_WORDS:
            start, separator, end = words[1].partition(f" {joiner} ")
            if separator:
                return start, end
        return words[1], None
    if len(words) == 2 and words[0] in _TO_WORDS + ("until",):
        return None, words[1]
    return None


def normalize_date_input(text):
    """Turn what someone typed into the stored form. None means not understood.

    Accepts 1921, 14.5.1921, 5.1921, 1921-05-14, about 1921, before 1900, after 1900,
    1880-1885 (between), 10.2.1708/09 (a double-dated year), 10.2.1708 (Julian), and
    periods: from 1950 to 1960, from 1950, to 1960, in any of the program's languages.
    Slashed day/month forms are refused, because 3/2/1951 means different days in
    different countries.
    """
    # Digits from any script (Arabic ١٩٢١, full-width １９２１) become 0-9.
    value = "".join(str(unicodedata.digit(c)) if c.isdigit() and not c.isascii() and unicodedata.digit(c, None)
                    is not None else c for c in text)
    value = " ".join(value.strip().lower().split())
    if not value:
        return ""
    value = value.rstrip(".").strip()
    match = _ANY_RANGE.match(re.sub(r"(\d{4})\.\s*-", r"\1-", value))  # "1880.-1885." as written in Croatian.
    if match:
        stored = f"{match[1]}/{match[2]}"
        return stored if parse_date(stored) else None
    whole, julian = _strip_julian(value)  # "from 1700 to 1710 (Julian)": both ends are Julian.
    parts = _period_parts(whole)
    if parts is not None:
        start, end = (None if part is None else _normalize_single(part) for part in parts)
        if julian:  # "from 1700 to 1710 (Julian)": the calendar word covers both ends.
            start, end = (part if part is None or part.endswith(" julian") else part + " julian"
                          for part in (start, end))
        if (parts[0] is not None and start is None) or (parts[1] is not None and end is None):
            return None
        if any(part and part.split(" ")[0] in ("abt", "bef", "aft") for part in (start, end)):
            return None
        stored = f"from {start} to {end}" if start and end else f"from {start}" if start else f"to {end}"
        return stored if parse_date(stored) else None
    return _normalize_single(value)


def _year_text(parsed):
    """Always four digits (0912), so the year reads back; a double-dated year as 1708/09."""
    return f"{parsed.year - 1:04d}/{parsed.year % 100:02d}" if parsed.dual else f"{parsed.year:04d}"


def _core_text(parsed):
    """'14.5.1921', '5.1921' or '1921'; a double-dated year as 1708/09."""
    year = _year_text(parsed)
    if parsed.day is not None:
        return f"{parsed.day}.{parsed.month}.{year}"
    if parsed.month is not None:
        return f"{parsed.month}.{year}"
    return year


def _single_input_text(parsed):
    text = _core_text(parsed)
    words = {"abt": "date_word_about", "bef": "date_word_before", "aft": "date_word_after"}
    if parsed.qualifier in words:
        text = t(words[parsed.qualifier], date=text)
    return t("date_word_julian", date=text) if parsed.calendar == "julian" else text


def date_input_text(stored):
    """The form of a stored date to show in a text box or the detail panel."""
    parsed = parse_date(stored)
    if parsed is None:
        return stored or ""
    if parsed.end_year is not None:
        return f"{parsed.year:04d}-{parsed.end_year:04d}"  # The form the parser reads in every language.
    if parsed.qualifier == "from":
        start = _single_input_text(replace(parsed, qualifier=None, end=None))
        if parsed.end is None:
            return t("date_word_from", date=start)
        return t("date_word_period", start=start, end=_single_input_text(parsed.end))
    if parsed.qualifier == "to":
        return t("date_word_to", date=_single_input_text(replace(parsed, qualifier=None)))
    return _single_input_text(parsed)


def date_label(text):
    """A short human form of a stored date. Unparsable text is shown as written."""
    parsed = parse_date(text)
    if parsed is None:
        return text or t("date_unknown")
    if parsed.end_year is not None:
        return t("date_between", start=parsed.year, end=parsed.end_year)
    year = _year_text(parsed)
    if parsed.qualifier == "from":
        if parsed.end is None:
            return t("date_word_from", date=year)
        end = _year_text(parsed.end)
        return t("date_between", start=year, end=end)
    if parsed.qualifier == "to":
        return t("date_word_to", date=year)
    if parsed.qualifier == "abt":
        return t("date_about", year=year)
    if parsed.qualifier == "bef":
        return t("date_before", year=year)
    if parsed.qualifier == "aft":
        return t("date_after", year=year)
    return year


def _take(data, key, kind, default, where):
    value = data.pop(key, default)
    if value is not default and not isinstance(value, kind):
        raise TreeFormatError(f"{where}: {key} has the wrong type")
    return value


def _event(data, key, where):
    value = data.pop(key, None)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TreeFormatError(f"{where}: {key} has the wrong type")
    for part in ("date", "place"):
        if not isinstance(value.get(part, ""), str):
            raise TreeFormatError(f"{where}: {key}.{part} has the wrong type")
    return value


@dataclass
class Person:
    id: str
    given: str = ""
    surname: str = ""
    birth_surname: str = ""
    sex: str = ""
    birth: dict | None = None
    death: dict | None = None
    living: str = "unknown"
    photo: str = ""
    notes: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, person_id, source):
        if not isinstance(source, dict):
            raise TreeFormatError(f"person {person_id}: not an object")
        data = dict(source)
        where = f"person {person_id}"
        fields = {
            name: _take(data, name, str, "", where)
            for name in ("given", "surname", "birth_surname", "sex", "photo", "notes")
        }
        living = _take(data, "living", str, "unknown", where)
        birth = _event(data, "birth", where)
        death = _event(data, "death", where)
        return cls(
            person_id, birth=birth, death=death, living=living, extra=data, **fields
        )

    def to_dict(self):
        return {
            "given": self.given,
            "surname": self.surname,
            "birth_surname": self.birth_surname,
            "sex": self.sex,
            "birth": self.birth,
            "death": self.death,
            "living": self.living,
            "photo": self.photo,
            "notes": self.notes,
            **self.extra,
        }

    @property
    def birth_date(self):
        return (self.birth or {}).get("date", "")

    @property
    def death_date(self):
        return (self.death or {}).get("date", "")

    @property
    def display_name(self):
        if self.extra.get("hidden"):  # Someone a shared copy left out (see privacy.py).
            return t("hidden_person", surname=self.surname) if self.surname else t("living_person")
        surname = self.surname
        if SURNAMES == "birth" and self.birth_surname.strip():
            surname = self.birth_surname
        return " ".join(p for p in (self.given, surname) if p) or t("unknown_person")

    @property
    def line_surname(self):
        """The surname someone was born with: what their family line is."""
        return (self.birth_surname.strip() or self.surname.strip())

    @property
    def born_as(self):
        """"rođ. Lukač", "geb. Lukač", "née Lukač": the birth surname, when cards show the
        current one and the two differ. Empty otherwise."""
        birth = self.birth_surname.strip()
        if SURNAMES != "both" or not birth or self.extra.get("hidden") or fold_text(birth) == fold_text(self.surname):
            return ""
        key = {"F": "born_as_f", "M": "born_as_m"}.get(self.sex, "born_as")
        return t(key, surname=birth)

    @property
    def full_name(self):
        """The name with the birth surname after it, for headings and reports."""
        born = self.born_as
        return f"{self.display_name}, {born}" if born else self.display_name

    def years_label(self):
        birth, death = self.birth_date, self.death_date
        if self.living == "yes":
            return t("years_living", birth=date_label(birth)) if birth else ""
        if not birth and not death:
            return ""
        return t("years_range", birth=date_label(birth), death=date_label(death))

    def age_label(self, today):
        """The living show their age. Everyone else shows years."""
        parsed = parse_date(self.birth_date)
        unusable = (
            self.living != "yes"
            or parsed is None
            or parsed.end_year is not None
            or parsed.qualifier in ("bef", "aft")
            or parsed.year > today.year
        )
        if unusable:
            return self.years_label()
        age = today.year - parsed.year
        if parsed.month is None or parsed.day is None or parsed.qualifier:
            return t("age_about", age=age)
        if (today.month, today.day) < (parsed.month, parsed.day):
            age -= 1
        return str(age) if age >= 0 else self.years_label()


@dataclass
class Family:
    id: str
    partners: list = field(default_factory=list)
    relationship: str = "unknown"
    children: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, family_id, source):
        if not isinstance(source, dict):
            raise TreeFormatError(f"family {family_id}: not an object")
        data = dict(source)
        where = f"family {family_id}"
        partners = _take(data, "partners", list, [], where)
        if not all(isinstance(p, str) for p in partners):
            raise TreeFormatError(f"{where}: partners must be person IDs")
        relationship = _take(data, "relationship", str, "unknown", where)
        children = _take(data, "children", list, [], where)
        for child in children:
            valid = (
                isinstance(child, dict)
                and isinstance(child.get("person"), str)
                and isinstance(child.get("link", "unknown"), str)
            )
            if not valid:
                raise TreeFormatError(f"{where}: invalid child entry")
        return cls(family_id, partners, relationship, children, data)

    def to_dict(self):
        return {
            "partners": self.partners,
            "relationship": self.relationship,
            "children": self.children,
            **self.extra,
        }

    @property
    def child_ids(self):
        return [child["person"] for child in self.children]


@dataclass
class Tree:
    people: dict = field(default_factory=dict)
    families: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    # One index shared while the window only looks (see `looking`); never while editing.
    _held_index: object = field(default=None, repr=False, compare=False)
    _held_depth: int = field(default=0, repr=False, compare=False)
    _held_cache: dict = field(default_factory=dict, repr=False, compare=False)

    def held(self, key, build):
        """build(), kept for the rest of a `looking` block; built fresh otherwise."""
        if self._held_depth == 0:
            return build()
        if key not in self._held_cache:
            self._held_cache[key] = build()
        return self._held_cache[key]

    def index(self):
        return self._held_index if self._held_index is not None else TreeIndex(self)

    @contextlib.contextmanager
    def looking(self):
        """While drawing or showing someone nothing changes the tree, so every lookup can
        share one index instead of rebuilding it (13 times per click, 80 ms each, on
        34,000 people). Edits must not happen inside."""
        if self._held_depth == 0:
            self._held_index = TreeIndex(self)
        self._held_depth += 1
        try:
            yield self
        finally:
            self._held_depth -= 1
            if self._held_depth == 0:
                self._held_index = None
                self._held_cache.clear()

    @classmethod
    def from_dict(cls, source):
        if not isinstance(source, dict):
            raise TreeFormatError("the top level is not an object")
        data = dict(source)
        data.pop("format_version", None)
        people = _take(data, "people", dict, {}, "tree")
        families = _take(data, "families", dict, {}, "tree")
        return cls(
            {key: Person.from_dict(key, value) for key, value in people.items()},
            {key: Family.from_dict(key, value) for key, value in families.items()},
            data,
        )

    def to_dict(self):
        return {
            "format_version": FORMAT_VERSION,
            "people": {key: value.to_dict() for key, value in self.people.items()},
            "families": {key: value.to_dict() for key, value in self.families.items()},
            **self.extra,
        }

    def families_of(self, person_id):
        """Families where this person is a partner, in file order."""
        return self.index().families_of(person_id)

    def birth_family_of(self, person_id):
        """The family this person is a child of, preferring a birth link."""
        return self.index().birth_family_of(person_id)

    def parent_families(self, person_id):
        """Every family this person is a child of, as (family, link), birth first."""
        return self.index().parent_families(person_id)

    def top_ancestor_of(self, person_id):
        """Climb through first-listed parents to the head of this person's family line."""
        index = self.index()
        seen = {person_id}
        current = person_id
        while True:
            family = index.birth_family_of(current)
            parents = [p for p in (family.partners if family else []) if p in self.people]
            if not parents or parents[0] in seen:
                return current
            current = parents[0]
            seen.add(current)

    def descendant_count(self, person_id, index=None):
        index = index or self.index()
        seen = set()
        stack = [person_id]
        while stack:
            for family in index.families_of(stack.pop()):
                for child in family.child_ids:
                    if child in self.people and child not in seen:
                        seen.add(child)
                        stack.append(child)
        return len(seen)

    def default_house_root(self):
        """The parentless person with the most descendants.

        A couple ties on descendants, so the partner listed first in their family
        heads the view. IDs are random and only make the final choice repeatable.
        """
        index = self.index()
        roots = [p for p in self.people if index.birth_family_of(p) is None]
        candidates = roots or list(self.people)
        if not candidates:
            return None

        def rank(person_id):
            listed_first = any(
                family.partners[0] == person_id for family in index.families_of(person_id)
            )
            return self.descendant_count(person_id, index), listed_first

        return max(sorted(candidates), key=rank)

    def family_line_heads(self):
        """Everyone who can head a view, biggest first, as (person id, descendants)."""
        index = self.index()
        roots = [p for p in self.people if index.birth_family_of(p) is None]
        # Someone who only married into families usually belongs under their partner,
        # but marriages across lines can leave nobody else, and the list must never be empty.
        firsts = [
            p for p in roots
            if not index.families_of(p) or any(f.partners[0] == p for f in index.families_of(p))
        ]
        heads = [(p, self.descendant_count(p, index)) for p in (firsts or roots or list(self.people))]
        heads.sort(key=lambda head: (-head[1], self.people[head[0]].display_name, head[0]))
        return heads


class TreeIndex:
    """Fast lookups for one moment of the tree. Build a new one after any change."""

    def __init__(self, tree):
        self._partner_of = {}
        self._child_of = {}
        for family in tree.families.values():
            for partner in family.partners:
                self._partner_of.setdefault(partner, []).append(family)
            for child in family.children:
                self._child_of.setdefault(child["person"], []).append((family, child))

    def families_of(self, person_id):
        return self._partner_of.get(person_id, [])

    def birth_family_of(self, person_id):
        entries = self._child_of.get(person_id)
        if not entries:
            return None
        return min(entries, key=lambda pair: pair[1].get("link") != "birth")[0]

    def parent_families(self, person_id):
        entries = self._child_of.get(person_id, [])
        ordered = sorted(entries, key=lambda pair: pair[1].get("link") != "birth")
        return [(family, child.get("link", "unknown")) for family, child in ordered]


@dataclass(frozen=True)
class Issue:
    code: str
    detail: str

    def message(self):
        return t(f"issue.{self.code}", detail=self.detail)


def photo_is_safe(path):
    if not path:
        return True
    if "\\" in path or PureWindowsPath(path).is_absolute() or PureWindowsPath(path).drive:
        return False
    parts = PurePosixPath(path).parts
    return len(parts) >= 2 and parts[0] == "media" and ".." not in parts


DOCUMENT_KINDS = ("certificate", "photo", "letter", "record", "newspaper", "other")


def person_documents(person):
    """The documents attached to someone: dicts with file, title, kind, date, private."""
    found = []
    for item in as_list(person.extra.get("documents")):
        if isinstance(item, dict) and isinstance(item.get("file"), str) and item["file"]:
            found.append({"file": item["file"], "title": str(item.get("title") or ""),
                          "kind": item.get("kind") if item.get("kind") in DOCUMENT_KINDS else "other",
                          "date": str(item.get("date") or ""), "private": bool(item.get("private"))})
    return found


def files_of(person):
    """Every file inside the tree folder this person refers to: the portrait and documents.
    Copying, sharing, combining and checking trees all go through here."""
    return [path for path in [person.photo] + [d["file"] for d in person_documents(person)] if path]


def validate(tree):
    """Report problems without changing anything. Data is never silently removed."""
    issues = []

    for person in tree.people.values():
        name = person.display_name
        if person.living not in LIVING_VALUES:
            issues.append(Issue("bad_living", name))
        for text in (person.birth_date, person.death_date):
            if text and parse_date(text) is None:
                issues.append(Issue("bad_date", name))
        if person.death is not None and person.living == "yes":
            issues.append(Issue("dead_marked_living", name))
        birth, death = parse_date(person.birth_date), parse_date(person.death_date)
        if birth and death and (death.end_year or death.year) < birth.year:
            issues.append(Issue("death_before_birth", name))
        if any(event["date"] and parse_date(event["date"]) is None for event in person_events(person)):
            issues.append(Issue("bad_date", name))
        if not photo_is_safe(person.photo):
            issues.append(Issue("unsafe_photo", name))
        if not all(photo_is_safe(d["file"]) for d in person_documents(person)):
            issues.append(Issue("unsafe_document", name))
    sources = tree_sources(tree)
    for _owner, _kind, fact in stored_facts(tree):
        for entry in clean_role_people(fact.get("people")):
            if entry.get("person") and entry["person"] not in tree.people:
                issues.append(Issue("missing_role_person", entry.get("name") or entry["person"]))
        for citation in clean_citations(fact.get("citations")):
            if citation["source"] not in sources:
                issues.append(Issue("missing_source", citation["source"]))
    for items in face_links(tree).values():
        for item in items:
            if item.get("person") and item["person"] not in tree.people:
                issues.append(Issue("missing_role_person", item.get("name") or item["person"]))
    records = place_records(tree)
    for name, record in records.items():
        if record.get("parent") and name in place_chain(tree, record["parent"], records):
            issues.append(Issue("place_loop", name))

    birth_links = {}
    for family in tree.families.values():
        members = family.partners + family.child_ids
        for member in set(members):
            if member not in tree.people:
                issues.append(Issue("missing_person", family.id))
        if len(family.partners) > 2:
            issues.append(Issue("too_many_partners", family.id))
        if len(set(family.child_ids)) < len(family.child_ids):
            issues.append(Issue("repeated_person", family.id))
        if len(set(family.partners)) < len(family.partners):
            issues.append(Issue("repeated_person", family.id))
        if set(family.partners) & set(family.child_ids):
            issues.append(Issue("own_child", family.id))
        if family.relationship not in RELATIONSHIPS:
            issues.append(Issue("bad_relationship", family.id))
        for child in family.children:
            link = child.get("link", "unknown")
            if link not in CHILD_LINKS:
                issues.append(Issue("bad_child_link", family.id))
            if link == "birth":
                birth_links[child["person"]] = birth_links.get(child["person"], 0) + 1

    for person_id, count in birth_links.items():
        if count > 1 and person_id in tree.people:
            issues.append(Issue("two_birth_families", tree.people[person_id].display_name))

    for person_id in _people_in_ancestor_loops(tree):
        issues.append(Issue("ancestor_loop", tree.people[person_id].display_name))
    for person_id in couples_related_by_descent(tree):
        issues.append(Issue("partner_is_ancestor", tree.people[person_id].display_name))
    return issues


def couples_related_by_descent(tree):
    """First partner of each couple where one partner descends from the other."""
    parents_of = {}
    for family in tree.families.values():
        for child in family.child_ids:
            parents_of.setdefault(child, set()).update(family.partners)
    memo = {}

    def ancestors(person_id):
        if person_id in memo:
            return memo[person_id]
        memo[person_id] = set()  # Guards against loops, which are reported separately.
        found = set()
        for parent in parents_of.get(person_id, ()):
            found.add(parent)
            found |= ancestors(parent)
        memo[person_id] = found
        return found

    related = []
    for family in tree.families.values():
        if len(family.partners) == 2 and all(p in tree.people for p in family.partners):
            a, b = family.partners
            if a in ancestors(b) or b in ancestors(a):
                related.append(a)
    return related


def _people_in_ancestor_loops(tree):
    """Everyone who is, through the records, their own ancestor. One pass over the tree
    (Tarjan's strongly connected groups): a person is in a loop when their group has
    more than one person, or they are their own child. Searching again from every
    person took 35 seconds on 34,000 people."""
    children_of = {}
    for family in tree.families.values():
        for parent in family.partners:
            children_of.setdefault(parent, set()).update(family.child_ids)

    index, low, on_stack, stack, looping, counter = {}, {}, set(), [], set(), [0]
    for root in tree.people:
        if root in index:
            continue
        work = [(root, iter(sorted(children_of.get(root, ()))))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            child = next(children, None)
            if child is not None:
                if child not in index:
                    index[child] = low[child] = counter[0]
                    counter[0] += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(children_of.get(child, ())))))
                elif child in on_stack:
                    low[node] = min(low[node], index[child])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                group = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group.append(member)
                    if member == node:
                        break
                if len(group) > 1 or node in children_of.get(node, ()):
                    looping.update(group)
    return [person for person in tree.people if person in looping]


def fold_text(text):
    """Lower case without accents, so "simic" finds Šimić and "dakovic" finds Đaković."""
    text = text.lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _year_bounds(text):
    """The earliest and latest year a date could mean, or (None, None) if unknown."""
    parsed = parse_date(text or "")
    if parsed is None:
        return None, None
    if parsed.end_year is not None:
        return parsed.year, parsed.end_year
    if parsed.qualifier == "from":  # A period: from its start to its end (if known).
        return parsed.year, parsed.end.year if parsed.end else None
    if parsed.qualifier == "to":
        return None, parsed.year
    if parsed.qualifier == "bef":
        return None, parsed.year
    if parsed.qualifier == "aft":
        return parsed.year, None
    if parsed.qualifier:  # "about": a couple of years either way.
        return parsed.year - 2, parsed.year + 2
    return parsed.year, parsed.year


def date_warnings(tree, person_id, today, index=None):
    """Dates that cannot all be right. Warnings only: old records are often uncertain.

    Each rule fires only when it is wrong however the uncertain dates are read.
    """
    index = index or TreeIndex(tree)  # Pass one in when checking many people.
    person = tree.people[person_id]
    name = person.display_name
    born_early, born_late = _year_bounds(person.birth_date)
    warnings = []
    for family, link in index.parent_families(person_id):
        if link != "birth":
            continue
        for parent_id in family.partners:
            parent = tree.people.get(parent_id)
            if parent is None:
                continue
            p_early, _p_late = _year_bounds(parent.birth_date)
            if p_early is not None and born_late is not None and p_early + 12 > born_late:
                warnings.append(t("warn_parent_too_young", parent=parent.display_name, child=name))
            _d_early, d_late = _year_bounds(parent.death_date)
            grace = 0 if parent.sex == "F" else 1
            if d_late is not None and born_early is not None and born_early > d_late + grace:
                warnings.append(t("warn_born_after_parent_died", parent=parent.display_name, child=name))
    # Found by the MCP sweep: a birth in 2090 was taken without a word. A year after this one
    # cannot be right, however the date is read.
    if born_early is not None and born_early > today.year:
        warnings.append(t("warn_born_future", name=name, year=born_early))
    died_early, _died_late = _year_bounds(person.death_date)
    if died_early is not None and died_early > today.year:
        warnings.append(t("warn_died_future", name=name, year=died_early))
    if person.living == "yes" and born_late is not None and today.year - born_late > 110:
        warnings.append(t("warn_too_old", name=name, age=today.year - born_late))
    for family in index.families_of(person_id):
        for partner_id in family.partners:
            partner = tree.people.get(partner_id)
            if partner is None or partner_id == person_id:
                continue
            _d_early, d_late = _year_bounds(partner.death_date)
            if d_late is not None and born_early is not None and born_early > d_late:
                warnings.append(t("warn_born_after_partner_died", name=name, partner=partner.display_name))
    return warnings


# Life events beyond birth and death, kept in a person's "events" list. Each is
# {"type", "date", "place", "text"} plus the citations and people every fact can have.
EVENT_TYPES = ("occupation", "residence", "religion", "education", "baptism", "burial",
               "emigration", "military", "other",
               # Read from other programs' files (GEDCOM's standard events and facts).
               "rank", "nationality", "immigration", "naturalisation", "census", "confirmation",
               "first_communion", "ordination", "graduation", "retirement", "will", "probate",
               "cremation", "adoption", "property", "description")
EVENT_FIELDS = ("type", "date", "place", "text")

# Every fact (birth, death, a life event, a marriage, another name) can have:
#   "citations": [{"source": source id, "page": "p. 47, no. 112", "quality": ..., "document": file}]
#   "people":    [{"person": person id or "", "name": "as written", "role": ...}]
# Sources themselves live once in the tree: tree.extra["sources"] = {id: {"title", ...}}.
CITATION_QUALITIES = ("original", "copy", "family", "unknown")
ROLES = ("godfather", "godmother", "witness", "priest", "informant", "midwife", "other")
NAME_TYPES = ("birth", "married", "nickname", "latin", "other")
SOURCE_FIELDS = ("title", "author", "repository", "note")


def clean_citations(value):
    found = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict) and isinstance(item.get("source"), str) and item["source"]:
            entry = {"source": item["source"]}
            for key in ("page", "document", "text"):
                if isinstance(item.get(key), str) and item[key].strip():
                    entry[key] = item[key].strip()
            if item.get("quality") in CITATION_QUALITIES and item["quality"] != "unknown":
                entry["quality"] = item["quality"]
            if entry not in found:
                found.append(entry)
    return found


def clean_role_people(value):
    found = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        person = item.get("person") if isinstance(item.get("person"), str) else ""
        name = item.get("name").strip() if isinstance(item.get("name"), str) else ""
        if not person and not name:
            continue
        entry = {"role": item.get("role") if item.get("role") in ROLES else "other"}
        if person:
            entry["person"] = person
        if name:
            entry["name"] = name
        if entry not in found:
            found.append(entry)
    return found


# A fact can also say, as other programs write them: the person's age then, an address,
# a cause (of death, mostly), and the file tag it came as when that is not our usual one.
FACT_EXTRAS = ("age", "address", "cause", "label", "text_on")


def fact_details(fact):
    """The citations, people and extras of a stored fact, cleaned, only the ones present."""
    details = {}
    if isinstance(fact, dict):
        for key in FACT_EXTRAS:
            if isinstance(fact.get(key), str) and fact[key].strip():
                details[key] = fact[key].strip()
        if isinstance(fact.get("tag"), str) and re.fullmatch(r"_?[A-Z][A-Z0-9_]{1,30}", fact["tag"]):
            details["tag"] = fact["tag"]
        citations, people = clean_citations(fact.get("citations")), clean_role_people(fact.get("people"))
        if citations:
            details["citations"] = citations
        if people:
            details["people"] = people
    return details


def person_events(person):
    """A person's life events, skipping anything malformed (say, from a hand-edited file)."""
    events = person.extra.get("events")
    if not isinstance(events, list):
        return []
    clean = []
    for event in events:
        if isinstance(event, dict) and event.get("type") in EVENT_TYPES:
            clean.append({**{key: str(event.get(key, "") or "") for key in EVENT_FIELDS}, **fact_details(event)})
    return clean


def family_marriage(family):
    """A couple's marriage date and place (empty strings when not known), with its
    citations and witnesses when there are any."""
    marriage = family.extra.get("marriage")
    marriage = marriage if isinstance(marriage, dict) else {}
    return {**{key: str(marriage.get(key, "") or "") for key in ("date", "place")}, **fact_details(marriage)}


def person_names(person):
    """Other names: as written in a record, a married name, a nickname, a Latin form."""
    found = []
    for item in as_list(person.extra.get("names")):
        if isinstance(item, dict) and (str(item.get("given") or "").strip() or str(item.get("surname") or "").strip()):
            entry = {"given": str(item.get("given") or "").strip(), "surname": str(item.get("surname") or "").strip(),
                     "type": item.get("type") if item.get("type") in NAME_TYPES else "other",
                     "date": str(item.get("date") or "")}
            if isinstance(item.get("written"), str) and item["written"].strip():
                entry["written"] = item["written"].strip()  # As another program wrote it.
            found.append({**entry, **fact_details(item)})
    return found


# Bookkeeping lines other programs add (record numbers, change stamps): kept and written
# back, but not worth showing.
BOOKKEEPING_TAGS = {"RIN", "_UID", "_UPD", "CHAN", "_PRIM", "UID", "EXID", "REFN", "_FSFTID", "_APID",
                    "_MTTAG", "_TID", "_PID", "_DATI"}


def kept_details(tree, lines, limit=25):
    """Lines kept from another program's file, readable: "BIRT › TIME 10:30". People they
    point at are shown by name. Bookkeeping is left out."""
    shown, path = [], {}
    for line in lines if isinstance(lines, list) else []:
        if not isinstance(line, str):
            continue
        wrapper = line.startswith("~")
        match = re.match(r"^(\d{1,2}) (?:@[^@]+@ )?([A-Za-z0-9_]+)(?:#\d+)?(?: (.*))?$", line[1:] if wrapper else line)
        if not match:
            continue
        level, tag, value = int(match[1]), match[2].upper(), match[3] or ""
        path = {k: v for k, v in path.items() if k < level}
        path[level] = tag
        if wrapper:
            continue
        if tag in ("CONC", "CONT") and shown:
            shown[-1] += ("" if tag == "CONC" else " ") + value
            continue
        if set(path.values()) & BOOKKEEPING_TAGS:
            continue
        if tag in ("GIVN", "SURN") and path.get(level - 1) == "NAME":
            continue  # The pieces of a name already shown as the name.

        def name(found):
            kind, key = found[1], found[2]
            if kind == "p" and key in tree.people:
                return tree.people[key].display_name
            return "…"
        value = re.sub(r"@ft:([a-z]):([^@]+)@", name, value).replace("@@", "@")
        where = " › ".join(path[k] for k in sorted(path) if k < level)
        shown.append(f"{where} › {tag} {value}".strip(" ›") if where else f"{tag} {value}".strip())
    return shown[:limit] + (["…"] if len(shown) > limit else [])


def tree_sources(tree):
    """{source id: {"title", "author", "repository", "note"}} for every source record."""
    found = {}
    sources = tree.extra.get("sources")
    for source_id, item in (sources.items() if isinstance(sources, dict) else []):
        if isinstance(item, dict):
            found[source_id] = {key: str(item.get(key) or "") for key in SOURCE_FIELDS}
    return found


def stored_facts(tree):
    """Every stored fact dict as (owner id, kind, the dict itself), for code that must
    see or change all of them: references to people and sources live only in these."""
    for person in tree.people.values():
        for kind, fact in (("birth", person.birth), ("death", person.death)):
            if isinstance(fact, dict):
                yield person.id, kind, fact
        for key in ("events", "names"):
            items = person.extra.get(key)
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict):
                    yield person.id, item.get("type", key) if key == "events" else "name", item
    for family in tree.families.values():
        marriage = family.extra.get("marriage")
        if isinstance(marriage, dict):
            yield family.id, "marriage", marriage


# Places: records keyed by the exact place text facts use ("Trogir"), so files stay
# readable by 1.1, which knows only the text. Each record: the place it lies in (another
# key), what kind of place it is, coordinates, and older names with the years they ended.
PLACE_KINDS = ("village", "town", "parish", "municipality", "county", "region", "country", "other")


def place_records(tree):
    found = {}
    places = tree.extra.get("places")
    for name, item in (places.items() if isinstance(places, dict) else []):
        if not isinstance(name, str) or not name.strip() or not isinstance(item, dict):
            continue
        record = {}
        if isinstance(item.get("parent"), str) and item["parent"].strip() and item["parent"] != name:
            record["parent"] = item["parent"]
        if item.get("kind") in PLACE_KINDS:
            record["kind"] = item["kind"]
        lat, lon = item.get("lat"), item.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and -90 <= lat <= 90 and -180 <= lon <= 180:
            record["lat"], record["lon"] = float(lat), float(lon)
        old = [{"name": str(o["name"]).strip(), **({"until": str(o["until"])} if o.get("until") else {})}
               for o in as_list(item.get("old_names")) if isinstance(o, dict) and str(o.get("name") or "").strip()]
        if old:
            record["old_names"] = old
        if isinstance(item.get("note"), str) and item["note"].strip():
            record["note"] = item["note"].strip()
        found[name] = record
    return found


def fact_places(tree):
    """Every place text facts use, with how many facts use it."""
    counts = {}
    for _owner, _kind, fact in stored_facts(tree):
        place = fact.get("place")
        if isinstance(place, str) and place.strip():
            counts[place] = counts.get(place, 0) + 1
    return counts


def place_chain(tree, name, records=None):
    """[name, the place it lies in, and so on up]; stops at a loop."""
    records = place_records(tree) if records is None else records
    chain = [name]
    while records.get(chain[-1], {}).get("parent") and records[chain[-1]]["parent"] not in chain:
        chain.append(records[chain[-1]]["parent"])
    return chain


def place_coordinates(tree, name, records=None):
    """(lat, lon) of a place, or of the nearest place above it that has them, or None."""
    records = place_records(tree) if records is None else records
    for step in place_chain(tree, name, records):
        if "lat" in records.get(step, {}):
            return records[step]["lat"], records[step]["lon"]
    return None


def person_tasks(person):
    """Research to-do items for someone: [{"text", "done", "note"}]. Never shared."""
    return [{"text": str(item["text"]).strip(), "done": bool(item.get("done")), "note": str(item.get("note") or "")}
            for item in as_list(person.extra.get("tasks"))
            if isinstance(item, dict) and str(item.get("text") or "").strip()]


def person_story(person):
    story = person.extra.get("story")
    return story.strip() if isinstance(story, str) else ""


def face_links(tree):
    """Faces marked in pictures: {stored file: [{"rect": [x, y, w, h], "person" or "name"}]}.
    The rectangle is a fraction of the picture the right way up, so it fits at any size.
    Kept per file, not per document entry: a group photo attached to several people has
    one set of faces, and editing someone's documents can't lose them."""
    found = {}
    faces = tree.extra.get("faces")
    for path, items in (faces.items() if isinstance(faces, dict) else []):
        clean = []
        for item in items if isinstance(items, list) else []:
            rect = item.get("rect") if isinstance(item, dict) else None
            if not (isinstance(rect, list) and len(rect) == 4 and all(isinstance(v, (int, float)) for v in rect)):
                continue
            x, y, w, h = (min(1.0, max(0.0, float(v))) for v in rect)
            if w <= 0 or h <= 0:
                continue
            entry = {"rect": [x, y, min(w, 1 - x), min(h, 1 - y)]}
            if isinstance(item.get("person"), str) and item["person"]:
                entry["person"] = item["person"]
            if isinstance(item.get("name"), str) and item["name"].strip():
                entry["name"] = item["name"].strip()
            clean.append(entry)
        if clean:
            found[path] = clean
    return found


def photos_of(tree, person_id):
    """Pictures where this person's face is marked: [(stored file, title)]."""
    titles = tree.held("document_titles", lambda: {
        d["file"]: d["title"] for person in tree.people.values() for d in person_documents(person)})
    links = tree.held("face_links", lambda: face_links(tree))
    return [(path, titles.get(path, "")) for path, items in links.items()
            if any(item.get("person") == person_id for item in items) and path in titles]


def not_duplicates(tree):
    """Pairs someone confirmed are different people, so the duplicate finder skips them."""
    pairs = tree.extra.get("not_duplicates")
    found = []
    for pair in pairs if isinstance(pairs, list) else []:
        if isinstance(pair, list) and len(pair) == 2 and all(isinstance(p, str) for p in pair) and pair[0] != pair[1]:
            if sorted(pair) not in found:
                found.append(sorted(pair))
    return found


def remap_people(tree, mapping, names=None, keep_unknown=True):
    """Every place one person points at another (people at events, faces in pictures,
    not-duplicate marks) after people change ids. `mapping`: old id -> new id, or None
    for someone deleted (their written name is kept where there is room for it). With
    keep_unknown=False, ids not in `mapping` go too (a relative's tree being copied in)."""
    names = names or {}

    def moved(entry):
        old = entry.get("person")
        if not old:
            return entry
        if old in mapping and mapping[old]:
            return {**entry, "person": mapping[old]}
        if old in mapping or not keep_unknown:
            entry = {k: v for k, v in entry.items() if k != "person"}
            if names.get(old) and not entry.get("name"):
                entry["name"] = names[old]
        return entry

    for _owner, _kind, fact in stored_facts(tree):
        if isinstance(fact.get("people"), list):
            people = []
            for entry in fact["people"]:
                if isinstance(entry, dict):
                    entry = moved(entry)
                    if (entry.get("person") or entry.get("name")) and entry not in people:
                        people.append(entry)
            if people:
                fact["people"] = people
            else:
                fact.pop("people")
    def token(found):
        new = mapping.get(found[1]) if found[1] in mapping else (found[1] if keep_unknown else None)
        return f"@ft:p:{new}@" if new else f"@ft:x:{found[1]}@"  # Gone: that line is not written.
    for person in tree.people.values():  # DNA matches linked to someone in the tree.
        dna = person.extra.get("dna")
        for test in as_list(dna.get("tests") if isinstance(dna, dict) else None):
            for match in as_list(test.get("matches") if isinstance(test, dict) else None):
                if isinstance(match, dict) and match.get("person"):
                    match["person"] = moved({"person": match["person"]}).get("person", "")
    holders = [p.extra for p in tree.people.values()] + [f.extra for f in tree.families.values()]
    for holder in holders:  # Lines kept from another program's file that name someone.
        if isinstance(holder.get("gedcom"), list):
            holder["gedcom"] = [re.sub(r"@ft:p:([^@]+)@", token, line) if isinstance(line, str) else line
                                for line in holder["gedcom"]]
    faces = face_links(tree)
    for path, items in faces.items():
        kept = []
        for item in items:  # A face whose person went stays, unnamed; one face is listed once.
            item = moved(item)
            if item not in kept:
                kept.append(item)
        faces[path] = kept
    if faces:
        tree.extra["faces"] = faces
    else:
        tree.extra.pop("faces", None)
    pairs = []
    for a, b in not_duplicates(tree):
        a, b = (mapping.get(a, a if keep_unknown else None), mapping.get(b, b if keep_unknown else None))
        if a and b and a != b and sorted([a, b]) not in pairs:
            pairs.append(sorted([a, b]))
    if pairs:
        tree.extra["not_duplicates"] = pairs
    else:
        tree.extra.pop("not_duplicates", None)


def roles_of(tree, person_id):
    """Where someone appears in other people's records: [(role, owner id, kind, fact)]."""
    def everyone():
        found = {}
        for owner, kind, fact in stored_facts(tree):
            for entry in clean_role_people(fact.get("people")):
                if entry.get("person"):
                    found.setdefault(entry["person"], []).append((entry["role"], owner, kind, fact))
        return found
    return list(tree.held("roles", everyone).get(person_id, []))


def cited_sources(tree):
    """{source id: number of citations}."""
    counts = {}
    for _owner, _kind, fact in stored_facts(tree):
        for citation in clean_citations(fact.get("citations")):
            counts[citation["source"]] = counts.get(citation["source"], 0) + 1
    return counts


@dataclass
class FactRow:
    """One thing that happened, for the places list, the timeline and map pins."""
    person_id: str
    kind: str  # "birth", "death", "marriage" or a life event type.
    date: str  # Stored form, may be empty.
    place: str
    text: str = ""
    with_id: str = ""  # The partner, for a marriage.


def all_facts(tree):
    """Every birth, death, marriage and life event in the tree."""
    rows = []
    for person in tree.people.values():
        for kind, event in (("birth", person.birth), ("death", person.death)):
            if event and (event.get("date") or event.get("place")):
                rows.append(FactRow(person.id, kind, event.get("date", ""), event.get("place", "")))
        for event in person_events(person):
            rows.append(FactRow(person.id, event["type"], event["date"], event["place"], event["text"]))
    for family in tree.families.values():
        marriage = family_marriage(family)
        partners = [p for p in family.partners if p in tree.people]
        if (marriage["date"] or marriage["place"]) and partners:
            other = partners[1] if len(partners) > 1 else ""
            rows.append(FactRow(partners[0], "marriage", marriage["date"], marriage["place"], with_id=other))
    return rows


def fact_year(row):
    parsed = parse_date(row.date)
    return parsed.year if parsed else None
