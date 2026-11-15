"""Documents attached to people: scans of certificates, letters, old photos.

Files are copied into the tree's media/docs folder and named by their content, so
the same scan attached twice (or brought in again by combining trees) is stored
once. Removing a document from someone never deletes the file: undo can bring the
reference back. Only known document, picture, sound and video types are accepted,
and only those are ever handed to the system to open, never a program or script.
"""
import hashlib
import os
import shutil
from pathlib import Path

from model import photo_is_safe

MEDIA_DIR = "media"
DOCS_DIR = "docs"
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
ALLOWED_TYPES = IMAGE_TYPES | {
    ".pdf", ".txt", ".rtf", ".odt", ".doc", ".docx", ".ods", ".xls", ".xlsx", ".csv",
    ".heic", ".mp3", ".m4a", ".ogg", ".wav", ".mp4", ".mov", ".webm",
}
MAX_SIZE = 500 * 1024 * 1024  # A film of a family wedding fits; a disk image doesn't.


class DocumentError(Exception):
    pass


def is_allowed(path):
    return Path(path).suffix.lower() in ALLOWED_TYPES


def is_image(path):
    return Path(path).suffix.lower() in IMAGE_TYPES


def _content_name(source, suffix):
    digest = hashlib.sha256()
    with open(source, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"{digest.hexdigest()[:24]}{suffix}"


def store_document(source, folder):
    """Copy a file into the tree and return its stored path (media/docs/...)."""
    source = Path(source)
    suffix = source.suffix.lower()
    if suffix not in ALLOWED_TYPES:
        raise DocumentError("type")
    if not source.is_file():
        raise DocumentError("missing")
    if source.stat().st_size > MAX_SIZE:
        raise DocumentError("size")
    docs = Path(folder) / MEDIA_DIR / DOCS_DIR
    docs.mkdir(parents=True, exist_ok=True)
    name = _content_name(source, suffix)
    target = docs / name
    if not target.exists():
        temp = docs / f".{name}.tmp"
        shutil.copyfile(source, temp)
        os.replace(temp, target)
    return f"{MEDIA_DIR}/{DOCS_DIR}/{name}"


def resolve_document(folder, stored):
    """The real file for a stored path, or None if it is unsafe, of a refused type or missing.
    Trees come from other people, so the path must stay inside the media folder."""
    if not folder or not stored or not photo_is_safe(stored) or not is_allowed(stored):
        return None
    media = (Path(folder) / MEDIA_DIR).resolve()
    path = (Path(folder) / stored).resolve()
    if not path.is_relative_to(media) or not path.is_file():
        return None
    return path


def copy_from_tree(their_folder, stored, my_folder):
    """A document of another tree, copied into this one; "" if it can't be used."""
    source = resolve_document(their_folder, stored)
    if source is None:
        return ""
    try:
        return store_document(source, my_folder)
    except (DocumentError, OSError):
        return ""
