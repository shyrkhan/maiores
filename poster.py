"""A wall poster of the current chart: one large sheet for a print shop (A2 to A0), or
tiles on ordinary paper to tape together. Drawn as vectors straight into the PDF, page
by page, so even an A0 poster needs no giant picture in memory.

Tiles overlap by OVERLAP_MM so they can be glued; each carries its row and column and
small corner marks showing where to cut.
"""
import math

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

PAPERS = {"A4": QPageSize.PageSizeId.A4, "A3": QPageSize.PageSizeId.A3, "A2": QPageSize.PageSizeId.A2,
          "A1": QPageSize.PageSizeId.A1, "A0": QPageSize.PageSizeId.A0}
DPI = 300
MARGIN_MM = 8
OVERLAP_MM = 10


def plan(area, paper="A4", across=1):
    """(orientation, rows, columns) for a chart of size `area` printed `across` sheets wide."""
    landscape = area.width() >= area.height()
    orientation = QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait
    size = QPageSize(PAPERS[paper]).size(QPageSize.Unit.Millimeter)
    width, height = (size.height(), size.width()) if landscape else (size.width(), size.height())
    usable_w, usable_h = width - 2 * MARGIN_MM, height - 2 * MARGIN_MM
    if across <= 1:
        return orientation, 1, 1
    step_w = usable_w - OVERLAP_MM
    total_w = across * step_w + OVERLAP_MM
    total_h = total_w * area.height() / max(area.width(), 1)
    rows = max(1, math.ceil((total_h - OVERLAP_MM) / (usable_h - OVERLAP_MM)))
    return orientation, rows, across


def write_poster(scene, area, path, paper="A4", across=1, label=lambda row, column: ""):
    """Draw `area` of `scene` onto one sheet, or onto tiles `across` sheets wide."""
    orientation, rows, columns = plan(area, paper, across)
    from storage import temp_beside
    temp = temp_beside(path)
    writer = QPdfWriter(str(temp))
    writer.setResolution(DPI)
    writer.setPageLayout(QPageLayout(QPageSize(PAPERS[paper]), orientation,
                                     QMarginsF(MARGIN_MM, MARGIN_MM, MARGIN_MM, MARGIN_MM), QPageLayout.Unit.Millimeter))
    painter = QPainter()
    try:
        if not painter.begin(writer):
            raise OSError(str(path))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        page = QRectF(painter.viewport())
        mm = page.width() / (writer.pageLayout().paintRect(QPageLayout.Unit.Millimeter).width())
        if columns == 1:
            painter.fillRect(page, QColor("white"))
            scene.render(painter, page, area, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            overlap = OVERLAP_MM * mm
            step_w, step_h = page.width() - overlap, page.height() - overlap
            scale = (columns * step_w + overlap) / area.width()
            for row in range(rows):
                for column in range(columns):
                    if row or column:
                        writer.newPage()
                    painter.fillRect(page, QColor("white"))
                    source = QRectF(area.left() + column * step_w / scale, area.top() + row * step_h / scale,
                                    page.width() / scale, page.height() / scale)
                    painter.save()
                    painter.setClipRect(page)
                    scene.render(painter, page, source, Qt.AspectRatioMode.IgnoreAspectRatio)
                    painter.restore()
                    _marks(painter, page, overlap, mm, label(row + 1, column + 1))
        painter.end()
        del writer  # Closes the file before it is renamed.
        temp.replace(path)
    finally:
        if painter.isActive():
            painter.end()
        temp.unlink(missing_ok=True)
    return rows * columns


def _marks(painter, page, overlap, mm, text):
    """Where to cut (the overlap is glued under the next sheet) and which tile this is."""
    painter.save()
    painter.setPen(QPen(QColor("#9a9a9a"), 0.2 * mm))
    right, bottom = page.right() - overlap, page.bottom() - overlap
    for x, y in ((right, page.top()), (right, bottom), (page.left(), bottom)):
        painter.drawLine(QPointF(x - 3 * mm, y), QPointF(x + 3 * mm, y))
        painter.drawLine(QPointF(x, y - 3 * mm), QPointF(x, y + 3 * mm))
    font = QFont()
    font.setPixelSize(round(3 * mm))
    painter.setFont(font)
    painter.setPen(QColor("#777777"))
    import branding
    mark = QImage(str(branding.SMALL_ICON))
    left = page.left() + 2 * mm
    if not mark.isNull():  # The Maiores mark beside which tile this is.
        painter.drawImage(QRectF(left, page.bottom() - 5.5 * mm, 4 * mm, 4 * mm), mark)
        left += 5 * mm
    painter.drawText(QRectF(left, page.bottom() - 6 * mm, page.width() / 2, 5 * mm),
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
    painter.restore()
