#!/usr/bin/env python3
"""Check translated interface text against the English set.

    i18n_check.py                  every language in translations/
    i18n_check.py FILE.json CODE   a translation still being written (a {key: text} JSON file)

Checks: every key present and nothing extra, the same {placeholders}, the same HTML tags,
exactly one & shortcut where English has one, "..." kept on texts that open a window,
and no empty text. Exit 1 on a problem.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PLACEHOLDER = re.compile(r"\{(\w*)\}")
TAG = re.compile(r"</?([a-zA-Z0-9]+)")
SHORTCUT = re.compile(r"&(?!&)\S")


def problems(english, table):
    found = []
    for key in sorted(set(english) - set(table)):
        found.append(f"{key}: missing")
    for key in sorted(set(table) - set(english)):
        found.append(f"{key}: not an English key")
    for key, source in english.items():
        text = table.get(key)
        if text is None:
            continue
        if not isinstance(text, str) or not text.strip():
            found.append(f"{key}: empty")
            continue
        if Counter(PLACEHOLDER.findall(source)) != Counter(PLACEHOLDER.findall(text)):
            found.append(f"{key}: placeholders {sorted(set(PLACEHOLDER.findall(source)))} "
                         f"became {sorted(set(PLACEHOLDER.findall(text)))}")
        if Counter(t.lower() for t in TAG.findall(source)) != Counter(t.lower() for t in TAG.findall(text)):
            found.append(f"{key}: HTML tags differ")
        if len(SHORTCUT.findall(source)) != len(SHORTCUT.findall(text)):
            found.append(f"{key}: needs exactly {len(SHORTCUT.findall(source))} & shortcut(s)")
        if source.endswith("...") and not (text.endswith("...") or text.endswith("…")):
            found.append(f"{key}: should end with ... like the English")
        try:
            text.format(**{name: "x" for name in PLACEHOLDER.findall(source)})
        except (KeyError, IndexError, ValueError) as error:
            found.append(f"{key}: does not format ({error})")
    return found


def main(argv):
    import strings
    english = strings.STRINGS["en"]
    if argv:
        tables = {argv[1]: json.loads(Path(argv[0]).read_text(encoding="utf-8"))}
    else:
        tables = {code: table for code, table in strings.STRINGS.items() if code != "en"}
    bad = 0
    for code, table in tables.items():
        found = problems(english, table)
        bad += len(found)
        print(f"{code}: {'ok' if not found else f'{len(found)} problem(s)'}")
        for line in found:
            print(f"  {line}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
