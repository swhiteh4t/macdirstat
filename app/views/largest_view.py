"""Vista de mayores consumidores de espacio."""

from __future__ import annotations

import html

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..formatting import format_mtime, format_percent, human_size, type_label
from ..models.file_node import FileNode, METRIC_LABELS, NodeKind, SizeMetric
from ..services.filter_engine import FilterSnapshot


class LargestTableModel(QAbstractTableModel):
    COL_NAME = 0
    COL_TYPE = 1
    COL_SIZE = 2
    COL_PERCENT = 3
    COL_MTIME = 4
    COL_PATH = 5
    COLUMNS = 6

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._snapshot: FilterSnapshot | None = None
        self._metric = SizeMetric.LOGICAL
        self._rows: list[FileNode] = []
        self._sort_column = self.COL_SIZE
        self._sort_order = Qt.DescendingOrder

    def set_data(self, snapshot: FilterSnapshot | None, metric: SizeMetric,
                 rows: list[FileNode]) -> None:
        self.beginResetModel()
        self._snapshot = snapshot
        self._metric = metric
        self._rows = list(rows)
        self._sort_rows()
        self.endResetModel()

    def set_rows(self, rows: list[FileNode]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._sort_rows()
        self.endResetModel()

    def rows(self) -> list[FileNode]:
        return list(self._rows)

    def node_at(self, row: int) -> FileNode | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def row_for_node(self, node: FileNode) -> int:
        for row, candidate in enumerate(self._rows):
            if candidate is node:
                return row
        return -1

    # ----------------------------------------------------------- Qt interface
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return self.COLUMNS

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or self._snapshot is None:
            return None
        node = self._rows[index.row()]
        column = index.column()
        if role == Qt.DisplayRole:
            if column == self.COL_NAME:
                return node.name
            if column == self.COL_TYPE:
                return type_label(node)
            if column == self.COL_SIZE:
                return human_size(self._snapshot.size_of(node))
            if column == self.COL_PERCENT:
                return format_percent(self._snapshot.size_of(node), self._snapshot.total_bytes)
            if column == self.COL_MTIME:
                return format_mtime(node.mtime_ns)
            if column == self.COL_PATH:
                return node.path()
        if role == Qt.TextAlignmentRole:
            if column in (self.COL_SIZE, self.COL_PERCENT):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            return f"<b>{html.escape(node.name)}</b><br>{html.escape(node.path())}"
        if role == Qt.UserRole:
            return node
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: N802
                   role: int = Qt.DisplayRole):
        if orientation != Qt.Horizontal or role != Qt.DisplayRole:
            return None
        labels = {
            self.COL_NAME: "Nombre",
            self.COL_TYPE: "Tipo",
            self.COL_SIZE: METRIC_LABELS[self._metric],
            self.COL_PERCENT: "% visible" if self._snapshot and self._snapshot.is_filtered else "% total",
            self.COL_MTIME: "Modificado",
            self.COL_PATH: "Ruta",
        }
        return labels.get(section)

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:  # noqa: N802
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        self._sort_rows()
        self.layoutChanged.emit()

    def _sort_rows(self) -> None:
        if self._snapshot is None:
            return
        column = self._sort_column
        reverse = self._sort_order == Qt.DescendingOrder

        def key(node: FileNode):
            if column == self.COL_NAME:
                primary = node.name.casefold()
            elif column == self.COL_TYPE:
                primary = type_label(node).casefold()
            elif column == self.COL_SIZE:
                primary = self._snapshot.size_of(node)
            elif column == self.COL_PERCENT:
                primary = self._snapshot.size_of(node)
            elif column == self.COL_MTIME:
                primary = node.mtime_ns
            else:
                primary = node.path().casefold()
            return (primary, node.name.casefold())

        self._rows.sort(key=key, reverse=reverse)


class LargestView(QWidget):
    nodeSelected = Signal(object)
    nodeActivated = Signal(object)
    openRequested = Signal(object)
    revealRequested = Signal(object)
    copyRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot: FilterSnapshot | None = None
        self._metric = SizeMetric.LOGICAL
        self._top_n = 100
        self._kind = "files"
        self._theme = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(8)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("Mostrar"))
        self._count_combo = QComboBox()
        for value in (20, 50, 100, 500):
            self._count_combo.addItem(str(value), value)
        self._count_combo.setCurrentIndex(2)
        controls.addWidget(self._count_combo)
        self._kind_combo = QComboBox()
        self._kind_combo.addItem("Archivos", "files")
        self._kind_combo.addItem("Directorios", "dirs")
        self._kind_combo.addItem("Ambos", "both")
        controls.addWidget(self._kind_combo)
        controls.addStretch(1)
        self._count_label = QLabel("")
        self._count_label.setObjectName("Muted")
        controls.addWidget(self._count_label)
        self._locate_button = QPushButton("Localizar en el mapa")
        self._open_button = QPushButton("Abrir")
        self._reveal_button = QPushButton("Finder")
        controls.addWidget(self._locate_button)
        controls.addWidget(self._open_button)
        controls.addWidget(self._reveal_button)
        layout.addLayout(controls)

        self._model = LargestTableModel(self)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setSelectionMode(QTableView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setWordWrap(False)
        self._table.setTextElideMode(Qt.ElideMiddle)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(LargestTableModel.COL_NAME, QHeaderView.Interactive)
        header.setSectionResizeMode(LargestTableModel.COL_TYPE, QHeaderView.Interactive)
        header.setSectionResizeMode(LargestTableModel.COL_SIZE, QHeaderView.Interactive)
        header.setSectionResizeMode(LargestTableModel.COL_PERCENT, QHeaderView.Interactive)
        header.setSectionResizeMode(LargestTableModel.COL_MTIME, QHeaderView.Interactive)
        header.setSectionResizeMode(LargestTableModel.COL_PATH, QHeaderView.Stretch)
        self._table.setColumnWidth(LargestTableModel.COL_NAME, 220)
        self._table.setColumnWidth(LargestTableModel.COL_TYPE, 120)
        self._table.setColumnWidth(LargestTableModel.COL_SIZE, 110)
        self._table.setColumnWidth(LargestTableModel.COL_PERCENT, 80)
        self._table.setColumnWidth(LargestTableModel.COL_MTIME, 145)
        self._table.setAccessibleName("Mayores consumidores de espacio")
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.selectionModel().currentRowChanged.connect(self._on_current_changed)
        layout.addWidget(self._table, 1)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(LargestTableModel.COL_SIZE, Qt.DescendingOrder)

        self._count_combo.currentIndexChanged.connect(self._refresh)
        self._kind_combo.currentIndexChanged.connect(self._refresh)
        self._locate_button.clicked.connect(self._locate_current)
        self._open_button.clicked.connect(self._open_current)
        self._reveal_button.clicked.connect(self._reveal_current)
        self._update_actions()

    @property
    def top_n(self) -> int:
        return int(self._count_combo.currentData() or self._top_n)

    def set_theme(self, theme) -> None:
        self._theme = theme

    def set_snapshot(self, snapshot: FilterSnapshot | None, metric: SizeMetric,
                     top_n: int | None = None) -> None:
        self._snapshot = snapshot
        self._metric = metric
        if top_n is not None:
            self._top_n = top_n
            index = self._count_combo.findData(top_n)
            if index >= 0 and index != self._count_combo.currentIndex():
                self._count_combo.blockSignals(True)
                self._count_combo.setCurrentIndex(index)
                self._count_combo.blockSignals(False)
        self._refresh()

    def _refresh(self) -> None:
        if self._snapshot is None:
            self._model.set_data(None, self._metric, [])
            self._count_label.setText("")
            self._update_actions()
            return
        top_n = int(self._count_combo.currentData() or self._top_n)
        self._top_n = top_n
        kind = str(self._kind_combo.currentData())
        self._kind = kind
        if kind == "files":
            nodes = self._snapshot.largest_files[:top_n]
        elif kind == "dirs":
            nodes = self._snapshot.largest_dirs[:top_n]
        else:
            combined = list(self._snapshot.largest_files) + list(self._snapshot.largest_dirs)
            combined.sort(key=lambda n: (-self._snapshot.size_of(n), n.name.casefold()))
            nodes = combined[:top_n]
        self._model.set_data(self._snapshot, self._metric, nodes)
        self._table.sortByColumn(self._model._sort_column, self._model._sort_order)
        total = len(nodes)
        self._count_label.setText(f"{total} resultados")
        self._update_actions()

    def _current_node(self) -> FileNode | None:
        index = self._table.currentIndex()
        if not index.isValid():
            return None
        return self._model.node_at(index.row())

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        node = self._model.node_at(current.row()) if current.isValid() else None
        self.nodeSelected.emit(node)
        self._update_actions()

    def _on_double_click(self, index: QModelIndex) -> None:
        node = self._model.node_at(index.row())
        if node is not None:
            self.nodeActivated.emit(node)

    def _update_actions(self) -> None:
        has = self._current_node() is not None
        self._locate_button.setEnabled(has)
        self._open_button.setEnabled(has)
        self._reveal_button.setEnabled(has)

    def _locate_current(self) -> None:
        node = self._current_node()
        if node is not None:
            self.nodeActivated.emit(node)

    def _open_current(self) -> None:
        node = self._current_node()
        if node is not None:
            self.openRequested.emit(node)

    def _reveal_current(self) -> None:
        node = self._current_node()
        if node is not None:
            self.revealRequested.emit(node)

    def select_node(self, node: FileNode | None) -> None:
        if node is None:
            self._table.clearSelection()
            return
        row = self._model.row_for_node(node)
        if row >= 0:
            index = self._model.index(row, 0)
            self._table.setCurrentIndex(index)
            self._table.scrollTo(index, QTableView.PositionAtCenter)

    def _context_menu(self, position: QPoint) -> None:
        index = self._table.indexAt(position)
        if not index.isValid():
            return
        self._table.setCurrentIndex(index)
        node = self._model.node_at(index.row())
        if node is None:
            return
        menu = QMenu(self)
        locate = QAction("Localizar en el mapa", menu)
        locate.triggered.connect(self._locate_current)
        open_action = QAction("Abrir", menu)
        open_action.triggered.connect(self._open_current)
        reveal_action = QAction("Mostrar en Finder", menu)
        reveal_action.triggered.connect(self._reveal_current)
        copy_action = QAction("Copiar ruta", menu)
        copy_action.triggered.connect(lambda: self.copyRequested.emit(node))
        menu.addAction(locate)
        menu.addAction(open_action)
        menu.addAction(reveal_action)
        menu.addSeparator()
        menu.addAction(copy_action)
        menu.exec(self._table.viewport().mapToGlobal(position))
