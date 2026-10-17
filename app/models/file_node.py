"""Modelo de datos compacto para el árbol de archivos."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag, StrEnum
from typing import Iterator

from .categories import Category


class NodeKind(IntEnum):
    FILE = 1
    DIRECTORY = 2
    PACKAGE = 3
    SYMLINK = 4
    SKIPPED_MOUNT = 5
    OTHER = 6


class NodeFlags(IntFlag):
    NONE = 0
    HIDDEN = 1
    HARDLINK_DUP = 2
    INCOMPLETE = 4


class SizeMetric(StrEnum):
    LOGICAL = "logical"
    ALLOCATED = "allocated"
    ALLOCATED_UNIQUE = "allocated_unique"


METRIC_LABELS: dict[SizeMetric, str] = {
    SizeMetric.LOGICAL: "Tamaño lógico",
    SizeMetric.ALLOCATED: "Espacio asignado (est.)",
    SizeMetric.ALLOCATED_UNIQUE: "Asignado único (est.)",
}


class ScanStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


@dataclass(slots=True, eq=False)
class FileNode:
    name: str
    parent: "FileNode | None"
    kind: NodeKind
    ext: str = ""
    category: Category = Category.OTHER
    logical_size: int = 0
    allocated_size: int = 0
    mtime_ns: int = 0
    dev: int = 0
    ino: int = 0
    nlink: int = 1
    st_flags: int = 0
    flags: NodeFlags = NodeFlags.NONE
    children: list["FileNode"] | None = field(default=None, repr=False)
    total_logical: int = 0
    total_allocated: int = 0
    total_unique_allocated: int = 0
    total_files: int = 0
    total_dirs: int = 0
    total_zero_files: int = 0
    total_errors: int = 0
    error_count: int = 0
    root_path: str = ""

    @property
    def is_dir_like(self) -> bool:
        return self.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE)

    @property
    def is_hidden(self) -> bool:
        return bool(self.flags & NodeFlags.HIDDEN)

    @property
    def is_hardlink_duplicate(self) -> bool:
        return bool(self.flags & NodeFlags.HARDLINK_DUP)

    @property
    def total_elements(self) -> int:
        return self.total_files + self.total_dirs

    def display_size(self, metric: SizeMetric) -> int:
        if metric is SizeMetric.LOGICAL:
            return self.total_logical
        if metric is SizeMetric.ALLOCATED:
            return self.total_allocated
        return self.total_unique_allocated

    def path(self) -> str:
        if self.parent is None:
            return self.root_path or self.name
        parts: list[str] = []
        node: FileNode = self
        while node.parent is not None:
            parts.append(node.name)
            node = node.parent
        base = node.root_path or node.name
        parts.reverse()
        return os.path.join(base, *parts)

    def walk(self) -> Iterator["FileNode"]:
        """Recorrido pre-orden iterativo, incluido este nodo."""
        stack = [self]
        while stack:
            node = stack.pop()
            yield node
            children = node.children
            if children:
                stack.extend(reversed(children))


@dataclass(frozen=True, slots=True)
class ScanOptions:
    cross_device: bool = False
    keep_max_errors: int = 500
    progress_interval_ms: int = 100


@dataclass(frozen=True, slots=True)
class ScanError:
    path: str
    errno: int | None
    message: str
    is_permission: bool = False


@dataclass(frozen=True, slots=True)
class ScanProgress:
    files: int
    dirs: int
    bytes: int
    current_path: str
    elapsed_s: float
    errors: int = 0


@dataclass(frozen=True, slots=True)
class ScanStats:
    files: int
    dirs: int
    symlinks: int
    packages: int
    zero_files: int
    logical_bytes: int
    allocated_bytes: int
    unique_allocated_bytes: int
    hardlink_groups: int
    error_count: int
    skipped_mounts: int


@dataclass(frozen=True, slots=True)
class ScanResult:
    root: FileNode
    root_path: str
    stats: ScanStats
    errors: list[ScanError]
    status: ScanStatus
    elapsed_s: float
    volume_total: int | None
    volume_free: int | None
    all_nodes: list[FileNode]
    options: ScanOptions


def make_file_node(
    name: str,
    parent: FileNode | None,
    kind: NodeKind,
    **kwargs,
) -> FileNode:
    """Constructor de conveniencia para tests y agregados."""
    return FileNode(name=name, parent=parent, kind=kind, **kwargs)
