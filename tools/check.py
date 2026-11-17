#!/usr/bin/env python3
"""Every check in one command. Prints one line per stage and a final verdict.

    python tools/check.py            unit tests twice, then the explorer on 4 seeds
    python tools/check.py --quick    unit tests and one short explorer run
    python tools/check.py --seeds 10 --steps 400     a longer hunt
    python tools/check.py --fuzz 2000 --leaks         broken input and memory, too
    python tools/check.py --looks --ui-sweep          how it looks in every language; the UI sweep

Nothing appears on your screen: the tests that need a real display get a
private virtual one (Xvfb), and the explorer only ever uses throwaway trees.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(name, command, env_extra):
    env = dict(os.environ, **env_extra)
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    seconds = time.monotonic() - started
    output = result.stdout + result.stderr
    ok = result.returncode == 0
    print(f"{'PASS' if ok else 'FAIL'}  {name}  ({seconds:.0f} s)", flush=True)
    if not ok:
        lines = [line for line in output.splitlines() if "propagateSizeHints" not in line]
        print("\n".join("      " + line for line in lines[-25:]))
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--steps", type=int, default=250)
    parser.add_argument("--first-seed", type=int, default=1)
    parser.add_argument("--perf", action="store_true", help="also time everyday actions on large families")
    parser.add_argument("--sweep", action="store_true",
                        help="also try every connection between every pair, and every action")
    parser.add_argument("--fuzz", type=int, metavar="ROUNDS", default=0,
                        help="also throw broken input at the readers and editing rules (devtools/fuzz.py)")
    parser.add_argument("--leaks", action="store_true", help="also look for memory never given back")
    parser.add_argument("--looks", action="store_true",
                        help="also look at every dialog in every language for cut-off text and the like")
    parser.add_argument("--ui-sweep", action="store_true",
                        help="also drive a hidden copy through every menu, chart and dialog (tools/mcp_sweep.py)")
    args = parser.parse_args()
    python = sys.executable
    unit = [python, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
    code = [str(p) for pattern in ("*.py", "devtools/*.py", "tools/*.py", "tests/*.py")
            for p in sorted(ROOT.glob(pattern))] + [str(ROOT / "tools" / "maiores-mcp")]
    stages = [
        ("code check (pyflakes)", [python, "-m", "pyflakes", *code], {}),
        ("unit tests, no display", unit, {"QT_QPA_PLATFORM": "offscreen", "FT_STILL": "1"}),
    ]
    if shutil.which("xvfb-run"):
        stages.append((
            "unit tests, virtual X display",
            ["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24", *unit],
            {"QT_QPA_PLATFORM": "xcb", "FT_STILL": "1"},
        ))
    else:
        print("SKIP  unit tests on a virtual X display (install xvfb)")
    seeds = 1 if args.quick else args.seeds
    steps = 80 if args.quick else args.steps
    for seed in range(args.first_seed, args.first_seed + seeds):
        stages.append((
            f"explorer seed {seed}, {steps} steps",
            [python, "-m", "devtools.explorer", "--seed", str(seed), "--steps", str(steps)],
            {},
        ))
    if args.sweep:
        stages.append(("sweep: every connection between every pair", [python, "-m", "devtools.sweep"],
                       {"QT_QPA_PLATFORM": "offscreen"}))
        stages.append(("sweep: every action on every person and view",
                       [python, "-m", "devtools.sweep", "--actions"], {"QT_QPA_PLATFORM": "offscreen"}))
    if args.fuzz:
        stages.append((f"fuzz: broken input, {args.fuzz} rounds each",
                       [python, "-m", "devtools.fuzz", "--rounds", str(args.fuzz)], {"QT_QPA_PLATFORM": "offscreen"}))
    if args.leaks:
        stages.append(("memory: every window and action, 60 rounds", [python, "-m", "devtools.leaks"],
                       {"QT_QPA_PLATFORM": "offscreen"}))
    if args.looks:
        stages.append(("looks: every dialog in 18 languages", [python, "-m", "devtools.looks"], {}))
    if args.ui_sweep:
        stages.append(("UI sweep: every menu, chart and dialog", [python, "tools/mcp_sweep.py"], {}))
    if args.perf:
        stages.append(("speed on 1,000 / 3,000 / 6,000 people", [python, "-m", "devtools.perf"],
                       {"QT_QPA_PLATFORM": "offscreen"}))
    results = [run(*stage) for stage in stages]
    failed = results.count(False)
    print(f"\n{'ALL CHECKS PASSED' if not failed else f'{failed} OF {len(results)} STAGES FAILED'}")
    print(f"Explorer reports: {ROOT / 'dev-output'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
