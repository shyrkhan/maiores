"""Sending a tree out of the program: GEDCOM files, pictures and PDFs."""
import shutil
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter

from canvas import BACKGROUND, INK_PRINT, INK_SCREEN, build_scene
from gedcom import write_gedcom
from photos import resolve_photo
from storage import atomic_write
from strings import t

PICTURE_SCALE = 2.0
PICTURE_LIMIT = 16000
PICTURE_MARGIN = 60
PDF_DPI = 300


class ExportError(Exception):
    pass


def export_gedcom(tree, folder, path):
    """Write a GEDCOM file, with its photos in a folder beside it."""
    path = Path(path)
    media_name = f"{path.stem}_media"
    copies = {}

    def record_photo(stored):
        source = resolve_photo(folder, stored)
        if source is None:
            return None
        copies[stored] = source
        return f"{media_name}/{source.name}"

    text = write_gedcom(tree, path, record_photo)
    try:
        if copies:
            media = path.parent / media_name
            media.mkdir(exist_ok=True)
            for source in copies.values():
                shutil.copy2(source, media / source.name)
        atomic_write(path, text)
    except OSError as error:
        raise ExportError(str(error)) from error
    return len(copies)


def _prepared_scene(tree, layout, today, photo_for, ink, detail="age"):
    scene, _ = build_scene(tree, layout, today, photo_for, ink, detail=detail)
    return scene, scene.itemsBoundingRect().adjusted(
        -PICTURE_MARGIN, -PICTURE_MARGIN, PICTURE_MARGIN, PICTURE_MARGIN
    )


def prepared_scene(tree, layout, today, photo_for, ink, detail="age"):
    """The chart drawn off screen, and the area it covers, for printing and posters."""
    return _prepared_scene(tree, layout, today, photo_for, ink, detail)


def _export_png(tree, layout, today, photo_for, path, detail="age"):
    scene, area = _prepared_scene(tree, layout, today, photo_for, INK_SCREEN, detail)
    scale = min(PICTURE_SCALE, PICTURE_LIMIT / max(area.width(), area.height()))
    image = QImage(
        round(area.width() * scale), round(area.height() * scale), QImage.Format.Format_RGB32
    )
    if image.isNull():
        raise ExportError(t("export_too_big"))
    image.fill(BACKGROUND)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scene.render(painter, QRectF(image.rect()), area)
    painter.end()
    temp = Path(path).with_name(f".{Path(path).name}.tmp")
    try:
        if not image.save(str(temp), "PNG"):
            raise ExportError(t("export_failed", path=path))
        temp.replace(path)
    except OSError as error:
        raise ExportError(str(error)) from error
    finally:
        temp.unlink(missing_ok=True)


def _export_pdf(tree, layout, today, photo_for, path, detail="age"):
    """One A3 page in whichever direction suits the tree, in ink-saving colours."""
    scene, area = _prepared_scene(tree, layout, today, photo_for, INK_PRINT, detail)
    temp = Path(path).with_name(f".{Path(path).name}.tmp")
    writer = QPdfWriter(str(temp))
    writer.setResolution(PDF_DPI)
    orientation = (
        QPageLayout.Orientation.Landscape
        if area.width() >= area.height()
        else QPageLayout.Orientation.Portrait
    )
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A3),
            orientation,
            QMarginsF(10, 10, 10, 10),
            QPageLayout.Unit.Millimeter,
        )
    )
    painter = QPainter()
    try:
        if not painter.begin(writer):
            raise ExportError(t("export_failed", path=path))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(painter.viewport(), QColor("white"))
        scene.render(painter, QRectF(painter.viewport()), area, Qt.AspectRatioMode.KeepAspectRatio)
        painter.end()
        del writer  # Closes the file, which Windows needs before it can be renamed.
        temp.replace(path)
    except OSError as error:
        raise ExportError(str(error)) from error
    finally:
        if painter.isActive():
            painter.end()
        temp.unlink(missing_ok=True)


def export_picture(tree, layout, today, photo_for, path, detail="age"):
    """Save the current view. The file's ending chooses between PDF and PNG."""
    exporter = _export_pdf if Path(path).suffix.lower() == ".pdf" else _export_png
    exporter(tree, layout, today, photo_for, path, detail)


def print_view(tree, layout, today, photo_for, printer, detail="age"):
    """Draw the chart onto a printer's pages: as large as fits, in ink-saving colours."""
    scene, area = _prepared_scene(tree, layout, today, photo_for, INK_PRINT, detail)
    painter = QPainter()
    if not painter.begin(printer):
        raise ExportError(t("print_failed"))
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        page = QRectF(painter.viewport())
        painter.fillRect(page, QColor("white"))
        scene.render(painter, page, area, Qt.AspectRatioMode.KeepAspectRatio)
    finally:
        painter.end()


def best_orientation(layout_area):
    """Landscape for wide charts, portrait for tall ones."""
    return (QPageLayout.Orientation.Landscape if layout_area.width() >= layout_area.height()
            else QPageLayout.Orientation.Portrait)


def export_map_pins(tree, path, rows, kinds=None):
    """A CSV for Google My Maps: one row per event with a place.

    Google turns the place names into pins when the file is imported; nothing is
    sent anywhere by this program. `kinds` limits it to, say, births only.
    """
    import csv
    import io
    from dialogs import fact_label
    from model import date_input_text
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([t("map_col_name"), t("map_col_event"), t("map_col_date"), t("map_col_place")])
    count = 0
    for row in rows:
        if not row.place or (kinds and row.kind not in kinds) or row.person_id not in tree.people:
            continue
        name = tree.people[row.person_id].display_name
        writer.writerow([name, fact_label(tree, row), date_input_text(row.date), row.place])
        count += 1
    try:
        atomic_write(path, "\ufeff" + buffer.getvalue())  # The mark lets spreadsheet programs see UTF-8.
    except OSError as error:
        raise ExportError(str(error)) from error
    return count
