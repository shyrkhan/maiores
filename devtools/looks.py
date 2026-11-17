#!/usr/bin/env python3
"""Look at the program the way a designer would, in every language.

Opens every menu entry (and each tab or page of every dialog it opens) on the made-up
family, in a hidden copy at a small laptop's size (1366 x 768), and checks what a person
would see at a glance:

  FAIL  text cut off (buttons, labels, check boxes, tabs, group titles, drop-downs, hints)
  FAIL  a widget cut off by its box or by the window, or two widgets on top of each other
  FAIL  a window bigger than a 1366 x 768 screen
  FAIL  English text in another language, a raw string key, an unfilled {placeholder},
        broken characters, an empty button
  NOTE  fields almost (but not quite) lined up, buttons in a row of different heights,
        tiny click targets, a column title cut off, a dialog without a title

    python -m devtools.looks                          every language, dark theme
    python -m devtools.looks --languages en,hr,de --themes dark,light
    python -m devtools.looks --shots all              keep a picture of every dialog

Writes dev-output/looks/report.html (each problem with a picture, the spot boxed in red)
and looks.json. Known, accepted findings live in devtools/looks_known.json. Exits 1 when
there is a FAIL that is not known.
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
KNOWN = Path(__file__).with_name("looks_known.json")
SCREEN_W, SCREEN_H = 1366, 768
FAIL, NOTE = "FAIL", "NOTE"
# Entries that leave the program, start a server, or only ask for a file to open.
SKIP = {"quit", "print...", "share live on this network...", "full screen", "new tree...", "open tree...",
        "report a problem or idea...", "support maiores..."}
SKIP_PREFIX = ("delete", "unlink")


def plain(text):
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def norm(text):
    return re.sub(r"\s+", " ", plain(text)).strip().rstrip(":.…").strip()


# ---------------------------------------------------------------------------------------
# One language in this process.

class Looker:
    def __init__(self, language, theme_name, out, shots):
        import strings
        strings.set_language(language)
        from PySide6.QtCore import QSettings
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QApplication

        import app as app_module
        from sample import sample_tree
        from storage import create_tree

        QDesktopServices.openUrl = staticmethod(lambda url: self.opened.append(url.toString()) or True)
        self.opened = []
        self.language, self.theme, self.out, self.shots = language, theme_name, Path(out), shots
        self.out.mkdir(parents=True, exist_ok=True)
        self.app = QApplication.instance() or QApplication([])
        app_module.apply_theme(self.app, theme_name)
        app_module.install_qt_translation(self.app)
        self.work = Path(tempfile.mkdtemp(prefix="maiores-looks-"))
        settings = QSettings(str(self.work / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue(app_module.TOUR_KEY, "done")
        settings.setValue(app_module.REOPEN_KEY, False)
        settings.setValue(app_module.MAP_TILES_KEY, "no")
        self.window = app_module.MainWindow(settings)
        self.window.alert = lambda title, text: None
        tree = self.work / "Made-up family"
        create_tree(tree, sample_tree())
        self.window.open_path(str(tree))
        from screen import fit_to_screen
        fit_to_screen(self.window, SCREEN_W, SCREEN_H)  # As big as a small laptop allows.
        self.window.show()
        self.settle(300)
        self.select("Luka")
        self.findings, self.seen, self.count = [], set(), 0
        self.checker_faults = []
        self.errors = []
        en = strings.STRINGS["en"]
        here = strings.STRINGS[language]
        self.english = {}
        for key, value in en.items():
            if isinstance(value, str) and len(norm(value)) > 2 and "{" not in value:
                self.english.setdefault(norm(value), []).append(key)
        self.here, self.keys = here, set(en)
        self.here_values = {norm(v) for v in here.values() if isinstance(v, str)}

    def settle(self, ms=150):
        from PySide6.QtTest import QTest
        QTest.qWait(ms)

    def select(self, name):
        for pid, person in self.window.tree.people.items():
            if person.given.startswith(name):
                self.window.go_to_person(pid)
                self.settle(100)
                return

    # Walking the menus.
    def entries(self):
        """(path, action) for every menu entry, submenus opened as a person would open them."""
        found = []

        def walk(menu, trail):
            menu.aboutToShow.emit()
            for action in menu.actions():
                text = plain(action.text()).strip()
                if not text or action.isSeparator():
                    continue
                low = text.lower()
                if low in SKIP or low.startswith(SKIP_PREFIX):
                    continue
                if action.menu() is not None:
                    walk(action.menu(), trail + [text])
                else:
                    found.append(("/".join(trail + [text]), action))

        for top in self.window.menuBar().actions():
            if top.menu() is not None:
                walk(top.menu(), [plain(top.text())])
        return found

    def run(self):
        self.inspect(self.window, "main window")
        # Errors inside button handlers land here (Qt cannot raise them through exec).
        sys.excepthook = lambda kind, error, trace: self.errors.append(f"{kind.__name__}: {error}")
        for path, action in self.entries():
            if path.split("/")[0].lower() == "person" and path.split("/")[-1].startswith("Luka"):
                continue
            self.visit(path, action)
        return self.findings

    def visit(self, path, action):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        before = {id(w) for w in QApplication.topLevelWidgets() if w.isVisible()}
        state = {"polls": 0, "done": False}
        print(f"visit {path}", file=sys.stderr, flush=True)

        def watch():
            if state["done"]:
                return
            state["polls"] += 1
            for w in self.new_windows(before):
                self.handle(w, path)
            QTimer.singleShot(150, watch)  # Until the entry returns: some ask twice.

        QTimer.singleShot(250, watch)
        if action.isEnabled():
            try:
                action.trigger()
            except Exception as error:  # noqa: BLE001 - reported, the walk goes on
                self.errors.append(f"{path}: {type(error).__name__}: {error}")
        self.settle(350)
        state["done"] = True
        for w in self.new_windows(before):  # Windows that do not wait (no exec).
            self.handle(w, path)
        if self.window.tour is not None:
            self.inspect(self.window, f"{path} (tour)")
            self.window.tour.finish()
            self.settle(100)
        elif path.split("/")[0].lower() == "view":
            self.inspect(self.window, f"main window after {path}")
        if self.errors:
            for error in self.errors:
                self.add(FAIL, "error", path, error, None, None)
            self.errors.clear()
        if not self.window.folder:
            self.window.open_path(str(self.work / "Made-up family"))
            self.settle(200)
        self.select("Luka")

    def handle(self, w, path):
        """Look at a window that opened, then close it, whatever the looking ran into."""
        try:
            self.inspect_all_pages(w, path)
        except Exception:  # noqa: BLE001 - a fault in this checker, not in the program
            import traceback
            traceback.print_exc()
            self.checker_faults.append(f"{path}: {traceback.format_exc().strip().splitlines()[-1]}")
        finally:
            self.close(w)

    def new_windows(self, before):
        from PySide6.QtWidgets import QApplication, QMenu
        return [w for w in QApplication.topLevelWidgets()
                if w.isVisible() and id(w) not in before and w is not self.window and not isinstance(w, QMenu)]

    def close(self, w):
        from PySide6.QtWidgets import QDialog
        if isinstance(w, QDialog):
            w.reject()
        w.close()
        self.settle(50)

    # Pages: every tab and every page of a stacked dialog.
    def inspect_all_pages(self, top, where):
        from PySide6.QtWidgets import QFileDialog, QStackedWidget, QTabWidget
        if isinstance(top, QFileDialog):
            return  # Qt's own.
        title = top.windowTitle() or type(top).__name__
        label = f"{where} > {title}"
        self.inspect(top, label)
        for tabs in top.findChildren(QTabWidget):
            start = tabs.currentIndex()
            for i in range(tabs.count()):
                if i != start and tabs.isTabEnabled(i):
                    tabs.setCurrentIndex(i)
                    self.settle(80)
                    self.inspect(top, f"{label} > {plain(tabs.tabText(i))}")
            tabs.setCurrentIndex(start)
        for stack in top.findChildren(QStackedWidget):
            if isinstance(stack.parent(), QTabWidget) or not stack.isVisible():
                continue
            start = stack.currentIndex()
            for i in range(stack.count()):
                if i != start:
                    stack.setCurrentIndex(i)
                    self.settle(80)
                    self.inspect(top, f"{label} > page {i + 1}")
            stack.setCurrentIndex(start)

    # The checks.
    def inspect(self, top, where):
        self.app.processEvents()
        problems = check(top, self)
        new = []
        for severity, kind, text, detail, rect in problems:
            if self.add(severity, kind, where, text, detail, rect, top_title=top.windowTitle()):
                new.append(rect)
        keep = self.shots == "all" or (self.shots == "review" and self.language in ("en", "hr", "ar"))
        if new or keep:
            self.count += 1
            name = f"{self.count:03d}.png"
            picture = top.grab()
            if new:
                from PySide6.QtGui import QColor, QPainter, QPen
                painter = QPainter(picture)
                painter.setPen(QPen(QColor("#ff2a2a"), 2))
                for rect in new:
                    if rect is not None:
                        painter.drawRect(rect.adjusted(-2, -2, 2, 2))
                painter.end()
            picture.save(str(self.out / name))
            for f in self.findings:
                if f.get("_pending"):
                    f["picture"] = name
                    del f["_pending"]
            if keep and not new:
                self.findings.append({"severity": "SHOT", "kind": "picture", "where": where, "text": "",
                                      "detail": "", "picture": name, "language": self.language,
                                      "theme": self.theme})

    def add(self, severity, kind, where, text, detail, rect, top_title=""):
        key = (kind, top_title or where.split(" > ")[0], text)
        if key in self.seen:
            return False
        self.seen.add(key)
        self.findings.append({"severity": severity, "kind": kind, "where": where, "text": text,
                              "detail": detail or "", "language": self.language, "theme": self.theme,
                              "_pending": True})
        return True


INPUTS = ("QLineEdit", "QComboBox", "QSpinBox", "QDoubleSpinBox", "QDateEdit", "QTextEdit", "QPlainTextEdit")


def check(top, looker):
    """Problems a person would see in this window right now, as
    (severity, kind, text, detail, rect in the window's coordinates)."""
    from PySide6.QtCore import QPoint, QRect, Qt
    from PySide6.QtGui import QTextDocument
    from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractScrollArea, QCheckBox,
                                   QComboBox, QGroupBox, QHeaderView, QLabel, QLineEdit, QPushButton,
                                   QRadioButton, QStyle, QTabBar, QToolButton, QWidget)
    out = []
    style = QWidget.style(top)  # A dialog may have its own "style" attribute.

    def place(w):
        return QRect(w.mapTo(top, QPoint(0, 0)), w.size())

    def qt_internal(w):
        while w is not None and w is not top:
            if w.objectName().startswith("qt_") or type(w).__name__ in ("QCalendarWidget", "QFileDialog"):
                return True
            w = w.parentWidget()
        return False

    def scrolled(w):
        p = w.parentWidget()
        while p is not None and p is not top:
            if isinstance(p, QAbstractScrollArea):
                return True
            p = p.parentWidget()
        return False

    def visible_part(w):
        r = place(w)
        p = w.parentWidget()
        while p is not None:
            r = r.intersected(place(p) if p is not top else top.rect())
            if p is top:
                break
            p = p.parentWidget()
        return r

    if isinstance(top, QWidget) and top is not looker.window:
        from screen import FRAME_H, FRAME_W
        if top.width() > SCREEN_W - FRAME_W or top.height() > SCREEN_H - FRAME_H:
            out.append((FAIL, "window too big", top.windowTitle(),
                        f"{top.width()} x {top.height()}, a {SCREEN_W} x {SCREEN_H} screen shows less", None))
        if not top.windowTitle().strip():
            out.append((NOTE, "no window title", type(top).__name__, "the title bar shows only the program's name", None))

    widgets = [w for w in top.findChildren(QWidget) if w.isVisible() and w.width() > 0 and not qt_internal(w)]
    content = []
    for w in widgets:
        fm = w.fontMetrics()
        name = type(w).__name__
        texts = []
        # Text cut off.
        if isinstance(w, (QPushButton, QToolButton)):
            text = plain(w.text())
            texts.append(text)
            icon_only = isinstance(w, QToolButton) and w.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
            if text and not icon_only:
                need = fm.horizontalAdvance(text) + 8
                if not w.icon().isNull():
                    need += w.iconSize().width() + 4
                if need > w.width() + 1 or fm.height() > w.height():
                    out.append((FAIL, "text cut off", text, f"button needs {need} px, has {w.width()}", place(w)))
            elif isinstance(w, QPushButton) and w.icon().isNull():
                out.append((FAIL, "empty button", w.objectName() or name, "no text and no picture", place(w)))
            if isinstance(w, QPushButton) and (w.width() < 20 or w.height() < 18):
                out.append((NOTE, "tiny button", text or w.toolTip(), f"{w.width()} x {w.height()} px", place(w)))
        elif isinstance(w, (QCheckBox, QRadioButton)):
            text = plain(w.text())
            texts.append(text)
            if text:
                metric = QStyle.PixelMetric
                indicator = style.pixelMetric(metric.PM_IndicatorWidth) + style.pixelMetric(metric.PM_CheckBoxLabelSpacing)
                need = indicator + fm.horizontalAdvance(text) + 2
                if need > w.width() + 1:
                    out.append((FAIL, "text cut off", text, f"needs {need} px, has {w.width()}", place(w)))
        elif isinstance(w, QLabel):
            text = w.text()
            if text and (w.pixmap() is None or w.pixmap().isNull()) and "<img" not in text:
                inner = w.contentsRect()
                rich = w.textFormat() == Qt.TextFormat.RichText or (
                    w.textFormat() == Qt.TextFormat.AutoText and re.search(r"<[a-zA-Z/!]", text) is not None)
                if rich:
                    doc = QTextDocument()
                    doc.setDefaultFont(w.font())
                    doc.setDocumentMargin(0)
                    doc.setHtml(text)
                    texts.append(doc.toPlainText())
                    if w.wordWrap():
                        doc.setTextWidth(inner.width())
                        tall = doc.size().height()
                        if tall > inner.height() + 3 and not scrolled(w):
                            out.append((FAIL, "text cut off", norm(doc.toPlainText())[:80],
                                        f"needs {tall:.0f} px high, has {inner.height()}", place(w)))
                    elif doc.idealWidth() > inner.width() + 2:
                        out.append((FAIL, "text cut off", norm(doc.toPlainText())[:80],
                                    f"needs {doc.idealWidth():.0f} px, has {inner.width()}", place(w)))
                else:
                    shown = plain(text) if w.buddy() is not None else text
                    texts.append(shown)
                    if w.wordWrap():
                        tall = w.heightForWidth(w.width())
                        if tall > w.height() + 3:
                            out.append((FAIL, "text cut off", norm(shown)[:80], f"needs {tall} px high, has {w.height()}",
                                        place(w)))
                    else:
                        lines = shown.split("\n")
                        wide = max(fm.horizontalAdvance(line) for line in lines)
                        if wide > inner.width() + 2:
                            out.append((FAIL, "text cut off", norm(shown)[:80], f"needs {wide} px, has {inner.width()}",
                                        place(w)))
        elif isinstance(w, QGroupBox):
            text = plain(w.title())
            texts.append(text)
            if text and fm.horizontalAdvance(text) + 16 > w.width():
                out.append((FAIL, "text cut off", text, "group title wider than its box", place(w)))
        elif isinstance(w, QComboBox) and not w.isEditable():
            text = w.currentText()
            texts.append(text)
            need = fm.horizontalAdvance(text) + 20  # The arrow and the frame.
            if text and need > w.width() + 1:
                out.append((FAIL, "text cut off", text, f"drop-down needs {need} px, has {w.width()}", place(w)))
        elif isinstance(w, QLineEdit) and not w.text() and w.placeholderText():
            texts.append(w.placeholderText())
            need = fm.horizontalAdvance(w.placeholderText()) + 10
            if not w.actions():
                if need > w.width() + 1:
                    out.append((FAIL, "text cut off", w.placeholderText(), f"hint needs {need} px, has {w.width()}",
                                place(w)))
        elif isinstance(w, QTabBar):
            for i in range(w.count()):
                text = plain(w.tabText(i))
                texts.append(text)
                rect = w.tabRect(i)
                need = fm.horizontalAdvance(text) + 8
                if text and need > rect.width() and rect.width() > 0:
                    out.append((FAIL, "text cut off", text, f"tab needs {need} px, has {rect.width()}",
                                QRect(w.mapTo(top, rect.topLeft()), rect.size())))
        elif isinstance(w, QHeaderView) and w.model() is not None:
            for i in range(w.count()):
                if w.isSectionHidden(i):
                    continue
                text = w.model().headerData(i, w.orientation())
                if not isinstance(text, str) or not text:
                    continue
                texts.append(text)
                size = w.sectionSize(i)
                need = fm.horizontalAdvance(text) + 12
                if w.orientation() == Qt.Orientation.Horizontal and need > size and size > 0 and not w.stretchLastSection():
                    out.append((NOTE, "column title cut off", text, f"needs {need} px, has {size}", place(w)))
        # Text that should not be there.
        for text in texts:
            out.extend(text_problems(text, looker, place(w)))
        if isinstance(w, (QAbstractButton, QLabel, QLineEdit, QComboBox, QGroupBox, QAbstractItemView)) or name in INPUTS:
            content.append(w)

    # Cut off by the box or the window; on top of each other.
    parts = {}
    for w in content:
        whole, seen = place(w), visible_part(w)
        parts[w] = seen
        if scrolled(w) or whole.width() < 4 or whole.height() < 4:
            continue
        if seen.width() < whole.width() - 2 or seen.height() < whole.height() - 2:
            label = plain(getattr(w, "text", lambda: "")() or "") or w.objectName() or type(w).__name__
            out.append((FAIL, "cut off by its box", label[:80],
                        f"{whole.width() - seen.width()} x {whole.height() - seen.height()} px hidden", whole))
    for i, a in enumerate(content):
        for b in content[i + 1:]:
            if a.isAncestorOf(b) or b.isAncestorOf(a):
                continue
            both = parts[a].intersected(parts[b])
            if both.width() > 3 and both.height() > 3:
                name_a = plain(getattr(a, "text", lambda: "")() or "") or type(a).__name__
                name_b = plain(getattr(b, "text", lambda: "")() or "") or type(b).__name__
                out.append((FAIL, "on top of each other", f"{name_a[:40]} / {name_b[:40]}",
                            f"{both.width()} x {both.height()} px shared", both))

    # Almost lined up: fields in one column whose edges differ by a few pixels.
    fields = [w for w in content if type(w).__name__ in INPUTS and not scrolled(w)]
    by_parent = {}
    for w in fields:
        by_parent.setdefault(id(w.parentWidget()), []).append(w)
    for group in by_parent.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                ra, rb = place(a), place(b)
                if ra.top() == rb.top():
                    continue
                gap = abs(ra.left() - rb.left())
                if 0 < gap <= 6:
                    out.append((NOTE, "almost lined up", f"{type(a).__name__} / {type(b).__name__}",
                                f"left edges {gap} px apart", ra.united(rb)))
    # Buttons in one row with different heights.
    buttons = [w for w in content if isinstance(w, QPushButton)]
    for i, a in enumerate(buttons):
        for b in buttons[i + 1:]:
            if a.parentWidget() is b.parentWidget() and abs(place(a).center().y() - place(b).center().y()) <= 3:
                if abs(a.height() - b.height()) > 2:
                    out.append((NOTE, "uneven buttons", f"{plain(a.text())} / {plain(b.text())}",
                                f"{a.height()} and {b.height()} px high", place(a).united(place(b))))
    return out


BROKEN = ("�", "Ã©", "Ã¨", "Â ", "Ä‡", "Å¡")


def text_problems(text, looker, rect):
    out = []
    if not text:
        return out
    if re.search(r"\{[a-z_]+\}|%\d|%s\b", text):
        out.append((FAIL, "unfilled placeholder", text[:80], "a {name} or %1 left in", rect))
    if any(b in text for b in BROKEN):
        out.append((FAIL, "broken characters", text[:80], "text decoded wrongly", rect))
    if re.fullmatch(r"[a-z]+(_[a-z0-9]+)+", text.strip()) and text.strip() in looker.keys:
        out.append((FAIL, "string key shown", text, "the key, not its text", rect))
    if looker.language != "en":
        n = norm(text)
        keys = looker.english.get(n)
        if keys and n not in looker.here_values:
            out.append((FAIL, "English text", text[:80], f"from {keys[0]}", rect))
    if text != text.strip() or "  " in text.strip():
        out.append((NOTE, "stray spaces", repr(text)[:80], "extra space at the start, end or middle", rect))
    return out


def laptop_screen(folder):
    """The hidden screen, made the size of a small laptop's (Qt's default is 800 x 600)."""
    folder.mkdir(parents=True, exist_ok=True)
    config = folder / "screen.json"
    config.write_text(json.dumps({"screens": [{"name": "laptop", "x": 0, "y": 0, "width": SCREEN_W,
                                                "height": SCREEN_H, "logicalDpi": 96, "logicalBaseDpi": 96,
                                                "dpr": 1}]}))
    return f"offscreen:configfile={config}"


def run_one(language, theme_name, out, shots):
    os.environ.setdefault("QT_QPA_PLATFORM", laptop_screen(Path(out)))
    os.environ.setdefault("FT_STILL", "1")
    looker = Looker(language, theme_name, out, shots)
    findings = looker.run()
    for fault in looker.checker_faults:
        findings.append({"severity": FAIL, "kind": "checker fault", "where": fault, "text": "", "detail": "",
                         "language": language, "theme": theme_name})
    (Path(out) / "findings.json").write_text(json.dumps(findings, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(looker.work, ignore_errors=True)
    return findings


# ---------------------------------------------------------------------------------------
# Every language, one process each, and the report.

def known_findings():
    try:
        return json.loads(KNOWN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def is_known(finding, known):
    for k in known:
        if k.get("kind") == finding["kind"] and k.get("text", finding["text"]) == finding["text"] and \
                k.get("language", finding["language"]) == finding["language"] and \
                k.get("where", "") in finding["where"]:
            return True
    return False


def report(findings, out):
    order = {FAIL: 0, NOTE: 1, "SHOT": 2}
    findings.sort(key=lambda f: (order[f["severity"]], f.get("known", False), f["kind"], f["language"], f["where"]))
    rows = []
    for f in findings:
        picture = f"{f['language']}-{f['theme']}/{f['picture']}" if f.get("picture") else ""
        image = f'<a href="{html.escape(picture)}"><img src="{html.escape(picture)}" loading="lazy"></a>' if picture else ""
        rows.append(
            f'<tr class="{f["severity"].lower()}{" known" if f.get("known") else ""}"><td>{f["severity"]}'
            f'{" (known)" if f.get("known") else ""}</td><td>{html.escape(f["kind"])}</td>'
            f'<td>{f["language"]} {f["theme"]}</td><td>{html.escape(f["where"])}</td>'
            f'<td><b>{html.escape(f["text"])}</b><br>{html.escape(f["detail"])}</td><td>{image}</td></tr>')
    fails = sum(1 for f in findings if f["severity"] == FAIL and not f.get("known"))
    notes = sum(1 for f in findings if f["severity"] == NOTE and not f.get("known"))
    page = f"""<!doctype html><meta charset="utf-8"><title>Maiores looks</title>
<style>body{{font:14px sans-serif;margin:16px;background:#fff;color:#111}}table{{border-collapse:collapse;width:100%}}
td{{border-top:1px solid #ccc;padding:6px;vertical-align:top}}img{{max-width:420px;border:1px solid #999}}
tr.fail td:first-child{{color:#c00;font-weight:bold}}tr.known{{opacity:.5}}</style>
<h1>Maiores: how it looks</h1><p>{fails} problems, {notes} notes. Red boxes mark the spot.</p>
<table>{''.join(rows)}</table>"""
    (out / "report.html").write_text(page, encoding="utf-8")
    (out / "looks.json").write_text(json.dumps(findings, ensure_ascii=False, indent=1), encoding="utf-8")
    return fails, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--languages", default="all", help="comma-separated codes, or all")
    parser.add_argument("--themes", default="dark", help="comma-separated: dark, light")
    parser.add_argument("--shots", default="review", choices=("problems", "review", "all"),
                        help="pictures of problems only, of every dialog in en/hr/ar too (default), or of all")
    parser.add_argument("--out", default=str(ROOT / "dev-output" / "looks"))
    parser.add_argument("--one", nargs=2, metavar=("LANGUAGE", "THEME"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    out = Path(args.out)
    if args.one:
        run_one(args.one[0], args.one[1], out, args.shots)
        return 0
    import strings
    languages = sorted(strings.STRINGS) if args.languages == "all" else args.languages.split(",")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    known = known_findings()
    findings = []
    for language in languages:
        for theme_name in args.themes.split(","):
            folder = out / f"{language}-{theme_name}"
            started = time.monotonic()
            env = dict(os.environ, QT_QPA_PLATFORM=laptop_screen(out), FT_STILL="1")
            for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
                env.pop(name, None)
            result = subprocess.run([sys.executable, "-m", "devtools.looks", "--one", language, theme_name,
                                     "--out", str(folder), "--shots", args.shots],
                                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
            got = []
            if (folder / "findings.json").exists():
                got = json.loads((folder / "findings.json").read_text(encoding="utf-8"))
            if result.returncode != 0:
                got.append({"severity": FAIL, "kind": "crashed", "where": "the whole run", "language": language,
                            "theme": theme_name, "text": "", "detail": (result.stderr or "")[-1500:]})
            for f in got:
                f["known"] = f["severity"] == "SHOT" or is_known(f, known)
            findings.extend(got)
            bad = sum(1 for f in got if f["severity"] == FAIL and not f["known"])
            print(f"{language:6} {theme_name:5} {bad:3} problems, "
                  f"{sum(1 for f in got if f['severity'] == NOTE and not f['known']):3} notes  "
                  f"({time.monotonic() - started:.0f} s)", flush=True)
    fails, notes = report(findings, out)
    print(f"\n{fails} problems, {notes} notes - {out / 'report.html'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
