#!/usr/bin/env python3
"""Make every picture of Maiores from branding.py: the program icon, the Windows setup
pictures, and the README banner and GitHub social preview of the public copy.

    python tools/make_graphics.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402


APP = None


def small_mark(size=55):
    """The setup wizard's small corner picture: the tile alone."""
    import branding
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(QRectF(0, 0, size, size), branding.app_icon(512))
    painter.end()
    return image


def main():
    global APP
    APP = QGuiApplication(sys.argv[:1])  # Fonts and drawing need an application.
    import branding
    made = {
        ROOT / "assets" / "icon.png": branding.app_icon(1024),
        ROOT / "assets" / "icon-64.png": branding.app_icon(64),
        ROOT / "assets" / "installer-side.png": branding.installer_side(),
        ROOT / "assets" / "installer-small.png": small_mark(),
        ROOT / "assets" / "dmg-background.png": branding.dmg_background(),
        ROOT / "tools" / "public" / "docs" / "banner.png": branding.banner(),
        ROOT / "tools" / "public" / "docs" / "social-preview.png": branding.social_preview(),
    }
    for path, image in made.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(path))
        print(f"{path.relative_to(ROOT)}  {image.width()}x{image.height()}")


if __name__ == "__main__":
    main()
