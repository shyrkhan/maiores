#!/usr/bin/env python3
"""Build the program for this computer's system, then pack it for sending.

PyInstaller can't cross-compile, so each system's version is built on that system.
Usage: build.py [--output DIR] [--work DIR]
"""
import argparse
import os
import platform
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from version import VERSION  # noqa: E402

NAME = "maiores"
BUNDLE_ID = "org.maiores.Maiores"
INCLUDED = ["fonts", "assets", "THIRD_PARTY.txt"]


def system_label():
    system = {"win32": "windows", "darwin": "mac"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    machine = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"{system}-{machine}"


def add_data(item):
    source = ROOT / item
    target = item if source.is_dir() else "."
    return f"{source}{os.pathsep}{target}"


def run_pyinstaller(output, work):
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", NAME,
        "--icon", str(ROOT / "assets" / "icon.png"),
        "--osx-bundle-identifier", BUNDLE_ID,
        "--exclude-module", "tkinter",
        "--exclude-module", "devtools",  # Developer mode stays out of what people install.
        "--paths", str(ROOT),
        "--distpath", str(output),
        "--workpath", str(work),
        "--specpath", str(work),
    ]
    for item in INCLUDED:
        command += ["--add-data", add_data(item)]
    subprocess.run(command + [str(ROOT / "app.py")], check=True, cwd=ROOT)


def pack(output):
    """A .app on Mac, otherwise a folder. Mac needs ditto to keep the bundle intact."""
    base = output / f"{NAME}-{VERSION}-{system_label()}"
    if sys.platform == "darwin":
        archive = Path(f"{base}.zip")
        subprocess.run(
            ["ditto", "-c", "-k", "--keepParent", str(output / f"{NAME}.app"), str(archive)],
            check=True,
        )
    elif sys.platform == "win32":
        archive = Path(f"{base}.zip")
        folder = output / NAME
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
            for path in folder.rglob("*"):
                package.write(path, Path(NAME) / path.relative_to(folder))
    else:
        archive = Path(f"{base}.tar.gz")
        with tarfile.open(archive, "w:gz") as package:
            package.add(output / NAME, arcname=NAME)
    return archive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "dist"))
    parser.add_argument("--work", default=str(ROOT / "build"))
    parser.add_argument("--no-installer", action="store_true", help="skip making the installer")
    args = parser.parse_args()
    output, work = Path(args.output).resolve(), Path(args.work).resolve()
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    run_pyinstaller(output, work)
    archive = pack(output)
    print(f"Built {archive} ({archive.stat().st_size / 1_000_000:.0f} MB)")
    if not args.no_installer:
        from installers import make_installer
        installer = make_installer(output)
        print(f"Installer {installer} ({installer.stat().st_size / 1_000_000:.0f} MB)")


if __name__ == "__main__":
    main()
