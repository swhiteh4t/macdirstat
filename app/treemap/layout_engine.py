"""Motor de layout squarified independiente de Qt."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from ..models.file_node import FileNode, NodeKind
from ..services.filter_engine import FilterSnapshot

_DIR_KINDS = (NodeKind.DIRECTORY, NodeKind.PACKAGE)
_EPS = 1e-9


class TreemapMode(StrEnum):
    CHILDREN = "children"
    SUBTREE = "subtree"


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def inset(self, dx: float, dy: float) -> "Rect":
        return Rect(
            self.x + dx,
            self.y + dy,
            max(0.0, self.w - 2 * dx),
            max(0.0, self.h - 2 * dy),
        )

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.right <= other.x
            or other.right <= self.x
            or self.bottom <= other.y
            or other.bottom <= self.y
        )


@dataclass(slots=True)
class LayoutItem:
    node: FileNode | None
    size: int
    label: str
    is_directory: bool = False
    is_aggregate: bool = False
    grouped: tuple[FileNode, ...] = ()


@dataclass(slots=True)
class Tile:
    node: FileNode | None
    rect: Rect
    label: str
    size: int
    depth: int
    is_directory: bool = False
    is_aggregate: bool = False
    grouped: tuple[FileNode, ...] = ()
    collapsed: bool = False

    @property
    def area(self) -> float:
        return self.rect.area


@dataclass(frozen=True, slots=True)
class LayoutRequest:
    root: FileNode
    snapshot: FilterSnapshot
    rect: Rect
    mode: TreemapMode = TreemapMode.CHILDREN
    min_tile_area: float = 6.0
    max_depth: int = 32
    max_tiles: int = 60_000
    max_children_per_level: int = 4096


@dataclass(slots=True)
class LayoutResult:
    tiles: list[Tile]
    hit_index: "HitIndex"
    request: LayoutRequest
    truncated: bool = False
    aggregated_nodes: int = 0
    tile_count_by_depth: dict[int, int] = field(default_factory=dict)

    def tile_for(self, node: FileNode | None) -> Tile | None:
        if node is None:
            return None
        for tile in self.tiles:
            if tile.node is node:
                return tile
        return None


class HitIndex:
    """Índice espacial por malla para resolver clics en O(1) aproximado."""

    def __init__(self, tiles: list[Tile], bounds: Rect, force_grid: bool = False) -> None:
        self._tiles = tiles
        self._bounds = bounds
        self._grid: dict[tuple[int, int], list[int]] | None = None
        self._cell = 32.0
        if not tiles:
            return
        if force_grid or len(tiles) > 6000:
            self._build_grid()
        elif not force_grid and len(tiles) > 1500:
            self._build_grid()

    def _build_grid(self) -> None:
        self._grid = {}
        cell = self._cell
        for index, tile in enumerate(self._tiles):
            r = tile.rect
            if r.area <= 0:
                continue
            x0 = max(0, int((r.x - self._bounds.x) // cell))
            y0 = max(0, int((r.y - self._bounds.y) // cell))
            x1 = max(x0, int((r.right - _EPS - self._bounds.x) // cell))
            y1 = max(y0, int((r.bottom - _EPS - self._bounds.y) // cell))
            for cy in range(y0, y1 + 1):
                for cx in range(x0, x1 + 1):
                    self._grid.setdefault((cx, cy), []).append(index)

    def hit_test(self, x: float, y: float) -> Tile | None:
        if not self._tiles or not self._bounds.contains(x, y):
            return None
        if self._grid is None:
            candidates: list[int] = range(len(self._tiles))  # type: ignore[assignment]
        else:
            cx = int((x - self._bounds.x) // self._cell)
            cy = int((y - self._bounds.y) // self._cell)
            candidates = self._grid.get((cx, cy), [])
        best: Tile | None = None
        for index in candidates:
            tile = self._tiles[index]
            if tile.rect.contains(x, y):
                if best is None or tile.depth >= best.depth:
                    best = tile
        return best


class TreemapLayoutEngine:
    def layout(self, request: LayoutRequest) -> LayoutResult:
        tiles: list[Tile] = []
        state = {"truncated": False, "aggregated": 0}

        def build(parent: FileNode, rect: Rect, depth: int) -> None:
            if rect.area <= 0 or depth > request.max_depth:
                return
            if len(tiles) >= request.max_tiles:
                state["truncated"] = True
                return
            items = self._build_items(parent, rect, request, state)
            for item, tile_rect in self._squarify(items, rect):
                if len(tiles) >= request.max_tiles:
                    state["truncated"] = True
                    return
                tile = Tile(
                    node=item.node,
                    rect=tile_rect,
                    label=item.label,
                    size=item.size,
                    depth=depth,
                    is_directory=item.is_directory,
                    is_aggregate=item.is_aggregate,
                    grouped=item.grouped,
                )
                tiles.append(tile)
                if (
                    request.mode is TreemapMode.SUBTREE
                    and item.node is not None
                    and item.node.kind in _DIR_KINDS
                    and not item.is_aggregate
                    and tile_rect.area > max(request.min_tile_area * 4.0, 400.0)
                    and depth < request.max_depth
                ):
                    header = 0.0
                    if tile_rect.h >= 34.0 and tile_rect.w >= 40.0:
                        header = min(18.0, max(11.0, tile_rect.h * 0.12))
                    inner = Rect(
                        tile_rect.x + 2.0,
                        tile_rect.y + header + 2.0,
                        max(0.0, tile_rect.w - 4.0),
                        max(0.0, tile_rect.h - header - 4.0),
                    )
                    before = len(tiles)
                    if inner.area > 0 and inner.w >= 4 and inner.h >= 4:
                        build(item.node, inner, depth + 1)
                    if len(tiles) == before:
                        tile.collapsed = True
                elif (
                    request.mode is TreemapMode.SUBTREE
                    and item.node is not None
                    and item.node.kind in _DIR_KINDS
                ):
                    tile.collapsed = True

        build(request.root, request.rect, 1)
        counts: dict[int, int] = {}
        for tile in tiles:
            counts[tile.depth] = counts.get(tile.depth, 0) + 1
        hit_index = HitIndex(tiles, request.rect)
        return LayoutResult(
            tiles=tiles,
            hit_index=hit_index,
            request=request,
            truncated=state["truncated"],
            aggregated_nodes=state["aggregated"],
            tile_count_by_depth=counts,
        )

    def _build_items(
        self,
        parent: FileNode,
        rect: Rect,
        request: LayoutRequest,
        state: dict[str, int | bool],
    ) -> list[LayoutItem]:
        snapshot = request.snapshot
        sizes: list[tuple[FileNode, int]] = []
        for child in snapshot.visible_children(parent):
            size = snapshot.size_of(child)
            if size <= 0:
                continue
            sizes.append((child, size))
        if not sizes:
            return []
        sizes.sort(key=lambda pair: (-pair[1], pair[0].name.casefold()))
        items = [
            LayoutItem(
                node=node,
                size=size,
                label=node.name,
                is_directory=node.kind in _DIR_KINDS,
            )
            for node, size in sizes
        ]
        total = sum(item.size for item in items)
        area = rect.area
        group_start = len(items)
        if request.min_tile_area > 0 and total > 0:
            for index, item in enumerate(items):
                if (item.size / total) * area < request.min_tile_area:
                    group_start = index
                    break
        if len(items) > request.max_children_per_level:
            group_start = min(group_start, request.max_children_per_level - 1)
        if group_start < len(items) - 1:
            tail = items[group_start:]
            grouped = tuple(item.node for item in tail if item.node is not None)
            aggregate = LayoutItem(
                node=None,
                size=sum(item.size for item in tail),
                label=f"Otros ({len(tail)})",
                is_aggregate=True,
                grouped=grouped,
            )
            state["aggregated"] = int(state["aggregated"]) + len(grouped)
            items = items[:group_start] + [aggregate]
            items.sort(key=lambda item: (-item.size, item.label.casefold()))
        return items

    def _squarify(self, items: list[LayoutItem], rect: Rect) -> list[tuple[LayoutItem, Rect]]:
        if not items or rect.area <= 0:
            return []
        total = sum(item.size for item in items)
        if total <= 0:
            return []
        area = rect.area
        entries = [(item, item.size * area / total) for item in items]
        result: list[tuple[LayoutItem, Rect]] = []
        x, y, w, h = rect.x, rect.y, rect.w, rect.h
        row: list[tuple[LayoutItem, float]] = []
        index = 0
        while index < len(entries):
            if w <= _EPS or h <= _EPS:
                break
            side = min(w, h)
            candidate = entries[index]
            if not row:
                row.append(candidate)
                index += 1
                continue
            current_worst = _worst([entry[1] for entry in row], side)
            next_worst = _worst([entry[1] for entry in row] + [candidate[1]], side)
            if next_worst <= current_worst + 1e-12:
                row.append(candidate)
                index += 1
            else:
                x, y, w, h = _place_row(row, x, y, w, h, result)
                row = []
        if row:
            x, y, w, h = _place_row(row, x, y, w, h, result)
        return result


def _worst(areas: list[float], side: float) -> float:
    if not areas or side <= 0:
        return math.inf
    total = sum(areas)
    if total <= 0:
        return math.inf
    largest = max(areas)
    smallest = min(areas)
    if smallest <= 0:
        return math.inf
    return max(
        (side * side * largest) / (total * total),
        (total * total) / (side * side * smallest),
    )


def _place_row(
    row: list[tuple[LayoutItem, float]],
    x: float,
    y: float,
    w: float,
    h: float,
    result: list[tuple[LayoutItem, Rect]],
) -> tuple[float, float, float, float]:
    if not row or w <= _EPS or h <= _EPS:
        return x, y, max(0.0, w), max(0.0, h)
    row_area = sum(area for _, area in row)
    if w >= h:
        strip = min(w, row_area / h)
        cursor = y
        for index, (item, area) in enumerate(row):
            if index == len(row) - 1:
                length = max(0.0, h - (cursor - y))
            else:
                length = area / strip if strip > 0 else 0.0
            length = min(length, max(0.0, h - (cursor - y)))
            result.append((item, Rect(x, cursor, strip, length)))
            cursor += length
        return x + strip, y, max(0.0, w - strip), h
    strip = min(h, row_area / w)
    cursor = x
    for index, (item, area) in enumerate(row):
        if index == len(row) - 1:
            length = max(0.0, w - (cursor - x))
        else:
            length = area / strip if strip > 0 else 0.0
        length = min(length, max(0.0, w - (cursor - x)))
        result.append((item, Rect(cursor, y, length, strip)))
        cursor += length
    return x, y + strip, w, max(0.0, h - strip)
