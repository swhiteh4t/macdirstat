"""Formato de cifras y fechas para la interfaz (sin dependencias de Qt)."""

from __future__ import annotations

import datetime as _dt

from .models.file_node import FileNode, NodeKind, SizeMetric


def human_size(value: int | None) -> str:
    """Tamaño legible con base 1024 (KB, MB, GB...)."""
    if value is None:
        return "—"
    if value < 0:
        return "—"
    if value < 1024:
        return f"{value} B"
    units = ("KB", "MB", "GB", "TB", "PB", "EB")
    number = float(value)
    unit = -1
    while number >= 1024 and unit < len(units) - 1:
        number /= 1024.0
        unit += 1
    if number >= 100:
        text = f"{number:.0f}"
    elif number >= 10:
        text = f"{number:.1f}"
    else:
        text = f"{number:.2f}"
    return f"{text} {units[unit]}"


def format_count(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def format_percent(part: int, total: int) -> str:
    if total <= 0:
        return "—"
    pct = part * 100.0 / total
    if 0 < pct < 0.05:
        return "<0,1 %"
    text = f"{pct:.1f}".replace(".", ",")
    return f"{text} %"


def format_mtime(mtime_ns: int) -> str:
    if not mtime_ns:
        return "—"
    try:
        dt = _dt.datetime.fromtimestamp(mtime_ns / 1_000_000_000)
    except (OverflowError, OSError, ValueError):
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")


_KIND_LABELS = {
    NodeKind.FILE: "Archivo",
    NodeKind.DIRECTORY: "Carpeta",
    NodeKind.PACKAGE: "Paquete",
    NodeKind.SYMLINK: "Enlace simbólico",
    NodeKind.SKIPPED_MOUNT: "Volumen omitido",
    NodeKind.OTHER: "Especial",
}


def kind_label(node: FileNode) -> str:
    if node.kind is NodeKind.FILE and node.ext:
        return f"Archivo .{node.ext}"
    return _KIND_LABELS.get(node.kind, "Elemento")


def type_label(node: FileNode) -> str:
    if node.kind is NodeKind.PACKAGE:
        return "Paquete/aplicación"
    if node.kind is NodeKind.DIRECTORY:
        return "Carpeta"
    if node.kind is NodeKind.SYMLINK:
        return "Enlace simbólico"
    if node.kind is NodeKind.SKIPPED_MOUNT:
        return "Volumen omitido"
    if node.ext:
        return f".{node.ext}"
    return "Sin extensión"


def size_label(node: FileNode, metric: SizeMetric) -> str:
    return human_size(node.display_size(metric))
