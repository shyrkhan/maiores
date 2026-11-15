"""Interface text in every language besides English, one module per language.

The modules are imported by name here, not looked up at run time, so the program
builders (PyInstaller, the Android stage) see them and pack them. A new language is
a new module with CODE, NAME and TEXT, added to the import list below.
"""
from translations import ar, cs, de, es, fr, hr, it, ja, ko, nl, pl, pt_BR, ru, tr, uk, zh_CN, zh_TW

MODULES = (ar, cs, de, es, fr, hr, it, ja, ko, nl, pl, pt_BR, ru, tr, uk, zh_CN, zh_TW,)
TABLES = {module.CODE: module.TEXT for module in MODULES}
NAMES = {module.CODE: module.NAME for module in MODULES}
