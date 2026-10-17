"""Ventana principal: integración de escaneo, vistas, filtros y acciones."""

from __future__ import annotations

import os
from dataclasses import replace

from PySide6.QtCore import QModelIndex, QPoint, QSize, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QToolBar,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, __version__
from .formatting import format_count, human_size
from .models.categories import CATEGORY_LABELS
from .models.file_node import (
    FileNode,
    NodeKind,
    ScanOptions,
    ScanProgress,
    ScanResult,
    ScanStatus,
    SizeMetric,
)
from .services.file_actions import ActionResult, FileActions
from .services.filter_engine import FilterEngine, FilterSnapshot, FilterState
from .services.settings_manager import SettingsManager
from .theme import ThemePalette, apply_theme
from .treemap.layout_engine import TreemapMode
from .treemap.treemap_widget import TreemapWidget
from .views.details_panel import DetailsPanel
from .views.file_tree_model import FileTreeModel
from .views.filter_bar import FilterBar
from .views.largest_view import LargestView
from .views.legend import LegendWidget
from .workers.scan_worker import ScanController
from .workers.filter_worker import SnapshotController

_VIEW_INDEX = {"map": 0, "tree": 1, "largest": 2}


class MainWindow(QMainWindow):
    def __init__(self, settings: SettingsManager | None = None,
                 file_actions: FileActions | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings or SettingsManager()
        self.file_actions = file_actions or FileActions(self)
        self._scan_controller = ScanController(self)
        self._snapshot_controller = SnapshotController(self)
        self._scan_result: ScanResult | None = None
        self._snapshot: FilterSnapshot | None = None
        self._metric = self.settings.size_metric
        self._view_root: FileNode | None = None
        self._selected_node: FileNode | None = None
        self._selected_aggregate: list[FileNode] = []
        self._scanning = False
        self._scan_modified = False
        self._syncing = False
        self._snapshot_generation = 0
        self._snapshot_state: FilterState | None = None
        self._pending_scan_path: str | None = None
        self._banner_details_callback = None
        self._nav_back: list[FileNode] = []
        self._nav_forward: list[FileNode] = []
        self._filter_state = FilterState(
            show_hidden=self.settings.show_hidden,
            show_zero=self.settings.show_zero,
            min_tile_area=self.settings.min_tile_area,
        )
        self._current_view_mode = self.settings.view_mode
        self._theme: ThemePalette = apply_theme(
            QApplication.instance(), self.settings.theme
        )
        self._build_actions()
        self._build_ui()
        self._build_menus()
        self._connect()
        self._restore_state()
        self._sync_actions()
        self.setWindowTitle(APP_NAME)
        self._status_summary.setText("Listo. Elige una carpeta para analizar.")
        self._apply_child_themes()

    # ------------------------------------------------------------------ build
    def _make_action(self, text: str, slot=None, shortcut: str | QKeySequence | None = None,
                     icon: QIcon | None = None, checkable: bool = False,
                     tip: str = "") -> QAction:
        action = QAction(icon, text, self) if icon is not None else QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut) if isinstance(shortcut, str) else shortcut)
        if slot is not None:
            action.triggered.connect(slot)
        action.setCheckable(checkable)
        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        return action

    def _build_actions(self) -> None:
        style = self.style()
        self.action_analyze = self._make_action(
            "Analizar carpeta…", self._choose_folder, QKeySequence.Open,
            style.standardIcon(QStyle.SP_DirOpenIcon),
            tip="Elegir una carpeta o volumen para analizar (⌘O)",
        )
        self.action_rescan = self._make_action(
            "Actualizar", self._rescan, "Ctrl+R",
            style.standardIcon(QStyle.SP_BrowserReload),
            tip="Repetir el análisis de la ubicación actual (⌘R)",
        )
        self.action_cancel = self._make_action(
            "Cancelar", self._cancel_scan, "Esc",
            style.standardIcon(QStyle.SP_BrowserStop),
            tip="Cancelar el análisis en curso",
        )
        self.action_back = self._make_action(
            "Atrás", self._go_back, "Ctrl+[",
            style.standardIcon(QStyle.SP_ArrowBack), tip="Volver a la vista anterior",
        )
        self.action_forward = self._make_action(
            "Adelante", self._go_forward, "Ctrl+]",
            style.standardIcon(QStyle.SP_ArrowForward), tip="Avanzar a la vista siguiente",
        )
        self.action_up = self._make_action(
            "Subir", self._go_up, "Ctrl+Up",
            style.standardIcon(QStyle.SP_ArrowUp), tip="Subir un directorio (⌘↑)",
        )
        self.action_home = self._make_action(
            "Vista general", self._go_home, "Ctrl+Shift+Up",
            style.standardIcon(QStyle.SP_DirHomeIcon), tip="Volver a la raíz analizada",
        )
        self.action_find = self._make_action(
            "Buscar", self._focus_search, QKeySequence.Find,
            style.standardIcon(QStyle.SP_FileDialogContentsView),
            tip="Buscar por nombre o extensión (⌘F)",
        )
        self.action_filters = self._make_action(
            "Filtros", self._toggle_filters, "Ctrl+Alt+F", None, True,
            tip="Mostrar u ocultar la barra de filtros",
        )
        self.action_filters.setChecked(self.settings.filters_visible)
        self.action_details = self._make_action(
            "Panel de detalles", self._toggle_details, None, None, True,
            tip="Mostrar u ocultar el panel lateral",
        )
        self.action_details.setChecked(self.settings.details_visible)

        self.action_open = self._make_action(
            "Abrir", self._open_selected, "Ctrl+Return", None, tip="Abrir el elemento seleccionado (⌘↵)",
        )
        self.action_reveal = self._make_action(
            "Mostrar en Finder", self._reveal_selected, "Ctrl+Shift+R", None,
            tip="Mostrar el elemento en Finder (⌘⇧R)",
        )
        self.action_copy = self._make_action(
            "Copiar ruta", self._copy_selected, "Ctrl+Shift+C", None,
            tip="Copiar la ruta absoluta al portapapeles (⌘⇧C)",
        )
        self.action_locate = self._make_action(
            "Localizar en el mapa", self._locate_selected, "Ctrl+Shift+L", None,
            tip="Mostrar el elemento seleccionado en el treemap",
        )
        self.action_zoom = self._make_action(
            "Abrir directorio en el mapa", self._zoom_selected, "Ctrl+Shift+O", None,
            tip="Entrar en el directorio seleccionado",
        )
        self.action_trash = self._make_action(
            "Mover a la Papelera…", self._trash_selected, "Ctrl+Backspace", None,
            tip="Enviar el elemento a la Papelera de macOS (pide confirmación)",
        )

        self.action_about = self._make_action("Acerca de MacDirStat", self._show_about)
        self.action_quit = self._make_action("Salir", self.close, QKeySequence.Quit)

        self._view_group = QActionGroup(self)
        self._view_group.setExclusive(True)
        self._view_actions: dict[str, QAction] = {}
        for mode, label, shortcut in (
            ("map", "Mapa", "Ctrl+1"),
            ("tree", "Árbol", "Ctrl+2"),
            ("largest", "Mayores", "Ctrl+3"),
        ):
            action = self._make_action(label, lambda checked=False, m=mode: self._set_view_mode(m),
                                       shortcut, None, True)
            self._view_group.addAction(action)
            self._view_actions[mode] = action
        self._view_actions["map"].setChecked(True)

        self._metric_group = QActionGroup(self)
        self._metric_group.setExclusive(True)
        self._metric_actions: dict[SizeMetric, QAction] = {}
        for metric, label, shortcut in (
            (SizeMetric.LOGICAL, "Tamaño lógico", "Ctrl+Alt+1"),
            (SizeMetric.ALLOCATED, "Espacio asignado (est.)", "Ctrl+Alt+2"),
            (SizeMetric.ALLOCATED_UNIQUE, "Asignado único (est.)", "Ctrl+Alt+3"),
        ):
            action = self._make_action(
                label, lambda checked=False, m=metric: self._change_metric(m), shortcut, None, True
            )
            self._metric_group.addAction(action)
            self._metric_actions[metric] = action
        self._metric_actions[self._metric].setChecked(True)

        self._mode_group = QActionGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_actions: dict[TreemapMode, QAction] = {}
        for mode, label in (
            (TreemapMode.SUBTREE, "Subárbol completo"),
            (TreemapMode.CHILDREN, "Solo nivel actual"),
        ):
            action = self._make_action(
                label, lambda checked=False, m=mode: self._change_treemap_mode(m), None, None, True
            )
            self._mode_group.addAction(action)
            self._mode_actions[mode] = action
        self._mode_actions[self.settings.treemap_mode].setChecked(True)

        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        for preference, label in (
            ("system", "Automático"), ("light", "Claro"), ("dark", "Oscuro")
        ):
            action = self._make_action(
                label, lambda checked=False, p=preference: self._change_theme(p), None, None, True
            )
            self._theme_group.addAction(action)
            self._theme_actions[preference] = action
        self._theme_actions[self.settings.theme].setChecked(True)

        self.action_cross_device = self._make_action(
            "Incluir otros volúmenes montados", self._toggle_cross_device, None, None, True,
            tip="Cruzar puntos de montaje (se aplica al próximo análisis)",
        )
        self.action_cross_device.setChecked(self.settings.cross_device)

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 10, 12, 8)
        outer.setSpacing(8)

        location = QHBoxLayout()
        location.setSpacing(7)
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Ninguna ubicación analizada")
        self.path_edit.setAccessibleName("Ubicación analizada")
        location.addWidget(self.path_edit, 1)
        self.browse_button = QPushButton("Elegir carpeta…")
        self.browse_button.setToolTip("Elegir una carpeta o volumen (⌘O)")
        self.browse_button.clicked.connect(self.action_analyze.trigger)
        location.addWidget(self.browse_button)
        outer.addLayout(location)

        self._crumbs_scroll = QScrollArea()
        self._crumbs_scroll.setWidgetResizable(True)
        self._crumbs_scroll.setFrameShape(QFrame.NoFrame)
        self._crumbs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._crumbs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._crumbs_scroll.setFixedHeight(32)
        self._crumbs_scroll.setAccessibleName("Ruta de navegación")
        self._crumbs_widget = QWidget()
        self._crumbs_layout = QHBoxLayout(self._crumbs_widget)
        self._crumbs_layout.setContentsMargins(0, 0, 0, 0)
        self._crumbs_layout.setSpacing(3)
        self._crumbs_scroll.setWidget(self._crumbs_widget)
        outer.addWidget(self._crumbs_scroll)

        self._banner = QFrame()
        self._banner.setObjectName("Banner")
        banner_layout = QHBoxLayout(self._banner)
        banner_layout.setContentsMargins(10, 6, 8, 6)
        banner_layout.setSpacing(8)
        self._banner_label = QLabel("")
        self._banner_label.setWordWrap(True)
        self._banner_label.setTextFormat(Qt.PlainText)
        banner_layout.addWidget(self._banner_label, 1)
        self._banner_details = QPushButton("Ver detalles…")
        self._banner_details.clicked.connect(self._banner_show_details)
        banner_layout.addWidget(self._banner_details)
        banner_close = QToolButton()
        banner_close.setText("Cerrar")
        banner_close.setAutoRaise(True)
        banner_close.clicked.connect(self._banner.hide)
        banner_layout.addWidget(banner_close)
        self._banner.hide()
        outer.addWidget(self._banner)

        self._filter_bar = FilterBar()
        self._filter_bar.set_state(self._filter_state)
        self._filter_bar.setVisible(self.settings.filters_visible)
        outer.addWidget(self._filter_bar)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        self._stack = QStackedWidget()

        self._treemap = TreemapWidget()
        self._treemap.set_mode(self.settings.treemap_mode)
        self._treemap.set_min_tile_area(self._filter_state.min_tile_area)
        map_container = QWidget()
        map_layout = QVBoxLayout(map_container)
        map_layout.setContentsMargins(0, 4, 0, 0)
        map_layout.setSpacing(4)
        map_layout.addWidget(self._treemap, 1)
        self._legend = LegendWidget()
        map_layout.addWidget(self._legend)
        self._stack.addWidget(map_container)

        self._tree_model = FileTreeModel(self)
        self._tree = QTreeView()
        self._tree.setModel(self._tree_model)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setSortingEnabled(True)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.setSelectionBehavior(QTreeView.SelectRows)
        self._tree.setSelectionMode(QTreeView.SingleSelection)
        self._tree.setAllColumnsShowFocus(True)
        self._tree.setAccessibleName("Árbol de archivos y carpetas")
        header = self._tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(FileTreeModel.COL_NAME, QHeaderView.Interactive)
        header.setSectionResizeMode(FileTreeModel.COL_TYPE, QHeaderView.Interactive)
        header.setSectionResizeMode(FileTreeModel.COL_CATEGORY, QHeaderView.Interactive)
        header.setSectionResizeMode(FileTreeModel.COL_SIZE, QHeaderView.Interactive)
        header.setSectionResizeMode(FileTreeModel.COL_PERCENT, QHeaderView.Interactive)
        header.setSectionResizeMode(FileTreeModel.COL_ELEMENTS, QHeaderView.Interactive)
        header.setSectionResizeMode(FileTreeModel.COL_MTIME, QHeaderView.Interactive)
        header.setSectionResizeMode(FileTreeModel.COL_PATH, QHeaderView.Stretch)
        self._tree.setColumnWidth(FileTreeModel.COL_NAME, 230)
        self._tree.setColumnWidth(FileTreeModel.COL_TYPE, 110)
        self._tree.setColumnWidth(FileTreeModel.COL_CATEGORY, 120)
        self._tree.setColumnWidth(FileTreeModel.COL_SIZE, 105)
        self._tree.setColumnWidth(FileTreeModel.COL_PERCENT, 78)
        self._tree.setColumnWidth(FileTreeModel.COL_ELEMENTS, 85)
        self._tree.setColumnWidth(FileTreeModel.COL_MTIME, 135)
        self._tree.sortByColumn(FileTreeModel.COL_SIZE, Qt.DescendingOrder)
        self._stack.addWidget(self._tree)

        self._largest = LargestView()
        self._stack.addWidget(self._largest)
        left_layout.addWidget(self._stack)
        self._stack.setCurrentIndex(_VIEW_INDEX[self.settings.view_mode])
        self._view_actions[self.settings.view_mode].setChecked(True)

        self._details = DetailsPanel()
        self._details.setVisible(self.settings.details_visible)

        self._splitter.addWidget(left)
        self._splitter.addWidget(self._details)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self._splitter.setSizes([900, 300])
        outer.addWidget(self._splitter, 1)
        self.setCentralWidget(central)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedWidth(130)
        self._progress.setTextVisible(False)
        self._progress.hide()
        self._status_summary = QLabel("Listo")
        self._status_summary.setObjectName("Muted")
        status = QStatusBar()
        self.setStatusBar(status)
        status.addPermanentWidget(self._progress)
        status.addPermanentWidget(self._status_summary, 1)

        self._toolbar = QToolBar("Principal")
        self._toolbar.setObjectName("MainToolBar")
        self._toolbar.setMovable(False)
        self._toolbar.setFloatable(False)
        self._toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._toolbar.setIconSize(QSize(16, 16))
        for action in (
            self.action_analyze, self.action_rescan, self.action_cancel,
        ):
            self._toolbar.addAction(action)
        self._toolbar.addSeparator()
        for action in (self.action_back, self.action_up, self.action_home):
            self._toolbar.addAction(action)
        self._toolbar.addSeparator()
        for mode in ("map", "tree", "largest"):
            self._toolbar.addAction(self._view_actions[mode])
        self._toolbar.addSeparator()
        self._toolbar.addAction(self.action_find)
        self._toolbar.addAction(self.action_filters)
        self.addToolBar(Qt.TopToolBarArea, self._toolbar)

        self.setMinimumSize(880, 560)
        self.resize(1220, 780)

    def _build_menus(self) -> None:
        menu_file = self.menuBar().addMenu("Archivo")
        menu_file.addAction(self.action_analyze)
        menu_file.addAction(self.action_rescan)
        menu_file.addAction(self.action_cancel)
        menu_file.addSeparator()
        menu_file.addAction(self.action_quit)

        menu_element = self.menuBar().addMenu("Elemento")
        menu_element.addAction(self.action_open)
        menu_element.addAction(self.action_reveal)
        menu_element.addAction(self.action_copy)
        menu_element.addSeparator()
        menu_element.addAction(self.action_locate)
        menu_element.addAction(self.action_zoom)
        menu_element.addSeparator()
        menu_element.addAction(self.action_trash)

        menu_go = self.menuBar().addMenu("Ir")
        menu_go.addAction(self.action_back)
        menu_go.addAction(self.action_forward)
        menu_go.addAction(self.action_up)
        menu_go.addAction(self.action_home)

        menu_view = self.menuBar().addMenu("Ver")
        for mode in ("map", "tree", "largest"):
            menu_view.addAction(self._view_actions[mode])
        menu_view.addSeparator()
        menu_view.addAction(self.action_filters)
        menu_view.addAction(self.action_details)
        menu_view.addSeparator()
        metric_menu = menu_view.addMenu("Métrica de tamaño")
        for action in self._metric_actions.values():
            metric_menu.addAction(action)
        mode_menu = menu_view.addMenu("Modo del treemap")
        for action in self._mode_actions.values():
            mode_menu.addAction(action)
        theme_menu = menu_view.addMenu("Tema")
        for action in self._theme_actions.values():
            theme_menu.addAction(action)
        menu_view.addSeparator()
        menu_view.addAction(self.action_cross_device)

        menu_help = self.menuBar().addMenu("Ayuda")
        menu_help.addAction(self.action_about)

    def _connect(self) -> None:
        self._scan_controller.progress.connect(self._on_scan_progress)
        self._scan_controller.finished.connect(self._on_scan_finished)
        self._scan_controller.cancelled.connect(self._on_scan_cancelled)
        self._scan_controller.failed.connect(self._on_scan_failed)
        self._snapshot_controller.ready.connect(self._on_snapshot_ready)

        self._filter_bar.filtersChanged.connect(self._on_filters_changed)
        self._treemap.nodeSelected.connect(self._on_treemap_selected)
        self._treemap.aggregateSelected.connect(self._on_aggregate_selected)
        self._treemap.nodeActivated.connect(self._open_node)
        self._treemap.zoomRequested.connect(self._zoom_node)
        self._treemap.openRequested.connect(self._open_node)
        self._treemap.aggregateActivated.connect(self._show_grouped)
        self._treemap.contextMenuRequested.connect(self._treemap_context_menu)
        self._treemap.aggregateContextRequested.connect(self._aggregate_context_menu)

        self._tree.selectionModel().currentChanged.connect(self._on_tree_current_changed)
        self._tree.doubleClicked.connect(self._on_tree_double_clicked)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._tree_context_menu)

        self._largest.nodeSelected.connect(self._on_largest_selected)
        self._largest.nodeActivated.connect(self._locate_node)
        self._largest.openRequested.connect(self._open_node)
        self._largest.revealRequested.connect(self._reveal_node)
        self._largest.copyRequested.connect(self._copy_node)

        self._details.openRequested.connect(self._open_node)
        self._details.revealRequested.connect(self._reveal_node)
        self._details.copyRequested.connect(self._copy_node)
        self._details.trashRequested.connect(self._confirm_trash)
        self._details.groupedRequested.connect(self._show_grouped)
        self.action_details.toggled.connect(self._toggle_details)
        self.action_filters.toggled.connect(self._toggle_filters)

        hints = QApplication.styleHints()
        signal = getattr(hints, "colorSchemeChanged", None)
        if signal is not None:
            signal.connect(self._on_system_scheme_changed)

    def _restore_state(self) -> None:
        geometry = self.settings.window_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self.settings.window_state()
        if state is not None:
            self.restoreState(state)
        splitter_state = self.settings.splitter_state()
        if splitter_state is not None:
            self._splitter.restoreState(splitter_state)
        if not self._window_is_visible():
            self.resize(1220, 780)
        self._filter_bar.setVisible(self.settings.filters_visible)
        self._details.setVisible(self.settings.details_visible)
        self.action_filters.setChecked(self.settings.filters_visible)
        self.action_details.setChecked(self.settings.details_visible)
        self._metric_actions[self._metric].setChecked(True)
        self._mode_actions[self.settings.treemap_mode].setChecked(True)
        self._theme_actions[self.settings.theme].setChecked(True)
        self._update_breadcrumb()

    def _window_is_visible(self) -> bool:
        frame = self.frameGeometry()
        if frame.width() <= 0 or frame.height() <= 0:
            return False
        for screen in QApplication.screens():
            if screen.availableGeometry().intersects(frame):
                return True
        return False

    def _apply_child_themes(self) -> None:
        self._treemap.set_theme(self._theme)
        self._legend.set_theme(self._theme)
        self._details.set_theme(self._theme)
        self._largest.set_theme(self._theme)

    # ------------------------------------------------------------------ scan
    def start_scan(self, path: str) -> None:
        """API pública para analizar una ruta (CLI y pruebas de humo)."""
        self._start_scan(path)

    def _choose_folder(self) -> None:
        if self._scanning or self._scan_controller.is_running():
            return
        start = self.settings.last_folder
        if not start or not os.path.isdir(start):
            start = QStandardPaths.writableLocation(QStandardPaths.HomeLocation)
        path = QFileDialog.getExistingDirectory(
            self, "Seleccionar carpeta o volumen", start, QFileDialog.ShowDirsOnly
        )
        if path:
            self._start_scan(path)

    def _start_scan(self, path: str) -> None:
        if self._scanning or self._scan_controller.is_running():
            return
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            self._show_banner("La ubicación seleccionada no es una carpeta accesible.")
            return
        self._snapshot_generation += 1
        self._scanning = True
        self._pending_scan_path = path
        self._scan_result = None
        self._snapshot = None
        self._snapshot_state = None
        self._view_root = None
        self._selected_node = None
        self._selected_aggregate = []
        self._nav_back.clear()
        self._nav_forward.clear()
        self._scan_modified = False
        self._tree_model.set_snapshot(None, self._metric)
        self._largest.set_snapshot(None, self._metric)
        self._treemap.set_snapshot(None)
        self._details.clear()
        self._hide_banner()
        self.path_edit.setText(path)
        self.path_edit.setToolTip(path)
        self._update_breadcrumb()
        self.settings.last_folder = path
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._status_summary.setText("Analizando…")
        self.setWindowTitle(f"{APP_NAME} — analizando {os.path.basename(path) or path}")
        self._update_actions()
        options = ScanOptions(cross_device=self.settings.cross_device)
        if not self._scan_controller.start(path, options):
            self._scanning = False
            self._progress.hide()
            self._show_banner("No se pudo iniciar el análisis.")
            self._update_actions()

    def _rescan(self) -> None:
        if self._scan_result is not None:
            self._start_scan(self._scan_result.root_path)
        else:
            self._choose_folder()

    def _cancel_scan(self) -> None:
        if self._scanning:
            self._scan_controller.cancel()
            self.action_cancel.setEnabled(False)
            self._status_summary.setText("Cancelando el análisis…")

    def _on_scan_progress(self, progress: ScanProgress) -> None:
        text = (
            f"Analizando · {format_count(progress.files)} archivos · "
            f"{format_count(progress.dirs)} carpetas · {human_size(progress.bytes)}"
        )
        if progress.errors:
            text += f" · {progress.errors} errores"
        self._status_summary.setText(text)
        if progress.current_path:
            self.path_edit.setText(progress.current_path)
            self.path_edit.setToolTip(progress.current_path)

    def _on_scan_finished(self, result: ScanResult) -> None:
        self._scanning = False
        self._progress.hide()
        self._adopt_result(result, cancelled=False)

    def _on_scan_cancelled(self, result: ScanResult) -> None:
        self._scanning = False
        self._progress.hide()
        self._adopt_result(result, cancelled=True)

    def _on_scan_failed(self, message: str) -> None:
        self._scanning = False
        self._progress.hide()
        self._status_summary.setText("El análisis no pudo completarse.")
        self._show_banner(message)
        self._update_actions()

    def _adopt_result(self, result: ScanResult, cancelled: bool) -> None:
        self._scan_result = result
        self._scan_modified = False
        self._view_root = result.root
        self._selected_node = None
        self._selected_aggregate = []
        self._nav_back.clear()
        self._nav_forward.clear()
        self.path_edit.setText(result.root_path)
        self.path_edit.setToolTip(result.root_path)
        self._details.set_volume_info(result.volume_total, result.volume_free)
        self._details.clear()
        self._update_breadcrumb()
        self._hide_banner()
        if cancelled:
            self._show_banner(
                "Análisis cancelado. Se muestran los elementos recorridos hasta la cancelación; "
                "el resultado está incompleto."
            )
        elif result.status is ScanStatus.PARTIAL:
            permissions = sum(1 for error in result.errors if error.is_permission)
            text = (
                f"Resultado parcial: {format_count(result.stats.error_count)} errores de acceso"
            )
            if permissions:
                text += f" ({permissions} por permisos)"
            if result.stats.skipped_mounts:
                text += f" y {result.stats.skipped_mounts} volúmenes omitidos"
            text += ". Los resultados no incluyen esos elementos."
            self._show_banner(text, self._show_error_details)
        self._filter_state = self._filter_bar.state()
        self._schedule_snapshot(self._filter_state)
        self._update_actions()
        self.statusBar().showMessage(
            f"Análisis terminado en {result.elapsed_s:.1f} s", 6000
        )
        self._update_title()

    def _update_title(self) -> None:
        if self._scanning and self._pending_scan_path:
            name = os.path.basename(self._pending_scan_path) or self._pending_scan_path
            self.setWindowTitle(f"{APP_NAME} — analizando {name}")
            return
        if self._scan_result is None:
            self.setWindowTitle(APP_NAME)
            return
        name = self._scan_result.root.name or self._scan_result.root_path
        suffix = " · modificado" if self._scan_modified else ""
        self.setWindowTitle(f"{APP_NAME} — {name}{suffix}")

    # -------------------------------------------------------------- snapshots
    def _schedule_snapshot(self, state: FilterState) -> None:
        if self._scan_result is None:
            self._filter_state = state
            return
        self._filter_state = state
        self._snapshot_generation += 1
        generation = self._snapshot_generation
        if len(self._scan_result.all_nodes) <= 12_000:
            snapshot = FilterEngine().build_snapshot(
                self._scan_result, state, self._metric, generation
            )
            self._on_snapshot_ready(generation, snapshot)
        else:
            self._status_summary.setText("Calculando la vista filtrada…")
            self._snapshot_controller.submit(
                generation, self._scan_result, state, self._metric
            )

    def _on_snapshot_ready(self, generation: int, snapshot: object) -> None:
        if generation != self._snapshot_generation or self._scan_result is None:
            return
        if not isinstance(snapshot, FilterSnapshot):
            self._show_banner("No se pudo calcular la vista filtrada. Se conserva la anterior.")
            return
        snapshot.state = self._filter_state
        self._snapshot = snapshot
        self._snapshot_state = self._filter_state
        self._metric = snapshot.metric
        self._metric_actions[self._metric].setChecked(True)
        if self._view_root is None or not snapshot.is_visible(self._view_root):
            self._view_root = self._nearest_visible(self._view_root) or snapshot.root
        self._selected_aggregate = []
        self._syncing = True
        try:
            self._tree_model.set_snapshot(snapshot, self._metric)
            self._largest.set_snapshot(snapshot, self._metric, self.settings.top_n)
            self._treemap.set_snapshot(snapshot)
            self._treemap.set_mode(self.settings.treemap_mode)
            self._treemap.set_min_tile_area(self._filter_state.min_tile_area)
            self._treemap.set_view_root(self._view_root)
        finally:
            self._syncing = False
        self._update_breadcrumb()
        self._refresh_selection_after_snapshot()
        if self._tree_model.rowCount() > 0:
            self._tree.expand(self._tree_model.index(0, 0))
        self._update_status_summary()
        self._update_actions()

    def _nearest_visible(self, node: FileNode | None) -> FileNode | None:
        snapshot = self._snapshot
        if snapshot is None:
            return None
        while node is not None and not snapshot.is_visible(node):
            node = node.parent
        return node

    def _refresh_selection_after_snapshot(self) -> None:
        node = self._selected_node
        if self._scan_result is None:
            return
        if node is None or not self._node_belongs(node):
            self._selected_node = None
            self._details.clear()
            self._treemap.clear_selection()
            return
        snapshot = self._snapshot
        if snapshot is None or not snapshot.is_visible(node):
            self._selected_node = None
            self._details.clear()
            self._treemap.clear_selection()
            self._tree.clearSelection()
            self._largest.select_node(None)
            return
        self._details.set_node(node, snapshot, self._metric)
        self._treemap.select_node(node)
        self._syncing = True
        try:
            self._select_in_tree(node)
            self._largest.select_node(node)
        finally:
            self._syncing = False

    def _update_status_summary(self) -> None:
        result = self._scan_result
        snapshot = self._snapshot
        if result is None or snapshot is None:
            self._status_summary.setText("Listo. Elige una carpeta para analizar.")
            return
        visible_elements = snapshot.total_files + snapshot.total_dirs
        original_elements = result.stats.files + result.stats.dirs
        original_bytes = result.root.display_size(self._metric)
        if snapshot.is_filtered:
            text = (
                f"Mostrando {format_count(visible_elements)} de "
                f"{format_count(original_elements)} elementos · "
                f"{human_size(snapshot.total_bytes)} de {human_size(original_bytes)}"
            )
        else:
            text = (
                f"{format_count(result.stats.files)} archivos · "
                f"{format_count(result.stats.dirs)} carpetas · "
                f"{human_size(snapshot.total_bytes)}"
            )
        text += f" · {result.elapsed_s:.1f} s"
        if result.status is ScanStatus.CANCELLED:
            text += " · cancelado"
        elif result.status is ScanStatus.PARTIAL:
            text += f" · {format_count(result.stats.error_count)} errores"
        if self._scan_modified:
            text += " · modificado tras la Papelera"
        self._status_summary.setText(text)

    # ---------------------------------------------------------------- filters
    def _on_filters_changed(self, state: FilterState) -> None:
        self.settings.show_hidden = state.show_hidden
        self.settings.show_zero = state.show_zero
        self.settings.min_tile_area = state.min_tile_area
        if self._scan_result is None:
            self._filter_state = state
            return
        current = self._filter_state
        if current == state:
            return
        if current is not None and replace(current, min_tile_area=0.0) == replace(state, min_tile_area=0.0):
            self._filter_state = state
            if self._snapshot is not None:
                self._snapshot.state = state
            self._treemap.set_min_tile_area(state.min_tile_area)
            return
        self._filter_state = state
        self._schedule_snapshot(state)

    def _change_metric(self, metric: SizeMetric) -> None:
        if metric is self._metric:
            return
        self._metric = metric
        self.settings.size_metric = metric
        self._metric_actions[metric].setChecked(True)
        if self._scan_result is not None:
            self._schedule_snapshot(self._filter_bar.state())

    def _change_treemap_mode(self, mode: TreemapMode) -> None:
        self.settings.treemap_mode = mode
        self._mode_actions[mode].setChecked(True)
        self._treemap.set_mode(mode)

    def _change_theme(self, preference: str) -> None:
        self.settings.theme = preference
        self._theme = apply_theme(QApplication.instance(), preference)
        self._theme_actions[preference].setChecked(True)
        self._apply_child_themes()

    def _on_system_scheme_changed(self, *args) -> None:
        if self.settings.theme == "system":
            self._theme = apply_theme(QApplication.instance(), "system")
            self._apply_child_themes()

    def _toggle_cross_device(self, checked: bool) -> None:
        self.settings.cross_device = checked
        if self._scan_result is not None:
            self.statusBar().showMessage(
                "La opción de volúmenes se aplicará en el próximo análisis.", 5000
            )

    def _toggle_filters(self, visible: bool) -> None:
        self._filter_bar.setVisible(visible)
        self.settings.filters_visible = visible
        self.action_filters.setChecked(visible)

    def _toggle_details(self, visible: bool) -> None:
        self._details.setVisible(visible)
        self.settings.details_visible = visible
        self.action_details.setChecked(visible)

    def _focus_search(self) -> None:
        if not self._filter_bar.isVisible():
            self._toggle_filters(True)
        self._filter_bar.search.setFocus()
        self._filter_bar.search.selectAll()

    # ---------------------------------------------------------------- views
    def _set_view_mode(self, mode: str, save: bool = True) -> None:
        if mode not in _VIEW_INDEX:
            return
        self._stack.setCurrentIndex(_VIEW_INDEX[mode])
        self._view_actions[mode].setChecked(True)
        self._current_view_mode = mode
        if save:
            self.settings.view_mode = mode

    def _update_breadcrumb(self) -> None:
        while self._crumbs_layout.count():
            item = self._crumbs_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self._scan_result is None or self._view_root is None:
            label = QLabel("Sin ubicación analizada")
            label.setObjectName("Muted")
            self._crumbs_layout.addWidget(label)
            self._crumbs_layout.addStretch(1)
            return
        chain: list[FileNode] = []
        node: FileNode | None = self._view_root
        while node is not None:
            chain.append(node)
            node = node.parent
        chain.reverse()
        for index, crumb in enumerate(chain):
            if index:
                separator = QLabel("›")
                separator.setObjectName("Muted")
                self._crumbs_layout.addWidget(separator)
            button = QToolButton()
            label = crumb.name or crumb.path()
            if crumb.parent is None and label == crumb.name and crumb.root_path == "/":
                label = "/"
            button.setText(label)
            button.setAutoRaise(True)
            button.setToolTip(crumb.path())
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, target=crumb: self._navigate_to(target, record=True)
            )
            self._crumbs_layout.addWidget(button)
        self._crumbs_layout.addStretch(1)
        QTimer.singleShot(0, self._scroll_crumbs_end)

    def _scroll_crumbs_end(self) -> None:
        bar = self._crumbs_scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def _navigate_to(self, node: FileNode | None, record: bool = True) -> None:
        if node is None or self._scan_result is None:
            return
        if node.kind not in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            return
        if self._snapshot is not None and not self._snapshot.is_visible(node):
            return
        if record and self._view_root is not None and self._view_root is not node:
            self._nav_back.append(self._view_root)
            self._nav_forward.clear()
        self._view_root = node
        self._treemap.set_view_root(node)
        self._update_breadcrumb()
        self._update_actions()

    def _go_back(self) -> None:
        if not self._nav_back:
            return
        current = self._view_root
        target = self._nav_back.pop()
        if current is not None:
            self._nav_forward.append(current)
        self._view_root = target
        self._treemap.set_view_root(target)
        self._update_breadcrumb()
        self._update_actions()

    def _go_forward(self) -> None:
        if not self._nav_forward:
            return
        current = self._view_root
        target = self._nav_forward.pop()
        if current is not None:
            self._nav_back.append(current)
        self._view_root = target
        self._treemap.set_view_root(target)
        self._update_breadcrumb()
        self._update_actions()

    def _go_up(self) -> None:
        if self._view_root is None or self._view_root.parent is None:
            return
        self._navigate_to(self._view_root.parent)

    def _go_home(self) -> None:
        if self._scan_result is not None:
            self._navigate_to(self._scan_result.root)

    # ------------------------------------------------------------- selection
    def _on_treemap_selected(self, node: FileNode | None) -> None:
        if self._syncing:
            return
        self._selected_aggregate = []
        self._selected_node = node
        self._syncing = True
        try:
            if node is None:
                self._details.clear()
                self._tree.clearSelection()
                self._largest.select_node(None)
            else:
                if self._snapshot is not None:
                    self._details.set_node(node, self._snapshot, self._metric)
                self._select_in_tree(node)
                self._largest.select_node(node)
        finally:
            self._syncing = False
        self._update_actions()

    def _on_tree_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if self._syncing:
            return
        node = self._tree_model.node_at(current)
        self._selected_node = node
        self._selected_aggregate = []
        self._syncing = True
        try:
            if node is None:
                self._details.clear()
                self._treemap.clear_selection()
                self._largest.select_node(None)
            else:
                if self._snapshot is not None:
                    self._details.set_node(node, self._snapshot, self._metric)
                self._treemap.select_node(node)
                self._largest.select_node(node)
        finally:
            self._syncing = False
        self._update_actions()

    def _on_largest_selected(self, node: FileNode | None) -> None:
        if self._syncing:
            return
        self._selected_node = node
        self._selected_aggregate = []
        self._syncing = True
        try:
            if node is None:
                self._details.clear()
                self._treemap.clear_selection()
                self._tree.clearSelection()
            else:
                if self._snapshot is not None:
                    self._details.set_node(node, self._snapshot, self._metric)
                self._treemap.select_node(node)
                self._select_in_tree(node)
        finally:
            self._syncing = False
        self._update_actions()

    def _on_aggregate_selected(self, nodes: object) -> None:
        grouped = [node for node in nodes if isinstance(node, FileNode)]
        self._selected_node = None
        self._selected_aggregate = grouped
        self._syncing = True
        try:
            if self._snapshot is not None:
                self._details.set_aggregate(grouped, self._snapshot, self._metric)
            self._tree.clearSelection()
            self._largest.select_node(None)
        finally:
            self._syncing = False
        self._update_actions()

    def _select_in_tree(self, node: FileNode) -> None:
        index = self._tree_model.index_for_node(node)
        if not index.isValid():
            return
        parent = index.parent()
        while parent.isValid():
            self._tree.expand(parent)
            parent = parent.parent()
        self._tree.setCurrentIndex(index)
        self._tree.scrollTo(index, QTreeView.PositionAtCenter)

    def _activate_current(self) -> None:
        node = self._selected_node
        if node is None:
            return
        if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            self._zoom_node(node)
        else:
            self._open_node(node)

    def _on_tree_double_clicked(self, index: QModelIndex) -> None:
        node = self._tree_model.node_at(index)
        if node is None:
            return
        if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            self._zoom_node(node)
        else:
            self._open_node(node)

    def _zoom_node(self, node: FileNode | None) -> None:
        if node is None or node.kind not in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            return
        self._set_view_mode("map")
        self._navigate_to(node, record=True)

    def _zoom_selected(self) -> None:
        self._zoom_node(self._selected_node)

    def _locate_selected(self) -> None:
        self._locate_node(self._selected_node)

    def _locate_node(self, node: FileNode | None) -> None:
        if node is None or self._scan_result is None or self._snapshot is None:
            return
        if not self._snapshot.is_visible(node):
            self.statusBar().showMessage(
                "El elemento está oculto por los filtros actuales.", 5000
            )
            return
        self._set_view_mode("map")
        if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            parent = node.parent
        else:
            parent = node.parent
        if parent is None:
            parent = self._scan_result.root
        self._navigate_to(parent, record=True)
        self._selected_node = node
        if self._snapshot is not None:
            self._details.set_node(node, self._snapshot, self._metric)
        self._treemap.select_node(node)
        self._syncing = True
        try:
            self._select_in_tree(node)
            self._largest.select_node(node)
        finally:
            self._syncing = False
        self._update_actions()
        self.statusBar().showMessage(f"Localizado: {node.path()}", 4000)

    # ---------------------------------------------------------------- actions
    def _selected_or_none(self) -> FileNode | None:
        return self._selected_node

    def _open_selected(self) -> None:
        node = self._selected_or_none()
        if node is not None:
            self._open_node(node)

    def _reveal_selected(self) -> None:
        node = self._selected_or_none()
        if node is not None:
            self._reveal_node(node)

    def _copy_selected(self) -> None:
        node = self._selected_or_none()
        if node is not None:
            self._copy_node(node)

    def _trash_selected(self) -> None:
        node = self._selected_or_none()
        if node is not None:
            self._confirm_trash(node)

    def _open_node(self, node: FileNode) -> None:
        result = self.file_actions.open_node(node)
        self._show_action_result(result)

    def _reveal_node(self, node: FileNode) -> None:
        result = self.file_actions.reveal(node)
        self._show_action_result(result)

    def _copy_node(self, node: FileNode) -> None:
        result = self.file_actions.copy_path(node)
        if result.ok:
            self.statusBar().showMessage("Ruta copiada al portapapeles.", 3500)
        else:
            self._show_action_result(result)

    def _show_action_result(self, result: ActionResult) -> None:
        if result.ok:
            return
        self.statusBar().showMessage(result.message, 7000)
        QMessageBox.warning(self, APP_NAME, result.message)

    def _confirm_trash(self, node: FileNode) -> None:
        if self._scan_result is None or not self._node_belongs(node):
            return
        problem = self.file_actions.validate_for_trash(node)
        if problem:
            QMessageBox.warning(self, "No se puede mover a la Papelera", problem)
            return
        if not self._ask_trash_confirmation(node):
            return
        result = self.file_actions.move_to_trash(node)
        if not result.ok:
            QMessageBox.critical(self, "No se pudo mover a la Papelera", result.message)
            return
        self._prune_after_trash(node)

    def _ask_trash_confirmation(self, node: FileNode) -> bool:
        logical = node.total_logical
        details = [
            node.path(),
            "",
            f"Tamaño lógico: {human_size(logical)}",
            f"Espacio asignado estimado: {human_size(node.total_allocated)}",
        ]
        if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            details.append(
                f"Contiene {format_count(node.total_files)} archivos y "
                f"{format_count(node.total_dirs)} subdirectorios."
            )
        details.extend([
            "",
            "Se moverá a la Papelera de macOS; podrás recuperarlo hasta vaciarla.",
            "El espacio liberable real puede diferir (clones, snapshots, compresión).",
        ])
        if logical >= 1024 ** 3 or node.total_files >= 1000:
            details.insert(-2, "AVISO: este elemento es grande. Revísalo antes de continuar.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Mover a la Papelera")
        box.setText(f"¿Mover «{node.name}» a la Papelera?")
        box.setInformativeText("\n".join(details))
        move = box.addButton("Mover a la Papelera", QMessageBox.DestructiveRole)
        cancel = box.addButton("Cancelar", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is move

    def _node_belongs(self, node: FileNode) -> bool:
        if self._scan_result is None:
            return False
        root = node
        while root.parent is not None:
            root = root.parent
        return root is self._scan_result.root

    def _prune_after_trash(self, node: FileNode) -> None:
        result = self._scan_result
        if result is None or node.parent is None:
            return
        parent = node.parent
        dir_delta = node.total_dirs + (
            1 if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE, NodeKind.SKIPPED_MOUNT) else 0
        )
        current: FileNode | None = parent
        while current is not None:
            current.total_files = max(0, current.total_files - node.total_files)
            current.total_dirs = max(0, current.total_dirs - dir_delta)
            current.total_logical = max(0, current.total_logical - node.total_logical)
            current.total_allocated = max(0, current.total_allocated - node.total_allocated)
            current.total_unique_allocated = max(
                0, current.total_unique_allocated - node.total_unique_allocated
            )
            current.total_zero_files = max(0, current.total_zero_files - node.total_zero_files)
            current.total_errors = max(0, current.total_errors - node.total_errors)
            current = current.parent
        try:
            parent.children.remove(node)
        except (ValueError, AttributeError):
            pass
        removed = list(node.walk())
        removed_ids = {id(item) for item in removed}
        root = result.root
        stats = result.stats
        symlinks = sum(1 for item in removed if item.kind is NodeKind.SYMLINK)
        packages = sum(1 for item in removed if item.kind is NodeKind.PACKAGE)
        skipped = sum(1 for item in removed if item.kind is NodeKind.SKIPPED_MOUNT)
        new_stats = replace(
            stats,
            files=root.total_files,
            dirs=root.total_dirs,
            symlinks=max(0, stats.symlinks - symlinks),
            packages=max(0, stats.packages - packages),
            zero_files=root.total_zero_files,
            logical_bytes=root.total_logical,
            allocated_bytes=root.total_allocated,
            unique_allocated_bytes=root.total_unique_allocated,
            error_count=root.total_errors,
            skipped_mounts=max(0, stats.skipped_mounts - skipped),
        )
        self._scan_result = replace(
            result,
            all_nodes=[item for item in result.all_nodes if id(item) not in removed_ids],
            stats=new_stats,
        )
        current_view = self._view_root
        cursor = current_view
        removed_view = False
        while cursor is not None:
            if cursor is node:
                removed_view = True
                break
            cursor = cursor.parent
        if removed_view:
            self._view_root = parent
        self._selected_node = None
        self._selected_aggregate = []
        self._details.clear()
        self._treemap.clear_selection()
        self._scan_modified = True
        self._snapshot_generation += 1
        self._filter_state = self._filter_bar.state()
        self._schedule_snapshot(self._filter_state)
        self._update_title()
        self._show_banner(
            "Elemento enviado a la Papelera. Los totales se han actualizado; "
            "usa Actualizar para un recuento exacto (enlaces duros y clones pueden diferir)."
        )
        self.statusBar().showMessage("Elemento enviado a la Papelera.", 5000)

    # ------------------------------------------------------------- context menus
    def _treemap_context_menu(self, node: FileNode, position: QPoint) -> None:
        menu = QMenu(self)
        open_action = menu.addAction("Abrir")
        reveal_action = menu.addAction("Mostrar en Finder")
        copy_action = menu.addAction("Copiar ruta")
        menu.addSeparator()
        locate_action = menu.addAction("Localizar en el mapa")
        zoom_action = None
        if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            zoom_action = menu.addAction("Abrir directorio en el mapa")
        menu.addSeparator()
        trash_action = menu.addAction("Mover a la Papelera…")
        move_action = menu.addAction("Subir un directorio")
        chosen = menu.exec(position)
        if chosen is open_action:
            self._open_node(node)
        elif chosen is reveal_action:
            self._reveal_node(node)
        elif chosen is copy_action:
            self._copy_node(node)
        elif chosen is locate_action:
            self._locate_node(node)
        elif zoom_action is not None and chosen is zoom_action:
            self._zoom_node(node)
        elif chosen is trash_action:
            self._confirm_trash(node)
        elif chosen is move_action:
            self._go_up()

    def _aggregate_context_menu(self, nodes: list[FileNode], position: QPoint) -> None:
        menu = QMenu(self)
        show_action = menu.addAction("Ver elementos agrupados…")
        chosen = menu.exec(position)
        if chosen is show_action:
            self._show_grouped(nodes)

    def _tree_context_menu(self, position: QPoint) -> None:
        index = self._tree.indexAt(position)
        node = self._tree_model.node_at(index)
        if node is None:
            return
        menu = QMenu(self)
        open_action = menu.addAction("Abrir")
        reveal_action = menu.addAction("Mostrar en Finder")
        copy_action = menu.addAction("Copiar ruta")
        menu.addSeparator()
        locate_action = menu.addAction("Localizar en el mapa")
        zoom_action = menu.addAction("Abrir en el mapa") if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE) else None
        menu.addSeparator()
        trash_action = menu.addAction("Mover a la Papelera…")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(position))
        if chosen is open_action:
            self._open_node(node)
        elif chosen is reveal_action:
            self._reveal_node(node)
        elif chosen is copy_action:
            self._copy_node(node)
        elif chosen is locate_action:
            self._locate_node(node)
        elif zoom_action is not None and chosen is zoom_action:
            self._zoom_node(node)
        elif chosen is trash_action:
            self._confirm_trash(node)

    # ---------------------------------------------------------------- dialogs
    def _show_grouped(self, nodes: list[FileNode]) -> None:
        if not nodes or self._snapshot is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Elementos agrupados")
        dialog.resize(680, 460)
        layout = QVBoxLayout(dialog)
        label = QLabel(
            "Estos elementos no tienen una ficha individual en el tamaño actual del mapa. "
            "Sus tamaños siguen sumando en los totales."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        listing = QListWidget()
        listing.setAlternatingRowColors(True)
        ordered = sorted(nodes, key=lambda item: -self._snapshot.size_of(item))
        for item in ordered:
            row = QListWidgetItem(
                f"{item.name} — {human_size(self._snapshot.size_of(item))} — {item.path()}"
            )
            row.setData(Qt.UserRole, item)
            listing.addItem(row)
        layout.addWidget(listing, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        locate = buttons.addButton("Localizar", QDialogButtonBox.ActionRole)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        locate.clicked.connect(dialog.accept)
        layout.addWidget(buttons)

        def locate_current() -> None:
            current = listing.currentItem()
            if current is not None:
                target = current.data(Qt.UserRole)
                if isinstance(target, FileNode):
                    QTimer.singleShot(0, lambda: self._locate_node(target))

        listing.itemDoubleClicked.connect(lambda _item: (locate_current(), dialog.accept()))
        locate.clicked.connect(locate_current)
        dialog.exec()

    def _show_error_details(self) -> None:
        if self._scan_result is None:
            return
        result = self._scan_result
        lines = [
            f"Errores registrados: {result.stats.error_count}",
            f"Volúmenes omitidos: {result.stats.skipped_mounts}",
            "",
        ]
        for error in result.errors:
            lines.append(error.path)
            lines.append(f"    {error.message}")
            lines.append("")
        if result.stats.error_count > len(result.errors):
            lines.append(
                f"… y {result.stats.error_count - len(result.errors)} errores más no listados."
            )
        lines.extend([
            "",
            "La aplicación no elude permisos del sistema. Para zonas protegidas, "
            "macOS puede requerir Acceso Total al Disco en Ajustes del Sistema.",
        ])
        dialog = QDialog(self)
        dialog.setWindowTitle("Elementos no analizados")
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n".join(lines))
        text.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _show_banner(self, text: str, details_callback=None) -> None:
        self._banner_label.setText(text)
        self._banner_details_callback = details_callback
        self._banner_details.setVisible(details_callback is not None)
        self._banner.show()

    def _hide_banner(self) -> None:
        self._banner.hide()
        self._banner_details_callback = None

    def _banner_show_details(self) -> None:
        if callable(self._banner_details_callback):
            self._banner_details_callback()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"Acerca de {APP_NAME}",
            f"<b>{APP_NAME} {__version__}</b><br><br>"
            "Analizador de espacio en disco para macOS con treemap squarified.<br>"
            "Funciona completamente en local: no envía rutas, archivos ni estadísticas "
            "a ningún servicio.<br><br>"
            "macOS 13 o posterior · PySide6 · QPainter<br><br>"
            "El tamaño lógico no equivale necesariamente al espacio recuperable. "
            "Clones APFS, snapshots, compresión y enlaces compartidos pueden alterar "
            "la estimación.",
        )

    # ------------------------------------------------------------------ state
    def _update_actions(self) -> None:
        scanning = self._scanning or self._scan_controller.is_running()
        has_scan = self._scan_result is not None
        node = self._selected_node
        has_node = node is not None
        self.action_analyze.setEnabled(not scanning)
        self.action_rescan.setEnabled(has_scan and not scanning)
        self.action_cancel.setEnabled(scanning)
        self.action_back.setEnabled(has_scan and bool(self._nav_back))
        self.action_forward.setEnabled(has_scan and bool(self._nav_forward))
        self.action_up.setEnabled(
            has_scan and self._view_root is not None and self._view_root.parent is not None
        )
        self.action_home.setEnabled(has_scan and self._view_root is not None)
        self.action_open.setEnabled(has_node)
        self.action_reveal.setEnabled(has_node)
        self.action_copy.setEnabled(has_node)
        self.action_locate.setEnabled(has_node and self._snapshot is not None)
        self.action_zoom.setEnabled(
            has_node and node is not None and node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE)
        )
        self.action_trash.setEnabled(
            has_node and node is not None and node.parent is not None
            and node.kind is not NodeKind.SKIPPED_MOUNT
        )
    def _sync_actions(self) -> None:
        self._update_actions()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_state()
        if self._scan_controller.is_running():
            self._scan_controller.shutdown(3000)
        event.accept()

    def _save_state(self) -> None:
        self.settings.show_hidden = self._filter_bar.state().show_hidden
        self.settings.show_zero = self._filter_bar.state().show_zero
        self.settings.min_tile_area = self._filter_bar.state().min_tile_area
        self.settings.view_mode = self._current_view_mode
        self.settings.top_n = self._largest.top_n
        self.settings.details_visible = not self._details.isHidden()
        self.settings.filters_visible = not self._filter_bar.isHidden()
        self.settings.save_window_geometry(self.saveGeometry())
        self.settings.save_window_state(self.saveState())
        self.settings.save_splitter_state(self._splitter.saveState())
        self.settings.sync()
