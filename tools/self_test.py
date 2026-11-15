#!/usr/bin/env python3
"""Run the finished program and check it can really draw, export and read photos.

Usage: self_test.py PATH_TO_PROGRAM
"""
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

GEDCOM = """0 HEAD
1 GEDC
2 VERS 5.5.1
1 CHAR UTF-8
0 @I1@ INDI
1 NAME Šime /Čulić/
1 OBJE
2 FILE photo.png
1 FAMS @F1@
0 @I2@ INDI
1 NAME Žana /Đurić/
1 FAMS @F1@
0 @I3@ INDI
1 NAME Mia /Čulić/
1 FAMC @F1@
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 CHIL @I3@
0 TRLR
"""

def small_png():
    """A small valid PNG, enough to prove the image code is in the finished program."""

    def chunk(kind, data):
        checksum = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    width, height = 16, 16
    pixels = b"".join(b"\x00" + b"\x33\x66\x99" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def main():
    program = Path(sys.argv[1]).resolve()
    env = {**os.environ, "QT_QPA_PLATFORM": os.environ.get("SELF_TEST_PLATFORM", "offscreen")}
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        (folder / "in.ged").write_text(GEDCOM, encoding="utf-8")
        (folder / "photo.png").write_bytes(small_png())
        shot, pdf, png, ged = (folder / n for n in ("view.png", "view.pdf", "export.png", "out.ged"))
        tree = folder / "Test.tree"
        command = [
            str(program),
            "--import-gedcom", str(folder / "in.ged"),
            str(tree),
            "--screenshot", str(shot),
            "--export-picture", str(pdf),
            "--export-picture-2", str(png),
            "--export-gedcom", str(ged),
        ]
        result = subprocess.run(command, env=env, timeout=240, capture_output=True, text=True)
        print(result.stdout[-2000:], result.stderr[-2000:], sep="\n")
        if result.returncode != 0:
            sys.exit(f"Program exited with {result.returncode}")
        for path, start in ((shot, b"\x89PNG"), (png, b"\x89PNG"), (pdf, b"%PDF"), (ged, b"0 HEAD")):
            if not path.is_file() or not path.read_bytes().startswith(start):
                sys.exit(f"Missing or wrong output: {path.name}")
        text = ged.read_text(encoding="utf-8")
        for name in ("Šime", "Žana", "Đurić", "Mia"):
            if name not in text:
                sys.exit(f"{name} did not survive the round trip")
        photos = list((tree / "media").glob("*.jpg"))
        if not photos:
            sys.exit("The photo was not converted to JPEG, so the image plugins are missing")
    dev = subprocess.run([str(program), "--dev", "--sample"], env=env, timeout=120,
                         capture_output=True, text=True)
    if dev.returncode != 2 or "source" not in dev.stderr:
        sys.exit("Developer mode is reachable in the release build")
    print("Self-test passed")


if __name__ == "__main__":
    main()
