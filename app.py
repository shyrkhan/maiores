#!/usr/bin/env python3
"""Family tree program: portrait cards joined by lines.

    maiores                   reopen the last tree, or show the start page
    maiores NAME.tree         open a tree folder
    maiores --sample          look at a made-up family
"""
import argparse
import collections
import copy
import datetime
import importlib
import os
import shutil
import sys
import tempfile
import time
import traceback
import uuid
from pathlib import Path

from PySide6.QtCore import (
    QLibraryInfo, QLocale, QLockFile, QPoint, QRect, QSettings, QStandardPaths, QStringListModel, QSysInfo, Qt,
    QSize, QTimer, QTranslator, QUrl,
)
from PySide6.QtGui import (
    QAction, QDesktopServices, QFontDatabase, QIcon, QImage, QImageReader, QKeySequence, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsScene,
    QGridLayout,
    QHBoxLayout,
    QComboBox,
    QDialog,
    QCompleter,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

import edits
import house_layout as hl
from canvas import (
    INK_PRINT,
    PICTURE_SUFFIXES,
    TreeView,
    build_scene,
    clear_layout,
    place_add_buttons,
)
from dialogs import (
    CropDialog,
    FindDialog,
    PersonDialog,
    PlacesDialog,
    PreferencesDialog,
    TimelineDialog,
    matching_people,
    person_to_values,
)
from edits import EditError, History, copy_tree
from exports import (
    ExportError,
    best_orientation,
    export_gedcom,
    export_map_pins,
    export_picture,
    prepared_scene,
    print_view,
)
from gedcom import GedcomError, read_gedcom
from model import (
    Tree,
    TreeIndex,
    all_facts,
    as_list,
    fold_text,
    date_input_text,
    date_warnings,
    fact_year,
    cited_sources,
    face_links,
    family_marriage,
    files_of,
    person_documents,
    person_tasks,
    validate,
)
from panel import PersonPanel
from photos import PhotoCache, PhotoError, import_photo, read_image, resolve_photo, store_photo
from sample import sample_tree
from storage import (
    BACKUP_DIR,
    TREE_FILE,
    DamagedTreeError,
    TreeLoadError,
    create_tree,
    has_tree,
    list_backups,
    make_backup,
    open_tree,
    read_backup,
    read_tree,
    recover_from_backup,
    save_tree,
    save_view,
)
import canvas as canvas_module
import combine
import icons
import model as model_module
import start_cards
import dna
import documents
import kinship
import poster
import privacy
import reports
import theme
import webshare
import strings
from combine_dialog import CombineDialog
from documents_dialog import DocumentsDialog
from faces_dialog import portrait_crop
from duplicates import find_duplicates
from duplicates_dialog import DuplicatesDialog
from facts_dialogs import FactContext, SourcesDialog, UnsourcedDialog
from reports_dialog import PosterDialog, ReportDialog
from research_dialogs import ResearchDialog, StoryDialog, TasksDialog
from views_dialogs import GalleryDialog, LifelinesDialog, StatisticsDialog, statistics
from webshare_dialog import LiveShareDialog, WebPageDialog
from screen import fit_to_screen
from strings import collation_key, t
from version import VERSION

RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
TREE_SUFFIX = ".tree"
LOCK_FILE = ".lock"
LAST_TREE_KEY = "last_tree"
RECENT_KEY = "recent_trees"
START_CARDS = 8  # Trees shown as cards on the start page; the rest are in File > Open.

# What each chart allows. Every place that differs by chart reads this table.
CHARTS = {
    "family": {"add": True, "folds": True, "label": "toolbar_centred_on"},
    "pyramid": {"add": True, "folds": True, "label": "toolbar_chart_of"},
    "pedigree": {"add": False, "folds": True, "label": "toolbar_ancestors_of"},
    "bowtie": {"add": False, "folds": False, "label": "toolbar_bowtie_of"},
    "fan": {"add": False, "folds": False, "label": "toolbar_fan_of"},
}
CARD_STYLE_KEY = "card_style"
GENERATIONS_KEY = "generations_up"
DETAIL_KEY = "detail_under_name"
REOPEN_KEY = "reopen_last_tree"
TOUR_KEY = "first_tour"
LANGUAGE_KEY = "language"
NAV_HISTORY_LIMIT = 100
THEME_KEY = "theme"
TOOLBAR_KEY = "toolbar_style"
MINIMAP_KEY = "show_minimap"
MOTION_KEY = "smooth_motion"
PLACEHOLDER_KEY = "card_placeholder"
LINES_KEY = "line_style"
COLOURS_KEY = "card_colours"
MARK_DECEASED_KEY = "mark_deceased"
SHADOWS_KEY = "card_shadows"
SURNAMES_KEY = "card_surnames"
LINE_FADE_KEY = "line_fade"
MAP_TILES_KEY = "map_tiles_allowed"  # "yes" / "no": may the map load pictures from OpenStreetMap?
MAP_SEARCH_KEY = "map_search_allowed"  # "yes" / "no": may place names be searched online?
RECENT_LIMIT = 8
PAGE_START, PAGE_EMPTY, PAGE_TREE = 0, 1, 2


def tree_folder_from(path):
    """Accept the tree folder, the tree.json inside it, or any file inside a .tree folder
    (with tree.json gone, File > Open can still reach the tree through its backups)."""
    path = Path(path)
    if path.name == TREE_FILE and path.parent.parent.name != BACKUP_DIR:
        return path.parent
    if path.suffix != TREE_SUFFIX:
        return next((p for p in path.parents if p.suffix == TREE_SUFFIX), path)
    return path


def default_trees_folder():
    documents = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation
    )
    return Path(documents or Path.home()) / t("folder_documents")


PROJECT_URL = "https://github.com/shyrkhan/maiores"
REPORT_URL = PROJECT_URL + "/issues/new/choose"  # The bug and idea forms.
SUPPORT_URL = "https://paypal.me/shyrkhan"


def _bring_old_settings():
    """Before the name Maiores, settings were kept as "FamilyTree": copied over once."""
    new = QSettings()
    if new.allKeys():
        return
    old = QSettings("FamilyTree", "FamilyTree")
    for key in old.allKeys():
        new.setValue(key, old.value(key))
    new.sync()


def centre_page(text, buttons):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addStretch(1)
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 1.6)
    label.setFont(font)
    layout.addWidget(label)
    layout.addSpacing(18)
    for caption, handler in buttons:
        row = QHBoxLayout()
        button = QPushButton(caption)
        button.setMinimumWidth(280)
        button.clicked.connect(lambda _checked=False, h=handler: h())
        row.addStretch(1)
        row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
    layout.addStretch(1)
    return page


def _readable_picture(path):
    """Whether this computer can really show the picture: a Mac claims every .heic, but
    gives up on some when it reads them."""
    reader = QImageReader(path)
    return reader.canRead() and not reader.read().isNull()


class MainWindow(QMainWindow):
    def __init__(self, settings=None, today=None):
        super().__init__()
        import a11y
        a11y.install(QApplication.instance())  # Screen-reader names for every window as it opens.
        self.settings = settings
        self.today = today or datetime.date.today()
        self.tree = None
        self.folder = None
        self.editable = False
        self.lock = None
        self.house = None  # The person in the centre, or the head of a descendant chart.
        self.chart = "family"  # Which chart: family, pyramid, pedigree, bowtie or fan (see CHARTS).
        self.generations_up = hl.FAMILY_GENERATIONS_UP
        stored = settings.value(CARD_STYLE_KEY) if settings is not None else None
        self.card_style = stored if isinstance(stored, str) and stored in hl.STYLES else "portrait"
        self.detail_mode = self._setting(DETAIL_KEY, "age", ("age", "years"))
        self.reopen_last = self._setting(REOPEN_KEY, "true", ("true", "false")) == "true"
        try:
            self.generations_up = max(1, min(hl.MAX_ANCESTOR_GENERATIONS,
                                             int(self._setting(GENERATIONS_KEY, self.generations_up, None))))
        except (TypeError, ValueError):
            pass
        self.panel_enabled = True
        self.selected = None
        self.visible_ids = set()
        self.blood_ids = set()
        self.nav_history = []
        self.collapsed = set()
        self.folded_up = set()  # People whose ancestors are folded away.
        self.side_folded = set()  # People whose brothers and sisters (with families) are folded away.
        self.family_line = None  # The surname whose line is highlighted, or None.
        self.line_only_from = None  # (chart, house, collapsed) to return to from "only this line".
        self.history = History()
        self.photos = PhotoCache()
        self.person_items = {}
        self.save_error = None
        self.add_button_items = []
        self.path_ids = set()  # People on a highlighted relationship path.
        self._left_out = []  # Files Combine could not bring across (see combine_with).
        self.auto_tour = False  # main() turns this on: the real program offers the tour once.
        self.tour = None
        self.trees_folder = default_trees_folder()  # Where the start page looks for trees.

        fit_to_screen(self, 1280, 860)
        self.setWindowTitle(t("window_title"))
        self.view = TreeView(
            self._clicked, self._double_clicked, self._context_menu, self.run_action, self._arrow_key
        )
        self.view.setAccessibleName(t("menu_chart").replace("&", ""))  # For screen readers.
        self.view.on_connect = self.connect_by_drag
        self.view.on_fold = self.toggle_fold
        self.view.on_fold_key = self._fold_key
        self.view.on_photo = self.photo_dropped
        self.panel = PersonPanel(self.go_to_person, self.run_action)
        self.panel.today = self.today
        self.panel.hide()
        self.panel_timer = QTimer(self)
        self.panel_timer.setSingleShot(True)
        self.panel_timer.setInterval(QApplication.doubleClickInterval())
        self.panel_timer.timeout.connect(self._show_panel_now)

        tree_page = QWidget()
        row = QHBoxLayout(tree_page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        chart_column = QVBoxLayout()
        chart_column.setContentsMargins(0, 0, 0, 0)
        chart_column.setSpacing(0)
        chart_column.addWidget(self._build_line_bar())
        chart_column.addWidget(self.view, 1)
        row.addLayout(chart_column, 1)
        row.addWidget(self.panel)

        self.pages = QStackedWidget()
        self.start_page = QWidget()
        QVBoxLayout(self.start_page)
        self.pages.addWidget(self.start_page)
        self._fill_start_page()
        self.pages.addWidget(
            centre_page(t("empty_text"), [(t("empty_add"), self.add_first_person)])
        )
        self.pages.addWidget(tree_page)
        self.setCentralWidget(self.pages)
        self._build_menus()
        unique_accelerators(self.menuBar())
        self._build_toolbar()
        self.count_label = QLabel()
        self.statusBar().addPermanentWidget(self.count_label)
        self.refresh(keep_view=False)

    # Small seams, so tests can answer without opening real dialogs.
    def alert(self, title, text):
        QMessageBox.warning(self, title, text)

    def inform(self, title, text):
        QMessageBox.information(self, title, text)

    def confirm(self, title, text):
        answer = QMessageBox.question(self, title, text)
        return answer == QMessageBox.StandardButton.Yes

    def choose(self, title, label, options):
        chosen, accepted = QInputDialog.getItem(self, title, label, options, 0, False)
        return options.index(chosen) if accepted else None

    def ask_person(self, title, initial=None, link=None, relationships=(), another=False):
        context = FactContext(self.tree, self.today, (initial or {}).get("documents", []),
                              find_person=lambda chooser_title: self.ask_existing_person(chooser_title, set()))
        dialog = PersonDialog(self, title, initial, link, relationships, another, context)
        values = dialog.values() if dialog.exec() else None
        dialog.deleteLater()
        self._pending_sources = (values or {}).get("new_sources", {})
        return values

    def show_menu(self, menu, position):
        menu.exec(position)
        menu.deleteLater()  # A menu made for one click must not live on with the window.

    def ask_duplicate(self, title, label, options):
        chosen, accepted = QInputDialog.getItem(self, title, label, options, 0, False)
        return options.index(chosen) if accepted else None

    def ask_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, t("photo_dialog"), str(Path.home()), t("photo_filter")
        )
        return path or None

    def ask_crop(self, image):
        dialog = CropDialog(self, image)
        return dialog.area.crop if dialog.exec() else None

    def ask_existing_person(self, title, exclude):
        dialog = FindDialog(self, self.tree, self.today, title, exclude)
        return dialog.chosen if dialog.exec() else None

    def ask_open_file(self, title, file_filter, start=None):
        start = start if start is not None and Path(start).exists() else Path.home()
        path, _ = QFileDialog.getOpenFileName(self, title, str(start), file_filter)
        return path or None

    def ask_save_file(self, title, suggested, file_filter=""):
        path, _ = QFileDialog.getSaveFileName(self, title, str(suggested), file_filter)
        return path or None

    def _build_menus(self):
        def add(menu, text, handler, shortcut=None, role=None):
            action = QAction(text, self)
            action.triggered.connect(lambda _checked=False: handler())
            if shortcut is not None:
                action.setShortcut(shortcut)
            if role is not None:
                action.setMenuRole(role)  # On a Mac these move to the application menu.
            menu.addAction(action)
            return action

        Role = QAction.MenuRole
        bar = self.menuBar()

        file_menu = bar.addMenu(t("menu_file"))
        add(file_menu, t("menu_new"), self.choose_new_tree, QKeySequence.StandardKey.New)
        add(file_menu, t("menu_open"), self.choose_open_tree, QKeySequence.StandardKey.Open)
        self.recent_menu = file_menu.addMenu(t("menu_recent"))
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        self.close_tree_action = add(file_menu, t("menu_close_tree"), self.close_tree, QKeySequence("Ctrl+W"))
        file_menu.addSeparator()
        add(file_menu, t("menu_import"), self.choose_import)
        self.combine_action = add(file_menu, t("menu_combine"), self.choose_combine)
        self.share_action = add(file_menu, t("menu_share_copy"), self.choose_share_copy)
        self.webpage_action = add(file_menu, t("menu_webpage"), self.choose_web_page)
        self.liveshare_action = add(file_menu, t("menu_liveshare"), self.start_live_share)
        export_menu = file_menu.addMenu(t("menu_export"))
        self.export_gedcom_action = add(export_menu, t("menu_export_gedcom"), self.choose_export_gedcom)
        self.export_picture_action = add(export_menu, t("menu_export_picture"), self.choose_export_picture,
                                         QKeySequence("Ctrl+E"))
        self.export_map_action = add(export_menu, t("menu_export_map"), self.choose_export_map)
        export_menu.addSeparator()
        self.report_action = add(export_menu, t("menu_report"), self.choose_report)
        self.poster_action = add(export_menu, t("menu_poster"), self.choose_poster)
        self.print_preview_action = add(file_menu, t("menu_print_preview"), self.print_preview,
                                        QKeySequence("Ctrl+Shift+P"))
        self.print_action = add(file_menu, t("menu_print"), self.print_tree, QKeySequence.StandardKey.Print)
        self.restore_action = add(file_menu, t("menu_restore"), self.choose_restore)
        file_menu.addSeparator()
        add(file_menu, t("menu_quit"), self.close, QKeySequence.StandardKey.Quit, Role.QuitRole)

        edit_menu = bar.addMenu(t("menu_edit"))
        self.undo_action = add(edit_menu, t("menu_undo"), self.undo, QKeySequence.StandardKey.Undo)
        self.redo_action = add(edit_menu, t("menu_redo"), self.redo, QKeySequence.StandardKey.Redo)
        # Both common Redo keys everywhere: the platform default can be only one of them.
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        self.undo_menu = edit_menu.addMenu(t("menu_undo_history"))
        self.undo_menu.aboutToShow.connect(self._fill_undo_menu)
        edit_menu.addSeparator()
        self.find_action = add(edit_menu, t("menu_find"), self.focus_search, QKeySequence.StandardKey.Find)
        edit_menu.addSeparator()
        add(edit_menu, t("menu_preferences"), self.show_preferences, QKeySequence("Ctrl+,"), Role.PreferencesRole)

        view_menu = bar.addMenu(t("menu_view"))
        chart_menu = view_menu.addMenu(t("menu_chart"))
        self.chart_actions = {}
        for number, chart in enumerate(CHARTS, start=1):
            handler = self.family_view_of_selected if chart == "family" else (lambda c=chart: self.show_chart(c))
            action = add(chart_menu, t(f"chart_{chart}"), handler, QKeySequence(f"Ctrl+{number}"))
            action.setCheckable(True)
            self.chart_actions[chart] = action
        self.lines_action = add(view_menu, t("menu_lines"), self.choose_family_line, QKeySequence("Ctrl+L"))
        style_menu = view_menu.addMenu(t("menu_card_style"))
        self.style_actions = {}
        for number, style in enumerate(hl.STYLES, start=1):
            action = add(style_menu, t(f"style_{style}"), lambda s=style: self.set_card_style(s),
                         QKeySequence(f"Ctrl+Shift+{number}"))
            action.setCheckable(True)
            action.setChecked(style == self.card_style)
            self.style_actions[style] = action
        view_menu.addSeparator()
        add(view_menu, t("menu_more_generations"), lambda: self.change_generations(1), QKeySequence("Ctrl+Up"))
        add(view_menu, t("menu_fewer_generations"), lambda: self.change_generations(-1), QKeySequence("Ctrl+Down"))
        self.expand_action = add(view_menu, t("menu_expand_all"), self.expand_all)
        view_menu.addSeparator()
        add(view_menu, t("toolbar_zoom_in"), lambda: self.view.zoom_by(1.25), QKeySequence.StandardKey.ZoomIn)
        add(view_menu, t("toolbar_zoom_out"), lambda: self.view.zoom_by(1 / 1.25), QKeySequence.StandardKey.ZoomOut)
        add(view_menu, t("menu_fit"), self.view.fit_tree, QKeySequence(Qt.Key.Key_Home))
        add(view_menu, t("menu_back"), self.go_back, QKeySequence("Alt+Left"))
        add(view_menu, t("menu_home"), self.go_home, QKeySequence("Alt+Home"))
        view_menu.addSeparator()
        self.toolbar_action = add(view_menu, t("menu_show_toolbar"), lambda: self.toolbar.setVisible(
            self.toolbar_action.isChecked() and bool(self.tree and self.tree.people)))
        self.toolbar_action.setCheckable(True)
        self.toolbar_action.setChecked(True)
        self.panel_action = add(view_menu, t("menu_show_panel"), self._toggle_panel)
        self.panel_action.setCheckable(True)
        self.panel_action.setChecked(True)
        self.family_line_action = add(view_menu, t("menu_family_line"), self.pick_family_line,
                                      QKeySequence("Ctrl+B"))
        self.minimap_action = add(view_menu, t("menu_minimap"), self._toggle_minimap)
        self.minimap_action.setCheckable(True)
        self.view.smooth = self._setting(MOTION_KEY, "yes", ("yes", "no")) == "yes"
        self.minimap_action.setChecked(self._setting(MINIMAP_KEY, "no", ("yes", "no")) == "yes")
        self.view.minimap.set_shown(self.minimap_action.isChecked())
        add(view_menu, t("menu_full_screen"), self._toggle_full_screen, QKeySequence.StandardKey.FullScreen)

        self.person_menu = bar.addMenu(t("menu_person"))
        self.person_menu.aboutToShow.connect(self._fill_person_menu)

        tools_menu = bar.addMenu(t("menu_tools"))
        self.check_dates_action = add(tools_menu, t("menu_check_dates"), self.check_dates)
        self.statistics_action = add(tools_menu, t("menu_statistics"), self.show_statistics)
        self.relation_action = add(tools_menu, t("menu_relation"), self.find_relationship, QKeySequence("Ctrl+R"))
        self.places_action = add(tools_menu, t("menu_places"), self.show_places)
        self.timeline_action = add(tools_menu, t("menu_timeline"), self.show_timeline)
        tools_menu.addSeparator()
        self.sources_action = add(tools_menu, t("menu_sources"), self.show_sources)
        self.unsourced_action = add(tools_menu, t("menu_unsourced"), self.show_unsourced)
        self.duplicates_action = add(tools_menu, t("menu_duplicates"), self.show_duplicates)
        self.research_action = add(tools_menu, t("menu_research"), self.show_research)
        self.map_action = add(tools_menu, t("menu_map"), self.show_map, QKeySequence("Ctrl+M"))
        self.lifelines_action = add(tools_menu, t("menu_lifelines"), self.show_lifelines)
        self.gallery_action = add(tools_menu, t("menu_gallery"), self.show_gallery)
        self.dna_action = add(tools_menu, t("menu_dna"), lambda: self.show_dna(self.selected or self.home_person()))

        help_menu = bar.addMenu(t("menu_help"))
        add(help_menu, t("menu_guide"), self.show_guide, QKeySequence(Qt.Key.Key_F1))
        self.tour_action = add(help_menu, t("menu_tour"), self.start_tour)
        add(help_menu, t("menu_shortcuts"), self.show_shortcuts)
        help_menu.addSeparator()
        add(help_menu, t("menu_report_problem"), lambda: QDesktopServices.openUrl(QUrl(REPORT_URL)))
        add(help_menu, t("menu_support"), lambda: QDesktopServices.openUrl(QUrl(SUPPORT_URL)))
        add(help_menu, t("menu_about"), self.show_about, role=Role.AboutRole)

        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._delete_selected)
        if sys.platform == "darwin":
            # The key labelled Delete on a Mac keyboard is really Backspace.
            QShortcut(QKeySequence(Qt.Key.Key_Backspace), self, activated=self._delete_selected)
        QShortcut(QKeySequence(Qt.Key.Key_F2), self, activated=self._edit_selected)
        self.paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self.view, activated=self.paste_photo)
        # Only while the tree has focus, so Ctrl+V still pastes text into the search box and dialogs.
        self.paste_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def _fill_person_menu(self):
        """The same actions as the side panel, for whoever is selected."""
        self.person_menu.clear()
        if not self.tree or self.selected not in self.tree.people:
            self.person_menu.addAction(t("menu_person_none")).setEnabled(False)
            return
        person_id = self.selected
        # The name as written ("Ana & Ivo" stays so): a heading, with no access letter.
        title = self.person_menu.addAction(self.tree.people[person_id].display_name.replace("&", "&&"))
        title.setEnabled(False)
        title.setProperty("no_accelerator", True)
        self.person_menu.addSeparator()
        for key, label, enabled in self.person_actions(person_id):
            action = self.person_menu.addAction(label)
            action.setEnabled(enabled)
            action.triggered.connect(lambda _checked=False, k=key: self.run_action(k, person_id))
        unique_accelerators(self.person_menu)

    def _toggle_panel(self):
        self.panel_enabled = self.panel_action.isChecked()
        self.panel.setVisible(self.panel_enabled and self.selected is not None and bool(self.tree and self.tree.people))

    def _toggle_minimap(self):
        shown = self.minimap_action.isChecked()
        if self.settings is not None:
            self.settings.setValue(MINIMAP_KEY, "yes" if shown else "no")
        self.view.minimap.set_shown(shown)

    def _toggle_full_screen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def close_tree(self):
        """Back to the start page, letting other windows or computers open the tree."""
        if self.tree is None:
            return True
        if not self._may_let_go():
            return False
        self._release_current()
        self.tree = None
        self.folder = None
        self.editable = False
        self.house = None
        self._forget_view_state()
        self.history.clear()
        self.photos.clear()
        self.panel.hide()
        self.setWindowTitle(t("window_title"))
        self.refresh(keep_view=False)
        return True

    def _may_let_go(self):
        """True when the open tree can be closed or replaced: everything is saved, or the
        person chose to lose what couldn't be. Asked before anything changes, so No keeps
        the tree open exactly as it was. Closing, opening another tree and the sample all ask."""
        if self.tree is None or self.save_error is None:
            return True
        self._save()
        if self.save_error is None:
            return True
        return self.confirm(t("close_unsaved_title"), t("close_unsaved", error=self.save_error))

    def show_statistics(self):
        if not self.tree or not self.tree.people:
            return
        tree = self.tree
        living = sum(1 for p in tree.people.values() if p.living == "yes")
        deceased = sum(1 for p in tree.people.values() if p.living == "no")
        # Counted as the Surnames tab counts them, so the two never disagree.
        common = ", ".join(f"{name} ({count})" for name, count in statistics(tree, self.today)["surnames"][:5]) or "-"
        depth = {}

        def generations(person_id, seen=()):
            if person_id in depth:
                return depth[person_id]
            family = tree.birth_family_of(person_id)
            parents = [p for p in (family.partners if family else []) if p in tree.people and p not in seen]
            depth[person_id] = 1 + max((generations(p, seen + (person_id,)) for p in parents), default=0)
            return depth[person_id]

        with tree.looking():  # One index for all, not one per person (281 s on 20,000 people).
            deepest = max(generations(p) for p in tree.people)
        summary = t("statistics_text", people=len(tree.people), living=living, deceased=deceased,
                    unknown=len(tree.people) - living - deceased, families=len(tree.families),
                    generations=deepest, surnames=common)
        self.ask_statistics(summary)

    def ask_statistics(self, summary):
        dialog = StatisticsDialog(self, self.tree, self.today, summary)
        dialog.exec()
        dialog.deleteLater()

    # Lifelines and the gallery: both lead to a person with a double-click.
    def show_lifelines(self):
        if self.tree and self.tree.people:
            chosen = self.ask_lifelines()
            if chosen in self.tree.people:
                self.go_to_person(chosen)

    def ask_lifelines(self):
        dialog = LifelinesDialog(self, self.tree, self.selected, self.today)
        dialog.exec()
        dialog.deleteLater()
        return dialog.chosen

    def _picture(self, stored):
        """A portrait or a picture document as a pixmap, the right way up; None if unusable."""
        from PySide6.QtGui import QPixmap
        path = resolve_photo(self.folder, stored) or documents.resolve_document(self.folder, stored)
        if path is None:
            return None
        try:
            return QPixmap.fromImage(read_image(path))
        except PhotoError:
            return None

    def show_gallery(self):
        if self.tree and self.tree.people:
            chosen = self.ask_gallery()
            if chosen in self.tree.people:
                self.go_to_person(chosen)

    # DNA: tests, matches and the chromosome map, one person at a time (see dna_dialog.py).
    def show_dna(self, person_id):
        if not self.tree or person_id not in self.tree.people:
            return
        changes = self.ask_dna(person_id)
        if changes and self.editable:
            self.apply_edit(lambda: edits.set_dna(self.tree, changes), focus=person_id)

    def ask_dna(self, person_id):
        from dna_dialog import DnaDialog
        with self.tree.looking():
            sides = {pid: colour.name() for pid, colour in family_sides(self.tree, person_id).items()}
        dialog = DnaDialog(self, self.tree, person_id, self.folder,
                           find_person=lambda title: self.ask_existing_person(title, {person_id}),
                           side_colours=sides, ask_file=self.ask_open_file)
        if not self.editable:  # The sample, or a tree open elsewhere: look, don't change.
            dialog.read_only = True
            dialog._show_test()
        shown = copy.deepcopy(dialog.values())  # A copy: the window edits its own lists in place.
        result = dialog.values() if dialog.exec() and self.editable else None
        result = None if result == shown else result
        dialog.deleteLater()
        return result

    def ask_gallery(self):
        dialog = GalleryDialog(self, self.tree, self._picture)
        dialog.exec()
        dialog.deleteLater()
        return dialog.chosen

    def show_guide(self):
        """One guide window, shown again each time: making a new one per F1 kept every old
        one alive (a parented dialog lives as long as the main window)."""
        from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout
        existing = getattr(self, "guide_dialog", None)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(t("menu_guide").replace("&", ""))
        fit_to_screen(dialog, 720, 640)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(t("guide_html"))
        QVBoxLayout(dialog).addWidget(browser)
        self.guide_dialog = dialog  # Tests read it; kept for the next time.
        dialog.show()

    def _tour_steps(self):
        """What the tour points at, in order: (where, text). Places are found when shown."""
        def widget_rect(widget):
            def find():
                if widget is None or not widget.isVisible():
                    return None
                return QRect(widget.mapTo(self, QPoint(0, 0)), widget.size())
            return find

        def selected_card():
            item = self.person_items.get(self.selected)
            if item is None:
                return widget_rect(self.view)()
            box = self.view.mapFromScene(item.sceneBoundingRect()).boundingRect()
            return QRect(self.view.viewport().mapTo(self, box.topLeft()), box.size())

        def a_fold():
            from canvas import FoldItem
            scene = self.view.scene()
            viewport = self.view.viewport().rect()
            boxes = [self.view.mapFromScene(i.sceneBoundingRect()).boundingRect()
                     for i in (scene.items() if scene else []) if isinstance(i, FoldItem)]
            # One that can be seen, nearest the middle: the first in the scene may be off screen.
            boxes = [box for box in boxes if viewport.contains(box)]
            if not boxes:
                return widget_rect(self.view)()
            middle = viewport.center()
            box = min(boxes, key=lambda b: (b.center() - middle).manhattanLength())
            return QRect(self.view.viewport().mapTo(self, box.topLeft()), box.size())

        return [
            (selected_card, "tour_cards"),
            (widget_rect(self.panel), "tour_panel"),
            (a_fold, "tour_folds"),
            (widget_rect(self.chart_box), "tour_charts"),
            (widget_rect(self.search_box), "tour_search"),
            (widget_rect(self.toolbar.widgetForAction(self.home_tool)), "tour_home"),
            (widget_rect(self.menuBar()), "tour_menus"),
        ]

    def start_tour(self):
        if not self.tree or not self.tree.people:
            return
        from tour import TourOverlay
        self.tour = TourOverlay(self, self._tour_steps())
        self.tour.finished.connect(self._tour_finished)

    def _tour_finished(self):
        outcome = self.tour.outcome if self.tour is not None else "finished"
        self.tour = None
        # Seen to the end, or "Don't show again": not offered at start any more. Skip only
        # closes it for now. Preferences can turn it on or off either way.
        if self.settings is not None and outcome in ("finished", "never"):
            self.settings.setValue(TOUR_KEY, "done")

    def _maybe_first_tour(self):
        """Once, the first time the real program shows a tree with people in it."""
        if (self.auto_tour and self.settings is not None and self.settings.value(TOUR_KEY) != "done"
                and self.tree and self.tree.people and getattr(self, "tour", None) is None):
            QTimer.singleShot(500, self.start_tour)
            self.auto_tour = False

    def set_toolbar_style(self, style, bar=None):
        """Icons only (names in the tooltips), icons with names, or names only."""
        bar = bar or self.toolbar
        bar.setIconSize(QSize(22, 22))
        bar.setToolButtonStyle({"icons": Qt.ToolButtonStyle.ToolButtonIconOnly,
                                "both": Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
                                "text": Qt.ToolButtonStyle.ToolButtonTextOnly}.get(style, Qt.ToolButtonStyle.ToolButtonIconOnly))

    # A family line: everyone born with one surname stays clear, the rest fades.
    def _build_line_bar(self):
        bar = QFrame()
        bar.setObjectName("line_bar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 4, 6, 4)
        self.line_label = QLabel()
        self.line_fade = QSlider(Qt.Orientation.Horizontal)
        self.line_fade.setRange(2, 60)
        self.line_fade.setFixedWidth(140)
        self.line_fade.setToolTip(t("line_fade_tip"))
        self.line_fade.valueChanged.connect(self._line_fade_changed)
        self.line_only = QCheckBox(t("line_only"))
        self.line_only.setToolTip(t("line_only_tip"))
        self.line_only.toggled.connect(self.show_only_line)
        stop = QPushButton(t("line_stop"))
        stop.clicked.connect(self.stop_family_line)
        layout.addWidget(self.line_label)
        layout.addStretch(1)
        layout.addWidget(QLabel(t("line_fade")))
        layout.addWidget(self.line_fade)
        layout.addSpacing(12)
        layout.addWidget(self.line_only)
        layout.addSpacing(12)
        layout.addWidget(stop)
        bar.hide()
        self.line_bar = bar
        return bar

    def line_members(self, surname=None):
        surname = fold_text(surname or self.family_line or "")
        if not surname or self.tree is None:
            return set()
        return {pid for pid, p in self.tree.people.items() if fold_text(p.line_surname) == surname}

    def family_lines(self):
        """The surnames people were born with, most common first: [(surname, count)]."""
        counts, spelling = collections.Counter(), {}
        for person in self.tree.people.values():
            if person.line_surname:
                key = fold_text(person.line_surname)
                counts[key] += 1
                spelling.setdefault(key, person.line_surname)
        return [(spelling[key], count) for key, count in counts.most_common()]

    def pick_family_line(self):
        if self.tree is None:  # Ctrl+B on the start page.
            return
        lines = self.family_lines()
        if not lines:
            self.inform(t("line_title"), t("line_none"))
            return
        chosen = self.choose(t("line_title"), t("line_choose"),
                             [t("line_option", surname=s, count=c) for s, c in lines])
        if chosen is not None:
            self.highlight_family_line(lines[chosen][0])

    def highlight_family_line(self, surname):
        if self.line_only.isChecked():
            self.line_only.setChecked(False)  # Back from the old line's own chart first.
        self.family_line = surname
        self.line_fade.blockSignals(True)
        self.line_fade.setValue(int(self._setting(LINE_FADE_KEY, "15", tuple(str(n) for n in range(2, 61)))))
        self.line_fade.blockSignals(False)
        self.line_label.setText(t("line_bar", surname=surname, count=len(self.line_members())))
        self.line_bar.show()
        self.refresh()

    def stop_family_line(self):
        if self.line_only.isChecked():
            self.line_only.setChecked(False)
        self.family_line = None
        self.line_bar.hide()
        if self.tree is not None:
            self.refresh()

    def _line_fade_changed(self, value):
        """Fade the others now, without rebuilding the chart."""
        if self.settings is not None:
            self.settings.setValue(LINE_FADE_KEY, str(value))
        canvas_module.DECOR.fade = value / 100
        members = canvas_module.DECOR.line_members or set()
        for person_id, item in self.person_items.items():
            if person_id not in members:
                item.setOpacity(value / 100)
        for item in self.view.scene().items():
            if isinstance(item, canvas_module.LinesItem) and item.colour is None:
                item.setOpacity(value / 100)

    def _children(self, person_id):
        return [c for f in self.tree.families_of(person_id) for c in f.child_ids if c in self.tree.people]

    def line_root(self, members):
        """Where a line's own chart starts: the member with the most of the line below them
        whose parents are not of the line."""
        def below(person_id):
            seen, waiting = set(), [person_id]
            while waiting:
                for child in self._children(waiting.pop()):
                    if child in members and child not in seen:
                        seen.add(child)
                        waiting.append(child)
            return len(seen)
        tops = [pid for pid in members if not (set(self._known_parents(pid)) & members)]
        return max(tops, key=below) if tops else None

    def show_only_line(self, only):
        """Only the line: its own descendant chart from its first known ancestor, with the
        branches that leave the line (a daughter's children, with another surname) folded."""
        if only and self.family_line and self.line_only_from is None:
            members = self.line_members()
            root = self.line_root(members)
            if root is None:
                self.line_only.setChecked(False)
                return
            self.line_only_from = (self.chart, self.house, set(self.collapsed))
            self.chart, self.house = "pyramid", root
            self.collapsed = {
                pid for pid in members
                if self._children(pid) and not set(self._children(pid)) & members
            }
            self.refresh(keep_view=False)
        elif not only and self.line_only_from is not None:
            self.chart, self.house, self.collapsed = self.line_only_from
            self.line_only_from = None
            self.refresh(keep_view=False)

    def decor(self):
        """How cards and lines look, from Preferences, with each person's tint worked out."""
        model_module.SURNAMES = self._setting(SURNAMES_KEY, "both", ("both", "birth", "current"))
        decor = canvas_module.Decor(
            placeholder=self._setting(PLACEHOLDER_KEY, "initials", ("initials", "silhouette")),
            lines=self._setting(LINES_KEY, "rounded", ("square", "rounded", "curved")),
            colours=self._setting(COLOURS_KEY, "plain", ("plain", "side", "surname")),
            mark_deceased=self._setting(MARK_DECEASED_KEY, "no", ("yes", "no")) == "yes",
            shadows=self._setting(SHADOWS_KEY, "yes", ("yes", "no")) == "yes",
        )
        if self.tree is not None and self.family_line:
            decor.line_members = frozenset(self.line_members())
            decor.fade = self.line_fade.value() / 100
        if self.tree is not None and decor.colours == "side":
            decor.tints = family_sides(self.tree, self.home_person())
        elif self.tree is not None and decor.colours == "surname":
            decor.tints = {pid: surname_colour(p) for pid, p in self.tree.people.items() if surname_colour(p)}
        return decor

    def use_theme(self, name):
        """Switch the colours now: the chart, the panel and every window opened from here on."""
        theme.apply(name, QApplication.instance())
        self.view.setBackgroundBrush(canvas_module.BACKGROUND)
        self.panel.divider.setStyleSheet(f"color: {theme.hex('divider')};")
        for action, icon_name in self.toolbar_icons.items():
            action.setIcon(icons.icon(icon_name))
        if self.tree is not None and self.tree.people:
            self.refresh()
        else:
            self.view.viewport().update()

    def show_shortcuts(self):
        self.inform(t("menu_shortcuts").replace("&", ""), t("shortcuts_text") + "\n" + t("shortcuts_folds"))

    def show_preferences(self):
        if self.settings is not None:
            self.settings.sync()  # What another window changed meanwhile is shown, and kept.
        shown = {
            "card_style": self.card_style,
            "generations_up": self.generations_up,
            "detail": self.detail_mode,
            "reopen_last": self.reopen_last,
            "language": self.language_setting(),
            "show_tour": self.settings is None or self.settings.value(TOUR_KEY) != "done",
            "theme": self._setting(THEME_KEY, "dark", theme.THEMES),
            "toolbar": self._setting(TOOLBAR_KEY, "icons", ("icons", "both", "text")),
            "placeholder": self._setting(PLACEHOLDER_KEY, "initials", ("initials", "silhouette")),
            "lines": self._setting(LINES_KEY, "rounded", ("square", "rounded", "curved")),
            "colours": self._setting(COLOURS_KEY, "plain", ("plain", "side", "surname")),
            "mark_deceased": self._setting(MARK_DECEASED_KEY, "no", ("yes", "no")) == "yes",
            "shadows": self._setting(SHADOWS_KEY, "yes", ("yes", "no")) == "yes",
            "motion": self._setting(MOTION_KEY, "yes", ("yes", "no")) == "yes",
            "surnames": self._setting(SURNAMES_KEY, "both", ("both", "birth", "current")),
            "map_tiles": self._setting(MAP_TILES_KEY, "", ("yes", "no")) == "yes",
            "map_search": self._setting(MAP_SEARCH_KEY, "", ("yes", "no")) == "yes",
        }
        values = self.ask_preferences(dict(shown))
        if values is None:
            return
        # Only what was changed here is written: the rest may have been set in another window.
        changed = {k for k in values if k not in shown or values[k] != shown[k]}
        self.generations_up = values["generations_up"]
        self.detail_mode = values["detail"]
        self.reopen_last = values["reopen_last"]
        stored_language = self.settings.value(LANGUAGE_KEY) if self.settings is not None else None
        if self.settings is not None and values.get("language") and (
                "language" in changed or str(stored_language or strings.SYSTEM) != values["language"]):
            # Also when the stored value is one this version doesn't know ("xx"): choosing
            # System then really stores "system".
            self.settings.setValue(LANGUAGE_KEY, values["language"])
            if "language" in changed:
                self.inform(t("pref_language"), t("pref_language_restart"))
        if self.settings is not None:
            for key, name, value in ((GENERATIONS_KEY, "generations_up", self.generations_up),
                                     (DETAIL_KEY, "detail", self.detail_mode), (REOPEN_KEY, "reopen_last", self.reopen_last)):
                if name in changed:
                    self.settings.setValue(key, value)
            if values.get("theme") and values["theme"] != self._setting(THEME_KEY, "dark", theme.THEMES):
                self.settings.setValue(THEME_KEY, values["theme"])
                self.use_theme(values["theme"])
            if values.get("toolbar") and "toolbar" in changed:
                self.settings.setValue(TOOLBAR_KEY, values["toolbar"])
                self.set_toolbar_style(values["toolbar"])
            for key, name in ((PLACEHOLDER_KEY, "placeholder"), (LINES_KEY, "lines"), (COLOURS_KEY, "colours"),
                              (SURNAMES_KEY, "surnames")):
                if values.get(name) and name in changed:
                    self.settings.setValue(key, values[name])
            for key, name in ((MARK_DECEASED_KEY, "mark_deceased"), (SHADOWS_KEY, "shadows"),
                              (MOTION_KEY, "motion")):
                if name in changed:
                    self.settings.setValue(key, "yes" if values[name] else "no")
            self.view.smooth = self._setting(MOTION_KEY, "yes", ("yes", "no")) == "yes"
            if "show_tour" in changed:
                if values["show_tour"]:
                    self.settings.remove(TOUR_KEY)
                else:
                    self.settings.setValue(TOUR_KEY, "done")
            for key, name in ((MAP_TILES_KEY, "map_tiles"), (MAP_SEARCH_KEY, "map_search")):
                if name in changed and (values[name] or self._setting(key, "", ("yes", "no"))):
                    self.settings.setValue(key, "yes" if values[name] else "no")
        if values["card_style"] != self.card_style:
            self.set_card_style(values["card_style"])
        elif self.tree is not None and self.tree.people:
            self.refresh(keep_view=False)

    def ask_preferences(self, values):
        dialog = PreferencesDialog(self, values)
        return dialog.values() if dialog.exec() else None

    def _build_toolbar(self):
        bar = QToolBar()
        bar.setObjectName("main_toolbar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.toolbar_icons = {}  # Action -> icon name, so a theme change can redraw them.
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)

        def add(key, handler, icon_name=None):
            action = bar.addAction(t(key))
            action.setToolTip(t(key))
            action.triggered.connect(lambda _checked=False: handler())
            if icon_name:
                action.setIcon(icons.icon(icon_name))
                self.toolbar_icons[action] = icon_name
            return action

        self.back_tool = add("toolbar_back", self.go_back, "back")
        self.home_tool = add("toolbar_home", self.go_home, "home")
        bar.addSeparator()
        self.undo_tool = add("toolbar_undo", self.undo, "undo")
        self.redo_tool = add("toolbar_redo", self.redo, "redo")
        bar.addSeparator()
        add("toolbar_zoom_out", lambda: self.view.zoom_by(1 / 1.25), "zoom_out")
        add("toolbar_zoom_in", lambda: self.view.zoom_by(1.25), "zoom_in")
        add("toolbar_fit", self.view.fit_tree, "fit")
        bar.addSeparator()
        self.family_tool = add("toolbar_family_view", self.family_view_of_selected, "centre")
        self.set_toolbar_style(self._setting(TOOLBAR_KEY, "icons", ("icons", "both", "text")), bar)
        self.chart_box = QComboBox()
        self.chart_box.setObjectName("chart_box")
        for chart in CHARTS:
            self.chart_box.addItem(t(f"chart_{chart}"), chart)
        self.chart_box.activated.connect(
            lambda index: self.show_chart(self.chart_box.itemData(index)) if self.chart_box.itemData(index) != "family"
            else self.family_view_of_selected())
        bar.addWidget(self.chart_box)
        self.lines_tool = self.lines_action  # The descendant-chart chooser lives in the View menu.
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        self.where_label = QLabel()  # Whose family is on screen, so a view change is never a mystery.
        self.where_label.setObjectName("where_label")
        font = self.where_label.font()
        font.setBold(True)
        self.where_label.setFont(font)
        bar.addWidget(self.where_label)
        gap = QWidget()
        gap.setFixedWidth(16)
        bar.addWidget(gap)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("search_box")
        self.search_box.setPlaceholderText(t("toolbar_find"))
        self.search_box.setAccessibleName(t("toolbar_find"))
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(260)
        self.search_hits = {}
        self.search_model = QStringListModel(self)
        completer = QCompleter(self.search_model, self)
        completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        completer.setMaxVisibleItems(12)
        completer.activated.connect(self._search_chosen)
        self.search_box.setCompleter(completer)
        self.search_box.textEdited.connect(self._search_typed)
        self.search_box.returnPressed.connect(self._search_enter)
        bar.addWidget(self.search_box)
        self.toolbar = bar

    def _search_typed(self, text):
        self.search_hits = {}
        if self.tree is None or not text.strip():
            self.search_model.setStringList([])
            return
        labels = []
        for person in matching_people(self.tree, text)[:50]:
            label = person.display_name
            age = person.age_label(self.today)
            if age:
                label = f"{label}, {age}"
            while label in self.search_hits:
                label += " "
            self.search_hits[label] = person.id
            labels.append(label)
        self.search_model.setStringList(labels)

    def _search_chosen(self, label):
        person_id = self.search_hits.get(label)
        if person_id is None:
            return
        self.search_box.clear()
        self.go_to_person(person_id)
        self.view.setFocus()

    def _search_enter(self):
        text = self.search_box.text()
        if text in self.search_hits:
            self._search_chosen(text)
            return
        found = matching_people(self.tree, text) if self.tree and text.strip() else []
        if found:
            self.search_box.clear()
            self.go_to_person(found[0].id)
            self.view.setFocus()

    def focus_search(self):
        if not self.tree or not self.tree.people:
            return
        self.search_box.setFocus()
        self.search_box.selectAll()

    # Recently opened trees, newest first.
    def _fill_undo_menu(self):
        """The last steps, newest first; picking one undoes it and everything after."""
        self.undo_menu.clear()
        labels = list(reversed(self.history.undo_labels))[:20] if self.editable else []
        if not labels:
            self.undo_menu.addAction(t("undo_history_none")).setEnabled(False)
            return
        for steps, label in enumerate(labels, start=1):
            action = self.undo_menu.addAction(t("undo_history_item", what=label or t("change_other")))
            action.triggered.connect(lambda _checked=False, n=steps: self.undo_steps(n))

    def undo_steps(self, count):
        for _ in range(count):
            if not self.history.can_undo():
                break
            self.tree = self.history.undo(self.tree)
        self._save()
        self.refresh()

    def _recent_trees(self):
        if self.settings is None:
            return []
        stored = self.settings.value(RECENT_KEY) or []
        if isinstance(stored, str):
            stored = [stored]
        if not isinstance(stored, (list, tuple)):
            return []  # A hand-edited settings file: start without a recent list, never fail.
        found, seen = [], set()
        for path in stored:
            if not isinstance(path, str) or not path:
                continue
            key = os.path.realpath(path)  # The same tree by a link or a trailing slash: once.
            if key not in seen:
                seen.add(key)
                found.append(path)
        return found

    def _add_recent(self, folder):
        self.settings.sync()  # Another window may have added its tree since: keep it.
        mine = os.path.realpath(folder)
        paths = [p for p in self._recent_trees() if os.path.realpath(p) != mine]
        self.settings.setValue(RECENT_KEY, [str(folder)] + paths[: RECENT_LIMIT - 1])

    def _fill_recent_menu(self):
        self.recent_menu.clear()
        shown = [p for p in self._recent_trees() if has_tree(p)]
        if not shown:
            self.recent_menu.addAction(t("menu_recent_none")).setEnabled(False)
            return
        for path in shown:
            action = self.recent_menu.addAction(Path(path).stem)
            action.setToolTip(path)
            action.triggered.connect(lambda _checked=False, p=path: self.open_path(p))

    def _arrow_key(self, key):
        """Move the selection to the nearest card in the arrow's direction."""
        directions = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._edit_selected()
            return True
        if key not in directions or self.selected not in self.person_items:
            return False
        dx, dy = directions[key]
        # By where each card is drawn, its centre: the fan chart's segments all sit at (0, 0)
        # and are drawn around it, so their positions say nothing.
        here = self.person_items[self.selected].sceneBoundingRect().center()
        best, best_score = None, None
        for person_id, item in self.person_items.items():
            if person_id == self.selected:
                continue
            offset = item.sceneBoundingRect().center() - here
            along = offset.x() * dx + offset.y() * dy
            if along <= 1:
                continue
            across = abs(offset.x() * dy) + abs(offset.y() * dx)
            # Straight ahead beats a closer card off to the side.
            score = along + across * 3
            if best_score is None or score < best_score:
                best, best_score = person_id, score
        if best is not None:
            self.select(best)
            self.view.ensureVisible(self.person_items[best], 80, 80)
        return True

    def show_about(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser
        notices = RESOURCE_ROOT / "THIRD_PARTY.txt"
        try:
            licences = notices.read_text(encoding="utf-8")
        except OSError:
            licences = ""
        dialog = QDialog(self)
        dialog.setWindowTitle(t("menu_about").replace("&", ""))
        fit_to_screen(dialog, 620, 560)
        layout = QVBoxLayout(dialog)
        layout.addWidget(start_cards.BrandHeader(t("app_tagline"), height=76))
        about = QLabel(f"<p>{t('about_text', version=VERSION)}</p><p>{t('about_free')}</p>"
                       f"<p>{t('about_project', link=f'<a href=\"{PROJECT_URL}\">{PROJECT_URL}</a>')}</p>"
                       f"<p>{t('about_support', link=f'<a href=\"{SUPPORT_URL}\">{SUPPORT_URL}</a>')}</p>")
        about.setOpenExternalLinks(True)
        about.setWordWrap(True)
        layout.addWidget(about)
        details = QTextBrowser()
        details.setPlainText(licences)
        layout.addWidget(details, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    # Opening and creating trees.
    def choose_new_tree(self):
        start = default_trees_folder()
        start.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, t("dialog_new_tree"), str(start / t("default_tree_name"))
        )
        if path:
            self.new_tree(path)

    def known_trees(self):
        """Trees to offer on the start page: recent ones first, then any in the usual folder."""
        found = [Path(p) for p in self._recent_trees()]
        folder = self.trees_folder
        if folder.is_dir():
            try:
                found += sorted(folder.glob(f"*{TREE_SUFFIX}"), key=lambda p: p.name.lower())
            except OSError:
                pass
        trees, seen = [], set()
        for path in found:
            key = str(path.resolve()) if path.exists() else str(path)
            if key not in seen and has_tree(path):
                seen.add(key)
                trees.append(path)
        return trees

    def _where_text(self):
        tree = self.tree
        if self.house not in tree.people:
            return ""
        return t(CHARTS[self.chart]["label"], name=tree.people[self.house].display_name)

    def tree_to_reopen(self):
        """The last tree, or if it has gone, the most recent one that still exists."""
        if self.settings is None:
            return None
        last = self.settings.value(LAST_TREE_KEY)
        candidates = ([str(last)] if last else []) + self._recent_trees()
        return next((c for c in candidates if has_tree(c)), None)

    def _fill_start_page(self):
        """Rebuilt each time it is shown, so the list of trees is up to date."""
        layout = self.start_page.layout()
        clear_layout(layout)
        trees = self.known_trees()[:START_CARDS]
        buttons = [
            (t("start_new"), self.choose_new_tree),
            (t("start_open"), self.choose_open_tree),
            (t("start_sample"), self.load_sample),
        ]
        page = centre_page(t("start_yours") if trees else t("start_text"), buttons)
        brand = QHBoxLayout()  # The name and its mark above everything else.
        brand.addStretch(1)
        brand.addWidget(start_cards.BrandHeader(t("app_tagline")))
        brand.addStretch(1)
        page.layout().insertLayout(1, brand)
        page.layout().insertSpacing(2, 18)
        if trees:
            grid = QGridLayout()
            grid.setSpacing(12)
            columns = 1 if len(trees) == 1 else 2
            for index, path in enumerate(trees):
                try:
                    summary = start_cards.summarise(path, TREE_FILE)
                except Exception:  # noqa: BLE001 - one odd tree must never stop the program starting.
                    summary = start_cards.TreeSummary(Path(path))
                card = start_cards.TreeCard(summary)
                card.setObjectName(f"start_tree_{index}")
                card.clicked.connect(lambda _checked=False, p=path: self.open_path(p))
                if index == 0:
                    card.setDefault(True)
                grid.addWidget(card, index // columns, index % columns)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addLayout(grid)
            row.addStretch(1)
            page.layout().insertLayout(5, row)
            page.layout().insertSpacing(6, 22)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(page)
        page.show()  # Added to a page that may already be on screen.

    def choose_open_tree(self):
        start = default_trees_folder()
        path = self.ask_open_file(t("dialog_open_tree"), t("open_filter"), start)
        if path:
            self.open_path(path)

    def new_tree(self, path):
        folder = Path(path)
        if folder.name == TREE_FILE:
            folder = folder.parent  # They picked the tree.json of an existing tree.
        if folder.suffix != TREE_SUFFIX and not has_tree(folder):
            folder = folder.with_name(folder.name + TREE_SUFFIX)
        if has_tree(folder):
            # A tree is already there (perhaps only its backups, its file gone): open it,
            # which offers to recover it, rather than start an empty one over it.
            if self.confirm(t("confirm_open_existing_title"), t("confirm_open_existing", path=folder)):
                return self.open_path(folder)
            return False
        outer = next((p for p in folder.parents if (p / TREE_FILE).is_file()), None)
        if outer is not None:
            self.alert(t("open_failed_title"), t("error_tree_inside", tree=outer))
            return False
        if not self._may_let_go():
            return False  # Asked before anything is made: No leaves no new folder behind.
        try:
            create_tree(folder, Tree())
        except FileExistsError:
            self.alert(t("open_failed_title"), t("error_tree_exists", path=folder))
            return False
        except OSError as error:
            self.alert(t("open_failed_title"), t("error_create_failed", error=error))
            return False
        return self.open_path(folder, asked=True)

    def open_path(self, path, asked=False):
        """Open a tree. On any failure the tree already open stays open. `asked`: the
        person has already agreed to let the open tree go (New tree asks first)."""
        # Absolute: "maiores A.tree" typed in one folder must not be remembered as "A.tree",
        # which the next start would look for wherever it happens to be started.
        folder = Path(os.path.abspath(tree_folder_from(path)))
        if self.folder is not None and folder.resolve() == Path(self.folder).resolve():
            return True  # Already open here (Open recent on itself): nothing to do, no "open elsewhere" alarm.
        if not asked and not self._may_let_go():
            return False
        lock = QLockFile(str(folder / LOCK_FILE))
        lock.setStaleLockTime(0)  # Only a dead process's lock counts as stale.
        if folder.is_dir() and not self._take_lock(lock, folder):
            return False
        try:
            opened = open_tree(folder)
        except (TreeLoadError, OSError) as error:
            opened = self._offer_recovery(folder, error)
            if opened is None:
                lock.unlock()
                return False

        self._release_current()
        self.lock = lock
        self.tree = opened.tree
        self.folder = folder
        self.editable = True
        self.house = opened.house
        self.chart = opened.mode
        self._forget_view_state()
        self.history.clear()
        self.photos.clear()
        self.save_error = None
        self.setWindowTitle(t("window_title_tree", name=folder.stem))
        if self.settings is not None:
            self.settings.setValue(LAST_TREE_KEY, str(folder))
            self._add_recent(folder)
        self.refresh(keep_view=False)
        message = t("status_tree")
        if opened.issues:
            message = t("status_issues", count=len(opened.issues), first=opened.issues[0].message())
        self.statusBar().showMessage(message)
        return True

    def _offer_recovery(self, folder, error):
        """A tree whose tree.json can't be read, but with readable backups: offer the newest
        (the damaged file is kept beside it). Returns the opened tree, or None after saying why."""
        # Only when tree.json itself is damaged: a disk error (say, writing the routine
        # backup) or a newer program's file must never lead to rolling back a sound tree.
        backups = list_backups(folder) if isinstance(error, DamagedTreeError) else []
        if not backups:
            self.alert(t("open_failed_title"), str(error))
            return None
        backup, when, people = backups[0]
        label = time.strftime("%d.%m.%Y. %H:%M:%S", when)
        if not self.confirm(t("open_failed_title"), t("recover_offer", error=error, when=label, people=people)):
            return None
        try:
            recover_from_backup(folder, backup)
            return open_tree(folder)
        except (TreeLoadError, OSError) as again:
            self.alert(t("open_failed_title"), str(again))
            return None

    def _take_lock(self, lock, folder):
        if lock.tryLock(0):
            return True
        if lock.error() != QLockFile.LockError.LockFailedError:
            if os.access(folder, os.W_OK) and shutil.disk_usage(folder).free < 1024 * 1024:
                # A full disk mustn't keep you out of your tree: open it, and say why
                # changes can't be saved until there is room again.
                self.alert(t("open_failed_title"), t("open_disk_full", path=folder))
                return True
            self.alert(t("open_failed_title"), t("error_not_writable", path=folder))
            return False
        host = lock.getLockInfo()[-2]
        if not host or host == QSysInfo.machineHostName():
            self.alert(t("open_failed_title"), t("error_already_open", path=folder))
            return False
        # A lock from another computer can't be checked from here. It may be left
        # over from a copy or a sync, so the person decides rather than being stuck.
        if not self.confirm(t("open_failed_title"), t("confirm_other_computer", host=host)):
            return False
        lock.removeStaleLockFile()
        return lock.tryLock(0)

    # Combining a relative's tree with this one.
    def choose_combine(self):
        if not self.editable or self.tree is None:
            return
        source = self.ask_open_file(t("combine_pick"), t("combine_filter"))
        if source:
            self.combine_with(source)

    def _read_other_tree(self, source):
        """(their tree, photo function, a name for them) or None. Their files are only read."""
        path = Path(source)
        if path.suffix.lower() == ".ged":
            result = read_gedcom(path, self.today)

            def gedcom_documents(their_id, _documents):
                stored = []
                for entry in result.documents.get(their_id, []):
                    one, failed = self._store_documents([entry], self.folder)
                    stored += one
                    if failed:  # Named in Combine's message, never dropped without a word.
                        self._left_out.append(entry[1] or entry[0].name)
                return stored

            def gedcom_photo(their_id, _stored):
                source = result.photos.get(their_id)
                copied = self._copy_photo_file(source)
                if source and not copied and their_id in result.tree.people:
                    self._left_out.append(t("combine_left_out_photo", name=result.tree.people[their_id].display_name))
                return copied

            return result.tree, gedcom_photo, gedcom_documents, None, path.stem
        folder = path.parent if path.name == TREE_FILE else path
        if self.folder is not None and folder.resolve() == Path(self.folder).resolve():
            raise TreeLoadError(t("combine_same_tree"))
        tree = read_tree(folder)
        name = folder.name[:-len(TREE_SUFFIX)] if folder.name.endswith(TREE_SUFFIX) else folder.name

        def folder_documents(_their_id, their_documents):
            copied = []
            for document in their_documents:
                stored = documents.copy_from_tree(folder, document["file"], self.folder) if self.folder else ""
                if stored:
                    copied.append({**document, "file": stored})
                else:  # Named in Combine's message, never dropped without a word.
                    self._left_out.append(document.get("title") or Path(document["file"]).name)
            return copied

        def folder_photo(their_id, stored):
            copied = self._copy_photo_file(resolve_photo(folder, stored))
            if stored and not copied and their_id in tree.people:
                self._left_out.append(t("combine_left_out_photo", name=tree.people[their_id].display_name))
            return copied

        def folder_raw(stored):
            return self._copy_raw_file(folder, stored)

        return tree, folder_photo, folder_documents, folder_raw, name

    def _copy_raw_file(self, their_folder, stored):
        """A DNA raw data file of their tree copied into this one's dna folder, or ""."""
        if not stored or self.folder is None:
            return ""
        source = (Path(their_folder) / stored).resolve()
        if not source.is_relative_to(Path(their_folder).resolve()) or not source.is_file():
            return ""
        target_dir = Path(self.folder) / dna.RAW_DIR
        target_dir.mkdir(parents=True, exist_ok=True)  # A disk error is raised, not taken for "no file".
        target = target_dir / f"{uuid.uuid4().hex[:12]}-{source.name}"
        shutil.copy2(source, target)
        return f"{dna.RAW_DIR}/{target.name}"

    def _copy_photo_file(self, path):
        if not path or self.folder is None:
            return ""
        try:  # The very same file as a portrait here already (your own share copy coming
            # back): that one, not a second copy that would then be kept as an extra photo.
            data = Path(path).read_bytes()
            for stored in dict.fromkeys(p.photo for p in self.tree.people.values() if p.photo):
                mine = resolve_photo(self.folder, stored)
                if mine is not None and mine.stat().st_size == len(data) and mine.read_bytes() == data:
                    return stored
        except OSError:
            pass
        try:
            return import_photo(path, self.folder)
        except PhotoError:
            return ""  # Not a usable picture. A disk error is raised: success must not be reported over it.

    def _store_documents(self, found, folder):
        """[(file path, title, kind, date)] from a GEDCOM file, copied into a tree folder as
        documents. Returns (the stored documents, how many could not be copied)."""
        stored, failed = [], 0
        if folder is None:
            return stored, len(found)
        for entry in found:
            path, title, kind, date = entry[:4]
            ref = entry[4] if len(entry) > 4 else ""
            try:
                stored.append({"file": documents.store_document(path, folder), "title": title or path.stem,
                               "kind": kind or ("photo" if documents.is_image(path) else "other"), "date": date,
                               **({"ref": ref} if ref else {})})
            except documents.DocumentError:
                failed += 1  # Refused (kind, size, gone). A disk error is raised to the caller.
        return stored, failed

    def ask_combine(self, theirs, suggestions, name, initial):
        dialog = CombineDialog(self, self.tree, theirs, suggestions, name, initial)
        return dialog.values() if dialog.exec() else None

    def combine_with(self, source):
        self._left_out = []  # Their files that couldn't be brought across, for the message.
        try:
            theirs, copy_photo, copy_documents, copy_raw, name = self._read_other_tree(source)
        except (TreeLoadError, GedcomError) as error:
            text = t("import_not_gedcom") if str(error) == "not_gedcom" else str(error)
            self.alert(t("open_failed_title"), text)
            return False
        if not theirs.people:
            self.alert(t("open_failed_title"), t("combine_empty"))
            return False
        suggestions = combine.suggest_matches(self.tree, theirs)
        choice = None
        while True:
            choice = self.ask_combine(theirs, suggestions, name, choice)
            if choice is None:
                return False
            try:  # A trial without photos first, so a refusal leaves no copied files behind.
                combine.combine(self.tree, theirs, choice["matches"], choice["take_theirs"])
                break
            except combine.CombineError as error:
                self.alert(t("combine_title", name=name),
                           t("combine_refused", theirs=error.theirs, mine=error.mine, reason=error))
        result = None

        def change():
            nonlocal result
            try:
                result = combine.combine(self.tree, theirs, choice["matches"], choice["take_theirs"], copy_photo,
                                         copy_documents, copy_raw)
            except OSError as error:  # Copying their files failed: nothing is combined.
                raise EditError(t("error_create_failed", error=error)) from error
            # Only gaps the combining made: an old broken link in your tree doesn't block it.
            already = set(combine.missing_records(self.tree) + self._missing_files(self.tree))
            missing = [item for item in combine.missing_records(result.tree) + self._missing_files(result.tree)
                       if item not in already]
            if missing:  # Never report success over a gap: nothing changes, and the reason is named.
                raise EditError(t("combine_incomplete", what=", ".join(missing[:5])))
            # The whole tree: sources, places, faces and marks live beside the people.
            self.tree.people, self.tree.families, self.tree.extra = \
                result.tree.people, result.tree.families, result.tree.extra

        if self.apply_edit(change) and self.save_error is None:
            message = combine.describe_result(result)
            if self._left_out:
                shown = ", ".join(self._left_out[:10]) + (" …" if len(self._left_out) > 10 else "")
                message += "\n\n" + t("combine_left_out", names=shown)
            self.inform(t("combine_title", name=name), message)
            return True
        return False

    def _missing_files(self, tree):
        """Stored paths (portraits, documents, DNA raw files) with no file in this tree's folder."""
        if self.folder is None:
            return []
        missing = []
        for person in tree.people.values():
            stored = list(files_of(person))
            for test in dna.tests_of(person):
                if test.get("raw"):
                    stored.append(test["raw"]["file"])
            for path in stored:
                target = (Path(self.folder) / path).resolve()
                if not target.is_relative_to(Path(self.folder).resolve()) or not target.is_file():
                    missing.append(path)
        return missing

    # A copy for relatives.
    # The tree as a web page: a single file to send, or shown live on this network.
    def _web_data(self, options):
        tree = privacy.shareable(self.tree, self.today, hide_living=options.get("hide_living", True))
        name = self.folder.name[:-len(TREE_SUFFIX)] if self.folder and self.folder.name.endswith(TREE_SUFFIX) else ""
        photo_path = (lambda stored: resolve_photo(self.folder, stored)) if options.get("photos", True) else None
        return webshare.site_data(tree, self.selected, photo_path, t("web_title", name=name) if name else "")

    def ask_web_page(self, with_password=True):
        name = self.folder.name[:-len(TREE_SUFFIX)] if self.folder and self.folder.name.endswith(TREE_SUFFIX) else ""
        dialog = WebPageDialog(self, name or t("window_title"), with_password)
        values = dialog.values() if dialog.exec() else None
        dialog.deleteLater()
        return values

    def choose_web_page(self):
        if not self.tree or not self.tree.people:
            return
        options = self.ask_web_page()
        if options is None:
            return
        name = self.folder.stem if self.folder else "family"
        path = self.ask_save_file(t("webpage_title"), Path.home() / f"{name}.html", t("webpage_filter"))
        if path:
            self.write_web_page(path, options)

    def write_web_page(self, path, options):
        path = Path(path)
        if path.suffix.lower() not in (".html", ".htm"):
            path = path.with_name(path.name + ".html")
        try:
            size = webshare.single_file(path, self._web_data(options), options.get("password") or None)
        except OSError as error:
            self._export_failed(t("webpage_title"), path, error)
            return False
        self.inform(t("webpage_title"), t("webpage_done", path=path, size=f"{size / 1_000_000:.1f}",
                                          locked=t("webpage_locked_yes") if options.get("password")
                                          else t("webpage_locked_no")))
        return True

    def start_live_share(self):
        if not self.tree or not self.tree.people:
            return
        options = self.ask_web_page(with_password=False)
        if options is None:
            return
        try:
            share = webshare.LiveShare(self._web_data(options))
        except OSError as error:
            self.alert(t("liveshare_title"), str(error))
            return
        self.live_share = share
        self.show_live_share(share)
        share.stop()  # Also when the window was closed some other way.
        self.live_share = None

    def show_live_share(self, share):
        dialog = LiveShareDialog(self, share)
        dialog.exec()
        dialog.deleteLater()

    def choose_share_copy(self):
        if not self.tree or not self.tree.people or self.folder is None:
            return
        hide = self._hide_living_chosen()
        if hide is None:
            return
        name = self.folder.name[:-len(TREE_SUFFIX)] if self.folder.name.endswith(TREE_SUFFIX) else self.folder.name
        target = self.ask_save_file(t("share_title"), default_trees_folder() / f"{t('share_name', name=name)}{TREE_SUFFIX}")
        if target:
            self.make_share_copy(target, hide)

    def make_share_copy(self, target, hide=True):
        """A separate tree folder with private items (and, if chosen, living people) left out.
        Only the files the shared people still refer to are copied; backups never are."""
        target = Path(target)
        if target.suffix != TREE_SUFFIX:
            target = target.with_name(target.name + TREE_SUFFIX)
        if self.folder is not None and target.resolve() == Path(self.folder).resolve():
            self.alert(t("share_title"), t("combine_same_tree"))
            return False
        if target.exists():
            self.alert(t("share_title"), t("error_tree_exists", path=target))
            return False
        # A file this tree refers to but doesn't have can't be sent: the copy leaves the
        # reference out too (so it never points at nothing), and the message says so.
        source_tree, missing = copy_tree(self.tree), 0
        for person in source_tree.people.values():
            if person.photo and resolve_photo(self.folder, person.photo) is None:
                person.photo, missing = "", missing + 1
            kept = [d for d in as_list(person.extra.get("documents"))
                    if not isinstance(d, dict) or resolve_photo(self.folder, d.get("file", "")) is not None]
            missing += len(as_list(person.extra.get("documents"))) - len(kept)
            if "documents" in person.extra:
                person.extra["documents"] = kept
        shared = privacy.shareable(source_tree, self.today, hide_living=hide)
        # Built in a hidden folder beside it and renamed into place only when complete: an
        # interrupted copy never looks like a finished tree, and trying again works.
        work = None
        try:
            # A private working folder (a name nobody else chose): only it is ever deleted.
            target.parent.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix=f".{target.stem[:60]}-share-", dir=target.parent))
            partial = work / target.name
            create_tree(partial, shared)
            copied = 0
            for person in shared.people.values():
                for stored in files_of(person):
                    source = resolve_photo(self.folder, stored)  # Safe path inside media, existing file.
                    destination = partial / stored
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    copied += 1
            if target.exists():
                raise FileExistsError(target)
            partial.rename(target)
        except FileExistsError:
            self.alert(t("share_title"), t("error_tree_exists", path=target))
            return False
        except OSError as error:
            self.alert(t("share_title"), t("error_create_failed", error=error))
            return False
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)
        text = t("share_done", path=target, files=copied,
                 hidden=sum(privacy.is_hidden(p) for p in shared.people.values()))
        if missing:
            text += "\n\n" + t("share_missing", count=missing)
        self.inform(t("share_title"), text)
        return True

    # GEDCOM and pictures.
    def choose_import(self, source=None):
        """Import a GEDCOM file; `source` when it is already known (given on the command
        line, as "maiores fam.ged")."""
        source = source or self.ask_open_file(t("import_title"), t("gedcom_filter"))
        if not source:
            return
        start = default_trees_folder()
        start.mkdir(parents=True, exist_ok=True)
        target = self.ask_save_file(
            t("import_target_title"), start / f"{Path(source).stem}{TREE_SUFFIX}"
        )
        if target:
            self.import_gedcom(source, target)

    def import_gedcom(self, source, target):
        """Read a GEDCOM file into a new tree folder. The GEDCOM is only ever read. A zipped
        bundle (a .zip with the file and its pictures, or GEDCOM 7's .gdz) is unpacked into
        a private folder first, and its pictures come along."""
        if Path(source).suffix.lower() in (".zip", ".gdz"):
            with tempfile.TemporaryDirectory(prefix="maiores-bundle-") as unpacked:
                found = unpack_gedcom_bundle(source, Path(unpacked))
                if found is None:
                    self.alert(t("import_title"), t("import_not_gedcom"))
                    return False
                return self._import_gedcom(found, target)
        return self._import_gedcom(source, target)

    def _import_gedcom(self, source, target):
        try:
            result = read_gedcom(source, self.today)
        except GedcomError as error:
            text = t("import_not_gedcom") if str(error) == "not_gedcom" else str(error)
            self.alert(t("import_title"), text)
            return False
        folder = Path(target)
        if folder.suffix != TREE_SUFFIX:
            folder = folder.with_name(folder.name + TREE_SUFFIX)
        if folder.exists():
            self.alert(t("import_title"), t("error_tree_exists", path=folder))
            return False
        if not self._may_let_go():
            return False  # Asked before anything is made: No leaves no new tree behind.
        # Made in a private working folder and moved into place only when complete: a
        # failure (a full disk) leaves nothing half-made behind, and trying again works.
        copied = failed = documents_failed = documents_copied = 0
        work = None
        try:
            folder.parent.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix=f".{folder.stem[:60]}-import-", dir=folder.parent))
            staged = work / folder.name
            create_tree(staged, result.tree)
            base = Path(source).parent.resolve()

            def keep_reference(person_id, file_path, title=""):
                # A file that couldn't be used: its line is kept, so the export still names it.
                try:
                    shown = file_path.resolve().relative_to(base).as_posix()
                except ValueError:
                    shown = file_path.name
                lines = ["1 OBJE", f"2 FILE {shown}"] + ([f"2 TITL {title}"] if title else [])
                person = result.tree.people[person_id]
                person.extra["gedcom"] = as_list(person.extra.get("gedcom")) + lines

            for person_id, photo in result.photos.items():
                try:
                    person = result.tree.people[person_id]
                    person.photo = import_photo(photo, staged)
                    if isinstance(person.extra.get("photo_title"), dict):
                        person.extra["photo_title"]["file"] = person.photo
                    copied += 1
                except PhotoError:
                    failed += 1  # Not a usable picture; a disk error stops the import.
                    keep_reference(person_id, photo)
            for person_id, found in result.documents.items():
                stored = []
                for entry in found:
                    one, not_copied = self._store_documents([entry], staged)
                    stored += one
                    if not_copied:
                        documents_failed += 1
                        keep_reference(person_id, entry[0], entry[1])
                if stored:
                    result.tree.people[person_id].extra["documents"] = stored
                    documents_copied += len(stored)
            if copied or documents_copied or failed or documents_failed:
                save_tree(staged, result.tree)
            if folder.exists():
                raise FileExistsError(folder)
            staged.rename(folder)
        except FileExistsError:
            self.alert(t("import_title"), t("error_tree_exists", path=folder))
            return False
        except OSError as error:
            self.alert(t("import_title"), t("error_create_failed", error=error))
            return False
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)

        lines = [
            t(
                "import_done",
                people=len(result.tree.people),
                families=len(result.tree.families),
            )
        ]
        if copied:
            lines.append(t("import_photos", count=copied))
        if documents_copied:
            lines.append(t("import_documents", count=documents_copied))
        if failed:
            lines.append(t("import_photos_failed", count=failed))
        if documents_failed:
            lines.append(t("import_documents_failed", count=documents_failed))
        for code, count in result.warnings:
            lines.append(t(f"import_warn.{code}", count=count))
        problems = validate(result.tree)
        if problems:
            lines.append(t("import_issues", count=len(problems)))
        opened = self.open_path(folder, asked=True)
        self.alert(t("import_done_title"), "\n\n".join(lines))
        return opened

    def _hide_living_chosen(self):
        """None means the export was cancelled."""
        options = [t("privacy_all"), t("privacy_hide")]
        index = self.choose(t("privacy_title"), t("privacy_label"), options)
        return None if index is None else index == 1

    def _export_tree(self, hide):
        """What leaves the computer: private items never, living people only if chosen."""
        return privacy.shareable(self.tree, self.today, hide_living=hide)

    def choose_export_gedcom(self):
        if not self.tree:
            return
        hide = self._hide_living_chosen()
        if hide is None:
            return
        name = self.folder.stem if self.folder else "family"
        path = self.ask_save_file(
            t("export_gedcom_title"), Path.home() / f"{name}.ged", t("gedcom_filter")
        )
        if path:
            self.export_gedcom(path, hide)

    def _export_failed(self, title, path, error):
        """Name the file the person chose (not a hidden working file), say why, and take
        away an earlier "Saved" from the status bar."""
        self.statusBar().clearMessage()
        text = str(error)
        if not text.startswith(t("export_failed", path=path)[:20]):
            reason = (getattr(error, "strerror", None) or getattr(getattr(error, "__cause__", None), "strerror", None)
                      or text).rstrip(".")
            text = t("export_failed", path=f"{path}: {reason}")
            if reason.endswith(("?", "？")) and text.endswith("."):
                text = text[:-1]  # "Is the disk full?" ends the sentence itself.
        self.alert(title, text)

    def export_gedcom(self, path, hide=False):
        path = Path(path)
        if not path.suffix:
            path = path.with_suffix(".ged")
        try:
            count = export_gedcom(self._export_tree(hide), self.folder, path)
        except ExportError as error:
            self._export_failed(t("export_gedcom_title"), path, error)
            return False
        message = (
            t("export_photos_note", path=path, count=count)
            if count
            else t("export_done", path=path)
        )
        self.statusBar().showMessage(message)
        return True

    def choose_export_picture(self):
        if not self.tree or not self.tree.people:
            return
        hide = self._hide_living_chosen()
        if hide is None:
            return
        name = self.folder.stem if self.folder else "family"
        path = self.ask_save_file(
            t("export_picture_title"), Path.home() / f"{name}.pdf", t("export_picture_filter")
        )
        if path:
            self.export_picture(path, hide)

    def export_picture(self, path, hide=False):
        path = Path(path)
        if path.suffix.lower() not in (".pdf", ".png"):
            path = path.with_name(path.name + ".pdf")
        try:
            tree = self._export_tree(hide)
            export_picture(
                tree,
                self._layout_for(tree),
                self.today,
                self._photo_for,
                path,
                self.detail_mode,
            )
        except ExportError as error:
            self._export_failed(t("export_picture_title"), path, error)
            return False
        self.statusBar().showMessage(t("export_done", path=path))
        return True

    def _printer(self):
        from PySide6.QtPrintSupport import QPrinter
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(self.windowTitle())
        scene = self.view.scene()
        if scene is not None:
            printer.setPageOrientation(best_orientation(scene.itemsBoundingRect()))
        return printer

    def _paint_pages(self, printer):
        try:
            print_view(self.tree, self._layout_for(self.tree), self.today, self._photo_for, printer,
                       self.detail_mode)
        except ExportError as error:
            self.alert(t("print_title"), str(error))

    def print_preview(self):
        """See exactly what will print; page size, orientation and printer are set there."""
        if not self.tree or not self.tree.people:
            return
        self.show_print_preview(self._printer())

    def show_print_preview(self, printer):
        from PySide6.QtPrintSupport import QPrintPreviewDialog
        dialog = QPrintPreviewDialog(printer, self)
        dialog.setWindowTitle(t("print_preview_title"))
        dialog.paintRequested.connect(self._paint_pages)
        fit_to_screen(dialog, 1100, 800)
        dialog.exec()
        dialog.deleteLater()

    def print_tree(self):
        if not self.tree or not self.tree.people:
            return
        printer = self._printer()
        if self.ask_print(printer):
            self._paint_pages(printer)

    def ask_print(self, printer):
        from PySide6.QtPrintSupport import QPrintDialog
        dialog = QPrintDialog(printer, self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()
        return accepted

    def choose_restore(self):
        if not self.editable:
            return
        backups = list_backups(self.folder)
        if not backups:
            self.alert(t("restore_title"), t("restore_none"))
            return
        labels = [time.strftime("%d.%m.%Y. %H:%M:%S", when) for _, when, _ in backups]
        options = [
            t("restore_option", when=label, people=entry[2])
            for label, entry in zip(labels, backups)
        ]
        index = self.choose(t("restore_title"), t("restore_label"), options)
        if index is None:
            return
        if self.confirm(t("restore_title"), t("restore_confirm", when=labels[index])):
            self.restore_backup(backups[index][0], labels[index])

    def restore_backup(self, backup, label):
        try:
            restored = read_backup(backup)
            make_backup(self.folder)
        except (TreeLoadError, OSError) as error:
            self.alert(t("restore_title"), str(error))
            return False

        def change():
            self.tree.people = restored.people
            self.tree.families = restored.families
            self.tree.extra = restored.extra

        if not self.apply_edit(change) or self.save_error is not None:
            # Shown on screen but not on disk is not restored: say so, keep the reason.
            self.alert(t("restore_title"), t("restore_not_saved", error=self.save_error or ""))
            return False
        self.statusBar().showMessage(t("restore_done", when=label))
        return True

    def load_sample(self):
        if not self._may_let_go():
            return False
        self._release_current()
        self.tree = sample_tree()
        self.folder = None
        self.editable = False
        self.house = None
        self.chart = "family"
        self._forget_view_state()
        self.history.clear()
        self.photos.clear()
        self.setWindowTitle(t("window_title"))
        self.refresh(keep_view=False)
        self.statusBar().showMessage(t("status_sample"))

    def _forget_view_state(self):
        """Everything about how the last tree was being looked at: another tree may reuse
        the same person ids, so a search, a highlighted path or line must not carry over."""
        self.selected = None
        # The tree it was about is let go: a failed save of it must not be asked about again
        # for the next one (the sample can never be saved).
        self.save_error = None
        if self.tour is not None:  # The tour points at cards of the tree going away.
            self.tour.finish("skipped")
        self.nav_history.clear()
        self.collapsed.clear()
        self.folded_up.clear()
        self.side_folded.clear()
        self.path_ids = set()
        self.family_line, self.line_only_from = None, None  # A new tree: no line highlighted.
        self.line_bar.hide()
        self.line_only.blockSignals(True)
        self.line_only.setChecked(False)
        self.line_only.blockSignals(False)
        self.search_box.clear()
        self.search_hits = {}
        self.search_model.setStringList([])

    def _release_current(self):
        if self.lock is not None:
            self.lock.unlock()
            self.lock = None

    def closeEvent(self, event):
        if not self._may_let_go():
            event.ignore()
            return
        if getattr(self, "live_share", None) is not None:
            self.live_share.stop()
        self._release_current()
        event.accept()

    # Showing the tree.
    def refresh(self, keep_view=True, focus=None):
        """Lookups share one index while this only reads the tree (see Tree.looking)."""
        tree = self.tree
        if tree is None:
            return self._refresh_now(keep_view=keep_view, focus=focus)
        with tree.looking():
            return self._refresh_now(keep_view=keep_view, focus=focus)

    def _refresh_now(self, keep_view=True, focus=None):
        """Rebuild everything on screen from the current data."""
        self.undo_action.setEnabled(self.editable and self.history.can_undo())
        self.redo_action.setEnabled(self.editable and self.history.can_redo())
        has_people = bool(self.tree and self.tree.people)
        self.find_action.setEnabled(has_people)
        self.check_dates_action.setEnabled(has_people)
        self.statistics_action.setEnabled(has_people)
        self.relation_action.setEnabled(bool(self.tree and len(self.tree.people) > 1))
        self.places_action.setEnabled(has_people)
        self.timeline_action.setEnabled(has_people)
        self.sources_action.setEnabled(bool(self.tree) and self.editable)
        self.unsourced_action.setEnabled(has_people)
        self.research_action.setEnabled(has_people)
        self.map_action.setEnabled(has_people)
        self.lifelines_action.setEnabled(has_people)
        self.gallery_action.setEnabled(has_people)
        self.dna_action.setEnabled(has_people)
        self.duplicates_action.setEnabled(bool(self.tree) and len(self.tree.people) > 1 and self.editable)
        self.export_map_action.setEnabled(has_people)
        self.report_action.setEnabled(has_people)
        self.poster_action.setEnabled(has_people)
        self.print_preview_action.setEnabled(has_people)
        self.print_action.setEnabled(has_people)
        self.close_tree_action.setEnabled(self.tree is not None)
        self.lines_action.setEnabled(has_people)
        self.expand_action.setEnabled(bool(self.collapsed or self.folded_up or self.side_folded))
        self.export_gedcom_action.setEnabled(has_people)
        self.export_picture_action.setEnabled(has_people)
        self.restore_action.setEnabled(self.editable)
        # Enabled only where they can do something, not to return without a word.
        self.combine_action.setEnabled(bool(self.tree) and self.editable)
        self.share_action.setEnabled(has_people and self.folder is not None)
        self.webpage_action.setEnabled(has_people)
        self.liveshare_action.setEnabled(has_people)
        self.family_line_action.setEnabled(self.tree is not None)
        self.undo_tool.setEnabled(self.undo_action.isEnabled())
        self.redo_tool.setEnabled(self.redo_action.isEnabled())
        undo_what, redo_what = self.history.next_undo(), self.history.next_redo()
        self.undo_action.setText(t("menu_undo_named", what=undo_what) if undo_what else t("menu_undo"))
        self.redo_action.setText(t("menu_redo_named", what=redo_what) if redo_what else t("menu_redo"))
        self.undo_tool.setToolTip(self.undo_action.text().replace("&", ""))
        self.redo_tool.setToolTip(self.redo_action.text().replace("&", ""))
        self.back_tool.setEnabled(bool(self.tree and self.nav_history))
        self.lines_tool.setEnabled(has_people)
        self.family_tool.setEnabled(has_people)
        self.home_tool.setEnabled(has_people)
        self.where_label.setText(self._where_text() if has_people else "")
        self.search_box.setEnabled(has_people)
        self.toolbar.setVisible(self.tree is not None and has_people and self.toolbar_action.isChecked())
        count = len(self.tree.people) if self.tree else 0
        label = t("status_count_one") if count == 1 else t("status_count", people=count)
        self.count_label.setText(label if has_people else "")

        if self.tree is None:
            self.selected = None
            # Let go of the last chart: its cards (with their portraits) aren't kept for the start page.
            self.person_items, self.visible_ids = {}, set()
            self.view.replace_scene(QGraphicsScene(), keep_view=False)
            self._place_add_buttons()  # Removes any left on the old picture.
            self._fill_start_page()
            self.pages.setCurrentIndex(PAGE_START)
            return
        if not self.tree.people:
            self.selected = None
            self.house = None
            self._place_add_buttons()  # Removes them: nobody is selected.
            self.panel.hide()
            self.pages.setCurrentIndex(PAGE_EMPTY)
            return

        if self.house not in self.tree.people:
            if self.chart != "pyramid":
                self.chart = "family"  # The chart's own person is gone: back to the family view.
            # The family view starts from the first person entered, usually the owner.
            self.house = (
                next(iter(self.tree.people)) if self.chart != "pyramid"
                else self.tree.default_house_root()
            )
            keep_view = False
        if self.selected not in self.tree.people:
            self.selected = None
        if focus is not None:
            self.selected = focus

        canvas_module.DECOR = self.decor()
        layout = self._layout_for(self.tree)
        wedge_ids = {wedge.person_id for wedge in layout.wedges}  # The fan chart has wedges, not cards.
        self.visible_ids = {card.person_id for card in layout.cards} | wedge_ids
        self.blood_ids = {card.person_id for card in layout.cards if card.blood} | wedge_ids
        scene, self.person_items = build_scene(
            self.tree, layout, self.today, self._photo_for, controls=True, detail=self.detail_mode
        )
        if self.selected not in self.visible_ids:
            # Someone is always selected, so the panel and add buttons are always there.
            self.selected = layout.root_id
            if self.selected not in self.visible_ids:
                self.selected = next(iter(self.visible_ids), None)
        self.add_button_items = []  # They belonged to the old scene.
        self.pages.setCurrentIndex(PAGE_TREE)
        self.view.replace_scene(scene, keep_view)
        self.tree_scene = scene  # Only now can the old scene safely go away.
        self._mark_selected()
        self._update_panel()
        if self.selected is not None and self.panel_enabled:
            self.panel.show()
        if not self.search_box.hasFocus():
            self.view.setFocus()  # So the arrow keys work without a click first.
        self.where_label.setText(self._where_text())
        self._sync_chart_controls()
        self._maybe_first_tour()

    def _layout_for(self, tree):
        metrics = hl.STYLES.get(self.card_style, hl.PORTRAIT)
        folded = frozenset(self.folded_up)
        if self.chart == "pedigree":
            return hl.layout_ancestors(tree, self.house, folded, metrics)
        if self.chart == "pyramid":
            return hl.layout_house(tree, self.house, self.collapsed, metrics)
        if self.chart == "bowtie":
            return hl.layout_bowtie(tree, self.house, self.generations_up + 1, metrics)
        if self.chart == "fan":
            return hl.layout_fan(tree, self.house, self.generations_up + 1, metrics)
        return hl.layout_family(tree, self.house, self.collapsed, self.generations_up, folded, metrics,
                                frozenset(self.side_folded))

    def _sync_chart_controls(self):
        """The toolbar box and the View > Chart ticks always show the chart on screen."""
        for key, action in self.chart_actions.items():
            action.setChecked(key == self.chart)
        index = self.chart_box.findData(self.chart)
        if index >= 0 and self.chart_box.currentIndex() != index:
            self.chart_box.setCurrentIndex(index)

    def show_chart(self, chart, person_id=None):
        """Switch to a chart around someone (the selected person by default)."""
        if not self.tree or not self.tree.people or chart not in CHARTS:
            return
        person_id = person_id or (self.selected if self.selected in self.tree.people else self.house)
        if chart == "pyramid":
            person_id = self.tree.top_ancestor_of(person_id)
        if chart == self.chart and person_id == self.house:
            return
        keep = self.selected if self.selected in self.tree.people else None
        self._push_nav()
        self.chart = chart
        self.house = person_id
        self.refresh(keep_view=False, focus=keep)
        self._remember_house()

    def language_setting(self):
        """The stored language choice: "system" or a language code the program has."""
        value = self.settings.value(LANGUAGE_KEY) if self.settings is not None else None
        if value is None or str(value) == strings.SYSTEM:
            return strings.SYSTEM
        return strings.canonical(value) or strings.SYSTEM

    def _setting(self, key, default, allowed):
        """A stored preference, or the default when missing or not one of the allowed values."""
        value = self.settings.value(key) if self.settings is not None else None
        if value is None:
            return default
        value = str(value).lower()
        return value if allowed is None or value in allowed else default

    def set_card_style(self, style):
        """Portrait, round, compact or names. A personal preference, kept with the user's settings."""
        if style not in hl.STYLES:
            return
        self.card_style = style
        if self.settings is not None:
            self.settings.setValue(CARD_STYLE_KEY, style)
        for key, action in self.style_actions.items():
            action.setChecked(key == style)
        if self.tree is not None and self.tree.people:
            self.refresh(keep_view=False)

    def _push_nav(self):
        self.nav_history.append((self.house, self.chart))
        del self.nav_history[:-NAV_HISTORY_LIMIT]  # Back goes far enough; older steps are let go.

    def show_ancestors(self, person_id):
        self._push_nav()
        self.chart = "pedigree"
        self.house = person_id
        self.selected = person_id
        self.refresh(keep_view=False)
        name = self.tree.people[person_id].display_name
        self.statusBar().showMessage(t("status_ancestors", name=name))

    def show_family_line(self, person_id):
        self._push_nav()
        self.chart = "pyramid"
        self.house = self._view_head_for(person_id)
        self.refresh(keep_view=False, focus=person_id)
        self._remember_house()

    def _photo_for(self, stored):
        return self.photos.get(self.folder, stored)

    def _mark_selected(self):
        # A screen reader hears who is selected: the cards themselves are drawn, not widgets.
        if self.tree is not None and self.selected in self.tree.people:
            person = self.tree.people[self.selected]
            self.view.setAccessibleDescription(f"{person.display_name} {person.years_label()}".strip())
        # Every card, not just the first: someone can rightly appear twice.
        from canvas import PersonItem
        scene = self.view.scene()
        for item in scene.items() if scene else []:
            if isinstance(item, PersonItem):
                item.highlighted = item.person_id == self.selected
                item.on_path = item.person_id in self.path_ids
                item.update()
        self._place_add_buttons()

    def add_button_entries(self, person_id):
        """The add buttons drawn around someone's card, as (key, short label)."""
        if not self.editable or not CHARTS[self.chart]["add"] or person_id not in self.tree.people:
            return []
        entries = []
        for key in ("add_father", "add_mother", "add_partner", "add_child", "add_sibling"):
            if self._add_allowed(key, person_id):
                entries.append((key, t(f"short_{key}")))
        return entries

    def _add_allowed(self, key, person_id):
        if key in ("add_father", "add_mother"):
            if not edits.can_add_parent(self.tree, person_id):
                return False
            family = self.tree.birth_family_of(person_id)
            sexes = [self.tree.people[p].sex for p in family.partners if p in self.tree.people] if family else []
            return ("M" if key == "add_father" else "F") not in sexes
        if key == "add_sibling":
            return edits.can_add_sibling(self.tree, person_id)
        return True

    def _place_add_buttons(self):
        scene = self.view.scene()
        for item in self.add_button_items:
            if item.scene() is scene:
                scene.removeItem(item)
        self.add_button_items = []
        card = self.person_items.get(self.selected)
        if card is None or card.scene() is not scene:
            return
        for item in place_add_buttons(card, self.add_button_entries(self.selected)):
            scene.addItem(item)
            self.add_button_items.append(item)

    def _update_panel(self):
        """Lookups share one index while this only reads the tree (see Tree.looking)."""
        tree = self.tree
        if tree is None:
            return self._update_panel_now()
        with tree.looking():
            return self._update_panel_now()

    def _update_panel_now(self):
        if self.selected is None or self.tree is None or self.selected not in self.tree.people:
            self.panel_timer.stop()
            self.panel.hide()
            return
        person = self.tree.people[self.selected]
        self.panel.show_person(
            self.tree,
            self.selected,
            self._photo_for(person.photo),
            [a for a in self.person_actions(self.selected) if a[0] not in ("family_line", "dna")],  # Menus only.
            self._relation_to_home(self.selected),
        )

    def _relation_to_home(self, person_id):
        """'Relationship to Marin: first cousin', for the side panel."""
        home = self.home_person()
        if home is None or home == person_id or home not in self.tree.people:
            return ""
        words, _relation = kinship.describe(self.tree, home, person_id, strings.LANGUAGE, t)
        return t("panel_relation", home=self.tree.people[home].given or self.tree.people[home].display_name,
                 words=words)

    def show_places(self):
        if self.tree and self.tree.people:
            answer = self.ask_places(all_facts(self.tree))
            chosen, operations = answer if isinstance(answer, tuple) else (answer, [])
            if operations and self.editable:
                self.apply_edit(lambda: self._replay_places(operations))
            if chosen in self.tree.people:
                self.go_to_person(chosen)

    def _replay_places(self, operations):
        for operation in operations:
            if operation[0] == "rename":
                edits.rename_place(self.tree, operation[1], operation[2])
            elif operation[0] == "set":
                edits.set_place(self.tree, operation[1], operation[2])
            else:
                edits.remove_place(self.tree, operation[1])

    def ask_places(self, rows):
        """(person to go to or None, place edits) after OK; edits are dropped on Cancel."""
        dialog = PlacesDialog(self, self.tree, rows)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()
        return dialog.chosen, dialog.operations if accepted else []

    def show_timeline(self):
        if self.tree and self.tree.people:
            chosen = self.ask_timeline(all_facts(self.tree))
            if chosen in self.tree.people:
                self.go_to_person(chosen)

    def show_sources(self):
        if not self.tree or not self.editable:
            return
        answer = self.ask_sources()
        if answer is not None:
            sources, merged, removed = answer
            self.apply_edit(lambda: edits.set_sources(self.tree, sources, merged, removed))

    def ask_sources(self):
        dialog = SourcesDialog(self, self.tree)
        shown = copy.deepcopy(dialog.values())  # A copy: the window edits its own lists in place.
        result = dialog.values() if dialog.exec() else None
        result = None if result == shown else result
        dialog.deleteLater()
        return result

    def show_duplicates(self):
        """One answer at a time; after each, the list is found again from the tree as it is."""
        if not self.tree or not self.editable:
            return
        selected = 0
        candidates = None
        while True:
            if candidates is None:  # Found again after a merge, which changes who looks alike.
                candidates = find_duplicates(self.tree)
            if not candidates:
                self.inform(t("duplicates_title"), t("duplicates_none"))
                return
            answer = self.ask_duplicates(candidates, selected)
            if answer is None:
                return
            action, keep, other, selected = answer
            if action == "merge":
                self.apply_edit(lambda: edits.merge_people(self.tree, keep, other), focus=keep)
                candidates = None
            else:
                # "Not the same" changes only that pair: the rest of the list stands, so it
                # is not searched again (two minutes on 34,000 people).
                if self.apply_edit(lambda: edits.mark_not_duplicate(self.tree, keep, other)):
                    candidates = [c for c in candidates if {c.a, c.b} != {keep, other}]
                else:
                    candidates = None

    def ask_duplicates(self, candidates, selected):
        dialog = DuplicatesDialog(self, self.tree, candidates, selected)
        dialog.exec()
        dialog.deleteLater()
        return dialog.answer

    # Research: to-do lists and life stories.
    def ask_tasks(self, person):
        dialog = TasksDialog(self, person)
        shown = copy.deepcopy(dialog.values())  # A copy: the window edits its own lists in place.
        result = dialog.values() if dialog.exec() else None
        result = None if result == shown else result  # OK with nothing changed: nothing saved.
        dialog.deleteLater()
        return result

    def _edit_tasks(self, person_id):
        tasks = self.ask_tasks(self.tree.people[person_id])
        if tasks is not None:
            self.apply_edit(lambda: edits.set_tasks(self.tree, person_id, tasks), focus=person_id)

    def ask_story(self, person):
        dialog = StoryDialog(self, person)
        shown = copy.deepcopy(dialog.values())  # A copy: the window edits its own lists in place.
        result = dialog.values() if dialog.exec() else None
        result = None if result == shown else result
        dialog.deleteLater()
        return result

    def _edit_story(self, person_id):
        answer = self.ask_story(self.tree.people[person_id])
        if answer is not None:
            story, private = answer
            self.apply_edit(lambda: edits.set_story(self.tree, person_id, story, private), focus=person_id)

    def show_research(self):
        if self.tree and self.tree.people:
            chosen = self.ask_research()
            if chosen in self.tree.people:
                self.go_to_person(chosen)

    def ask_research(self):
        dialog = ResearchDialog(self, self.tree)
        dialog.exec()
        dialog.deleteLater()
        return dialog.chosen

    # The map. Nothing goes over the network until the person has agreed, once for map
    # pictures and once for searching place names; Preferences can take either back.
    def _allowed(self, key, title, text):
        if self.settings is None:  # Screenshots and tests never use the network.
            return False
        answer = self._setting(key, "", ("yes", "no"))
        if not answer:
            answer = "yes" if self.confirm(title, text) else "no"
            self.settings.setValue(key, answer)
        return answer == "yes"

    def _map_cache(self):
        return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)) / "map"

    def _tile_source_factory(self):
        """(factory or None, why the map has no pictures)."""
        from map_view import TileSource
        if not self._allowed(MAP_TILES_KEY, t("map_consent_title"), t("map_consent_tiles")):
            return None, t("map_offline_no_consent")
        if not TileSource.available():
            return None, t("map_offline_no_ssl")
        url = str(self.settings.value("map_tile_url") or "") or None  # Switchable without an update.
        cache = self._map_cache() / "tiles"
        return (lambda ready: TileSource(cache, ready, url) if url else TileSource(cache, ready)), ""

    def _place_search(self):
        from map_dialog import PlaceSearch
        if not self._allowed(MAP_SEARCH_KEY, t("map_consent_title"), t("map_consent_search")):
            return None
        from map_view import TileSource
        if not TileSource.available():
            self.alert(t("map_window_title"), t("map_offline_no_ssl"))
            return None
        url = str(self.settings.value("map_search_url") or "") or None
        cache = self._map_cache() / "place-search.json"
        return PlaceSearch(cache, url) if url else PlaceSearch(cache)

    def show_map(self):
        if not self.tree or not self.tree.people:
            return
        answer = self.ask_map()
        if answer is None:
            return
        chosen, operations = answer
        if operations and self.editable:
            self.apply_edit(lambda: self._replay_places(operations))
        if chosen in self.tree.people:
            self.go_to_person(chosen)

    def ask_map(self):
        from map_dialog import MapDialog
        factory, reason = self._tile_source_factory()
        dialog = MapDialog(self, self.tree, self.selected, factory,
                           self._place_search if self.editable and self.settings is not None else None, reason)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()
        return dialog.chosen, dialog.operations if accepted else []

    def show_unsourced(self):
        if self.tree and self.tree.people:
            chosen = self.ask_unsourced()
            if chosen in self.tree.people:
                self.go_to_person(chosen)

    def ask_unsourced(self):
        dialog = UnsourcedDialog(self, self.tree)
        dialog.exec()
        dialog.deleteLater()
        return dialog.chosen

    def ask_timeline(self, rows):
        dialog = TimelineDialog(self, self.tree, rows, fact_year)
        dialog.exec()
        dialog.deleteLater()
        return dialog.chosen

    # Reports, books and the wall poster.
    def ask_report(self, name):
        dialog = ReportDialog(self, name, reports.odt_supported())
        values = dialog.values() if dialog.exec() else None
        dialog.deleteLater()
        return values

    def choose_report(self):
        if not self.tree or self.selected not in self.tree.people:
            return
        options = self.ask_report(self.tree.people[self.selected].display_name)
        if options is None:
            return
        hide = self._hide_living_chosen()
        if hide is None:
            return
        suffix = ".odt" if options["format"] == "odt" else ".pdf"
        # The name as the report will show it: a hidden or private person's is not suggested.
        shown = self._export_tree(hide).people.get(self.selected)
        name = f"{t('report_kind_' + options['kind'])} - {shown.display_name if shown else ''}".rstrip(" -") + suffix
        path = self.ask_save_file(t("report_title"), Path.home() / name, t(f"report_filter_{options['format']}"))
        if path:
            self.write_report(path, options, hide)

    def write_report(self, path, options, hide=True, person_id=None):
        path = Path(path)
        suffix = ".odt" if options.get("format") == "odt" else ".pdf"
        if path.suffix.lower() != suffix:
            path = path.with_name(path.name + suffix)
        tree = self._export_tree(hide)
        root = person_id or self.selected
        make = {"family": lambda: reports.family_sheet(tree, root, options["notes"], options["sources"]),
                "ancestors": lambda: reports.ancestor_book(tree, root, options["generations"], options["notes"],
                                                           options["sources"]),
                "descendants": lambda: reports.descendant_book(tree, root, options["generations"], options["notes"],
                                                               options["sources"])}[options["kind"]]
        try:
            reports.write_document(make(), path)
        except OSError as error:
            self._export_failed(t("report_title"), path, error)
            return False
        self.statusBar().showMessage(t("export_done", path=path))
        return True

    def ask_poster(self, area):
        dialog = PosterDialog(self, area)
        values = dialog.values() if dialog.exec() else None
        dialog.deleteLater()
        return values

    def _poster_scene(self, tree):
        return prepared_scene(tree, self._layout_for(tree), self.today, self._photo_for, INK_PRINT, self.detail_mode)

    def choose_poster(self):
        if not self.tree or not self.tree.people:
            return
        options = self.ask_poster(self._poster_scene(self.tree)[1])
        if options is None:
            return
        hide = self._hide_living_chosen()
        if hide is None:
            return
        name = self.folder.stem if self.folder else "family"
        path = self.ask_save_file(t("poster_title"), Path.home() / f"{name} poster.pdf", t("report_filter_pdf"))
        if path:
            self.export_poster(path, options, hide)

    def export_poster(self, path, options, hide=True):
        path = Path(path)
        if path.suffix.lower() != ".pdf":
            path = path.with_name(path.name + ".pdf")
        scene, area = self._poster_scene(self._export_tree(hide))
        try:
            pages = poster.write_poster(scene, area, path, options["paper"], options["across"],
                                        lambda row, column: t("poster_tile", row=row, column=column))
        except OSError as error:
            self._export_failed(t("poster_title"), path, error)
            return False
        self.statusBar().showMessage(t("poster_done", path=path, count=pages))
        return True

    def choose_export_map(self):
        """Pins for Google My Maps: the user imports the file there; nothing is sent from here."""
        if not self.tree or not self.tree.people:
            return
        which = self.choose(t("map_title"), t("map_which"), [t("map_births"), t("map_everything")])
        if which is None:
            return
        hide = self._hide_living_chosen()
        if hide is None:
            return
        name = self.folder.stem if self.folder else "family"
        path = self.ask_save_file(t("map_title"), Path.home() / f"{name} map.csv", t("map_filter"))
        if path:
            self.export_map(path, births_only=which == 0, hide=hide)

    def export_map(self, path, births_only=True, hide=False):
        path = Path(path)
        if path.suffix.lower() != ".csv":
            path = path.with_name(path.name + ".csv")
        tree = self._export_tree(hide)
        try:
            count = export_map_pins(tree, path, all_facts(tree), {"birth"} if births_only else None)
        except ExportError as error:
            self._export_failed(t("map_title"), path, error)
            return False
        self.inform(t("map_title"), t("map_done", count=count, path=path))
        return True

    def find_relationship(self):
        """Tools > How are they related: any two people, with the path between them lit up."""
        if not self.tree or len(self.tree.people) < 2 or self.selected not in self.tree.people:
            return
        first = self.selected
        other = self.ask_existing_person(t("relation_pick", name=self.tree.people[first].display_name), {first})
        if other is None:
            return
        words, relation = kinship.describe(self.tree, first, other, strings.LANGUAGE, t)
        self.path_ids = set(relation.path)
        missing = [p for p in relation.path if p not in self.visible_ids]
        if relation.path and missing:
            self.centre_on(first)
            self.path_ids = set(relation.path)
        self._mark_selected()
        names = {"a": self.tree.people[first].display_name, "b": self.tree.people[other].display_name}
        # "Ana is Ivo's not related..." reads wrong in English: a sentence of its own.
        self.inform(t("relation_title"), t("relation_none", **names) if relation.kind == "none"
                    else t("relation_text", **names, words=words))

    def _show_panel_now(self):
        if self.selected is None:
            return
        self._update_panel()
        if self.panel_enabled:
            self.panel.show()
        item = self.person_items.get(self.selected)
        if item is not None:
            QApplication.processEvents()
            self.view.ensureVisible(item, 40, 40)

    def select(self, person_id):
        if person_id is None:
            return  # Someone always stays selected; clicking empty space changes nothing.
        with self.tree.looking():
            self._select_now(person_id)

    def _select_now(self, person_id):
        self.path_ids = set()
        self.selected = person_id
        self._mark_selected()
        self._show_panel_now()

    def _clicked(self, person_id):
        self.select(person_id)
        self.view.setFocus()  # So the arrow keys work straight away.

    def _double_clicked(self, person_id, blood):
        self.panel_timer.stop()
        if self.chart != "pyramid":
            # Opening someone's details is what a double-click means almost everywhere.
            # Moving the view is a separate, deliberate step: "Centre the view on them".
            if self.editable:
                self.run_action("edit", person_id)
            elif person_id != self.house or self.chart != "family":
                self.centre_on(person_id)
            return
        has_parents = self.tree.birth_family_of(person_id) is not None
        if not blood and has_parents:
            self.open_house_of(person_id)
        elif self.editable:
            self.run_action("edit", person_id)
        elif not blood:
            name = self.tree.people[person_id].display_name
            self.statusBar().showMessage(t("status_no_house", name=name))

    def _context_menu(self, person_id, position):
        if person_id is None:  # From the keyboard: whoever is selected.
            person_id = self.selected
            if self.tree is None or person_id not in self.person_items:
                return
            card = self.person_items[person_id].sceneBoundingRect().center()
            position = self.view.viewport().mapToGlobal(self.view.mapFromScene(card))
        self.select(person_id)
        menu = QMenu(self)
        for key, label, enabled in self.person_actions(person_id):
            action = menu.addAction(label)
            action.setEnabled(enabled)
            action.triggered.connect(lambda _checked=False, k=key: self.run_action(k, person_id))
        self.show_menu(menu, position)

    def go_to_person(self, person_id):
        if person_id not in self.tree.people:
            return
        if person_id not in self.visible_ids:
            self._push_nav()
            if self.chart == "pyramid":
                self.house = self._view_head_for(person_id)
            else:
                self.chart, self.house = "family", person_id
            self.refresh(keep_view=False, focus=person_id)
            self._remember_house()
        if person_id not in self.visible_ids:
            self.collapsed.clear()  # They were inside a hidden branch.
            self.folded_up.clear()
            self.side_folded.clear()
            self.refresh(focus=person_id)
        self.select(person_id)
        item = self.person_items.get(person_id)
        if item is not None:
            self.view.glide_to(item.sceneBoundingRect().center())

    def _view_head_for(self, person_id):
        """The view someone belongs in. People who married in appear with their partner."""
        if self.tree.birth_family_of(person_id) is not None:
            return self.tree.top_ancestor_of(person_id)
        families = self.tree.families_of(person_id)
        if any(f.partners[0] == person_id for f in families):
            return person_id
        for family in families:
            return self.tree.top_ancestor_of(family.partners[0])
        return person_id

    def centre_on(self, person_id):
        """Make someone the middle of the family view."""
        if person_id not in self.tree.people:
            return
        if self.chart == "family" and person_id == self.house:
            return
        old_item = self.person_items.get(person_id)
        on_screen = (
            self.view.mapFromScene(old_item.sceneBoundingRect().center())
            if old_item is not None else None
        )
        self._push_nav()
        self.chart = "family"
        self.house = person_id
        self.refresh(keep_view=on_screen is not None, focus=person_id)
        new_item = self.person_items.get(person_id)
        if on_screen is not None and new_item is not None:
            # The tree rearranges around them instead of jumping somewhere else.
            moved = self.view.mapToScene(on_screen) - new_item.sceneBoundingRect().center()
            centre = self.view.mapToScene(self.view.viewport().rect().center())
            self.view.centerOn(centre - moved)
        self._remember_house()
        self.statusBar().showMessage(
            t("status_family_view", name=self.tree.people[person_id].display_name)
        )

    def home_person(self):
        """Where Home goes: the first person entered, usually the owner."""
        return next(iter(self.tree.people), None) if self.tree else None

    def go_home(self):
        home = self.home_person()
        if home is not None:
            self.centre_on(home)
            self.view.fit_tree()

    def family_view_of_selected(self):
        if self.tree and self.selected in self.tree.people:
            self.centre_on(self.selected)

    def change_generations(self, step):
        self.generations_up = max(1, min(hl.MAX_ANCESTOR_GENERATIONS, self.generations_up + step))
        self.refresh(keep_view=False)

    def open_house_of(self, person_id):
        """Double-clicking someone who married in opens the family they came from."""
        target = self.tree.top_ancestor_of(person_id)
        if target == self.house:
            return
        self._push_nav()
        self.house = target
        self.refresh(keep_view=False, focus=person_id)
        self._remember_house()

    def go_back(self):
        if self.tree is None or not self.nav_history:
            return
        self.house, self.chart = self.nav_history.pop()
        self.refresh(keep_view=False)
        self._remember_house()

    def choose_family_line(self):
        if not self.tree or not self.tree.people:
            return
        heads = self.tree.family_line_heads()
        options = [
            t("lines_option", name=self.tree.people[head].display_name, count=count)
            for head, count in heads
        ]
        index = self.choose(t("lines_title"), t("lines_label"), options)
        if index is None or (heads[index][0] == self.house and self.chart == "pyramid"):
            return
        self._push_nav()
        self.chart = "pyramid"
        self.house = heads[index][0]
        self.selected = None
        self.refresh(keep_view=False)
        self._remember_house()

    def _fold_key(self, key):
        """Shift+Up, Shift+Down, Shift+Left or Right: fold or unfold the selected person's
        ancestors, descendants, or brothers and sisters."""
        direction = {Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
                     Qt.Key.Key_Left: "side", Qt.Key.Key_Right: "side"}.get(key)
        if direction is None or self.tree is None or self.selected not in self.tree.people:
            return False
        self.toggle_fold(self.selected, direction)
        return True

    def toggle_fold(self, person_id, direction):
        """A fold button: hide or show someone's ancestors ("up") or descendants ("down")."""
        if direction == "down":
            self.toggle_collapsed(person_id)
            return
        if direction == "side":
            self.side_folded.symmetric_difference_update({person_id})
            self.refresh()
            return
        if person_id in self.folded_up:
            self.folded_up.discard(person_id)
        else:
            self.folded_up.add(person_id)
        self.refresh()

    def toggle_collapsed(self, person_id):
        if person_id in self.collapsed:
            self.collapsed.discard(person_id)
        else:
            self.collapsed.add(person_id)
        self.refresh()

    def expand_all(self):
        self.collapsed.clear()
        self.folded_up.clear()
        self.side_folded.clear()
        self.refresh()

    def all_date_warnings(self):
        """Every date warning in the tree, as (person id, text), in surname order."""
        found = []
        index = TreeIndex(self.tree)  # Built once: per person it made this take minutes.
        for person in sorted(self.tree.people.values(), key=lambda p: (collation_key(p.surname), collation_key(p.given), p.id)):
            for text in date_warnings(self.tree, person.id, self.today, index):
                found.append((person.id, text))
        return found

    def check_dates(self):
        if not self.tree or not self.tree.people:
            return
        found = self.all_date_warnings()
        if not found:
            self.statusBar().showMessage(t("check_dates_none"))
            self.inform(t("check_dates_title"), t("check_dates_none"))
            return
        index = self.choose(t("check_dates_title"), t("check_dates_label"), [text for _p, text in found])
        if index is not None:
            self.go_to_person(found[index][0])

    def find_person(self):
        if not self.tree or not self.tree.people:
            return
        dialog = FindDialog(self, self.tree, self.today)
        if dialog.exec() and dialog.chosen:
            self.go_to_person(dialog.chosen)

    def _remember_house(self):
        if self.folder is None:
            return
        try:
            save_view(self.folder, self.house, self.chart)
        except OSError as error:
            self.statusBar().showMessage(t("status_view_not_saved", error=error))

    # Actions on a person.
    def person_actions(self, person_id):
        """What can be done to someone, as (key, label, enabled)."""
        actions = []
        family_view = self.chart == "family"
        if self.chart != "pyramid":
            if person_id != self.house or not family_view:
                actions.append(("centre", t("action_centre"), True))
        elif person_id not in self.blood_ids and self.tree.birth_family_of(person_id):
            actions.append(("open_family", t("action_open_family"), True))
        has_parents = bool(self._known_parents(person_id))
        if self.chart != "pedigree" and has_parents:
            actions.append(("ancestors", t("action_ancestors"), True))
        if (
            self.chart in ("family", "pyramid")
            and person_id in self.blood_ids
            and self.tree.descendant_count(person_id)
            and (not family_view or person_id == self.house
                 or edits.is_ancestor(self.tree, self.house, person_id))
        ):
            hidden = person_id in self.collapsed
            label = t("action_expand") if hidden else t("action_collapse")
            actions.append(("collapse", label, True))
        actions.append(("dna", t("action_dna"), True))
        surname = self.tree.people[person_id].line_surname
        if surname and fold_text(surname) != fold_text(self.family_line or ""):
            actions.append(("family_line", t("action_family_line", surname=surname), True))
        if not self.editable:
            return actions
        person = self.tree.people[person_id]
        actions += [
            ("edit", t("action_edit"), True),
            ("photo", t("action_photo"), True),
        ]
        if person.photo:
            actions.append(("remove_photo", t("action_remove_photo"), True))
        count = len(person_documents(person))
        actions.append(("documents", t("action_documents_count", count=count) if count else t("action_documents"), True))
        open_tasks = sum(1 for task in person_tasks(person) if not task["done"])
        actions.append(("tasks", t("action_tasks_count", count=open_tasks) if open_tasks else t("action_tasks"), True))
        actions.append(("story", t("action_story"), True))
        actions += [
            ("add_father", t("action_add_father"), self._add_allowed("add_father", person_id)),
            ("add_mother", t("action_add_mother"), self._add_allowed("add_mother", person_id)),
            ("add_partner", t("action_add_partner"), True),
            ("add_child", t("action_add_child"), True),
            ("add_sibling", t("action_add_sibling"), edits.can_add_sibling(self.tree, person_id)),
            ("add_extra_parent", t("action_add_extra_parent"), True),
            ("connect", t("action_connect"), len(self.tree.people) > 1),
            ("merge", t("action_merge"), len(self.tree.people) > 1),
        ]
        if has_parents:
            actions.append(("remove_parents", t("action_remove_parents"), True))
        if any(len(f.partners) == 2 for f in self.tree.families_of(person_id)):
            actions.append(("remove_partner", t("action_remove_partner"), True))
        if not family_view and self._can_make_head(person_id):
            actions.append(("make_head", t("action_make_head"), True))
        actions.append(("delete", t("action_delete"), True))
        return actions

    def _known_parents(self, person_id):
        """Parents actually recorded; brothers and sisters can share a family with none."""
        family = self.tree.birth_family_of(person_id)
        return [p for p in (family.partners if family else []) if p in self.tree.people]

    def _can_make_head(self, person_id):
        if person_id in self.blood_ids or self.tree.birth_family_of(person_id):
            return False
        return any(person_id in f.partners for f in self.tree.families_of(self.house))

    def run_action(self, key, person_id):
        if key == "centre":
            self.centre_on(person_id)
            return
        if key == "open_family":
            self.open_house_of(person_id)
            return
        if key == "collapse":
            self.toggle_collapsed(person_id)
            return
        if key == "dna":
            self.show_dna(person_id)
            return
        if key == "family_line":
            self.highlight_family_line(self.tree.people[person_id].line_surname)
            return
        if key == "ancestors":
            self.show_ancestors(person_id)
            return
        if key == "family_view":
            self.show_family_line(person_id)
            return
        if key.startswith("open_document:"):
            self.open_document(person_id, int(key.split(":", 1)[1]))
            return
        if key.startswith("open_file:"):
            self.open_stored_file(key.split(":", 1)[1])
            return
        handlers = {
            "edit": self._edit_person,
            "photo": self._set_photo,
            "remove_photo": self._remove_photo,
            "documents": self._edit_documents,
            "tasks": self._edit_tasks,
            "story": self._edit_story,
            "add_parent": self._add_parent,
            "add_father": lambda pid: self._add_parent(pid, "M"),
            "add_mother": lambda pid: self._add_parent(pid, "F"),
            "add_extra_parent": lambda pid: self._add_parent(pid, "", extra=True),
            "add_partner": self._add_partner,
            "add_child": self._add_child,
            "add_sibling": self._add_sibling,
            "connect": self._connect_existing,
            "merge": self._merge_duplicate,
            "remove_parents": self._remove_from_parents,
            "remove_partner": self._remove_partnership,
            "make_head": self._make_head,
            "delete": self._delete_person,
        }
        if self.editable and person_id in self.tree.people:
            handlers[key](person_id)

    def _edit_selected(self):
        if self.selected is not None and self.editable:
            self._edit_person(self.selected)

    def _delete_selected(self):
        if self.selected is not None and self.editable:
            self._delete_person(self.selected)

    def apply_edit(self, change, focus=None):
        """Make one undoable change. Saving happens immediately."""
        snapshot = copy_tree(self.tree)
        try:
            change()
            self._store_new_sources()
        except EditError as error:
            self.tree = snapshot
            self.alert(t("window_title"), str(error))
            return False
        if self.tree == snapshot:
            self.refresh(focus=focus)
            return True
        self.history.push(snapshot, edits.describe_change(snapshot, self.tree))
        self._save()
        self.refresh(focus=focus)
        return True

    def _store_new_sources(self):
        """Sources made in the person window just answered, kept if the change cites them."""
        pending, self._pending_sources = getattr(self, "_pending_sources", {}), {}
        cited = cited_sources(self.tree)
        edits.add_sources(self.tree, {k: v for k, v in pending.items() if k in cited})

    def _save(self):
        if self.folder is None:
            return
        try:
            save_tree(self.folder, self.tree)
        except (OSError, TypeError, ValueError) as error:
            self.save_error = str(error)
            self.statusBar().showMessage(t("status_saved_failed", error=error))
        else:
            if self.save_error is not None:  # Saved again: the old failure must not stay on show.
                self.statusBar().clearMessage()
            self.save_error = None

    def undo(self):
        if self.editable and self.history.can_undo():
            self.tree = self.history.undo(self.tree)
            self._save()
            self.refresh()

    def redo(self):
        if self.editable and self.history.can_redo():
            self.tree = self.history.redo(self.tree)
            self._save()
            self.refresh()

    def _new_person(self, values):
        person = edits.make_person(values)
        self._attach_photo(person, values.get("photo_source"))
        return person

    def _attach_photo(self, person, source):
        """source: a picture file, or an image already in memory (pasted or dragged)."""
        if source is None or (isinstance(source, str) and not source):
            return
        try:
            image = source if isinstance(source, QImage) else read_image(source)
            crop = self.ask_crop(image)
            if crop is not None:
                person.photo = store_photo(image, self.folder, crop)
        except (PhotoError, OSError) as error:
            self.alert(t("window_title"), t("photo_failed", error=error))

    def _after_add(self, person):
        """Keep the new person in view, or say where they went."""
        name = person.display_name
        if person.id in self.visible_ids:
            self.select(person.id)
        else:
            # Never leave a new person off screen: take the user to them.
            self.go_to_person(person.id)
            self.statusBar().showMessage(t("status_moved_to_new", name=name))

    def add_first_person(self):
        values = self.ask_person(t("title_first"))
        if values is None:
            return
        person = self._new_person_safely(values)
        if person is None:
            return
        self.apply_edit(lambda: edits.add_first_person(self.tree, person))
        self.house = person.id
        self.refresh(keep_view=False, focus=person.id)
        self._remember_house()

    def _link_existing_instead(self, values, kind, person_id, **extra):
        """Offer to link someone already in the tree rather than add a duplicate.

        Returns True when that is settled: linked, or the question was cancelled.
        """
        candidates = edits.possible_duplicates(self.tree, values, exclude={person_id})
        if not candidates:
            return False
        name = f"{values.get('given', '')} {values.get('surname', '')}".strip()
        options = [
            t("dup_use", name=self.tree.people[c].display_name, details=self._who_is(c))
            for c in candidates
        ] + [t("dup_new")]
        index = self.ask_duplicate(t("dup_title"), t("dup_label", name=name), options)
        if index is None:
            return True
        if index >= len(candidates):
            return False
        self._link(kind, person_id, candidates[index], values.get("link", "birth"), **extra)
        return True

    def _who_is(self, person_id):
        person = self.tree.people[person_id]
        family = self.tree.birth_family_of(person_id)
        parents = [self.tree.people[p].display_name for p in family.partners] if family else []
        parts = [person.years_label()] if person.years_label() else []
        parts.append(
            t("dup_details_parents", names=" & ".join(parents)) if parents else t("dup_details_none")
        )
        return ", ".join(parts)

    def _link(self, kind, person_id, other, link="birth", relationship="married",
              family_id=None, new_family=False):
        """Connect two people already in the tree, then show the result."""
        changes = {
            "parent": lambda: edits.link_parent(self.tree, person_id, other, link),
            "partner": lambda: edits.link_partner(self.tree, person_id, other, relationship),
            "child": lambda: edits.link_child(self.tree, person_id, other, link, family_id, new_family),
            "sibling": lambda: edits.link_sibling(self.tree, person_id, other, link),
        }
        was_head = person_id == self.house
        if not self.apply_edit(changes[kind], focus=other):
            return False
        if kind == "parent" and was_head and self.chart == "pyramid":
            self.house = self.tree.top_ancestor_of(person_id)
            self.refresh(keep_view=False, focus=other)
            self._remember_house()
        self._after_add(self.tree.people[other])
        return True

    def connect_by_drag(self, source, target, position):
        """One card was dragged onto another: ask how they are related."""
        if not self.editable or source not in self.tree.people or target not in self.tree.people:
            return
        a = self.tree.people[source].display_name
        b = self.tree.people[target].display_name
        menu = QMenu(self)
        choices = [
            ("child", t("drag_is_child", a=a, b=b)),
            ("parent", t("drag_is_parent", a=a, b=b)),
            ("partner", t("drag_is_partner", a=a, b=b)),
            ("sibling", t("drag_is_sibling", a=a, b=b)),
            ("adopted_child", t("drag_is_adopted_child", a=a, b=b)),
            ("adoptive_parent", t("drag_is_adoptive_parent", a=a, b=b)),
        ]
        for kind, label in choices:
            menu.addAction(label).triggered.connect(
                lambda _checked=False, k=kind: self._link_dragged(k, source, target)
            )
        menu.addSeparator()
        menu.addAction(t("drag_same", a=a, b=b)).triggered.connect(
            lambda _checked=False: self._merge_dragged(source, target)
        )
        self.show_menu(menu, position)

    def _link_dragged(self, kind, source, target):
        if kind == "adopted_child":
            picked = self._pick_child_family(source)
            if picked is None:
                return
            self._link("child", source, target, "adopted", family_id=picked[0], new_family=picked[1])
            return
        if kind == "adoptive_parent":
            self._link("parent", source, target, "adopted")
            return
        family_id, new_family = None, False
        if kind == "child":
            picked = self._pick_child_family(source)
            if picked is None:
                return
            family_id, new_family = picked
        self._link(kind, source, target, family_id=family_id, new_family=new_family)

    def _merge_dragged(self, source, target):
        """The dragged card is the duplicate; the one it was dropped on stays."""
        name = self.tree.people[target].display_name
        other = self.tree.people[source].display_name
        if not self.confirm(t("merge_confirm_title"), t("merge_confirm", other=other, name=name)):
            return
        if self.apply_edit(lambda: edits.merge_people(self.tree, target, source), focus=target) \
                and self.save_error is None:
            self.statusBar().showMessage(t("merge_done", other=other, name=name))

    def _new_person_safely(self, values):
        try:
            return self._new_person(values)
        except EditError as error:
            self.alert(t("window_title"), str(error))
            return None

    def _edit_person(self, person_id):
        person = self.tree.people[person_id]
        family = self.tree.birth_family_of(person_id)
        link = None
        if family is not None:
            link = next(c.get("link", "unknown") for c in family.children if c["person"] == person_id)
        rows = []
        for own in self.tree.families_of(person_id):
            partner = next((p for p in own.partners if p != person_id and p in self.tree.people), None)
            if partner is not None:
                marriage = family_marriage(own)
                marriage = {**marriage, "date": date_input_text(marriage["date"])}
                rows.append((own.id, self.tree.people[partner].display_name, own.relationship, marriage))
        values = self.ask_person(
            t("title_edit", name=person.display_name), person_to_values(person), link, rows
        )
        if values is None or values.get("unchanged"):
            return

        source = values.get("photo_source")

        def change():
            edits.update_person(self.tree, person_id, values)
            for family_id, relationship in values.get("relationships", {}).items():
                edits.set_relationship(self.tree, family_id, relationship)
            for family_id, marriage in values.get("marriages", {}).items():
                edits.set_marriage(self.tree, family_id, marriage.get("date", ""), marriage.get("place", ""),
                                   marriage.get("citations"), marriage.get("people"))
            if "link" in values:
                edits.set_child_link(self.tree, person_id, values["link"])
            self._attach_photo(self.tree.people[person_id], source)

        self.apply_edit(change)

    def _set_photo(self, person_id):
        source = self.ask_photo()
        if source:
            self.apply_edit(lambda: self._attach_photo(self.tree.people[person_id], source))

    def photo_dropped(self, person_id, picture):
        """A picture file or image dragged onto someone's card becomes the portrait;
        a document file (a PDF, a letter) is attached to them."""
        if not self.editable or person_id not in self.tree.people:
            return
        self.select(person_id)
        if isinstance(picture, list):
            self.attach_documents(person_id, picture)  # Several files: every one is attached.
            return
        if isinstance(picture, str) and (Path(picture).suffix.lower() not in PICTURE_SUFFIXES
                                         or not _readable_picture(picture) and documents.is_allowed(picture)):
            # A picture this computer cannot show (an iPhone .heic, say) is still kept, as a document.
            self.attach_documents(person_id, [picture])
            return
        self.apply_edit(lambda: self._attach_photo(self.tree.people[person_id], picture), focus=person_id)

    # Documents.
    def ask_documents(self, person):
        context = FactContext(self.tree, self.today,
                              find_person=lambda chooser_title: self.ask_existing_person(chooser_title, set()))
        dialog = DocumentsDialog(self, person, self.folder, default_trees_folder().parent, face_links(self.tree),
                                 context)
        shown = copy.deepcopy(dialog.values())  # A copy: the window edits its own lists in place.
        accepted = dialog.exec()
        result = (dialog.values(), dialog.portrait_from, dialog.face_changes, dialog.portraits) if accepted else None
        if result is not None and result[0] == shown and result[1] is None and not result[2] and not result[3]:
            result = None  # OK with nothing changed: nothing saved, no undo step.
        dialog.deleteLater()
        return result

    def _edit_documents(self, person_id):
        if self.folder is None:
            return
        answer = self.ask_documents(self.tree.people[person_id])
        if answer is None:
            return
        chosen, portrait_from = answer[0], answer[1]
        face_changes, portraits = (answer[2], answer[3]) if len(answer) > 3 else ({}, [])

        def change():
            person = self.tree.people[person_id]
            person.extra.pop("documents", None)
            if chosen:
                person.extra["documents"] = chosen
            for stored, faces in face_changes.items():
                edits.set_faces(self.tree, stored, faces)
            for face_person, stored, rect in portraits:
                self._portrait_from_face(face_person, stored, rect)
            if portrait_from is not None:
                self._attach_photo(person, str(portrait_from))

        self.apply_edit(change, focus=person_id)

    def _portrait_from_face(self, person_id, stored, rect):
        """Cut a portrait around a marked face, from the upright picture."""
        path = documents.resolve_document(self.folder, stored)
        if path is None or person_id not in self.tree.people:
            return
        try:
            image = read_image(path)
            self.tree.people[person_id].photo = store_photo(image, self.folder, portrait_crop(image, rect))
        except (PhotoError, OSError) as error:
            self.alert(t("window_title"), t("photo_failed", error=error))

    def attach_documents(self, person_id, paths):
        """Files dropped on someone: copied into the tree and attached, in one undoable step."""
        if self.folder is None:
            return False
        added, refused, failed = [], [], []
        for path in paths:
            try:
                stored = documents.store_document(path, self.folder)
            except documents.DocumentError:
                refused.append(Path(path).name)
                continue
            except OSError as error:  # The file is fine; the tree's folder could not take it.
                failed.append((Path(path).name, error))
                continue
            added.append({"file": stored, "title": Path(path).stem,
                          "kind": "photo" if documents.is_image(path) else "other", "date": ""})
        if refused:
            self.alert(t("window_title"), t("documents_refused", names=", ".join(refused)))
        if failed:
            self.alert(t("window_title"), t("documents_not_copied", names=", ".join(n for n, _e in failed),
                                             error=failed[0][1].strerror or failed[0][1]))
        if not added:
            return False

        def change():
            person = self.tree.people[person_id]
            current = person_documents(person)
            person.extra["documents"] = current + [d for d in added if all(d["file"] != c["file"] for c in current)]

        ok = self.apply_edit(change, focus=person_id) and self.save_error is None
        if ok:  # Not after a failed save: the message about that stays in view.
            self.statusBar().showMessage(t("status_documents_added", count=len(added),
                                           name=self.tree.people[person_id].display_name))
        return ok

    def open_stored_file(self, stored):
        """A picture or document of this tree, opened in the system's own viewer."""
        path = documents.resolve_document(self.folder, stored)
        if path is None:
            self.alert(t("window_title"), t("documents_missing"))
            return False
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        return True

    def open_document(self, person_id, index):
        items = person_documents(self.tree.people[person_id]) if person_id in self.tree.people else []
        path = documents.resolve_document(self.folder, items[index]["file"]) if 0 <= index < len(items) else None
        if path is None:
            self.alert(t("window_title"), t("documents_missing"))
            return False
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        return True

    def paste_photo(self):
        """Ctrl+V: a copied picture, or a copied picture file, becomes the selected person's photo."""
        if not self.editable or self.selected not in (self.tree.people if self.tree else {}):
            return
        picture = TreeView.dropped_picture(QApplication.clipboard().mimeData())
        if picture is None:
            self.statusBar().showMessage(t("status_no_picture_to_paste"))
            return
        self.photo_dropped(self.selected, picture)

    def _remove_photo(self, person_id):
        def change():
            self.tree.people[person_id].photo = ""

        self.apply_edit(change)

    def _add_parent(self, person_id, sex="", extra=False):
        child = self.tree.people[person_id]
        initial = {"living": "yes", "sex": sex}
        if sex != "F" and not extra:
            # A mother's surname is often different; a guess there is usually wrong.
            initial["surname"] = child.birth_surname or child.surname
        title = {"M": "title_add_father", "F": "title_add_mother"}.get(sex, "title_add_parent")
        if extra:
            title = "title_add_extra_parent"
        values = self.ask_person(t(title, name=child.display_name), initial,
                                 link="adopted" if extra else "birth")
        if values is None:
            return
        if self._link_existing_instead(values, "parent", person_id):
            return
        parent = self._new_person_safely(values)
        if parent is None:
            return
        was_head = person_id == self.house
        if not self.apply_edit(
            lambda: edits.add_parent(self.tree, person_id, parent, values.get("link", "birth")),
            focus=parent.id,
        ):
            return
        if was_head and self.chart == "pyramid":
            self.house = self.tree.top_ancestor_of(person_id)
            self.refresh(keep_view=False, focus=parent.id)
            self._remember_house()
        self._after_add(parent)

    def _add_partner(self, person_id):
        person = self.tree.people[person_id]
        open_families = edits.open_single_parent_families(self.tree, person_id)
        family_id, new_family = None, False
        if len(open_families) > 1:
            def children_of(family):
                return ", ".join(
                    self.tree.people[c].display_name
                    for c in family.child_ids
                    if c in self.tree.people
                )

            options = [children_of(f) for f in open_families] + [t("choose_no_children")]
            index = self.choose(t("choose_partner_title"), t("choose_partner_label"), options)
            if index is None:
                return
            if index == len(open_families):
                new_family = True
            else:
                family_id = open_families[index].id
        values = self.ask_person(
            t("title_add_partner", name=person.display_name),
            {"living": "yes"},
            relationships=[(None, "", "married")],
        )
        if values is None:
            return
        if self._link_existing_instead(
            values, "partner", person_id,
            relationship=values.get("relationships", {}).get(None, "married"),
        ):
            return
        partner = self._new_person_safely(values)
        if partner is None:
            return
        relationship = values.get("relationships", {}).get(None, "married")
        if self.apply_edit(
            lambda: edits.add_partner(
                self.tree, person_id, partner, relationship, family_id, new_family
            ),
            focus=partner.id,
        ):
            self._after_add(partner)

    def _pick_child_family(self, person_id):
        """Which of someone's families a child belongs to.

        Returns (family id, make a new family), or None if the choice was cancelled.
        """
        families = self.tree.families_of(person_id)
        if len(families) <= 1:
            return None, False

        def other_parent(family):
            others = [p for p in family.partners if p != person_id and p in self.tree.people]
            return self.tree.people[others[0]].display_name if others else t("choose_unknown_parent")

        options = [other_parent(f) for f in families]
        if not any(len(f.partners) == 1 for f in families):
            options.append(t("choose_unknown_parent"))
        index = self.choose(t("choose_child_title"), t("choose_child_label"), options)
        if index is None:
            return None
        if index == len(families):
            return None, True
        return families[index].id, False

    def _connect_existing(self, person_id):
        """Link two people already in the tree, as for a cousin marriage."""
        name = self.tree.people[person_id].display_name
        kinds = [t("connect_partner"), t("connect_child"), t("connect_parent")]
        kind = self.choose(t("connect_title", name=name), t("connect_label", name=name), kinds)
        if kind is None:
            return
        other = self.ask_existing_person(t("connect_find"), {person_id})
        if other is None:
            return
        if kind == 0:
            change = lambda: edits.link_partner(self.tree, person_id, other)
        elif kind == 1:
            picked = self._pick_child_family(person_id)
            if picked is None:
                return
            family_id, new_family = picked
            change = lambda: edits.link_child(
                self.tree, person_id, other, "birth", family_id, new_family
            )
        else:
            change = lambda: edits.link_parent(self.tree, person_id, other)
        was_head = person_id == self.house
        if self.apply_edit(change, focus=other) and kind == 2 and was_head and self.chart == "pyramid":
            self.house = self.tree.top_ancestor_of(person_id)
            self.refresh(keep_view=False, focus=other)
            self._remember_house()
        if other not in self.visible_ids:
            person = self.tree.people[other]
            self.statusBar().showMessage(t("status_added_elsewhere", name=person.display_name))

    def _merge_duplicate(self, person_id):
        name = self.tree.people[person_id].display_name
        other = self.ask_existing_person(t("merge_find", name=name), {person_id})
        if other is None:
            return
        other_name = self.tree.people[other].display_name
        text = t("merge_confirm", other=other_name, name=name)
        if not self.confirm(t("merge_confirm_title"), text):
            return
        if self.apply_edit(lambda: edits.merge_people(self.tree, person_id, other), focus=person_id) \
                and self.save_error is None:
            self.statusBar().showMessage(t("merge_done", other=other_name, name=name))

    def _add_child(self, person_id):
        person = self.tree.people[person_id]
        self.collapsed.discard(person_id)
        picked = self._pick_child_family(person_id)
        if picked is None:
            return
        family_id, new_family = picked
        initial = {"surname": person.surname, "living": "yes"}
        values = self.ask_person(
            t("title_add_child", name=person.display_name), initial, link="birth", another=True
        )
        if values is None:
            return
        if self._link_existing_instead(
            values, "child", person_id, family_id=family_id, new_family=new_family
        ):
            return
        child = self._new_person_safely(values)
        if child is None:
            return
        if self.apply_edit(
            lambda: edits.add_child(
                self.tree, person_id, child, values.get("link", "birth"), family_id, new_family
            ),
            focus=child.id,
        ):
            self._after_add(child)
            if values.get("add_another"):
                self._add_child(person_id)

    def _add_sibling(self, person_id):
        person = self.tree.people[person_id]
        initial = {"surname": person.birth_surname or person.surname, "living": "yes"}
        values = self.ask_person(
            t("title_add_sibling", name=person.display_name), initial, link="birth", another=True
        )
        if values is None:
            return
        if self._link_existing_instead(values, "sibling", person_id):
            return
        sibling = self._new_person_safely(values)
        if sibling is None:
            return
        if self.apply_edit(
            lambda: edits.add_sibling(self.tree, person_id, sibling, values.get("link", "birth")),
            focus=sibling.id,
        ):
            self._after_add(sibling)
            if values.get("add_another"):
                self._add_sibling(person_id)

    def _remove_from_parents(self, person_id):
        families = [f for f, _kind in self.tree.parent_families(person_id)]
        if not families:
            return
        family = families[0]
        if len(families) > 1:
            options = [" & ".join(self.tree.people[p].display_name for p in f.partners) for f in families]
            index = self.choose(t("confirm_remove_parents_title"), t("choose_parents_to_remove"), options)
            if index is None:
                return
            family = families[index]
        child = self.tree.people[person_id].display_name
        parents = " & ".join(self.tree.people[p].display_name for p in family.partners)
        if not self.confirm(t("confirm_remove_parents_title"),
                            t("confirm_remove_parents", child=child, parents=parents)):
            return
        self.apply_edit(lambda: edits.unlink_from_parents(self.tree, person_id, family.id), focus=person_id)

    def _remove_partnership(self, person_id):
        partners = [p for f in self.tree.families_of(person_id) for p in f.partners
                    if p != person_id and p in self.tree.people]
        if not partners:
            return
        if len(partners) > 1:
            index = self.choose(t("confirm_remove_partner_title"), t("choose_partner_to_remove"),
                                [self.tree.people[p].display_name for p in partners])
            if index is None:
                return
            partner = partners[index]
        else:
            partner = partners[0]
        a, b = self.tree.people[person_id].display_name, self.tree.people[partner].display_name
        if not self.confirm(t("confirm_remove_partner_title"), t("confirm_remove_partner", a=a, b=b)):
            return
        self.apply_edit(lambda: edits.unlink_partner(self.tree, person_id, partner), focus=person_id)

    def _make_head(self, person_id):
        old_head = self.house

        def change():
            edits.make_head(self.tree, person_id, old_head)
            self.house = person_id

        self.apply_edit(change, focus=person_id)
        self._remember_house()
        self.view.fit_tree()

    def _delete_person(self, person_id):
        name = self.tree.people[person_id].display_name
        was_visible = set(self.visible_ids)
        trial = copy_tree(self.tree)
        edits.delete_person(trial, person_id)
        cut_off = 0
        if self.house != person_id:
            remaining = {c.person_id for c in self._layout_for(trial).cards}
            cut_off = len(was_visible - remaining - {person_id})
        text = (
            t("confirm_delete_cut", name=name, count=cut_off)
            if cut_off
            else t("confirm_delete", name=name)
        )
        if not self.confirm(t("confirm_delete_title"), text):
            return
        self.selected = None
        self.panel.hide()
        self.apply_edit(lambda: edits.delete_person(self.tree, person_id))


def family_sides(tree, home):
    """{person id: tint} for the home person's father's side and mother's side: each
    parent's ancestors and everyone descended from them. Someone on both sides (the home
    person's own brothers and sisters, or after cousins married) stays plain."""
    if home not in tree.people:
        return {}
    family = next((f for f, link in tree.parent_families(home) if link == "birth"), None)
    parents = [p for p in (family.partners if family else []) if p in tree.people]
    father = next((p for p in parents if tree.people[p].sex == "M"), parents[0] if parents else None)
    mother = next((p for p in parents if p != father), None)

    def ancestors(start):
        found, waiting = set(), [start]
        while waiting:
            person = waiting.pop()
            if person in found:
                continue
            found.add(person)
            for f, link in tree.parent_families(person):
                waiting += [p for p in f.partners if p in tree.people]
        return found

    def descendants(people):
        found, waiting = set(), list(people)
        while waiting:
            person = waiting.pop()
            if person in found:
                continue
            found.add(person)
            for f in tree.families_of(person):
                waiting += [c for c in f.child_ids if c in tree.people]
        return found

    sides = {}
    for parent, key in ((father, "father_side"), (mother, "mother_side")):
        if parent is not None:
            for person in descendants(ancestors(parent)):
                sides.setdefault(person, set()).add(key)
    own = descendants([home])
    return {person: theme.colour(next(iter(keys))) for person, keys in sides.items()
            if len(keys) == 1 and person not in own}


def surname_colour(person):
    """A calm colour of its own for each surname (the birth surname when known)."""
    name = fold_text(person.birth_surname or person.surname)
    if not name:
        return None
    return theme.soft_colour(sum(ord(c) * (i + 7) for i, c in enumerate(name)))


def unpack_gedcom_bundle(bundle, into, limit=4 << 30):
    """The GEDCOM file in a .zip or .gdz, unpacked with its pictures into `into`; None if
    there is none. Nothing is written outside `into` ("../" names and links are skipped),
    and an archive that would unpack to more than `limit` bytes is refused."""
    import zipfile
    root = into.resolve()
    try:
        with zipfile.ZipFile(bundle) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if sum(m.file_size for m in members) > limit:
                return None
            for member in members:
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    continue  # A link inside the archive: never followed.
                target = (root / member.filename).resolve()
                if not target.is_relative_to(root):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, open(target, "wb") as copy:
                    shutil.copyfileobj(source, copy)
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    candidates = sorted(root.rglob("*.ged"), key=lambda p: (p.name.lower() != "gedcom.ged", len(p.parts)))
    return candidates[0] if candidates else None


def unique_accelerators(menu):
    """Every menu title and item gets a letter (Alt+letter) of its own within its menu:
    the translator's choice where it is free, else the first free letter of the text.
    Two items with one letter only highlight each other; an item with none can't be
    reached by letter at all."""
    def give(actions):
        used = set()
        for action in actions:
            text = action.text()
            if action.isSeparator() or not text or "&&" in text or action.property("no_accelerator"):
                continue
            marked = text.find("&")
            plain = text.replace("&", "")
            choices = ([marked] if 0 <= marked < len(plain) else []) + list(range(len(plain)))
            choice = next((i for i in choices if plain[i].isalnum() and plain[i].lower() not in used), None)
            if choice is None:
                action.setText(plain)
            else:
                used.add(plain[choice].lower())
                action.setText(plain[:choice] + "&" + plain[choice:])
            if action.menu() is not None:
                give(action.menu().actions())

    give(menu.actions())


def apply_theme(app, name="dark"):
    """One look on every computer: the chosen theme, not the system's widget style."""
    app.setStyle(theme.OutlinedStyle("Fusion"))  # Fusion, with check boxes that can be seen.
    QFontDatabase.addApplicationFont(str(RESOURCE_ROOT / "fonts" / "NotoSerif-Regular.ttf"))
    app.setWindowIcon(QIcon(str(RESOURCE_ROOT / "assets" / "icon.png")))
    theme.apply(name, app)


def install_qt_translation(app):
    """Qt's own texts (the Cancel and Yes buttons, the file dialogs) in the chosen language,
    and right-to-left layout for Arabic. The tree charts themselves are never mirrored."""
    if strings.LANGUAGE != "en":
        translator = QTranslator(app)
        folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if translator.load(f"qtbase_{strings.LANGUAGE}", folder):
            app.installTranslator(translator)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if strings.right_to_left() else Qt.LayoutDirection.LeftToRight)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="maiores")
    parser.add_argument("folder", nargs="?", help="a tree folder to open")
    parser.add_argument("--sample", action="store_true", help="show a made-up family")
    parser.add_argument("--dev", action="store_true", help="developer mode (from source only)")
    parser.add_argument("--language", help=argparse.SUPPRESS)  # For screenshots in another language.
    parser.add_argument("--screenshot", help=argparse.SUPPRESS)
    parser.add_argument("--export-picture", help=argparse.SUPPRESS)
    parser.add_argument("--export-picture-2", help=argparse.SUPPRESS)
    parser.add_argument("--export-gedcom", help=argparse.SUPPRESS)
    parser.add_argument("--import-gedcom", help=argparse.SUPPRESS)
    parser.add_argument("--network-check", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--theme", choices=theme.THEMES, help=argparse.SUPPRESS)  # For screenshots.  # Can the map use HTTPS?
    args = parser.parse_args(argv)
    if args.network_check:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtNetwork import QSslSocket
        QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
        print(f"https {'yes' if QSslSocket.supportsSsl() else 'no'} ({QSslSocket.sslLibraryVersionString()})")
        return 0 if QSslSocket.supportsSsl() else 3

    # A program with no console window has nowhere to print errors on Windows.
    for stream in ("stdout", "stderr"):
        if getattr(sys, stream) is None:
            setattr(sys, stream, open(os.devnull, "w", encoding="utf-8"))

    app = QApplication(sys.argv[:1])
    app.setOrganizationName("Maiores")
    app.setApplicationName("Maiores")
    _bring_old_settings()
    chosen_theme = args.theme or str(QSettings().value(THEME_KEY) or "dark")
    apply_theme(app, chosen_theme if chosen_theme in theme.THEMES else "dark")

    def report_unexpected(kind, error, trace):
        # Without this, an unhandled error in a button handler closes the program.
        traceback.print_exception(kind, error, trace)
        QMessageBox.critical(None, t("window_title"), t("error_unexpected", error=error))

    sys.excepthook = report_unexpected

    # A test screenshot must not change which tree the program reopens next time.
    settings = None if args.screenshot else QSettings()
    if args.language:
        strings.set_language(args.language, QLocale.system().uiLanguages())
    elif settings is not None:
        strings.set_language(str(settings.value(LANGUAGE_KEY) or strings.SYSTEM), QLocale.system().uiLanguages())
    install_qt_translation(app)
    window = MainWindow(settings)

    if args.screenshot:
        def report(title, text):
            print(f"{title}: {text}", file=sys.stderr)

        window.alert = report
        window.confirm = lambda title, text: False

    if args.import_gedcom:
        if not window.import_gedcom(args.import_gedcom, args.folder):
            return 1
    elif args.folder and Path(args.folder).suffix.lower() in (".ged", ".gedcom") and Path(args.folder).is_file():
        window.choose_import(args.folder)  # A GEDCOM file: imported into a new tree, as File > Import does.
    elif args.folder:
        if not window.open_path(args.folder) and args.screenshot:
            return 1
    elif args.sample or args.screenshot:
        window.load_sample()
    elif settings is not None:
        reopen = window.tree_to_reopen() if window.reopen_last else None
        if reopen:
            window.open_path(reopen)
    if args.dev:
        try:
            # Looked up by name, so the release builds leave developer tools out.
            devmode = importlib.import_module("devtools.devmode")
        except ImportError:
            print("Developer mode only works when running from source.", file=sys.stderr)
            return 2
        devmode.install(window, serve=not args.screenshot)
    window.auto_tour = settings is not None and not args.screenshot
    window._maybe_first_tour()
    window.show()

    if args.screenshot:
        app.processEvents()
        window.view.fit_tree()
        app.processEvents()
        ok = window.grab().save(args.screenshot)
        if args.export_picture:
            ok = window.export_picture(args.export_picture) and ok
        if args.export_picture_2:
            ok = window.export_picture(args.export_picture_2) and ok
        if args.export_gedcom:
            ok = window.export_gedcom(args.export_gedcom) and ok
        return 0 if ok else 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
