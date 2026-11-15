#!/usr/bin/env python3
"""How much of other programs' GEDCOM files survives import and export.

    python -m devtools.gedcom_check FOLDER      every .ged file in FOLDER, at any depth

For each file: every original line (tag path and value) must appear in what we write
back. Values are compared by meaning: continued lines joined, references (@I12@) ignored
since they are renumbered, dates compared as dates, "1 MARR" equal to "1 MARR Y". The
header and submitter are left out: they say who made the file and are written fresh.
Then a second round: what we write, read back and written again, must not change.

Good test files: github.com/findmypast/gedcom-samples (MyHeritage, Family Tree Maker,
Gramps, the GEDCOM 5.5 torture tests) and gedcom.io/testfiles/gedcom70/.
"""
import collections
import datetime
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gedcom import GedcomError, _parse_lines, date_from_gedcom, decode_gedcom, read_gedcom, write_gedcom  # noqa: E402

TODAY = datetime.date(2026, 11, 15)
POINTER = re.compile(r"@(?!#)[^@\s]+@")
EVENTS = ("BIRT", "DEAT", "MARR", "DIV", "BURI", "CHR", "BAPM", "EVEN", "RESI")


def lines_of(text):
    records, _bad = _parse_lines(text)
    found = collections.Counter()

    def walk(node, path):
        if node.tag in ("CONT", "CONC"):
            return
        value = " ".join(POINTER.sub("@P@", node.full_text()).split())
        if node.tag in EVENTS and value.upper() == "Y":
            value = ""
        if node.tag == "DATE":
            stored = date_from_gedcom(value, True)
            value = f"date:{stored}" if stored else value
        found[(" > ".join(path + (node.tag,)), value)] += 1
        for child in node.children:
            walk(child, path + (node.tag,))

    for record in records:
        if record.tag in ("HEAD", "TRLR", "SUBM", "SUBN"):
            continue
        found[(record.tag, "")] += 1
        for child in record.children:
            walk(child, (record.tag,))
    return found


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    missing_by_place, examples = collections.Counter(), {}
    unstable = 0
    work = Path(tempfile.mkdtemp())
    for path in sorted(folder.rglob("*.ged")):
        try:
            tree = read_gedcom(path, today=TODAY).tree
        except GedcomError as error:
            print(f"{path.name[:40]:40} not read: {error}")
            continue
        original = lines_of(decode_gedcom(path.read_bytes())[0])
        first = write_gedcom(tree, None, today=TODAY)
        missing = original - lines_of(first)
        again = work / "again.ged"
        again.write_text(first, encoding="utf-8")
        second = write_gedcom(read_gedcom(again, today=TODAY).tree, None, today=TODAY)
        stable = "" if first == second else "  CHANGES ON A SECOND ROUND"
        unstable += bool(stable)
        lost, total = sum(missing.values()), sum(original.values())
        print(f"{path.name[:40]:40} {total:7} lines, missing {lost:5} ({100 * lost / max(total, 1):4.1f}%){stable}")
        for (place, value), count in missing.items():
            missing_by_place[place] += count
            examples.setdefault(place, (path.name[:24], value[:60]))
    print("\nMissing, by where they were (links to records not in the file are expected here):")
    for place, count in missing_by_place.most_common(30):
        print(f"{count:7}  {place:40} e.g. {examples[place]}")
    return 1 if unstable else 0


if __name__ == "__main__":
    sys.exit(main())
