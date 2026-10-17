"""Panel lateral de detalles del elemento seleccionado."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..formatting import (
    format_mtime,
    format_percent,
    human_size,
    kind_label,
)
from ..models.categories import CATEGORY_LABELS
from ..models.file_node import FileNode, METRIC_LABELS, NodeKind, SizeMetric
from ..services.filter_engine import FilterSnapshot
from ..theme import ThemePalette


class DetailsPanel(QFrame):
    openRequested = Signal(object)
    revealRequested = Signal(object)
    copyRequested = Signal(object)
    trashRequested = Signal(object)
    groupedRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DetailsPanel")
        self.setMinimumWidth(270)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._theme: ThemePalette | None = None
        self._node: FileNode | None = None
        self._aggregate: list[FileNode] = []
        self._snapshot: FilterSnapshot | None = None
        self._metric = SizeMetric.LOGICAL
        self._volume_total: int | None = None
        self._volume_free: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(14, 14, 14, 14)
        self._layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(9)
        self._swatch = QFrame()
        self._swatch.setFixedSize(6, 38)
        self._swatch.setStyleSheet("border-radius: 3px; background: #8A94A6;")
        header.addWidget(self._swatch)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self._title = QLabel("Sin selección")
        self._title.setObjectName("DetailsTitle")
        self._title.setTextFormat(Qt.PlainText)
        self._title.setWordWrap(True)
        self._subtitle = QLabel("Selecciona un elemento del mapa, el árbol o la lista.")
        self._subtitle.setObjectName("Muted")
        self._subtitle.setWordWrap(True)
        self._subtitle.setTextFormat(Qt.PlainText)
        titles.addWidget(self._title)
        titles.addWidget(self._subtitle)
        header.addLayout(titles, 1)
        self._layout.addLayout(header)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self._path = QLineEdit()
        self._path.setReadOnly(True)
        self._path.setPlaceholderText("Ruta absoluta")
        self._path.setAccessibleName("Ruta del elemento seleccionado")
        path_row.addWidget(self._path, 1)
        self._copy_button = QPushButton("Copiar")
        self._copy_button.setToolTip("Copiar la ruta absoluta (⌘⇧C)")
        self._copy_button.setAccessibleName("Copiar ruta")
        self._copy_button.clicked.connect(self._emit_copy)
        path_row.addWidget(self._copy_button)
        self._layout.addLayout(path_row)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._open_button = QPushButton("Abrir")
        self._open_button.setToolTip("Abrir el archivo con su aplicación predeterminada (⌘↵)")
        self._open_button.clicked.connect(self._emit_open)
        self._reveal_button = QPushButton("Finder")
        self._reveal_button.setToolTip("Mostrar en Finder (⌘⇧R)")
        self._reveal_button.clicked.connect(self._emit_reveal)
        actions.addWidget(self._open_button)
        actions.addWidget(self._reveal_button)
        actions.addStretch(1)
        self._layout.addLayout(actions)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("color: rgba(128,128,128,0.25);")
        self._layout.addWidget(separator)

        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(7)
        self._grid.setColumnStretch(1, 1)
        self._layout.addLayout(self._grid)

        self._group_button = QPushButton("Ver elementos agrupados…")
        self._group_button.clicked.connect(self._emit_grouped)
        self._group_button.hide()
        self._layout.addWidget(self._group_button)

        self._trash_button = QPushButton("Mover a la Papelera…")
        self._trash_button.setToolTip("Enviar a la Papelera de macOS tras confirmar")
        self._trash_button.clicked.connect(self._emit_trash)
        self._layout.addWidget(self._trash_button)

        self._note = QLabel(
            "El tamaño lógico no es necesariamente el espacio que macOS liberará. "
            "Clones APFS, snapshots, compresión y enlaces compartidos alteran la estimación."
        )
        self._note.setObjectName("Muted")
        self._note.setWordWrap(True)
        self._note.setContentsMargins(0, 4, 0, 0)
        self._layout.addWidget(self._note)
        self._layout.addStretch(1)

        self.clear()

    # ------------------------------------------------------------------ public
    def set_theme(self, theme: ThemePalette) -> None:
        self._theme = theme
        self._trash_button.setStyleSheet(f"color: {theme.error.name()};")
        self._refresh_swatch()

    def set_volume_info(self, total: int | None, free: int | None) -> None:
        self._volume_total = total
        self._volume_free = free

    def set_node(self, node: FileNode, snapshot: FilterSnapshot, metric: SizeMetric) -> None:
        self._node = node
        self._aggregate = []
        self._snapshot = snapshot
        self._metric = metric
        self._group_button.hide()
        self._title.setText(node.name)
        self._subtitle.setText(kind_label(node))
        self._path.setText(node.path())
        self._copy_button.setEnabled(True)
        self._open_button.setEnabled(True)
        self._reveal_button.setEnabled(True)
        self._trash_button.setEnabled(node.parent is not None and node.kind is not NodeKind.SKIPPED_MOUNT)
        self._trash_button.show()
        self._refresh_swatch()
        self._fill_details(node)

    def set_aggregate(self, nodes: list[FileNode], snapshot: FilterSnapshot,
                      metric: SizeMetric) -> None:
        self._node = None
        self._aggregate = list(nodes)
        self._snapshot = snapshot
        self._metric = metric
        self._title.setText(f"Otros ({len(nodes)} elementos)")
        self._subtitle.setText("Elementos agrupados por el umbral de tamaño visible")
        self._path.setText("")
        self._copy_button.setEnabled(False)
        self._open_button.setEnabled(False)
        self._reveal_button.setEnabled(False)
        self._trash_button.setEnabled(False)
        self._trash_button.hide()
        self._group_button.show()
        self._swatch.setStyleSheet("border-radius: 3px; background: #59667A;")
        total = sum(snapshot.size_of(node) for node in nodes)
        self._clear_grid()
        self._add_row("Tamaño", human_size(total))
        self._add_row("Elementos", f"{len(nodes):,}".replace(",", "."))
        self._add_row("Total visible", human_size(snapshot.total_bytes))
        self._add_row("Porcentaje", format_percent(total, snapshot.total_bytes))

    def clear(self) -> None:
        self._node = None
        self._aggregate = []
        self._snapshot = None
        self._title.setText("Sin selección")
        self._subtitle.setText("Selecciona un elemento del mapa, el árbol o la lista.")
        self._path.clear()
        self._copy_button.setEnabled(False)
        self._open_button.setEnabled(False)
        self._reveal_button.setEnabled(False)
        self._trash_button.setEnabled(False)
        self._trash_button.show()
        self._group_button.hide()
        self._swatch.setStyleSheet("border-radius: 3px; background: #8A94A6;")
        self._clear_grid()
        self._add_row("", "—")

    # ------------------------------------------------------------------ private
    def _refresh_swatch(self) -> None:
        if self._theme is None:
            return
        if self._node is not None:
            color = (
                self._theme.directory
                if self._node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE)
                else self._theme.category_color(self._node.category)
            )
            self._swatch.setStyleSheet(f"border-radius: 3px; background: {color.name()};")

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_row(self, label: str, value: str) -> None:
        key = QLabel(label)
        key.setObjectName("Muted")
        val = QLabel(value)
        val.setWordWrap(True)
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row = self._grid.rowCount()
        self._grid.addWidget(key, row, 0, Qt.AlignTop)
        self._grid.addWidget(val, row, 1, Qt.AlignTop)

    def _fill_details(self, node: FileNode) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            return
        self._clear_grid()
        self._add_row("Base de cálculo", METRIC_LABELS[self._metric])
        self._add_row("Tamaño lógico", human_size(node.total_logical))
        if node.kind not in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            self._add_row("Bytes", f"{node.logical_size:,}".replace(",", "."))
        self._add_row("Espacio asignado (est.)", human_size(node.total_allocated))
        self._add_row("Asignado único (est.)", human_size(node.total_unique_allocated))
        if snapshot.is_filtered:
            self._add_row("Total analizado", human_size(snapshot.root.display_size(self._metric) if snapshot.root else 0))
            self._add_row("Total visible", human_size(snapshot.total_bytes))
        self._add_row(
            "% del total analizado",
            format_percent(
                snapshot.size_of(node),
                snapshot.root.display_size(self._metric) if snapshot.root else 0,
            ),
        )
        if snapshot.is_filtered:
            self._add_row(
                "% de lo visible",
                format_percent(snapshot.size_of(node), snapshot.total_bytes),
            )
        if (
            snapshot.is_filtered
            and node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE)
            and snapshot.size_of(node) != node.display_size(self._metric)
        ):
            self._add_row("Tamaño completo", human_size(node.display_size(self._metric)))
            self._add_row("Elementos totales", f"{node.total_elements:,}".replace(",", "."))
        if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            self._add_row("Archivos", f"{node.total_files:,}".replace(",", "."))
            self._add_row("Subdirectorios", f"{node.total_dirs:,}".replace(",", "."))
            self._add_row("Elementos visibles", f"{snapshot.element_count(node):,}".replace(",", "."))
        if node.kind is NodeKind.PACKAGE:
            self._add_row("Paquete", "Sí (contenido analizado)")
        self._add_row("Categoría", CATEGORY_LABELS.get(node.category, "Otros"))
        self._add_row("Extensión", f".{node.ext}" if node.ext else "—")
        self._add_row("Modificado", format_mtime(node.mtime_ns))
        if node.nlink > 1 and node.kind is NodeKind.FILE:
            self._add_row("Enlaces duros", str(node.nlink))
            if node.is_hardlink_duplicate:
                self._add_row("Nota", "Enlace adicional; el asignado único se cuenta una vez.")
        if node.kind is NodeKind.SYMLINK:
            self._add_row("Enlace simbólico", "No se sigue; se mide el enlace.")
        if node.total_errors:
            self._add_row("Errores en el subárbol", f"{node.total_errors:,}".replace(",", "."))
        if snapshot.root is not None and node is snapshot.root:
            if self._volume_total is not None:
                self._add_row("Volumen total", human_size(self._volume_total))
            if self._volume_free is not None:
                self._add_row("Disponible en el volumen", human_size(self._volume_free))

    def _emit_open(self) -> None:
        if self._node is not None:
            self.openRequested.emit(self._node)

    def _emit_reveal(self) -> None:
        if self._node is not None:
            self.revealRequested.emit(self._node)

    def _emit_copy(self) -> None:
        if self._node is not None:
            self.copyRequested.emit(self._node)

    def _emit_trash(self) -> None:
        if self._node is not None:
            self.trashRequested.emit(self._node)

    def _emit_grouped(self) -> None:
        if self._aggregate:
            self.groupedRequested.emit(list(self._aggregate))
