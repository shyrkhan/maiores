#!/usr/bin/env python3
"""Turn a finished build into an installer for this computer's system.

    Linux:   maiores_1.4.0_amd64.deb   (made here in Python, so it builds on any Linux)
    Windows: Maiores 1.4.0 setup.exe   (Inno Setup's compiler, iscc, must be installed)
    Mac:     Maiores 1.4.0 (Apple chip).dmg / (Intel).dmg         (hdiutil, which every Mac has)

Usage: installers.py [--dist DIR]. build.py calls this after building.
"""
import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from version import VERSION  # noqa: E402

NAME = "maiores"
TITLE = "Maiores"
SUMMARY = "Family tree program: charts, sources, DNA, GEDCOM; your tree stays on your computer"
MAINTAINER = "Maiores <noreply@maiores.invalid>"
OLD_NAME = "family-tree"  # What the program was called before; the new package replaces it.


# Linux: a .deb is an 'ar' archive of three members, written here directly.

def _ar_member(name, data):
    header = (f"{name:<16}{int(time.time()):<12}{0:<6}{0:<6}{0o100644:<8o}{len(data):<10}`\n").encode()
    return header + data + (b"\n" if len(data) % 2 else b"")


def _tar_gz(entries):
    """entries: (archive path, bytes or None for a folder, mode, symlink target or None)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for path, data, mode, link in entries:
            info = tarfile.TarInfo(path)
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = int(time.time())
            info.mode = mode
            if link is not None:
                info.type, info.linkname = tarfile.SYMTYPE, link
                tar.addfile(info)
            elif data is None:
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _translated_names():
    """GenericName[de]=Stammbaum and so on: what the program is, in the system's language."""
    import strings
    return "".join(f"GenericName[{code}]={table['app_tagline']}\n" for code, table in strings.STRINGS.items()
                   if code != "en" and table.get("app_tagline"))


def make_deb(dist):
    program = dist / NAME
    if not (program / NAME).is_file():
        raise SystemExit(f"Build the program first: {program / NAME} is missing")
    entries, folders = [], set()

    def folder(path):
        parts = Path(path).parts
        for depth in range(1, len(parts) + 1):
            name = "./" + "/".join(parts[:depth])
            if name not in folders:
                folders.add(name)
                entries.append((name, None, 0o755, None))

    for path in sorted(program.rglob("*")):
        relative = Path("opt") / NAME / path.relative_to(program)
        if path.is_symlink():
            folder(relative.parent)
            entries.append(("./" + relative.as_posix(), None, 0o777, os.readlink(path)))
        elif path.is_dir():
            folder(relative)
        else:
            folder(relative.parent)
            executable = os.access(path, os.X_OK)
            entries.append(("./" + relative.as_posix(), path.read_bytes(), 0o755 if executable else 0o644, None))
    folder("usr/bin")
    entries.append((f"./usr/bin/{NAME}", None, 0o777, f"/opt/{NAME}/{NAME}"))
    desktop = (
        "[Desktop Entry]\nType=Application\n"
        f"Name={TITLE}\nGenericName=Family tree\n{_translated_names()}Comment={SUMMARY}\n"
        f"Exec=/opt/{NAME}/{NAME} %f\nIcon={NAME}\nTerminal=false\nCategories=Office;\n"
    )
    folder("usr/share/applications")
    entries.append((f"./usr/share/applications/{NAME}.desktop", desktop.encode(), 0o644, None))
    from PIL import Image
    icon = Image.open(ROOT / "assets" / "icon.png")
    for size in (48, 64, 128, 256, 512):  # Each size the desktop may ask for.
        buffer = io.BytesIO()
        icon.resize((size, size), Image.Resampling.LANCZOS).save(buffer, "PNG")
        folder(f"usr/share/icons/hicolor/{size}x{size}/apps")
        entries.append((f"./usr/share/icons/hicolor/{size}x{size}/apps/{NAME}.png", buffer.getvalue(), 0o644, None))
    size_kb = sum(len(data) for _p, data, _m, _l in entries if data) // 1024
    control = (
        f"Package: {NAME}\nVersion: {VERSION}\nSection: misc\nPriority: optional\n"
        f"Architecture: amd64\nMaintainer: {MAINTAINER}\nInstalled-Size: {size_kb}\n"
        "Depends: libgl1, libegl1, libxkbcommon0, libxkbcommon-x11-0, libfontconfig1, libdbus-1-3, "
        "libxcb-cursor0\n"
        f"Conflicts: {OLD_NAME}\nReplaces: {OLD_NAME}\nProvides: {OLD_NAME}\n"
        f"Description: {SUMMARY}\n Keep your family tree on your own computer: portrait cards,\n"
        " family, pyramid, pedigree, bow tie and fan charts, GEDCOM import and export.\n"
    )
    control_tar = _tar_gz([("./control", control.encode(), 0o644, None)])
    data_tar = _tar_gz(entries)
    target = dist / f"{NAME}_{VERSION}_amd64.deb"
    target.write_bytes(b"!<arch>\n" + _ar_member("debian-binary", b"2.0\n")
                       + _ar_member("control.tar.gz", control_tar) + _ar_member("data.tar.gz", data_tar))
    return target


# Windows: Inno Setup does the installing, the Start menu entry and the uninstaller.

INNO = r"""
#define AppVersion "{version}"
[Setup]
AppId={{{{6C8E3B1A-2F4D-4E8B-9A57-3D1C2B4F7A90}}
AppName={title}
AppVersion={{#AppVersion}}
AppPublisher=Maiores
AppPublisherURL=https://github.com/shyrkhan/maiores
WizardImageFile={side_image}
WizardSmallImageFile={small_image}
DefaultDirName={{autopf}}\{title}
DefaultGroupName={title}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={output}
OutputBaseFilename={title} {{#AppVersion}} setup
SetupIconFile={icon}
UninstallDisplayIcon={{app}}\{name}.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
{extra_languages}[Tasks]
Name: "desktopicon"; Description: "{{cm:CreateDesktopIcon}}"; GroupDescription: "{{cm:AdditionalIcons}}"
[Files]
Source: "{source}\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{{group}}\{title}"; Filename: "{{app}}\{name}.exe"
Name: "{{group}}\{{cm:UninstallProgram,{title}}}"; Filename: "{{uninstallexe}}"
Name: "{{autodesktop}}\{title}"; Filename: "{{app}}\{name}.exe"; Tasks: desktopicon
[Run]
Filename: "{{app}}\{name}.exe"; Description: "{{cm:LaunchProgram,{title}}}"; Flags: nowait postinstall skipifsilent
"""


def _windows_icon(dist):
    """Inno Setup wants an .ico; make one from the PNG with Pillow (a build requirement)."""
    from PIL import Image
    icon = dist / "installer-icon.ico"
    Image.open(ROOT / "assets" / "icon.png").save(icon, sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    return icon


def _installer_images(dist):
    """Inno Setup's pictures are BMP files: made from the PNGs in assets (make_graphics.py)."""
    from PIL import Image
    made = []
    for name in ("installer-side", "installer-small"):
        target = dist / f"{name}.bmp"
        Image.open(ROOT / "assets" / f"{name}.png").convert("RGB").save(target)
        made.append(target)
    return made


def make_windows_installer(dist):
    compiler = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if not Path(compiler).is_file():
        raise SystemExit("Inno Setup is not installed (iscc not found)")
    script = dist / "installer.iss"
    # Inno Setup ships no Croatian wizard text officially; use it only when someone installed it.
    croatian = Path(compiler).parent / "Languages" / "Croatian.isl"
    extra = 'Name: "croatian"; MessagesFile: "compiler:Languages\\Croatian.isl"\n' if croatian.is_file() else ""
    side, small = _installer_images(dist)
    script.write_text(INNO.format(version=VERSION, title=TITLE, name=NAME, output=dist,
                                  icon=_windows_icon(dist), source=dist / NAME, extra_languages=extra,
                                  side_image=side, small_image=small),
                      encoding="utf-8")
    subprocess.run([compiler, "/Q", str(script)], check=True)
    return dist / f"{TITLE} {VERSION} setup.exe"


# Mac: a disk image holding the app and a shortcut to Applications to drag it onto.

def _hdiutil(command, check=False):
    for attempt in range(5):  # "Resource busy" happens now and then while macOS indexes the files.
        if subprocess.run(command).returncode == 0:
            return True
        time.sleep(5 * (attempt + 1))
    if check:
        subprocess.run(command, check=True)
    return False


ARRANGE = """
tell application "Finder"
  tell disk "{volume}"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {{200, 120, 860, 520}}
    set viewOptions to the icon view options of container window
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to 112
    set background picture of viewOptions to file ".background:background.png"
    set position of item "{title}.app" of container window to {{180, 200}}
    set position of item "Applications" of container window to {{480, 200}}
    close
    open
    update without registering applications
    delay 2
    close
  end tell
end tell
"""


def _arrange_window(image, volume):
    """The install window as people should see it: the picture behind, the app on the left,
    Applications on the right. Needs Finder; returns False if this Mac can't do it."""
    mount = Path("/Volumes") / volume
    if not _hdiutil(["hdiutil", "attach", str(image), "-readwrite", "-noverify", "-noautoopen"]):
        return False
    try:
        script = ARRANGE.format(volume=volume, title=TITLE)
        done = subprocess.run(["osascript", "-e", script], timeout=120).returncode == 0
        subprocess.run(["sync"])
        return done
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        _hdiutil(["hdiutil", "detach", str(mount), "-force"])


def make_dmg(dist):
    staging = dist / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    subprocess.run(["ditto", str(dist / f"{NAME}.app"), str(staging / f"{TITLE}.app")], check=True)
    (staging / "Applications").symlink_to("/Applications")
    background = staging / ".background"
    background.mkdir()
    shutil.copy(ROOT / "assets" / "dmg-background.png", background / "background.png")
    import platform
    chip = "Apple chip" if platform.machine().lower() in ("arm64", "aarch64") else "Intel"
    target = dist / f"{TITLE} {VERSION} ({chip}).dmg"
    target.unlink(missing_ok=True)
    volume = f"{TITLE} {VERSION}"
    writable = dist / "dmg-writable.dmg"
    writable.unlink(missing_ok=True)
    made = _hdiutil(["hdiutil", "create", "-volname", volume, "-srcfolder", str(staging), "-ov", "-format",
                     "UDRW", str(writable)])
    if made and _arrange_window(writable, volume):
        _hdiutil(["hdiutil", "convert", str(writable), "-format", "UDZO", "-ov", "-o", str(target)], check=True)
    else:  # The window could not be arranged here: a plain disk image, as before.
        _hdiutil(["hdiutil", "create", "-volname", volume, "-srcfolder", str(staging), "-ov", "-format", "UDZO",
                  str(target)], check=True)
    writable.unlink(missing_ok=True)
    shutil.rmtree(staging, ignore_errors=True)
    return target


def make_installer(dist):
    if sys.platform == "win32":
        return make_windows_installer(dist)
    if sys.platform == "darwin":
        return make_dmg(dist)
    return make_deb(dist)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default=str(ROOT / "dist"))
    target = make_installer(Path(parser.parse_args().dist).resolve())
    print(f"Installer {target} ({target.stat().st_size / 1_000_000:.0f} MB)")


if __name__ == "__main__":
    main()
