"""Búsqueda, filtros y snapshots de la vista, sin dependencias de Qt."""

from __future__ import annotations

import fnmatch
import heapq
import threading
from dataclasses import dataclass, field
from typing import Iterable

from ..models.categories import Category
from ..models.file_node import (
    FileNode,
    NodeKind,
    ScanResult,
    SizeMetric,
)

_DIR_KINDS = (NodeKind.DIRECTORY, NodeKind.PACKAGE)
_TOP_LIMIT = 500


@dataclass(frozen=True, slots=True)
class FilterState:
    query: str = ""
    extensions: frozenset[str] = frozenset()
    categories: frozenset[Category] = frozenset()
    min_bytes: int = 0
    max_bytes: int | None = None
    show_hidden: bool = True
    show_zero: bool = True
    excluded_dirs: tuple[str, ...] = ()
    min_tile_area: float = 6.0

    @property
    def query_normalised(self) -> str:
        return self.query.strip().casefold()

    @property
    def has_attribute_filter(self) -> bool:
        return bool(
            self.extensions
            or self.categories
            or self.min_bytes > 0
            or self.max_bytes is not None
        )

    @property
    def has_data_filter(self) -> bool:
        return bool(
            self.query_normalised
            or self.has_attribute_filter
            or not self.show_hidden
            or not self.show_zero
            or self.excluded_dirs
        )


@dataclass(slots=True)
class FilterSnapshot:
    revision: int
    state: FilterState
    metric: SizeMetric
    total_bytes: int
    total_files: int
    total_dirs: int
    total_zero_files: int
    largest_files: list[FileNode] = field(default_factory=list)
    largest_dirs: list[FileNode] = field(default_factory=list)
    visible_ids: set[int] | None = None
    aggregates: dict[int, int] | None = None
    element_counts: dict[int, int] | None = None
    root: FileNode | None = None

    @property
    def is_identity(self) -> bool:
        return self.visible_ids is None

    @property
    def is_filtered(self) -> bool:
        return not self.is_identity

    def is_visible(self, node: FileNode) -> bool:
        if self.visible_ids is None:
            return True
        return id(node) in self.visible_ids

    def size_of(self, node: FileNode) -> int:
        if self.aggregates is None:
            return node.display_size(self.metric)
        return self.aggregates.get(id(node), 0)

    def visible_children(self, node: FileNode) -> list[FileNode]:
        children = node.children or []
        if self.visible_ids is None:
            return list(children)
        return [child for child in children if id(child) in self.visible_ids]

    def element_count(self, node: FileNode) -> int:
        if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            if self.element_counts is None:
                return node.total_elements
            return self.element_counts.get(id(node), 0)
        return 1


class FilterEngine:
    """Construye una proyección filtrada del árbol sin volver a tocar el disco."""

    def build_snapshot(
        self,
        result: ScanResult,
        state: FilterState,
        metric: SizeMetric,
        revision: int,
        top_limit: int = _TOP_LIMIT,
        cancel: threading.Event | None = None,
    ) -> FilterSnapshot | None:
        identity = not state.has_data_filter
        if identity:
            snapshot = self._identity_snapshot(result, state, metric, revision, top_limit)
            return snapshot

        root = result.root
        nodes = result.all_nodes
        blocked: set[int] = set()
        direct: dict[int, bool] = {}
        query = state.query_normalised
        patterns = tuple(p.casefold() for p in state.excluded_dirs if p.strip())

        def attrs_match(node: FileNode) -> bool:
            if state.extensions and node.ext not in state.extensions:
                return False
            if state.categories and node.category not in state.categories:
                return False
            size = node.display_size(metric)
            if state.min_bytes > 0 and size < state.min_bytes:
                return False
            if state.max_bytes is not None and size > state.max_bytes:
                return False
            return True

        def text_match(node: FileNode) -> bool:
            if not query:
                return False
            if query.startswith(".") and len(query) > 1 and "/" not in query:
                return node.ext == query[1:]
            if "/" in query:
                return query in node.path().casefold()
            return query in node.name.casefold() or query in node.ext.casefold()

        def is_excluded(node: FileNode) -> bool:
            if not patterns:
                return False
            name = node.name.casefold()
            for pattern in patterns:
                if "/" in pattern:
                    if fnmatch.fnmatch(node.path().casefold(), pattern):
                        return True
                elif fnmatch.fnmatch(name, pattern):
                    return True
            return False

        # 1. Poda top-down de ramas completas.
        stack: list[FileNode] = [root]
        visited = 0
        while stack:
            node = stack.pop()
            visited += 1
            if visited % 4096 == 0 and cancel is not None and cancel.is_set():
                return None
            if node is not root:
                if not state.show_hidden and node.is_hidden:
                    blocked.add(id(node))
                    continue
                if node.kind in _DIR_KINDS and is_excluded(node):
                    blocked.add(id(node))
                    continue
                if node.kind is NodeKind.PACKAGE and state.has_attribute_filter:
                    if not attrs_match(node):
                        blocked.add(id(node))
                        continue
            children = node.children
            if children:
                stack.extend(children)

        # 2. Coincidencia directa.
        for node in nodes:
            if id(node) in blocked:
                continue
            if node.kind is NodeKind.PACKAGE and state.has_attribute_filter:
                direct[id(node)] = text_match(node) if query else True
                continue
            if node.kind in _DIR_KINDS:
                direct[id(node)] = bool(query) and text_match(node)
                continue
            if node.kind is NodeKind.SKIPPED_MOUNT:
                direct[id(node)] = False
                continue
            if state.query_normalised and not text_match(node):
                direct[id(node)] = False
                continue
            if not attrs_match(node):
                direct[id(node)] = False
                continue
            if not state.show_zero and node.logical_size == 0:
                direct[id(node)] = False
                continue
            direct[id(node)] = True

        # 3. ¿Hay algún descendiente incluido?
        subtree_any: dict[int, bool] = {}
        for node in reversed(nodes):
            node_id = id(node)
            if node_id in blocked:
                subtree_any[node_id] = False
                continue
            any_child = any(subtree_any.get(id(child), False) for child in (node.children or ()))
            subtree_any[node_id] = bool(direct.get(node_id, False) or any_child)

        # 4. Inclusión completa por ancestro o coincidencia de directorio.
        full: dict[int, bool] = {}
        visible: set[int] = set()
        for node in nodes:
            node_id = id(node)
            if node_id in blocked:
                full[node_id] = False
                continue
            parent_full = full.get(id(node.parent), False) if node.parent is not None else False
            is_direct = bool(direct.get(node_id, False))
            full[node_id] = parent_full or is_direct
            if node is root:
                visible.add(node_id)
                continue
            if node.kind is NodeKind.SKIPPED_MOUNT:
                visible.add(node_id)
                continue
            if node.kind in _DIR_KINDS:
                if full[node_id] or subtree_any.get(node_id, False):
                    visible.add(node_id)
            else:
                if full[node_id]:
                    if node.logical_size == 0 and not state.show_zero:
                        continue
                    visible.add(node_id)

        # 5. Agregados y conteos.
        aggregates: dict[int, int] = {}
        element_counts: dict[int, int] = {}
        total_files = 0
        total_dirs = 0
        total_zero = 0
        for node in reversed(nodes):
            node_id = id(node)
            if node_id not in visible:
                aggregates[node_id] = 0
                element_counts[node_id] = 0
                continue
            if node.kind in _DIR_KINDS or node.kind is NodeKind.SKIPPED_MOUNT:
                total = 0
                children_count = 0
                for child in node.children or ():
                    total += aggregates.get(id(child), 0)
                    children_count += 1 + element_counts.get(id(child), 0)
                aggregates[node_id] = total
                element_counts[node_id] = children_count
                if node is not root:
                    total_dirs += 1
            else:
                value = node.display_size(metric)
                aggregates[node_id] = value
                element_counts[node_id] = 0
                total_files += 1
                if node.logical_size == 0:
                    total_zero += 1
        total_bytes = aggregates.get(id(root), 0)

        snapshot = FilterSnapshot(
            revision=revision,
            state=state,
            metric=metric,
            total_bytes=total_bytes,
            total_files=total_files,
            total_dirs=total_dirs,
            total_zero_files=total_zero,
            visible_ids=visible,
            aggregates=aggregates,
            element_counts=element_counts,
            root=root,
        )
        self._fill_largest(snapshot, result.all_nodes, top_limit)
        return snapshot

    def _identity_snapshot(
        self,
        result: ScanResult,
        state: FilterState,
        metric: SizeMetric,
        revision: int,
        top_limit: int,
    ) -> FilterSnapshot:
        root = result.root
        snapshot = FilterSnapshot(
            revision=revision,
            state=state,
            metric=metric,
            total_bytes=root.display_size(metric),
            total_files=root.total_files,
            total_dirs=root.total_dirs,
            total_zero_files=root.total_zero_files,
            visible_ids=None,
            aggregates=None,
            root=root,
        )
        self._fill_largest(snapshot, result.all_nodes, top_limit)
        return snapshot

    def _fill_largest(
        self,
        snapshot: FilterSnapshot,
        nodes: Iterable[FileNode],
        top_limit: int,
    ) -> None:
        files: list[tuple[int, str, FileNode]] = []
        dirs: list[tuple[int, str, FileNode]] = []
        root = snapshot.root
        for node in nodes:
            if not snapshot.is_visible(node):
                continue
            size = snapshot.size_of(node)
            if size <= 0:
                continue
            key = (size, node.name.casefold())
            if node.kind in _DIR_KINDS:
                if node is not root:
                    dirs.append((*key, node))
            elif node.kind is not NodeKind.SKIPPED_MOUNT:
                files.append((*key, node))
        snapshot.largest_files = [
            item[2] for item in heapq.nlargest(top_limit, files, key=lambda x: x[:2])
        ]
        snapshot.largest_dirs = [
            item[2] for item in heapq.nlargest(top_limit, dirs, key=lambda x: x[:2])
        ]


def make_filter_state(**kwargs) -> FilterState:
    """Normaliza conjuntos y patrones antes de construir el estado."""
    if "extensions" in kwargs:
        kwargs["extensions"] = frozenset(
            str(e).strip().lstrip(".").casefold() for e in kwargs["extensions"] if str(e).strip()
        )
    if "categories" in kwargs:
        kwargs["categories"] = frozenset(kwargs["categories"])
    if "excluded_dirs" in kwargs:
        kwargs["excluded_dirs"] = tuple(
            item.strip() for item in kwargs["excluded_dirs"] if item.strip()
        )
    return FilterState(**kwargs)
