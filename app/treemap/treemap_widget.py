"""Widget de treemap: dibujo con QPainter, hit-testing y navegación."""

from __future__ import annotations

import html
import math
from dataclasses import dataclass

from PySide6.QtCore import (
    QObject,
    QPoint,
    QPointF,
    QRectF,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..formatting import human_size, kind_label
from ..models.categories import CATEGORY_LABELS
from ..models.file_node import FileNode, NodeKind, SizeMetric
from ..services.filter_engine import FilterSnapshot
from ..theme import ThemePalette
from .layout_engine import (
    LayoutRequest,
    LayoutResult,
    Rect,
    Tile,
    TreemapLayoutEngine,
    TreemapMode,
)


class _LayoutSignals(QObject):
    done = Signal(int, object)


class _LayoutTask(QRunnable):
    def __init__(self, generation: int, request: LayoutRequest, signals: _LayoutSignals) -> None:
        super().__init__()
        self.generation = generation
        self.request = request
        self.signals = signals

    def run(self) -> None:
        try:
            result = TreemapLayoutEngine().layout(self.request)
        except Exception:  # noqa: BLE001 - nunca debe tumbar el hilo gráfico
            result = None
        self.signals.done.emit(self.generation, result)


@dataclass(frozen=True, slots=True)
class _CacheKey:
    snapshot_revision: int
    root_id: int
    metric: SizeMetric
    mode: TreemapMode
    min_area: float
    width: int
    height: int


class TreemapWidget(QWidget):
    nodeSelected = Signal(object)          # FileNode | None
    nodeActivated = Signal(object)         # FileNode
    aggregateSelected = Signal(object)     # list[FileNode]
    aggregateActivated = Signal(object)    # list[FileNode]
    zoomRequested = Signal(object)         # FileNode directorio
    openRequested = Signal(object)         # FileNode archivo
    contextMenuRequested = Signal(object, QPoint)
    aggregateContextRequested = Signal(object, QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot: FilterSnapshot | None = None
        self._metric = SizeMetric.LOGICAL
        self._view_root: FileNode | None = None
        self._mode = TreemapMode.CHILDREN
        self._min_tile_area = 6.0
        self._theme: ThemePalette | None = None
        self._layout: LayoutResult | None = None
        self._cache_key: _CacheKey | None = None
        self._generation = 0
        self._selected_node: FileNode | None = None
        self._selected_tile: Tile | None = None
        self._hover_tile: Tile | None = None
        self._pending_select_node: FileNode | None = None
        self._layout_error = False
        self._tasks: dict[int, tuple[_LayoutTask, _LayoutSignals]] = {}
        self._engine = TreemapLayoutEngine()

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(240, 180)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(30)
        self._resize_timer.timeout.connect(self._compute_layout)

    # ------------------------------------------------------------------ API
    @property
    def snapshot(self) -> FilterSnapshot | None:
        return self._snapshot

    @property
    def view_root(self) -> FileNode | None:
        return self._view_root

    @property
    def mode(self) -> TreemapMode:
        return self._mode

    @property
    def layout_result(self) -> LayoutResult | None:
        return self._layout

    @property
    def selected_node(self) -> FileNode | None:
        return self._selected_node

    def set_theme(self, theme: ThemePalette) -> None:
        self._theme = theme
        self.update()

    def set_snapshot(self, snapshot: FilterSnapshot | None) -> None:
        self._snapshot = snapshot
        if snapshot is not None:
            root = self._view_root
            if root is None or not snapshot.is_visible(root):
                self._view_root = snapshot.root
        else:
            self._view_root = None
        self._clear_layout_and_schedule()

    def set_metric(self, metric: SizeMetric) -> None:
        if metric is self._metric:
            return
        self._metric = metric
        self._clear_layout_and_schedule()

    def set_mode(self, mode: TreemapMode) -> None:
        if mode is self._mode:
            return
        self._mode = mode
        self._clear_layout_and_schedule()

    def set_min_tile_area(self, area: float) -> None:
        area = max(0.0, float(area))
        if area == self._min_tile_area:
            return
        self._min_tile_area = area
        self._clear_layout_and_schedule()

    def set_view_root(self, node: FileNode | None) -> None:
        if node is not None and self._snapshot is not None and not self._snapshot.is_visible(node):
            node = None
        if node is not None and node.kind not in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            node = node.parent
        self._view_root = node
        self._hover_tile = None
        self._clear_layout_and_schedule()

    def select_node(self, node: FileNode | None) -> bool:
        self._selected_node = node
        self._selected_tile = None
        self._pending_select_node = node
        if node is not None and self._layout is not None:
            for tile in self._layout.tiles:
                if tile.node is node:
                    self._selected_tile = tile
                    self._pending_select_node = None
                    break
        self.update()
        return self._selected_tile is not None

    def _apply_pending_selection(self) -> None:
        node = self._pending_select_node
        if node is None:
            return
        self._pending_select_node = None
        if self._layout is None:
            return
        for tile in self._layout.tiles:
            if tile.node is node:
                self._selected_tile = tile
                self.update()
                return

    def clear_selection(self) -> None:
        had_selection = self._selected_node is not None or self._selected_tile is not None
        self._selected_node = None
        self._selected_tile = None
        if had_selection:
            self.nodeSelected.emit(None)
        self.update()

    def current_tile(self) -> Tile | None:
        return self._selected_tile

    def refresh_layout(self) -> None:
        self._clear_layout_and_schedule()

    # ------------------------------------------------------------- layout
    def _clear_layout_and_schedule(self) -> None:
        self._layout = None
        self._cache_key = None
        self._selected_tile = None
        self._hover_tile = None
        self._layout_error = False
        self._generation += 1
        self._resize_timer.start()
        self.update()

    def _schedule_layout(self) -> None:
        self._generation += 1
        self._resize_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._generation += 1
        self._resize_timer.start()

    def _cache_key_now(self) -> _CacheKey | None:
        if self._snapshot is None or self._view_root is None:
            return None
        return _CacheKey(
            snapshot_revision=self._snapshot.revision,
            root_id=id(self._view_root),
            metric=self._metric,
            mode=self._mode,
            min_area=self._min_tile_area,
            width=max(1, self.width()),
            height=max(1, self.height()),
        )

    def _compute_layout(self) -> None:
        if self._snapshot is None or self._view_root is None or self.width() <= 0 or self.height() <= 0:
            self._layout = None
            self.update()
            return
        key = self._cache_key_now()
        if key is not None and key == self._cache_key and self._layout is not None:
            self.update()
            return
        request = LayoutRequest(
            root=self._view_root,
            snapshot=self._snapshot,
            rect=Rect(0.0, 0.0, float(self.width()), float(self.height())),
            mode=self._mode,
            min_tile_area=self._min_tile_area,
        )
        self._cache_key = key
        estimated = self._snapshot.total_files + self._snapshot.total_dirs
        if estimated <= 5000:
            self._layout = self._engine.layout(request)
            self._layout_error = False
            self._selected_tile = None
            if self._selected_node is not None:
                for tile in self._layout.tiles:
                    if tile.node is self._selected_node:
                        self._selected_tile = tile
                        break
            self._apply_pending_selection()
            self.update()
            return
        # Subárbol grande: layout fuera del hilo de la interfaz.
        generation = self._generation
        signals = _LayoutSignals()
        task = _LayoutTask(generation, request, signals)
        signals.done.connect(self._on_layout_done)
        self._tasks[generation] = (task, signals)
        self._layout = None
        self._layout_error = False
        self.update()
        QThreadPool.globalInstance().start(task)

    def _on_layout_done(self, generation: int, result: object) -> None:
        self._tasks.pop(generation, None)
        if generation != self._generation:
            return
        if not isinstance(result, LayoutResult):
            self._layout = None
            self._layout_error = True
            self.update()
            return
        self._layout = result
        self._layout_error = False
        self._selected_tile = None
        if self._selected_node is not None:
            for tile in result.tiles:
                if tile.node is self._selected_node:
                    self._selected_tile = tile
                    break
        self._apply_pending_selection()
        self.update()

    # ------------------------------------------------------------- painting
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            self._paint(painter, event)
        finally:
            if painter.isActive():
                painter.end()

    def _paint(self, painter: QPainter, event) -> None:
        theme = self._theme
        background = theme.surface if theme is not None else self.palette().base().color()
        painter.fillRect(self.rect(), background)
        if theme is None:
            return
        if self._snapshot is None or self._view_root is None:
            self._draw_message(painter, "Selecciona una carpeta y pulsa Analizar (⌘O).", theme)
            return
        if self._layout is None:
            message = (
                "No se pudo calcular el mapa. Prueba a cambiar el tamaño de la ventana."
                if self._layout_error
                else "Calculando el mapa…"
            )
            self._draw_message(painter, message, theme)
            return
        if not self._layout.tiles:
            message = (
                "No hay elementos con tamaño positivo que dibujar."
                if self._snapshot.total_bytes == 0
                else "No hay elementos visibles con los filtros actuales."
            )
            self._draw_message(painter, message, theme)
            return
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        clip = QRectF(event.rect())
        for tile in self._layout.tiles:
            rect = QRectF(tile.rect.x, tile.rect.y, tile.rect.w, tile.rect.h)
            if not rect.intersects(clip):
                continue
            self._draw_tile(painter, tile, rect, theme)
        if self._selected_tile is not None:
            self._draw_outline(painter, self._selected_tile, theme.accent, 2.0)
        if self._hover_tile is not None and self._hover_tile is not self._selected_tile:
            self._draw_outline(painter, self._hover_tile, theme.text, 1.0)
        if self._layout.truncated:
            painter.setPen(theme.text)
            painter.setFont(self._small_font())
            painter.drawText(
                QRectF(8, self.height() - 24, self.width() - 16, 18),
                Qt.AlignRight | Qt.AlignVCenter,
                "Mapa simplificado: algunos descendientes no se dibujan.",
            )

    def _small_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(max(8.0, font.pointSizeF() - 2.0))
        return font

    def _draw_message(self, painter: QPainter, text: str, theme: ThemePalette) -> None:
        painter.setPen(theme.muted)
        font = QFont(self.font())
        font.setPointSizeF(max(11.0, font.pointSizeF()))
        painter.setFont(font)
        painter.drawText(
            self.rect().adjusted(28, 28, -28, -28),
            Qt.AlignCenter | Qt.TextWordWrap,
            text,
        )

    def _draw_tile(self, painter: QPainter, tile: Tile, rect: QRectF,
                   theme: ThemePalette) -> None:
        if tile.is_aggregate:
            color = theme.aggregate
            painter.fillRect(rect, color)
            painter.setPen(QPen(theme.border, 1))
            painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
            self._draw_label(painter, tile.label, rect, color, theme)
            return
        node = tile.node
        if node is None:
            return
        if tile.is_directory:
            color = theme.directory
            painter.fillRect(rect, color)
            header = self._header_height(rect)
            if header > 0:
                header_rect = QRectF(rect.x(), rect.y(), rect.width(), header)
                painter.fillRect(header_rect, theme.directory_header)
                self._draw_text_clipped(
                    painter,
                    node.name,
                    header_rect.adjusted(4, 1, -4, -1),
                    ThemePalette.contrasting_text(theme.directory_header),
                    9.5,
                )
            else:
                self._draw_label(painter, node.name, rect, color, theme, padding=3)
            painter.setPen(QPen(theme.directory_header.darker(112), 1))
            painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
            return
        color = theme.category_color(node.category)
        painter.fillRect(rect, color)
        if rect.width() > 2 and rect.height() > 2:
            self._draw_label(painter, node.name, rect, color, theme, padding=3)

    def _draw_label(self, painter: QPainter, text: str, rect: QRectF,
                    color: QColor, theme: ThemePalette, padding: float = 2.0) -> None:
        if rect.width() < 34 or rect.height() < 13:
            return
        inner = rect.adjusted(padding, 1, -padding, -1)
        painter.setPen(ThemePalette.contrasting_text(color))
        self._draw_text_clipped(painter, text, inner, painter.pen().color(), 9.5)

    def _draw_text_clipped(self, painter: QPainter, text: str, rect: QRectF,
                           color: QColor, point_size: float) -> None:
        if rect.width() < 8 or rect.height() < 8:
            return
        font = QFont(self.font())
        font.setPointSizeF(max(7.5, point_size))
        painter.save()
        painter.setClipRect(rect)
        painter.setFont(font)
        painter.setPen(color)
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(text, Qt.ElideMiddle, int(max(0, rect.width())))
        painter.drawText(
            rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            elided,
        )
        painter.restore()

    @staticmethod
    def _header_height(rect: QRectF) -> float:
        if rect.height() >= 34 and rect.width() >= 40:
            return min(18.0, max(11.0, rect.height() * 0.12))
        return 0.0

    def _draw_outline(self, painter: QPainter, tile: Tile,
                      color: QColor, width: float) -> None:
        rect = QRectF(tile.rect.x, tile.rect.y, tile.rect.w, tile.rect.h)
        pen = QPen(color, width)
        pen.setJoinStyle(Qt.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        inset = width / 2.0
        painter.drawRect(rect.adjusted(inset, inset, -inset, -inset))

    # --------------------------------------------------------------- mouse
    def _tile_at(self, position: QPointF) -> Tile | None:
        if self._layout is None:
            return None
        return self._layout.hit_index.hit_test(position.x(), position.y())

    def _select_tile(self, tile: Tile | None) -> None:
        if tile is None:
            self._selected_node = None
            self._selected_tile = None
            self.nodeSelected.emit(None)
            self.update()
            return
        self._selected_tile = tile
        self._selected_node = tile.node
        if tile.is_aggregate:
            self.aggregateSelected.emit(list(tile.grouped))
        else:
            self.nodeSelected.emit(tile.node)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            tile = self._tile_at(event.position())
            self._select_tile(tile)
            self.setFocus()
            event.accept()
            return
        if event.button() == Qt.RightButton:
            tile = self._tile_at(event.position())
            if tile is not None:
                if tile.is_aggregate:
                    self.aggregateContextRequested.emit(list(tile.grouped), event.globalPosition().toPoint())
                elif tile.node is not None:
                    self.contextMenuRequested.emit(tile.node, event.globalPosition().toPoint())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        tile = self._tile_at(event.position())
        if tile is None:
            return
        if tile.is_aggregate:
            self.aggregateActivated.emit(list(tile.grouped))
        elif tile.node is not None:
            if tile.node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
                self.zoomRequested.emit(tile.node)
            else:
                self.openRequested.emit(tile.node)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        tile = self._tile_at(event.position())
        if tile is not self._hover_tile:
            self._hover_tile = tile
            self.setCursor(Qt.PointingHandCursor if tile is not None else Qt.ArrowCursor)
            if tile is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPosition().toPoint(), self._tooltip_html(tile), self)
            self.update()
        event.accept()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_tile = None
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)

    def _tooltip_html(self, tile: Tile) -> str:
        snapshot = self._snapshot
        if snapshot is None:
            return ""
        if tile.is_aggregate:
            count = len(tile.grouped)
            return (
                f"<b>{html.escape(tile.label)}</b><br>"
                f"{count} elementos agrupados<br>"
                f"{html.escape(human_size(tile.size))}<br>"
                "<i>Agrupados por el umbral de tamaño visible; los datos originales no cambian.</i>"
            )
        node = tile.node
        if node is None:
            return ""
        size = snapshot.size_of(node)
        lines = [
            f"<b>{html.escape(node.name)}</b>",
            html.escape(kind_label(node)),
            f"{html.escape(human_size(size))} (métrica actual)",
            html.escape(node.path()),
        ]
        if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            lines.append(
                f"{node.total_files:,} archivos · {node.total_dirs:,} subdirectorios".replace(",", ".")
            )
            if tile.collapsed:
                lines.append("<i>Contenido no dibujado a este tamaño; doble clic para ampliar.</i>")
        if node.kind is NodeKind.SKIPPED_MOUNT:
            lines.append("<i>Volumen no incluido en el análisis.</i>")
        return "<br>".join(lines)

    # ------------------------------------------------------------- keyboard
    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            self._move_selection(key)
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            tile = self._selected_tile
            if tile is not None:
                if tile.is_aggregate:
                    self.aggregateActivated.emit(list(tile.grouped))
                elif tile.node is not None:
                    if tile.node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
                        self.zoomRequested.emit(tile.node)
                    else:
                        self.openRequested.emit(tile.node)
            event.accept()
            return
        if key == Qt.Key_Escape:
            self.clear_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def _move_selection(self, key: int) -> None:
        if self._layout is None or not self._layout.tiles:
            return
        current = self._selected_tile
        if current is None:
            target = max(self._layout.tiles, key=lambda t: t.area)
            self._select_tile(target)
            return
        cx = current.rect.x + current.rect.w / 2
        cy = current.rect.y + current.rect.h / 2
        best: Tile | None = None
        best_score = math.inf
        for tile in self._layout.tiles:
            if tile is current:
                continue
            tx = tile.rect.x + tile.rect.w / 2
            ty = tile.rect.y + tile.rect.h / 2
            dx, dy = tx - cx, ty - cy
            if key == Qt.Key_Left and dx >= 0:
                continue
            if key == Qt.Key_Right and dx <= 0:
                continue
            if key == Qt.Key_Up and dy >= 0:
                continue
            if key == Qt.Key_Down and dy <= 0:
                continue
            primary = abs(dx) if key in (Qt.Key_Left, Qt.Key_Right) else abs(dy)
            secondary = abs(dy) if key in (Qt.Key_Left, Qt.Key_Right) else abs(dx)
            score = primary + secondary * 2.0
            if score < best_score:
                best_score = score
                best = tile
        if best is not None:
            self._select_tile(best)
