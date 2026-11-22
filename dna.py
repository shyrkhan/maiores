"""DNA: tests, matches, segments and raw files, and what the shared amount says about a
relationship. No interface code here.

Stored per person in extra["dna"] = {"tests": [test, ...]}, each test:
    {"id", "company", "kind": "autosomal" | "y" | "mt", "kit", "haplogroup", "notes",
     "raw": {"file", "snps", "build", "sex"}             a raw data file kept in the tree folder
     "matches":  [{"id", "name", "cm", "segments", "longest", "guess", "person", "notes", "source"}],
     "segments": [{"match", "chr", "start", "end", "cm", "snps"}]}
"person" links a match to someone in the tree. DNA never leaves the computer with shared
copies, web pages or GEDCOM files (privacy.py, gedcom.py).

Relationship ranges: the Shared cM Project, version 4 (March 2020), by Blaine T. Bettinger,
CC BY 4.0 (thegeneticgenealogist.com); the averages more distant than half second cousin
count only the cousins who share any DNA at all. The figures do not allow for endogamy or
pedigree collapse (cousin marriages), which raise the amounts.
"""
import bisect
import csv
import gzip
import io
import json
import re
import uuid
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAP_FILE = ROOT / "assets" / "genetic_map_grch37.json.gz"
COMPANIES = ("MyHeritage", "Ancestry", "23andMe", "FamilyTreeDNA", "GEDmatch", "LivingDNA", "Other")
KINDS = ("autosomal", "y", "mt")
RAW_DIR = "dna"  # Raw files live in the tree's folder; shared copies never take them.
AUTOSOMES = [str(n) for n in range(1, 23)]

# (generations up from the tester, down to the match, half) -> (average, low, high) cM.
# Shared cM Project v4; reversed pairs (grandparent / grandchild) share the same figures.
_TABLE = {
    (1, 0, False): (3485, 2376, 3720), (0, 1, False): (3487, 2376, 3720),
    (1, 1, False): (2613, 1613, 3488), (1, 1, True): (1759, 1160, 2436),
    (2, 0, False): (1754, 984, 2462), (0, 2, False): (1754, 984, 2462),
    (2, 1, False): (1741, 1201, 2282), (1, 2, False): (1740, 1201, 2282),
    (2, 1, True): (871, 492, 1315), (1, 2, True): (871, 492, 1315),
    (3, 0, False): (887, 485, 1486), (0, 3, False): (887, 485, 1486),
    (3, 1, False): (850, 330, 1467), (1, 3, False): (850, 330, 1467),
    (3, 1, True): (431, 184, 668), (1, 3, True): (431, 184, 668),
    (4, 1, False): (420, 186, 713), (1, 4, False): (420, 186, 713),
    (4, 1, True): (208, 103, 284), (1, 4, True): (208, 103, 284),
    (2, 2, False): (866, 396, 1397), (2, 2, True): (449, 156, 979),
    (3, 2, False): (433, 102, 980), (2, 3, False): (433, 102, 980),
    (3, 2, True): (224, 62, 469), (2, 3, True): (224, 62, 469),
    (4, 2, False): (221, 33, 471), (2, 4, False): (221, 33, 471),
    (4, 2, True): (125, 16, 269), (2, 4, True): (125, 16, 269),
    (5, 2, False): (117, 25, 238), (2, 5, False): (117, 25, 238),
    (5, 2, True): (60, 0, 120), (2, 5, True): (60, 0, 120),
    (3, 3, False): (229, 41, 592), (3, 3, True): (120, 10, 325),
    (4, 3, False): (122, 14, 353), (3, 4, False): (122, 14, 353),
    (4, 3, True): (66, 0, 190), (3, 4, True): (66, 0, 190),
    (5, 3, False): (71, 0, 244), (3, 5, False): (71, 0, 244),
    (5, 3, True): (48, 0, 144), (3, 5, True): (48, 0, 144),
    (6, 3, False): (51, 0, 154), (3, 6, False): (51, 0, 154),
    (4, 4, False): (73, 0, 234), (4, 4, True): (48, 0, 168),
    (5, 4, False): (48, 0, 192), (4, 5, False): (48, 0, 192),
    (5, 4, True): (37, 0, 139), (4, 5, True): (37, 0, 139),
    (6, 4, False): (36, 0, 166), (4, 6, False): (36, 0, 166),
    (6, 4, True): (27, 0, 78), (4, 6, True): (27, 0, 78),
    (7, 4, False): (27, 0, 98), (4, 7, False): (27, 0, 98),
    (5, 5, False): (35, 0, 139),
    (6, 5, False): (28, 0, 126), (5, 6, False): (28, 0, 126),
    (7, 5, False): (22, 0, 93), (5, 7, False): (22, 0, 93),
    (8, 5, False): (19, 0, 60), (5, 8, False): (19, 0, 60),
    (6, 6, False): (25, 0, 117),
    (7, 6, False): (21, 0, 80), (6, 7, False): (21, 0, 80),
    (8, 6, False): (18, 0, 65), (6, 8, False): (18, 0, 65),
    (9, 6, False): (13, 0, 30), (6, 9, False): (13, 0, 30),
    (7, 7, False): (18, 0, 71),
    (8, 7, False): (15, 0, 56), (7, 8, False): (15, 0, 56),
    (9, 7, False): (13, 0, 45), (7, 9, False): (13, 0, 45),
    (8, 8, False): (14, 0, 57),
    (9, 8, False): (12, 0, 50), (8, 9, False): (12, 0, 50),
    (9, 9, False): (11, 0, 42),
}
CREDIT = "Shared cM Project v4 (2020), Blaine T. Bettinger, CC BY 4.0"
GENOME_CM = 7440  # 23andMe's "percent shared" is of this many cM (both copies of 22 autosomes and X).


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4()}"


# Stored data, cleaned the way model.py cleans everything read from a file.
def _number(value, whole=False):
    try:
        number = float(str(value).replace(",", ".")) if value not in (None, "") else None
    except ValueError:
        return None
    if number is None or number != number or number < 0 or number > 1e9:
        return None
    return int(number) if whole else round(number, 2)


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def clean_match(item):
    if not isinstance(item, dict):
        return None
    match = {"id": _text(item.get("id")) or new_id("m"), "name": _text(item.get("name")),
             "cm": _number(item.get("cm"))}
    for key in ("segments",):
        match[key] = _number(item.get(key), whole=True)
    match["longest"] = _number(item.get("longest"))
    for key in ("guess", "person", "notes", "source"):
        match[key] = _text(item.get(key))
    if _text(item.get("kit")):
        match["kit"] = _text(item.get("kit"))  # The company's id for the match: names repeat.
    if item.get("from_segments") is True:
        match["from_segments"] = True  # The totals were added up here, from its segments.
    return match if match["name"] or match["person"] else None


def clean_segment(item):
    if not isinstance(item, dict):
        return None
    chromosome = _text(str(item.get("chr", ""))).upper().replace("CHR", "")
    start, end = _number(item.get("start"), whole=True), _number(item.get("end"), whole=True)
    if chromosome not in AUTOSOMES + ["X"] or start is None or end is None or end <= start:
        return None
    return {"match": _text(item.get("match")), "chr": chromosome, "start": start, "end": end,
            "cm": _number(item.get("cm")), "snps": _number(item.get("snps"), whole=True)}


def clean_test(item):
    if not isinstance(item, dict):
        return None
    test = {"id": _text(item.get("id")) or new_id("t"),
            "company": _text(item.get("company")) or "Other",
            "kind": item.get("kind") if item.get("kind") in KINDS else "autosomal"}
    for key in ("kit", "haplogroup", "notes"):
        test[key] = _text(item.get(key))
    raw = item.get("raw")
    if isinstance(raw, dict) and _text(raw.get("file")):
        test["raw"] = {"file": _text(raw.get("file")), "snps": _number(raw.get("snps"), whole=True) or 0,
                       "build": _text(raw.get("build")), "sex": _text(raw.get("sex"))}
    matches = [m for m in map(clean_match, item.get("matches") or []) if m]
    test["matches"] = matches
    ids = {m["id"] for m in matches}
    test["segments"] = [s for s in map(clean_segment, item.get("segments") or []) if s and s["match"] in ids]
    return test


def tests_of(person):
    dna = person.extra.get("dna")
    items = dna.get("tests") if isinstance(dna, dict) else None
    return [t for t in map(clean_test, items if isinstance(items, list) else []) if t]


def store_tests(person, tests):
    if tests:
        person.extra["dna"] = {"tests": tests}
    else:
        person.extra.pop("dna", None)


def all_matches(tree):
    """[(tester id, test, match)] across the tree."""
    found = []
    for person_id, person in tree.people.items():
        for test in tests_of(person):
            for match in test["matches"]:
                found.append((person_id, test, match))
    return found


# What a shared amount could mean.
def ranges():
    return dict(_TABLE)


def expected(up, down, half=False):
    """(average, low, high) for a relation, or None when the project has no figures."""
    return _TABLE.get((up, down, bool(half) and up >= 1 and down >= 1))


def possible(cm, limit=8):
    """Relations whose range holds this amount, most likely first: [(up, down, half, figures)].
    Reversed pairs (aunt / niece) are listed once, with up >= down."""
    if cm is None:
        return []
    found = {}
    for (up, down, half), (avg, low, high) in _TABLE.items():
        if low <= cm <= high:
            found.setdefault((max(up, down), min(up, down), half), (avg, low, high))
    import math
    order = sorted(found.items(), key=lambda item: abs(math.log((cm + 1) / (item[1][0] + 1))))
    return [(up, down, half, figures) for (up, down, half), figures in order][:limit]


def check(tree, tester, match):
    """How a linked match's DNA fits the tree: ("fits" | "low" | "high" | "unrelated" |
    "unknown", relation or None, figures or None). "unknown": no figures for that relation."""
    import kinship
    other = match.get("person")
    if not other or other not in tree.people or match.get("cm") is None:
        return "unknown", None, None
    relation = kinship.blood_relation(tree, tester, other)
    if relation is None or relation.kind != "blood":
        return "unrelated", relation, None
    figures = expected(relation.up, relation.down, relation.half)
    if figures is None:
        return "unknown", relation, None
    avg, low, high = figures
    cm = match["cm"]
    return ("fits" if low <= cm <= high else "low" if cm < low else "high"), relation, figures


# Reading match lists and segment files (CSV from MyHeritage, FamilyTreeDNA, GEDmatch,
# 23andMe...). Their column names differ and change, so columns are found by meaning.
def _key(header):
    return re.sub(r"[^a-z0-9#%]", "", header.lower())


def _find(headers, *wanted, avoid=()):
    for want in wanted:
        for index, header in enumerate(headers):
            key = _key(header)
            if want(key) and not any(a in key for a in avoid):
                return index
    return None


def _cm_value(text):
    """'250', '250 cM', '3.5% (250 cM)', '1,234.5' -> cM; None if no number."""
    text = (text or "").strip()
    found = re.search(r"([\d.,]+)\s*cm", text, re.IGNORECASE)
    number = found[1] if found else (re.search(r"[\d.,]+", text) or [None])[0]
    if number is None:
        return None
    number = number.strip(".,")
    if "," in number and "." in number:  # Whichever comes last is the decimal mark.
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")  # 1.234,5
        else:
            number = number.replace(",", "")  # 1,234.5
    elif "," in number:
        thousands = re.fullmatch(r"\d{1,3}(,\d{3})+", number)
        number = number.replace(",", "") if thousands else number.replace(",", ".")
    return _number(number)


KIT_COLUMNS = ("kit", "kitnumber", "kitid", "matchkit", "matchkitid", "matchid", "matchguid", "testid",
               "matchtestid", "profileid", "kit2")


def read_table(data):
    """A CSV file's rows as (headers, rows), whatever the separator and encoding."""
    # UTF-16 only when the file says so (a byte-order mark, or the zero bytes it is full
    # of): tried blindly, any even-length Windows file "decodes" as UTF-16 nonsense.
    utf16 = data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in data[:4000]
    for encoding in ("utf-8-sig",) + (("utf-16",) if utf16 else ()) + ("cp1252",):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1")
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return [], []
    try:
        dialect = csv.Sniffer().sniff(lines[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO("\n".join(lines)), dialect))
    return [h.strip() for h in rows[0]], [r for r in rows[1:] if any(c.strip() for c in r)]


def read_match_file(data, source=""):
    """("matches", [match]) or ("segments", [(match name, segment)]), or ("unknown", [])."""
    headers, rows = read_table(data)
    if not headers:
        return "unknown", []
    chromosome = _find(headers, lambda k: k in ("chromosome", "chr", "chrom"))
    start = _find(headers, lambda k: "start" in k and ("loc" in k or "pos" in k or k in ("start", "b37start", "b36start")))
    end = _find(headers, lambda k: ("end" in k or "stop" in k) and ("loc" in k or "pos" in k or k in ("end", "b37end", "b36end", "stop")))
    if chromosome is not None and start is not None and end is not None:
        name = _find(headers, lambda k: k == "matchname", lambda k: k in ("name", "kit2name", "matchingkitname"),
                     lambda k: "name" in k)
        cm = _find(headers, lambda k: "centimorgan" in k or k in ("cm", "segmentcm", "lengthcm"))
        snps = _find(headers, lambda k: "snp" in k)
        kit = _find(headers, lambda k: k in KIT_COLUMNS)
        found = []
        for row in rows:
            cell = lambda i: row[i].strip() if i is not None and i < len(row) else ""
            segment = clean_segment({"match": "x", "chr": cell(chromosome), "start": cell(start).replace(",", ""),
                                     "end": cell(end).replace(",", ""), "cm": _cm_value(cell(cm)),
                                     "snps": cell(snps).replace(",", "")})
            if segment and cell(name):
                found.append((cell(name), segment, cell(kit)))
        return "segments", found
    name = _find(headers, lambda k: k in ("fullname", "matchname", "displayname", "name"),
                 lambda k: k.endswith("name") and "first" not in k and "last" not in k and "middle" not in k
                 and "manager" not in k and "kit" not in k)
    first = _find(headers, lambda k: k == "firstname")
    last = _find(headers, lambda k: k in ("lastname", "surname"))
    longest = _find(headers, lambda k: "largest" in k or "longest" in k)
    cm = _find(headers, lambda k: ("cm" in k or "centimorgan" in k or (("shared" in k or "total" in k) and "dna" in k))
               and "%" not in k and "percent" not in k, avoid=("largest", "longest", "segments"))
    percent = _find(headers, lambda k: ("percent" in k or "%" in k) and ("dna" in k or "shared" in k))
    segments = _find(headers, lambda k: "segment" in k and "largest" not in k and "longest" not in k)
    kit = _find(headers, lambda k: k in KIT_COLUMNS)
    guess = _find(headers, lambda k: "estimatedrelationship" in k or "relationshiprange" in k or
                  "suggestedrelationship" in k or "predictedrelationship" in k or k == "relationship")
    if (name is None and first is None) or (cm is None and percent is None):
        return "unknown", []
    matches = []
    for row in rows:
        cell = lambda i: row[i].strip() if i is not None and i < len(row) else ""
        who = cell(name) or " ".join(x for x in (cell(first), cell(last)) if x)
        if cell(name) and cell(last) and cell(last).casefold() not in who.casefold():
            who = f"{who} {cell(last)}"  # 23andMe: "Display Name" and "Surname" apart.
        amount = _cm_value(cell(cm)) if cm is not None else None
        if amount is None and percent is not None:  # 23andMe: share of the whole genome.
            share = _cm_value(cell(percent).replace("%", ""))
            amount = round(share * GENOME_CM / 100, 1) if share is not None else None
        match = clean_match({"name": who, "kit": cell(kit), "cm": amount, "segments": _cm_value(cell(segments)),
                             "longest": _cm_value(cell(longest)), "guess": cell(guess), "source": source})
        if match:
            matches.append(match)
    return "matches", matches


def _index(test):
    """Lookups for a test's matches: by kit id, and by name (a list: names repeat)."""
    by_kit = {m["kit"]: m for m in test["matches"] if m.get("kit")}
    by_name = {}
    for match in test["matches"]:
        if match["name"]:
            by_name.setdefault(match["name"].casefold(), []).append(match)
    return by_kit, by_name


def _existing(by_kit, by_name, name, kit, used):
    """The match a row means: the same kit id when the row has one; otherwise the next
    match of that name this file hasn't already used (two Ana rows mean two Anas, and the
    same file read again finds the same two). A match with another kit id is never taken."""
    if kit and kit in by_kit:
        return by_kit[kit]
    for match in by_name.get(name.casefold(), []):
        if id(match) in used or (kit and match.get("kit") and match["kit"] != kit):
            continue
        return match
    return None


def add_matches(test, matches):
    """New matches join the test; one already there gets the new figures, and keeps its
    link and notes (see _existing for which one is "already there"). Returns (added, updated)."""
    by_kit, by_name = _index(test)
    used = set()
    added = updated = 0
    for match in matches:
        old = _existing(by_kit, by_name, match["name"], match.get("kit", ""), used)
        if old is None:
            test["matches"].append(match)
            by_name.setdefault(match["name"].casefold(), []).append(match)
            if match.get("kit"):
                by_kit[match["kit"]] = match
            used.add(id(match))
            added += 1
            continue
        used.add(id(old))
        if match.get("kit"):
            old["kit"] = match["kit"]
            by_kit[match["kit"]] = old
        for key in ("cm", "segments", "longest", "guess", "source"):
            if match.get(key) not in (None, ""):
                old[key] = match[key]
        if match.get("cm") is not None:
            old.pop("from_segments", None)  # The company's own figures win from now on.
        updated += 1
    return added, updated


def add_segments(test, found, source=""):
    """Segments by match (name, segment) or (name, segment, kit id): joined to the test's
    match with that kit id, else the first of that name, or a new match made from them.
    A segment already there (same match and place) is not added twice."""
    by_kit, by_name = _index(test)
    have = {(s["match"], s["chr"], s["start"], s["end"]) for s in test["segments"]}
    added = 0
    for entry in found:
        name, segment = entry[0], entry[1]
        kit = entry[2] if len(entry) > 2 else ""
        match = _existing(by_kit, by_name, name, kit, set())
        if match is None:
            match = clean_match({"name": name, "kit": kit, "source": source})
            test["matches"].append(match)
            by_name.setdefault(name.casefold(), []).append(match)
            if kit:
                by_kit[kit] = match
        segment = {**segment, "match": match["id"]}
        if segment["cm"] is None:
            segment["cm"] = round(segment_cm(segment["chr"], segment["start"], segment["end"]), 2)
        key = (segment["match"], segment["chr"], segment["start"], segment["end"])
        if key not in have:
            test["segments"].append(segment)
            have.add(key)
            added += 1
    for match in test["matches"]:
        # A match known only from segments: its totals from them, added up again after
        # every import, so a second segment file counts too.
        own = [s for s in test["segments"] if s["match"] == match["id"] and s["chr"] in AUTOSOMES]
        if own and (match.get("cm") is None or match.get("from_segments")):
            match["cm"] = round(sum(s["cm"] or 0 for s in own), 1)
            match["segments"] = len(own)
            match["longest"] = max(s["cm"] or 0 for s in own)
            match["from_segments"] = True
    return added


MAP_BUILD = "37"  # The genetic map's coordinates (GRCh37); positions of other builds differ.


def comparable(info_a, info_b):
    """Whether two raw files' positions can be compared: the same reference build, and the
    one the genetic map is in. Otherwise the same position is a different place."""
    return (info_a.get("build") or MAP_BUILD) == (info_b.get("build") or MAP_BUILD) == MAP_BUILD


# Raw DNA files: 23andMe, AncestryDNA, MyHeritage, FamilyTreeDNA, LivingDNA.
ANCESTRY_CHROMOSOMES = {"23": "X", "24": "Y", "25": "X", "26": "MT"}


def read_raw(path):
    """{chromosome: {position: genotype}} plus a summary. Genotypes are two letters, sorted
    ("AG"); no-calls and insertions/deletions are left out."""
    calls = {}
    build = ""
    snps = 0
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("#"):
                found = re.search(r"build\s*(\d{2})|GRCh(\d{2})", line, re.IGNORECASE)
                if found and not build:
                    build = found[1] or found[2]
                continue
            fields = [f.strip().strip('"') for f in re.split(r"[\t,]", line.strip())]
            if len(fields) < 4 or not fields[2].isdigit():
                continue  # The column line, or something else.
            chromosome = fields[1].upper().replace("CHR", "")
            chromosome = ANCESTRY_CHROMOSOMES.get(chromosome, chromosome)
            genotype = (fields[3] + fields[4]) if len(fields) >= 5 and len(fields[3]) == 1 else fields[3]
            genotype = genotype.upper()
            if len(genotype) == 1 and chromosome in ("Y", "MT", "X"):
                genotype *= 2  # One copy written once (men's X and Y).
            if len(genotype) != 2 or not set(genotype) <= set("ACGT"):
                continue
            calls.setdefault(chromosome, {})[int(fields[2])] = "".join(sorted(genotype))
            snps += 1
    y = len(calls.get("Y", {}))
    x = calls.get("X", {})
    mixed_x = sum(1 for g in x.values() if g[0] != g[1])
    sex = "M" if y > 1000 and mixed_x < len(x) * 0.02 else "F" if x and y < 1000 else ""
    return calls, {"snps": snps, "build": build or "37", "sex": sex}


@lru_cache(maxsize=1)
def _genetic_map():
    with gzip.open(MAP_FILE, "rt", encoding="utf-8") as handle:
        data = json.load(handle)["map"]
    return {c: ([p[0] for p in points], [p[1] for p in points]) for c, points in data.items()}


def position_cm(chromosome, position):
    positions, cms = _genetic_map().get(chromosome, ([], []))
    if not positions:
        return position / 1e6  # Roughly 1 cM per million bases where no map is known.
    index = bisect.bisect_right(positions, position)
    if index == 0:
        return cms[0]
    if index >= len(positions):
        return cms[-1]
    p0, p1, c0, c1 = positions[index - 1], positions[index], cms[index - 1], cms[index]
    return c0 + (c1 - c0) * (position - p0) / (p1 - p0) if p1 > p0 else c0


def segment_cm(chromosome, start, end):
    return max(0.0, position_cm(chromosome, end) - position_cm(chromosome, start))


def chromosome_length(chromosome):
    return _genetic_map().get(chromosome, ([], [0]))[1][-1]


ERROR_GAP = 200  # Clean positions on both sides that make a lone mismatch an error.


def compare(calls_a, calls_b, min_cm=7.0, min_snps=None):
    """Half-identical segments between two raw files, the way GEDmatch's one-to-one does it:
    a segment runs until both people are homozygous for different letters (AA against GG),
    which cannot happen where they share a piece of DNA. Autosomes only.
    Returns [segment], each {"chr", "start", "end", "cm", "snps"}."""
    found = []
    overlap = sum(len(set(calls_a.get(c, {})) & set(calls_b.get(c, {}))) for c in AUTOSOMES)
    if min_snps is None:  # Fewer shared positions between different companies' chips.
        min_snps = max(150, min(500, int(500 * overlap / 550_000)))
    for chromosome in AUTOSOMES:
        a, b = calls_a.get(chromosome, {}), calls_b.get(chromosome, {})
        positions = sorted(set(a) & set(b))
        opposite_at = [i for i, p in enumerate(positions)
                       if a[p][0] == a[p][1] and b[p][0] == b[p][1] and a[p][0] != b[p][0]]
        # A lone mismatch deep inside a shared stretch is a reading error, not its end:
        # where nothing is shared, mismatches come every few dozen positions.
        breaks = set()
        for n, i in enumerate(opposite_at):
            before = i - opposite_at[n - 1] if n else i + 1
            after = opposite_at[n + 1] - i if n + 1 < len(opposite_at) else len(positions) - i
            if before <= ERROR_GAP or after <= ERROR_GAP:
                breaks.add(i)
        run_start, run_count, last = None, 0, None

        def close(end_position):
            if run_start is not None and run_count >= min_snps:
                cm = segment_cm(chromosome, run_start, end_position)
                if cm >= min_cm:
                    found.append({"chr": chromosome, "start": run_start, "end": end_position,
                                  "cm": round(cm, 2), "snps": run_count})

        for index, position in enumerate(positions):
            if index in breaks:
                close(last)
                run_start, run_count = None, 0
            else:
                if run_start is None:
                    run_start = position
                run_count += 1
            last = position
        close(last)
    return found


def summary(segments):
    """(total cM, number of segments, longest) for autosomal segments."""
    own = [s for s in segments if s["chr"] in AUTOSOMES and s.get("cm")]
    return (round(sum(s["cm"] for s in own), 1), len(own), round(max((s["cm"] for s in own), default=0), 1))
