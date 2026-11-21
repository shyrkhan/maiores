"""Copying portraits into a tree's media folder, and loading them safely."""
import collections
import os
import uuid
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QRect, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QImageWriter, QPainter, QPixmap

from house_layout import PORTRAIT_H, PORTRAIT_W
from model import inside_media, photo_is_safe

MEDIA_DIR = "media"
STORED_W, STORED_H = 480, round(480 * PORTRAIT_H / PORTRAIT_W)
FACE_BIAS = 0.25  # Faces sit high in a photo, so a tall crop keeps more of the top.


class PhotoError(Exception):
    pass


def default_crop(image):
    """The automatic crop: the portrait shape, keeping more of the top of the picture."""
    target_ratio = STORED_W / STORED_H
    width, height = image.width(), image.height()
    if width / height > target_ratio:
        crop_w, crop_h = round(height * target_ratio), height
        return QRect((width - crop_w) // 2, 0, crop_w, crop_h)
    crop_w, crop_h = width, round(width / target_ratio)
    return QRect(0, round((height - crop_h) * FACE_BIAS), crop_w, crop_h)


def _prepared(image, crop):
    """Cut out the chosen part, then shrink it, flattening any transparency."""
    piece = image.copy(crop).scaled(
        STORED_W,
        STORED_H,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    flat = QImage(piece.size(), QImage.Format.Format_RGB32)
    flat.fill(QColor("white"))
    painter = QPainter(flat)
    painter.drawImage(0, 0, piece)
    painter.end()
    return flat


def read_image(source):
    """Load a picture the right way up, or raise PhotoError."""
    reader = QImageReader(str(source))
    reader.setAutoTransform(True)  # Phone photos are stored sideways with a rotation tag.
    image = reader.read()
    if image.isNull():
        raise PhotoError(reader.errorString())
    return image


def store_photo(image, folder, crop=None):
    """Save a prepared copy into media/ under a new name and return its stored path.

    The name is always new, so undoing a photo change still finds the old file.
    """
    media = Path(folder) / MEDIA_DIR
    media.mkdir(exist_ok=True)
    name = f"{uuid.uuid4().hex}.jpg"
    temp = media / f".{name}.tmp"
    try:
        # The file must be closed before the rename, or Windows refuses to move it.
        output = QFile(str(temp))
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise PhotoError(output.errorString())
        writer = QImageWriter(output, b"jpeg")
        writer.setQuality(90)
        written = writer.write(_prepared(image, crop or default_crop(image)))
        problem = writer.errorString()
        output.close()
        if not written:
            raise PhotoError(problem)
        os.replace(temp, media / name)
    finally:
        temp.unlink(missing_ok=True)
    return f"{MEDIA_DIR}/{name}"


def import_photo(source, folder, crop=None):
    return store_photo(read_image(source), folder, crop)


def resolve_photo(folder, stored):
    """The real file for a stored path, or None if it is unsafe or missing.

    Trees can come from other people, so a path must stay inside the media folder.
    """
    if not folder or not photo_is_safe(stored) or not stored:
        return None
    path = inside_media(folder, stored)
    return path if path is not None and path.is_file() else None


class PhotoCache:
    """Decoded portraits, the most recently used kept up to LIMIT bytes. Keeping every one
    until the tree closed held hundreds of megabytes on a tree full of photos."""
    LIMIT = 48 * 1024 * 1024

    def __init__(self, limit=None):
        self._loaded = collections.OrderedDict()
        self._bytes = 0
        self.limit = self.LIMIT if limit is None else limit

    def clear(self):
        self._loaded.clear()
        self._bytes = 0

    @staticmethod
    def _size(pixmap):
        return 0 if pixmap is None else pixmap.width() * pixmap.height() * max(1, pixmap.depth() // 8)

    def get(self, folder, stored):
        if not stored:
            return None
        if stored in self._loaded:
            self._loaded.move_to_end(stored)
            return self._loaded[stored]
        path = resolve_photo(folder, stored)
        pixmap = QPixmap(str(path)) if path else QPixmap()
        pixmap = None if pixmap.isNull() else pixmap
        self._loaded[stored] = pixmap
        self._bytes += self._size(pixmap)
        while self._bytes > self.limit and len(self._loaded) > 1:
            _old, dropped = self._loaded.popitem(last=False)
            self._bytes -= self._size(dropped)
        return pixmap
