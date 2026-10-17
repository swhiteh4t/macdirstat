"""Utilidades compartidas por las pruebas (sin Qt)."""

from __future__ import annotations

from typing import Any

from app.models.file_node import FileNode, NodeKind, SizeMetric
from app.services.filter_engine import FilterSnapshot, FilterState


def make_tree(spec: dict[str, Any]) -> FileNode:
    """Construye un FileNode agregado a partir de un dict anidado.

    Los valores ``int`` crean archivos con ese tamaño; los ``dict`` crean
    directorios cuyos totales se agregan en post-orden.
    """

    def build(name: str, value: Any, parent: FileNode | None) -> FileNode:
        if isinstance(value, dict):
            node = FileNode(name=name, parent=parent, kind=NodeKind.DIRECTORY, children=[])
            for child_name, child_value in value.items():
                node.children.append(build(child_name, child_value, node))
            node.total_logical = sum(c.total_logical for c in node.children)
            node.total_allocated = sum(c.total_allocated for c in node.children)
            node.total_unique_allocated = sum(c.total_unique_allocated for c in node.children)
            node.total_files = sum(c.total_files for c in node.children)
            node.total_dirs = sum(
                1 + c.total_dirs for c in node.children if c.kind is NodeKind.DIRECTORY
            )
            node.logical_size = node.total_logical
            return node
        node = FileNode(name=name, parent=parent, kind=NodeKind.FILE)
        size = int(value)
        node.logical_size = size
        node.total_logical = size
        node.total_allocated = size
        node.total_unique_allocated = size
        node.total_files = 1
        return node

    return build("raiz", spec, None)


def make_snapshot(root: FileNode, metric: SizeMetric = SizeMetric.LOGICAL) -> FilterSnapshot:
    return FilterSnapshot(
        revision=1,
        state=FilterState(),
        metric=metric,
        total_bytes=root.display_size(metric),
        total_files=root.total_files,
        total_dirs=root.total_dirs,
        total_zero_files=0,
        root=root,
    )
