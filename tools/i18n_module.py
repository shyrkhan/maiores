#!/usr/bin/env python3
"""Write translations/<code>.py from a {key: text} JSON file, in the English key order,
and list it in translations/__init__.py.

    i18n_module.py FILE.json CODE
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NAMES = {
    "ar": "العربية", "cs": "Čeština", "de": "Deutsch", "es": "Español", "fr": "Français", "hr": "Hrvatski",
    "it": "Italiano", "ja": "日本語", "ko": "한국어", "nl": "Nederlands", "pl": "Polski",
    "pt_BR": "Português (Brasil)", "ru": "Русский", "tr": "Türkçe", "uk": "Українська",
    "zh_CN": "简体中文", "zh_TW": "繁體中文",
}


def write_module(table, code):
    import strings
    english = strings.STRINGS["en"]
    lines = [f'"""{NAMES[code]} interface text, machine-translated from the English in strings.py.',
             'Keys match the English set; anything missing falls back to English."""', "",
             f"CODE = {code!r}", f"NAME = {NAMES[code]!r}", "TEXT = {"]
    for key in english:
        if key in table:
            lines.append(f"    {json.dumps(key)}: {json.dumps(table[key], ensure_ascii=False)},")
    lines.append("}")
    (ROOT / "translations" / f"{code}.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_index():
    codes = sorted(path.stem for path in (ROOT / "translations").glob("*.py") if path.stem != "__init__")
    init = ROOT / "translations" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    text = re.sub(r"from translations import [^\n]+\n\nMODULES = \([^)]*\)",
                  f"from translations import {', '.join(codes)}\n\nMODULES = ({', '.join(codes)},)", text)
    init.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    write_module(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")), sys.argv[2])
    write_index()
