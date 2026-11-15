#!/usr/bin/env python3
"""Screenshots of the real window, using its real dialogs. Usage: smoke.py OUTPUT_DIR

Run with QT_QPA_PLATFORM=offscreen so no window appears on the user's screen.
"""
import datetime
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import edits
import house_layout as hl
from app import MainWindow, apply_theme
from dialogs import CropDialog, PersonDialog
from photos import default_crop
from sample import sample_tree
from storage import create_tree

TODAY = datetime.date(2026, 11, 4)


def drag(viewport, start, end):
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    for step in range(1, 11):
        QTest.mouseMove(viewport, start + (end - start) * step / 10)
        QApplication.processEvents()
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
    QApplication.processEvents()


def double_click(window, person_id):
    view, item = window.view, window.person_items[person_id]
    middle = item.scenePos() + QPointF(hl.PORTRAIT_W / 2, hl.PORTRAIT_H / 2)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(middle))
    QApplication.processEvents()


def fake_portrait(path, colour):
    image = QImage(600, 800, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#e0b9a0"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(300, 300), 130, 165)
    painter.setBrush(QColor("#404a60"))
    painter.drawEllipse(QPointF(300, 900), 280, 380)
    painter.end()
    image.save(str(path))
    return path


def main():
    out = Path(sys.argv[1])
    app = QApplication(sys.argv[:1])
    apply_theme(app)
    window = MainWindow(today=TODAY)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.grab().save(str(out / "0_start.png"))

    window.load_sample()
    QTest.qWait(50)
    view, viewport = window.view, window.view.viewport()
    window.grab().save(str(out / "1_tree.png"))
    assert window.house == "ante", window.house

    anchor = view.mapToScene(QPoint(20, 40))
    drag(viewport, QPoint(20, 40), QPoint(170, 140))
    assert view.mapToScene(QPoint(20, 40)) != anchor, "background drag did not pan"

    zoom = view.zoom_level()
    wheel = QWheelEvent(
        QPointF(viewport.rect().center()),
        QPointF(viewport.mapToGlobal(viewport.rect().center())),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(viewport, wheel)
    assert view.zoom_level() > zoom, "wheel did not zoom in"
    view.fit_tree()

    double_click(window, "mara")
    assert window.house == "stipe", f"partner's family did not open: {window.house}"
    assert window.person_items["mara"].highlighted, "arrival person not highlighted"
    window.grab().save(str(out / "2_partner_family.png"))
    window.go_back()
    assert window.house == "ante", "back did not return"

    double_click(window, "ana")
    assert window.house == "ante", "person with no parents must not change the view"
    assert "no recorded parents" in window.statusBar().currentMessage()
    double_click(window, "ivan")
    assert window.house == "ante", "double-clicking a blood relative changed the view"

    reversed_tree = sample_tree()
    reversed_tree.families["f-luka"].partners.reverse()
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp) / "Sample.tree"
        create_tree(folder, reversed_tree)
        other = MainWindow(today=TODAY)
        other.show()
        other.open_path(folder)
        QTest.qWaitForWindowExposed(other)
        QTest.qWait(50)
        other.ask_person = lambda *a, **k: None
        other.ask_crop = default_crop
        double_click(other, "ivana")
        assert other.house == "ante", f"partner order moved a blood relative: {other.house}"
        double_click(other, "mara")
        assert other.house == "stipe", f"partner's family did not open: {other.house}"
        other.go_back()

        for person_id, colour in (("ante", "#6b7b8c"), ("ruzica", "#8c6b7b"), ("luka", "#6b8c7b"), ("mara", "#8c7b6b")):
            portrait = fake_portrait(Path(temp) / f"{person_id}.png", colour)
            other.ask_photo = lambda path=portrait: path
            other.run_action("photo", person_id)
        other.select("luka")
        other._show_panel_now()
        other.view.fit_tree()
        QApplication.processEvents()
        other.grab().save(str(out / "3_panel_and_photos.png"))

        other.export_picture(out / "5_print.pdf")
        other.export_picture(out / "6_picture.png")
        crop_image = QImage(str(fake_portrait(Path(temp) / "wide.png", "#556677"))).scaled(1400, 900)
        crop = CropDialog(other, crop_image)
        crop.show()
        QApplication.processEvents()
        crop.grab().save(str(out / "7_crop.png"))
        crop.close()

        heavy = sample_tree()
        for number in range(2):
            person = edits.make_person({"given": f"Second{number}", "surname": "Partner", "living": "yes"})
            edits.add_partner(heavy, "josip", person, new_family=True)
            edits.add_child(heavy, person.id, edits.make_person({"given": f"Halfkid{number}", "living": "yes"}))
        heavy_folder = Path(temp) / "Heavy.tree"
        create_tree(heavy_folder, heavy)
        third = MainWindow(today=TODAY)
        third.show()
        third.open_path(heavy_folder)
        third.toggle_collapsed("luka")
        third.view.fit_tree()
        QApplication.processEvents()
        third.grab().save(str(out / "8_partners_and_hidden.png"))
        for number in range(3, 5):
            person = edits.make_person({"given": f"Second{number}", "surname": "Partner", "living": "yes"})
            edits.add_partner(third.tree, "ivan", person, new_family=True)
            edits.add_child(third.tree, person.id, edits.make_person({"given": f"Halfkid{number}", "living": "yes"}))
        person = edits.make_person({"given": "Third", "surname": "Partner", "living": "yes"})
        edits.add_partner(third.tree, "ivan", person, new_family=True)
        edits.add_child(third.tree, person.id, edits.make_person({"given": "Thirdkid", "living": "yes"}))
        third.refresh(keep_view=False)
        QApplication.processEvents()
        third.grab().save(str(out / "9_three_partners.png"))
        third.show_ancestors("ivana")
        third.view.fit_tree()
        QApplication.processEvents()
        third.grab().save(str(out / "10_ancestors.png"))
        third.close()

        dialog = PersonDialog(other, "Add a child of Luka Šimić", {"surname": "Šimić", "living": "yes"}, link="birth")
        dialog.given.setText("Ema")
        dialog.birth_date.setText("sometime")
        dialog.show()
        QApplication.processEvents()
        dialog.grab().save(str(out / "4_dialog.png"))
        dialog.close()
        other.close()

    print("OK: start page, tree, pan, zoom, partner's family, panel, photos, dialog")
    app.quit()


if __name__ == "__main__":
    main()
