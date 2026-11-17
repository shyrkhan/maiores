#!/usr/bin/env python3
"""Bug sweep through tools/maiores-mcp: every menu entry, every person action, every chart and
card style, on an editable copy of the made-up family, in a hidden copy of the program.
Collects errors, failed checks and a screenshot of every dialog.

    python tools/mcp_sweep.py [OUTPUT_FOLDER]     (default dev-output/mcp-sweep)

Look through the screenshots afterwards: the checks cannot see a cut-off button.
2026-11-17 it found: the export "Report or book" entry renamed by the Help menu's
"Report a problem", Open recent on the open tree saying "open in another window",
the tour's cut-off "Don't show again" and its bubble covering the card."""
import base64, json, subprocess, sys, time
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "dev-output" / "mcp-sweep"
OUT.mkdir(parents=True, exist_ok=True)
p = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "maiores-mcp")], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, text=True)
n = 0
findings = []


def rpc(method, params=None):
    global n
    n += 1
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}}) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())


def t(name, **a):
    r = rpc("tools/call", {"name": name, "arguments": a})["result"]
    if r.get("isError"):
        raise RuntimeError(r["content"][0]["text"])
    for c in r["content"]:
        if c["type"] == "image":
            return c["data"]
    txt = r["content"][0]["text"]
    try:
        return json.loads(txt)
    except ValueError:
        return txt


def shot(label):
    data = t("maiores_screenshot")
    path = OUT / (label.replace("/", "_").replace(" ", "_").replace(".", "") + ".png")
    path.write_bytes(base64.b64decode(data))
    return path


log_seen = 0


def new_trouble():
    """Tracebacks in the program output since last time, and error message boxes."""
    global log_seen
    text = Path.home().joinpath(".cache/maiores-mcp/hidden.log").read_text(errors="replace")
    fresh, log_seen = text[log_seen:], len(text)
    bad = [l for l in fresh.splitlines() if any(k in l for k in ("Traceback", "Error", "error", "Warning", "warning"))
           and not l.startswith("This plugin")]
    return bad, fresh


def close_all(label):
    for _ in range(6):
        wins = t("maiores_windows")
        if len(wins) <= 1:
            return
        front = wins[-1]
        if front["class"] in ("QMessageBox",) and ("rror" in front["title"] or "nexpected" in json.dumps(front)):
            findings.append((label, "error box", front))
        t("maiores_close")
        t("maiores_wait", ms=400)
    findings.append((label, "could not close", t("maiores_windows")))


def visit(label, do):
    try:
        do()
    except RuntimeError as e:
        findings.append((label, "tool error", str(e)))
        return
    t("maiores_wait", ms=900)
    wins = t("maiores_windows")
    if len(wins) > 1:
        front = wins[-1]
        path = shot(label)
        if front["class"] == "QMessageBox":
            box = t("maiores_widgets", depth=3, limit=30)
            if "nexpected" in box or "rror" in box:
                findings.append((label, "message box", box))
        close_all(label)
    bad, fresh = new_trouble()
    if bad:
        findings.append((label, "program output", fresh[-2500:]))
    checks = t("maiores_checks")
    if checks:
        findings.append((label, "checks", checks))
    fit = t("maiores_fit")
    if fit:
        findings.append((label, "fit", fit))
    print("ok" if not bad and not checks else "!!", label, flush=True)
    state = t("maiores_state")
    if not state["folder"]:
        findings.append((label, "note", "tree closed; reopening"))
        t("maiores_open", path=str(Path.home() / ".cache/maiores-mcp/home/Documents/Maiores/Made-up family"))
        t("maiores_wait", ms=800)


SKIP = {"quit", "print...", "share live on this network...",
        "full screen", "new tree...", "open tree..."}
def submenu_or_run(path):
    result = t("maiores_menu", path=path)
    if isinstance(result, dict):  # A submenu: visit each entry.
        for sub in result["entries"]:
            if sub and sub.lower() not in SKIP:
                visit(f"{path}/{sub}", lambda p=f"{path}/{sub}": t("maiores_menu", path=p))


rpc("initialize")
print(t("maiores_launch", editable=True, fresh=True, size="1500x950")[:80])
new_trouble()

# 1. Every menu entry (Person menu on a selected person).
t("maiores_select", who="Luka")
for top in ["File", "Edit", "View", "Tools", "Help", "Person"]:
    entries = t("maiores_menu", path=top)["entries"]
    for entry in entries:
        if not entry or entry.lower() in SKIP or (top == "Person" and entry.lower().startswith(("delete", "unlink"))):
            continue
        if top == "Person" and entry.startswith("Luka"):
            continue
        visit(f"{top}/{entry}", lambda path=f"{top}/{entry}": submenu_or_run(path))
        t("maiores_select", who="Luka")

# 2. Every chart and card style, with checks after each.
for chart in t("maiores_menu", path="View/Chart")["entries"]:
    for style in t("maiores_menu", path="View/Card style")["entries"]:
        visit(f"chart {chart} + {style}", lambda c=chart, s=style: (t("maiores_menu", path=f"View/Chart/{c}"),
                                                                    t("maiores_wait", ms=300),
                                                                    t("maiores_menu", path=f"View/Card style/{s}")))
    shot(f"chart_{chart}")
t("maiores_menu", path="View/Chart/Family view")

# 3. Right-click menu on each kind of person, every non-destructive entry.
for who in ["Ante", "Mara", "Ivana", "Katica", "Nikola"]:
    t("maiores_select", who=who)
    t("maiores_click_person", who=who, button="right")
    t("maiores_wait", ms=500)
    wins = t("maiores_windows")
    entries = next((w.get("entries", []) for w in wins if w["class"] == "QMenu"), [])
    t("maiores_key", keys="Esc")
    t("maiores_wait", ms=300)
    if not entries:
        findings.append((who, "no context menu", wins))
    for entry in entries:
        if entry.lower().startswith(("delete", "unlink")):
            continue
        def go(who=who, entry=entry):
            t("maiores_select", who=who)
            t("maiores_click_person", who=who, button="right")
            t("maiores_wait", ms=400)
            t("maiores_menu", path=entry)
        visit(f"context {who}/{entry}", go)

# 4. Undo everything, redo everything.
state = t("maiores_state")
for _ in range(state["undo"]):
    t("maiores_history", do="undo")
visit("after undo all", lambda: None)

(OUT / "findings.json").write_text(json.dumps(findings, ensure_ascii=False, indent=1))
print("FINDINGS", len(findings))
for f in findings:
    print(json.dumps(f, ensure_ascii=False)[:600])
t("maiores_stop")
