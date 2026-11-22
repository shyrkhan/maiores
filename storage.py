"""Reading and writing a tree folder, built so a crash cannot destroy the data.

    Name.tree/
      tree.json   the family record
      view.json   which house was open; losing it costs nothing
      media/      photos
      backups/    dated copies of tree.json and view.json
"""
import json
import os
import shutil
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from model import FORMAT_VERSION, Issue, Tree, TreeFormatError, validate
from strings import t

TREE_FILE = "tree.json"
VIEW_FILE = "view.json"
BACKUP_DIR = "backups"
MEDIA_DIR = "media"
BACKUP_KEEP = 30
BACKUP_INTERVAL_SECONDS = 600
_BACKUP_PREFIX = "backup-"

# Upgrades from older formats: {old_version: function(dict) -> dict at old_version + 1}.
def _sources_from_text(data):
    """Format 1 to 2: each fact's free-text "source" becomes a citation of a source record.
    The same text written on several facts becomes one source."""
    sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
    by_title = {source.get("title"): source_id for source_id, source in sources.items() if isinstance(source, dict)}

    def cite(fact):
        if not isinstance(fact, dict):
            return
        text = fact.pop("source", None)
        if not isinstance(text, str) or not text.strip():
            return
        title = text.strip()
        if title not in by_title:
            by_title[title] = f"s-{uuid.uuid4()}"
            sources[by_title[title]] = {"title": title}
        citations = fact.get("citations") if isinstance(fact.get("citations"), list) else []
        fact["citations"] = citations + [{"source": by_title[title]}]

    for person in (data.get("people") or {}).values():
        if isinstance(person, dict):
            cite(person.get("birth"))
            cite(person.get("death"))
            for event in person.get("events") if isinstance(person.get("events"), list) else []:
                cite(event)
    for family in (data.get("families") or {}).values():
        if isinstance(family, dict):
            cite(family.get("marriage"))
    if sources:
        data["sources"] = sources
    return data


MIGRATIONS = {1: _sources_from_text}


class TreeLoadError(Exception):
    """The tree could not be opened. The files on disk have not been touched."""


class DamagedTreeError(TreeLoadError):
    """The file was read but isn't a sound tree (broken JSON or structure): the only case
    in which a backup is offered in its place. A disk error is not damage."""


class NewerTreeError(TreeLoadError):
    """Saved by a newer Maiores. Not damaged: an older backup must not be offered over it."""


@dataclass
class OpenedTree:
    tree: Tree
    house: str | None = None
    issues: list = field(default_factory=list)
    mode: str = "family"


def atomic_write(path, text):
    """Replace a file in one step. Any failure leaves the old file intact."""
    path = Path(path)
    data = text.encode("utf-8")
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "wb") as temp:
            temp.write(data)
            temp.flush()
            os.fsync(temp.fileno())
        if path.exists():
            os.chmod(temp_name, stat.S_IMODE(path.stat().st_mode))
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    try:
        _sync_directory(path.parent)
    except OSError:
        pass  # The new file is already in place: reporting a failure now would be untrue.


def temp_beside(path):
    """A new, empty file with a name no one else has, beside `path`: a replacement is written
    there and then moved over `path`. A fixed name (".family.pdf.tmp") could be a file of
    the person's own, overwritten and then deleted."""
    handle, name = tempfile.mkstemp(prefix=f".{Path(path).name}.", suffix=".tmp", dir=Path(path).parent)
    os.close(handle)
    return Path(name)


def _sync_directory(directory):
    if not hasattr(os, "O_DIRECTORY"):
        return
    handle = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def _to_json(data):
    # Convert first: if this fails, nothing on disk has been touched.
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _read_json(path):
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        raise TreeLoadError(t("error_unreadable", name=Path(path).name, detail=error)) from error
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError as error:  # Not JSON, or not UTF-8: the file itself is damaged.
        raise DamagedTreeError(t("error_unreadable", name=Path(path).name, detail=error)) from error


def _backups(folder):
    directory = Path(folder) / BACKUP_DIR
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.name.startswith(_BACKUP_PREFIX))


def make_backup(folder, keep=BACKUP_KEEP):
    """Copy the current files into backups/. Skipped if nothing has changed.

    Skipping matters: reopening an unchanged tree must not push real history out
    of the limited set of backups.
    """
    folder = Path(folder)
    tree_file = folder / TREE_FILE
    if not tree_file.exists():
        return None
    existing = _backups(folder)
    if existing:
        previous = existing[-1] / TREE_FILE
        if previous.exists() and previous.read_bytes() == tree_file.read_bytes():
            return None

    directory = folder / BACKUP_DIR
    directory.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000_000:09d}"
    temp = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=directory))
    try:
        shutil.copy2(tree_file, temp / TREE_FILE)
        if (folder / VIEW_FILE).exists():
            shutil.copy2(folder / VIEW_FILE, temp / VIEW_FILE)
        target = directory / f"{_BACKUP_PREFIX}{stamp}"
        os.rename(temp, target)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    for old in _backups(folder)[:-keep]:
        shutil.rmtree(old)
    return target


def list_backups(folder):
    """Readable backups, newest first, as (folder, time, number of people)."""
    found = []
    for backup in reversed(_backups(folder)):
        try:
            data = json.loads((backup / TREE_FILE).read_text(encoding="utf-8"))
            tree = Tree.from_dict(data)
            when = time.localtime((backup / TREE_FILE).stat().st_mtime)
        except (OSError, ValueError, TreeFormatError):
            continue
        if data.get("format_version", 0) <= FORMAT_VERSION:
            found.append((backup, when, len(tree.people)))
    return found


def read_backup(backup):
    """The tree stored in one backup."""
    data = _read_json(Path(backup) / TREE_FILE)
    version = _check_version(data, TREE_FILE)
    while version < FORMAT_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
    try:
        return Tree.from_dict(data)
    except TreeFormatError as error:
        raise TreeLoadError(t("error_format", name=TREE_FILE, detail=error)) from error


def _backup_is_due(folder):
    existing = _backups(folder)
    if not existing:
        return True
    return time.time() - existing[-1].stat().st_mtime >= BACKUP_INTERVAL_SECONDS


def _check_version(data, name):
    version = data.get("format_version") if isinstance(data, dict) else None
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise DamagedTreeError(t("error_format", name=name, detail="bad format_version"))
    if version > FORMAT_VERSION:
        raise NewerTreeError(t("error_newer", name=name, version=version))
    return version


def _migrate(data, version, folder):
    """Upgrade in memory. The old file is backed up by open_tree once it has loaded, so a
    file that turns out to be broken is refused without anything written."""
    if version == FORMAT_VERSION:
        return data
    while version < FORMAT_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
        data["format_version"] = version
    return data


def _read_view(folder):
    """Returns (house id or None, issues). A bad view file never blocks the family."""
    path = Path(folder) / VIEW_FILE
    if not path.exists():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        house = data["house"]
        if house is not None and not isinstance(house, str):
            raise ValueError("house is not an ID")
    except (OSError, ValueError, KeyError, TypeError):
        return None, [Issue("view_unreadable", VIEW_FILE)]
    return house, []


def read_view_mode(folder):
    """Which chart was open. Older files said "line" for the descendant chart."""
    try:
        mode = json.loads((Path(folder) / VIEW_FILE).read_text(encoding="utf-8")).get("mode")
    except (OSError, ValueError, AttributeError):
        return "family"
    mode = "pyramid" if mode == "line" else mode
    return mode if mode in ("family", "pyramid", "pedigree", "bowtie", "fan") else "family"


def open_tree(folder):
    """Load and check a tree folder, backing it up once it is known to be readable."""
    folder = Path(folder)
    tree_file = folder / TREE_FILE
    if not tree_file.is_file():
        if not tree_file.exists() and (folder / BACKUP_DIR).is_dir():
            # The tree's own folder with backups, but its file gone: that is damage too.
            raise DamagedTreeError(t("error_no_tree", path=folder))
        raise TreeLoadError(t("error_no_tree", path=folder))
    data = _read_json(tree_file)
    version = _check_version(data, TREE_FILE)
    data = _migrate(data, version, folder)
    try:
        tree = Tree.from_dict(data)
    except TreeFormatError as error:
        raise DamagedTreeError(t("error_format", name=TREE_FILE, detail=error)) from error
    try:
        make_backup(folder)
    except OSError:
        pass  # A full disk mustn't keep you out of your tree; the next save tries again.
    house, view_issues = _read_view(folder)
    if house not in tree.people:
        house = None
    return OpenedTree(tree, house, validate(tree) + view_issues, read_view_mode(folder))


def recover_from_backup(folder, backup):
    """Put a backup's tree.json in place of a damaged one. The damaged file is kept beside
    it (never deleted), and photos, documents and the other backups are left alone."""
    folder = Path(folder)
    tree_file = folder / TREE_FILE
    text = (Path(backup) / TREE_FILE).read_text(encoding="utf-8")
    if tree_file.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        kept = folder / f"tree-damaged-{stamp}.json"
        number = 1
        while kept.exists():
            number += 1
            kept = folder / f"tree-damaged-{stamp}-{number}.json"
        shutil.copy2(tree_file, kept)
    atomic_write(tree_file, text)


def read_tree(folder):
    """Load someone else's tree folder without writing anything into it: no backup, no
    lock, an older format upgraded in memory only. Used for combining trees."""
    folder = Path(folder)
    tree_file = folder / TREE_FILE
    if not tree_file.is_file():
        raise TreeLoadError(t("error_no_tree", path=folder))
    data = _read_json(tree_file)
    version = _check_version(data, TREE_FILE)
    while version < FORMAT_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
    try:
        return Tree.from_dict(data)
    except TreeFormatError as error:
        raise TreeLoadError(t("error_format", name=TREE_FILE, detail=error)) from error


def create_tree(folder, tree):
    """Make a new tree folder. Refuses to replace an existing tree."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / TREE_FILE).exists():
        raise FileExistsError(folder / TREE_FILE)
    (folder / MEDIA_DIR).mkdir(exist_ok=True)
    (folder / BACKUP_DIR).mkdir(exist_ok=True)
    atomic_write(folder / TREE_FILE, _to_json(tree.to_dict()))


def save_tree(folder, tree):
    """Save the family record, keeping a backup if one is due."""
    text = _to_json(tree.to_dict())
    if _backup_is_due(folder):
        make_backup(folder)
    atomic_write(Path(folder) / TREE_FILE, text)


def save_view(folder, house, mode="family"):
    atomic_write(
        Path(folder) / VIEW_FILE,
        _to_json({"format_version": FORMAT_VERSION, "house": house, "mode": mode}),
    )
