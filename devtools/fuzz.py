"""Throws random and broken input at the program's readers and editing rules.

    python devtools/fuzz.py                 every target, 2,000 rounds each
    python devtools/fuzz.py --rounds 20000 --seed 7 --only dates gedcom

Targets and what each may do with bad input:
- dates:   normalize_date_input / parse_date never raise; anything accepted reads back
           unchanged in every language and survives GEDCOM.
- gedcom:  read_gedcom on mutated files raises GedcomError or returns a tree that
           validates without crashing; nothing else.
- treefile: open_tree on mutated tree.json raises TreeLoadError or opens.
- edits:   random edits on random trees either refuse (EditError) or leave no new
           problems behind (validate), including merges and combining trees.
Each failure is saved under dev-output/fuzz/ with the seed and input that caused it.
Seeded: the same --seed finds the same things.
"""
import os
import argparse
import json
import random
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("FT_STILL", "1")  # No gliding: checks look right after each move.

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "dev-output" / "fuzz"


class Failure(Exception):
    pass


def save(target, seed, round_number, text, problem):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{target}-seed{seed}-round{round_number}.txt"
    path.write_text(f"{problem}\n\n--- input ---\n{text}", encoding="utf-8")
    return path


# Dates.

PIECES = ["1921", "1708", "09", "9", "1880", "1885", "0", "13", "29", "31", "2", "12", "99999", "-", "/", ".", " ",
          "about", "before", "after", "from", "to", "until", "between", "and", "(julian)", "julian", "jul.", "o.s.",
          "oko", "prije", "poslije", "od", "do", "ca.", "c.", "~", "?", "年", "頃", "约", "von", "bis", "ок.",
          "–", "  ", "abt", "bef", "aft", ",", "%", "{date}", "\x00", "١٩٢١"]


def fuzz_dates(rng, rounds, seed):
    import strings
    from gedcom import date_from_gedcom, date_to_gedcom
    from model import date_input_text, date_label, normalize_date_input, parse_date
    found = []
    languages = list(strings.LANGUAGES)
    for number in range(rounds):
        text = "".join(rng.choice(PIECES) for _ in range(rng.randint(1, 7)))
        strings.set_language(rng.choice(languages))
        try:
            parse_date(text)
            date_label(text)
            stored = normalize_date_input(text)
            if stored:
                if parse_date(stored) is None:
                    raise Failure(f"accepted {text!r} as {stored!r}, which does not parse")
                shown = date_input_text(stored)
                if normalize_date_input(shown) != stored:
                    raise Failure(f"{stored!r} shows as {shown!r}, which reads back as {normalize_date_input(shown)!r}")
                back = date_from_gedcom(date_to_gedcom(stored), period=True)
                if back != stored:
                    raise Failure(f"{stored!r} comes back from GEDCOM as {back!r}")
        except Exception as error:  # noqa: BLE001 - any error is a finding.
            found.append(save("dates", seed, number, f"{text!r} (language {strings.LANGUAGE})",
                              f"{error}\n{traceback.format_exc()}"))
        finally:
            strings.set_language("en")
    return found


# GEDCOM files.

def _seed_gedcom():
    sys.path.insert(0, str(ROOT / "tests"))
    from gedcom import write_gedcom
    from sample import sample_tree
    from test_sources import parish_tree
    return [write_gedcom(tree, Path("x.ged")) for tree in (sample_tree(), parish_tree())]


def _mutate_lines(rng, text):
    lines = text.splitlines()
    for _ in range(rng.randint(1, 8)):
        if not lines:
            break
        n = rng.randrange(len(lines))
        kind = rng.randrange(9)
        if kind == 0:
            del lines[n]
        elif kind == 1:
            lines.insert(n, lines[rng.randrange(len(lines))])
        elif kind == 2:
            lines[n] = str(rng.randint(0, 99)) + lines[n][1:]
        elif kind == 3:
            m = rng.randrange(len(lines))
            lines[n], lines[m] = lines[m], lines[n]
        elif kind == 4:
            lines[n] = lines[n][:rng.randrange(len(lines[n]) + 1)]
        elif kind == 5:
            lines[n] += " " + rng.choice(["@I1@", "@@", "@#DJULIAN@", "é", "ÿ" * 300, "\t", "FROM 1950 TO",
                                          "BET AND", "29 FEB 1700", "1708/10", "@X", "0 TRLR"])
        elif kind == 6:
            lines.insert(n, rng.choice(["1 ASSO @I999@", "2 SOUR @S999@", "1 FAMC @F999@", "0 @I1@ INDI",
                                        "1 NAME /", "3 MAP", "4 LATI X", "1 OBJE", "2 FILE ../../etc/passwd",
                                        "1 _FT_ROLE godfather", "2 _FT_FACT EVEN:99", "1 _FT_STORY",
                                        "0 @S1@ SOUR", "1 REPO @R9@"]))
        elif kind == 7:
            lines[n] = lines[n].replace(" ", "  ", 1)
        else:
            lines[n] = "".join(rng.choice("0123456789 @#ABCDEFGHIJKLMNOPQRSTUVWXYZ/_š") for _ in range(20))
    return "\n".join(lines) + rng.choice(["\n", "", "\r\n"])


def fuzz_gedcom(rng, rounds, seed):
    from gedcom import GedcomError, read_gedcom
    from model import validate
    found, seeds = [], _seed_gedcom()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "f.ged"
        for number in range(rounds):
            text = _mutate_lines(rng, rng.choice(seeds))
            raw = text.encode(rng.choice(["utf-8", "utf-8", "utf-16", "latin-1"]), errors="replace")
            if rng.random() < 0.1:
                raw = bytearray(raw)
                for _ in range(rng.randint(1, 20)):
                    raw[rng.randrange(len(raw))] = rng.randrange(256)
                raw = bytes(raw)
            path.write_bytes(raw)
            try:
                result = read_gedcom(path)
                validate(result.tree)
            except GedcomError:
                pass
            except Exception as error:  # noqa: BLE001
                found.append(save("gedcom", seed, number, text, f"{error}\n{traceback.format_exc()}"))
    return found


# tree.json files.

def _mutate_json(rng, value, depth=0):
    if depth > 6:
        return value
    choice = rng.random()
    if isinstance(value, dict) and value:
        key = rng.choice(list(value))
        if choice < 0.15:
            del value[key]
        elif choice < 0.3:
            value[key] = rng.choice([None, 0, -1, 1.5, "", "x", [], {}, True, [None], {"a": 1}, "media/../../x"])
        else:
            value[key] = _mutate_json(rng, value[key], depth + 1)
    elif isinstance(value, list) and value:
        n = rng.randrange(len(value))
        if choice < 0.2:
            del value[n]
        elif choice < 0.35:
            value.append(rng.choice([None, "x", {}, [], 3]))
        else:
            value[n] = _mutate_json(rng, value[n], depth + 1)
    elif choice < 0.5:
        return rng.choice([None, 0, "", "1708/10", "from", "abt", {}, [], 10 ** 30, float("nan"), "\x00"])
    return value


def fuzz_treefile(rng, rounds, seed):
    import storage
    from model import validate
    found = []
    sys.path.insert(0, str(ROOT / "tests"))
    from test_sources import parish_tree
    base = parish_tree().to_dict()
    with tempfile.TemporaryDirectory() as folder:
        for number in range(rounds):
            data = _mutate_json(rng, json.loads(json.dumps(base)))
            for _ in range(rng.randint(0, 4)):
                data = _mutate_json(rng, data)
            tree_folder = Path(folder) / f"t{number}.tree"
            tree_folder.mkdir()
            text = json.dumps(data, default=str) if rng.random() > 0.05 else json.dumps(data)[:rng.randrange(200)]
            (tree_folder / "tree.json").write_text(text, encoding="utf-8")
            try:
                opened = storage.open_tree(tree_folder)
                validate(opened.tree)
            except storage.TreeLoadError:
                pass
            except Exception as error:  # noqa: BLE001
                found.append(save("treefile", seed, number, text, f"{error}\n{traceback.format_exc()}"))
    return found


# Editing rules.

def fuzz_edits(rng, rounds, seed):
    import combine
    import edits
    sys.path.insert(0, str(ROOT / "devtools"))
    from model import validate
    from perf import generate
    found = []
    for number in range(rounds):
        tree = generate(rng.randint(8, 40), seed=seed * 100003 + number)
        people = list(tree.people)
        before = {(issue.code, issue.detail) for issue in validate(tree)}
        operation = rng.choice(["merge", "delete", "link_child", "link_partner", "link_sibling", "combine",
                                "rename_place", "set_place"])
        a, b = rng.choice(people), rng.choice(people)
        try:
            if operation == "merge":
                edits.merge_people(tree, a, b)
            elif operation == "delete":
                edits.delete_person(tree, a)
            elif operation == "link_child":
                edits.link_child(tree, a, b)
            elif operation == "link_partner":
                edits.link_partner(tree, a, b)
            elif operation == "link_sibling":
                edits.link_sibling(tree, a, b)
            elif operation == "combine":
                other = generate(rng.randint(5, 20), seed=seed * 7919 + number)
                matches = {}
                for suggestion in combine.suggest_matches(tree, other):
                    if suggestion.mine and suggestion.mine not in matches.values() and rng.random() < 0.7:
                        matches[suggestion.theirs] = suggestion.mine
                try:
                    tree = combine.combine(tree, other, matches).tree
                except combine.CombineError:
                    pass
            elif operation == "rename_place":
                edits.set_place(tree, "Here", {"parent": "There"})
                edits.rename_place(tree, rng.choice(["Here", "There", "Elsewhere"]), rng.choice(["There", "X"]))
            else:
                edits.set_place(tree, "A", {"parent": "B"})
                edits.set_place(tree, "B", {"parent": rng.choice(["A", "C"])})
        except edits.EditError:
            continue
        except Exception as error:  # noqa: BLE001
            found.append(save("edits", seed, number, f"{operation} {a} {b}", f"{error}\n{traceback.format_exc()}"))
            continue
        new = [i for i in validate(tree) if (i.code, i.detail) not in before]
        if new:
            found.append(save("edits", seed, number, f"{operation} {a} {b}",
                              "left problems: " + "; ".join(i.message() for i in new)))
    return found


def fuzz_window(rng, rounds, seed):
    """Damaged trees opened in the real window: every chart, every person's panel."""
    import datetime
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    import app as app_module
    import storage
    found = []
    sys.path.insert(0, str(ROOT / "tests"))
    from test_sources import parish_tree
    base = parish_tree().to_dict()
    errors = []
    sys.excepthook = lambda kind, error, trace: errors.append("".join(traceback.format_exception(kind, error, trace)))
    with tempfile.TemporaryDirectory() as folder:
        window = app_module.MainWindow(QSettings(str(Path(folder) / "s.ini"), QSettings.Format.IniFormat),
                                       today=datetime.date(2026, 11, 13))
        window.alert = window.inform = lambda *a: None
        window.confirm = lambda *a: False
        window.resize(1200, 800)
        window.show()
        for number in range(rounds):
            data = json.loads(json.dumps(base))
            for _ in range(rng.randint(1, 5)):
                data = _mutate_json(rng, data)
            tree_folder = Path(folder) / f"w{number}.tree"
            tree_folder.mkdir()
            text = json.dumps(data, default=str)
            (tree_folder / "tree.json").write_text(text, encoding="utf-8")
            errors.clear()
            try:
                try:
                    storage.read_tree(tree_folder)
                except storage.TreeLoadError:
                    continue
                window.open_path(tree_folder)
                for chart in ("family", "pyramid", "pedigree", "bowtie", "fan"):
                    window.show_chart(chart)
                    QApplication.processEvents()
                for person in list(window.tree.people)[:12]:
                    window.select(person)
                    QApplication.processEvents()
                window.close_tree()
            except Exception as error:  # noqa: BLE001
                errors.append(f"{error}\n{traceback.format_exc()}")
            if errors:
                found.append(save("window", seed, number, text, "\n".join(errors)))
                try:
                    window.close_tree()
                except Exception:  # noqa: BLE001
                    pass
        window.close()
    sys.excepthook = sys.__excepthook__
    return found


TARGETS = {"dates": fuzz_dates, "gedcom": fuzz_gedcom, "treefile": fuzz_treefile, "edits": fuzz_edits,
           "window": fuzz_window}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--only", nargs="+", choices=sorted(TARGETS))
    args = parser.parse_args()
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])  # Photos and documents use Qt's image readers.
    total = 0
    for name in args.only or TARGETS:
        rng = random.Random(f"{name}-{args.seed}")
        found = TARGETS[name](rng, args.rounds, args.seed)
        total += len(found)
        print(f"{name:9} {args.rounds} rounds: {'no problems' if not found else f'{len(found)} problems'}")
        for path in found[:5]:
            print(f"          {path}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
