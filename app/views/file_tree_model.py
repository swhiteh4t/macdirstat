"""Modelo Qt de árbol para explorar los resultados."""

from __future__ import annotations

import html

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QObject, Qt
from PySide6.QtGui import QColor

from ..formatting import (
    format_mtime,
    format_percent,
    human_size,
    type_label,
)
from ..models.categories import CATEGORY_LABELS
from ..models.file_node import FileNode, METRIC_LABELS, NodeKind, SizeMetric
from ..services.filter_engine import FilterSnapshot


class FileTreeModel(QAbstractItemModel):
    COL_NAME = 0
    COL_TYPE = 1
    COL_CATEGORY = 2
    COL_SIZE = 3
    COL_PERCENT = 4
    COL_ELEMENTS = 5
    COL_MTIME = 6
    COL_PATH = 7
    COLUMN_COUNT = 8

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._snapshot: FilterSnapshot | None = None
        self._metric = SizeMetric.LOGICAL
        self._sort_column = self.COL_SIZE
        self._sort_order = Qt.DescendingOrder
        self._children_cache: dict[int, list[FileNode]] = {}

    @property
    def snapshot(self) -> FilterSnapshot | None:
        return self._snapshot

    def set_snapshot(self, snapshot: FilterSnapshot | None, metric: SizeMetric) -> None:
        self.beginResetModel()
        self._snapshot = snapshot
        self._metric = metric
        self._children_cache.clear()
        self.endResetModel()

    def set_metric(self, metric: SizeMetric) -> None:
        if metric is self._metric:
            return
        self._metric = metric
        self._children_cache.clear()
        if self._snapshot is not None:
            self.headerDataChanged.emit(Qt.Horizontal, self.COL_SIZE, self.COL_PERCENT)
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(0, self.COLUMN_COUNT - 1),
            )

    def set_sort(self, column: int, order: Qt.SortOrder) -> None:
        if column < 0 or column >= self.COLUMN_COUNT:
            return
        self._sort_column = column
        self._sort_order = order
        self._children_cache.clear()
        self.layoutAboutToBeChanged.emit()
        self.layoutChanged.emit()

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:  # noqa: N802
        self.set_sort(column, order)

    def index_for_node(self, node: FileNode | None) -> QModelIndex:
        if node is None or self._snapshot is None or self._snapshot.root is None:
            return QModelIndex()
        if not self._snapshot.is_visible(node):
            return QModelIndex()
        root = self._snapshot.root
        if node is root:
            return self.createIndex(0, 0, root)
        chain: list[FileNode] = []
        current: FileNode | None = node
        while current is not None and current is not root:
            chain.append(current)
            current = current.parent
        if current is not root:
            return QModelIndex()
        parent_index = self.createIndex(0, 0, root)
        for child in reversed(chain):
            parent_node = parent_index.internalPointer()
            siblings = self._sorted_children(parent_node)
            row = -1
            for index, sibling in enumerate(siblings):
                if sibling is child:
                    row = index
                    break
            if row < 0:
                return QModelIndex()
            parent_index = self.createIndex(row, 0, child)
        return self.createIndex(parent_index.row(), 0, node)

    def node_at(self, index: QModelIndex) -> FileNode | None:
        if not index.isValid():
            return None
        return index.internalPointer()

    # ---------------------------------------------------------- Qt interface
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if self._snapshot is None or self._snapshot.root is None:
            return 0
        if not parent.isValid():
            return 1
        node = parent.internalPointer()
        if node is None or node.kind not in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            return 0
        return len(self._sorted_children(node))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return self.COLUMN_COUNT

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if self._snapshot is None or self._snapshot.root is None:
            return QModelIndex()
        if column < 0 or column >= self.COLUMN_COUNT or row < 0:
            return QModelIndex()
        if not parent.isValid():
            if row == 0:
                return self.createIndex(0, column, self._snapshot.root)
            return QModelIndex()
        parent_node = parent.internalPointer()
        children = self._sorted_children(parent_node)
        if row >= len(children):
            return QModelIndex()
        return self.createIndex(row, column, children[row])

    def parent(self, index: QModelIndex) -> QModelIndex:  # noqa: N802
        if not index.isValid() or self._snapshot is None:
            return QModelIndex()
        node = index.internalPointer()
        if node is None or node is self._snapshot.root or node.parent is None:
            return QModelIndex()
        # El índice del padre es el de su propio nodo entre sus hermanos.
        return self.index_for_node(node.parent)

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:  # noqa: N802
        return self.rowCount(parent) > 0

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or self._snapshot is None:
            return None
        node: FileNode = index.internalPointer()
        if node is None:
            return None
        column = index.column()
        if role == Qt.DisplayRole:
            if column == self.COL_NAME:
                return node.name
            if column == self.COL_TYPE:
                return type_label(node)
            if column == self.COL_CATEGORY:
                return CATEGORY_LABELS.get(node.category, "Otros")
            if column == self.COL_SIZE:
                return human_size(self._snapshot.size_of(node))
            if column == self.COL_PERCENT:
                return format_percent(self._snapshot.size_of(node), self._snapshot.total_bytes)
            if column == self.COL_ELEMENTS:
                if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
                    return f"{self._snapshot.element_count(node):,}".replace(",", ".")
                return ""
            if column == self.COL_MTIME:
                return format_mtime(node.mtime_ns)
            if column == self.COL_PATH:
                return node.path()
        if role == Qt.TextAlignmentRole:
            if column in (self.COL_SIZE, self.COL_PERCENT, self.COL_ELEMENTS):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            label = node.name
            extra = ""
            if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
                extra = (
                    f"<br>{self._snapshot.element_count(node)} elementos visibles"
                )
            return (
                f"<b>{html.escape(label)}</b>{extra}"
                f"<br>{html.escape(node.path())}"
                f"<br>{html.escape(human_size(self._snapshot.size_of(node)))}"
            )
        if role == Qt.UserRole:
            return node
        if role == Qt.ForegroundRole:
            if node.kind is NodeKind.SKIPPED_MOUNT:
                return QColor("#8A8F98")
            if node.is_hidden:
                color = QColor("#7A828E")
                return color
        return None

    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: N802
                   role: int = Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            if role == Qt.DisplayRole:
                return section + 1
            return None
        if role == Qt.DisplayRole:
            if section == self.COL_NAME:
                return "Nombre"
            if section == self.COL_TYPE:
                return "Tipo"
            if section == self.COL_CATEGORY:
                return "Categoría"
            if section == self.COL_SIZE:
                return METRIC_LABELS[self._metric]
            if section == self.COL_PERCENT:
                return "% visible" if self._snapshot is not None and self._snapshot.is_filtered else "% total"
            if section == self.COL_ELEMENTS:
                return "Elementos"
            if section == self.COL_MTIME:
                return "Modificado"
            if section == self.COL_PATH:
                return "Ruta"
        if role == Qt.TextAlignmentRole and section in (
            self.COL_SIZE, self.COL_PERCENT, self.COL_ELEMENTS
        ):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    # ---------------------------------------------------------------- helpers
    def _sorted_children(self, node: FileNode | None) -> list[FileNode]:
        if node is None or self._snapshot is None:
            return []
        cached = self._children_cache.get(id(node))
        if cached is not None:
            return cached
        children = self._snapshot.visible_children(node)
        if node is self._snapshot.root:
            # La raíz ya es la fila superior; sus hijos son filas hijas.
            pass
        reverse = self._sort_order == Qt.DescendingOrder
        column = self._sort_column

        def key(child: FileNode):
            if column == self.COL_NAME:
                primary = child.name.casefold()
            elif column == self.COL_TYPE:
                primary = type_label(child).casefold()
            elif column == self.COL_CATEGORY:
                primary = CATEGORY_LABELS.get(child.category, "").casefold()
            elif column in (self.COL_SIZE, self.COL_PERCENT):
                primary = self._snapshot.size_of(child)
            elif column == self.COL_ELEMENTS:
                primary = self._snapshot.element_count(child)
            elif column == self.COL_MTIME:
                primary = child.mtime_ns
            elif column == self.COL_PATH:
                primary = child.path().casefold()
            else:
                primary = self._snapshot.size_of(child)
            return (primary, child.name.casefold())

        children.sort(key=key, reverse=reverse)
        self._children_cache[id(node)] = children
        return children

    def refresh(self) -> None:
        self._children_cache.clear()
        if self._snapshot is not None:
            self.beginResetModel()
            self.endResetModel()
