"""Escáner de sistemas de archivos basado en os.scandir, sin dependencias de Qt."""

from __future__ import annotations

import errno as errno_mod
import os
import stat as stat_mod
import threading
import time
from collections.abc import Callable

from ..models.categories import category_for, extension_of
from ..models.file_node import (
    FileNode,
    NodeFlags,
    NodeKind,
    ScanError,
    ScanOptions,
    ScanProgress,
    ScanResult,
    ScanStats,
    ScanStatus,
)

_UF_HIDDEN = getattr(stat_mod, "UF_HIDDEN", 0x8000)
_PACKAGE_SUFFIXES = frozenset({".app", ".bundle", ".framework", ".pkg"})
_PERMISSION_ERRNOS = frozenset({errno_mod.EACCES, errno_mod.EPERM})


class RootScanError(Exception):
    """La raíz no existe, no es una carpeta o no se puede abrir."""


def _allocated_size(st: os.stat_result) -> int:
    return max(0, int(getattr(st, "st_blocks", 0)) * 512)


def _mtime_ns(st: os.stat_result) -> int:
    value = getattr(st, "st_mtime_ns", None)
    if value is None:
        return int(float(getattr(st, "st_mtime", 0.0)) * 1_000_000_000)
    return int(value)


def _hidden(name: str, st: os.stat_result) -> bool:
    return name.startswith(".") or bool(int(getattr(st, "st_flags", 0)) & _UF_HIDDEN)


def _is_package(name: str) -> bool:
    return os.path.splitext(name)[1].casefold() in _PACKAGE_SUFFIXES


class FileSystemScanner:
    """Recorre un árbol de directorios y construye FileNode con totales agregados.

    No sigue enlaces simbólicos. Por defecto no cruza a otros dispositivos.
    Los errores se registran y no interrumpen el recorrido.
    """

    def scan(
        self,
        root_path: str,
        options: ScanOptions | None = None,
        cancel: threading.Event | None = None,
        progress: Callable[[ScanProgress], None] | None = None,
    ) -> ScanResult:
        options = options or ScanOptions()
        cancel = cancel or threading.Event()
        started = time.monotonic()
        errors: list[ScanError] = []

        absolute = os.path.abspath(root_path)
        try:
            real_root = os.path.realpath(absolute)
            root_stat = os.stat(real_root)
        except OSError as exc:
            raise RootScanError(f"No se puede abrir la ubicación: {exc.strerror or exc}") from exc
        if not stat_mod.S_ISDIR(root_stat.st_mode):
            raise RootScanError("La ubicación seleccionada no es una carpeta.")

        root_name = os.path.basename(real_root.rstrip(os.sep)) or os.sep
        root = FileNode(
            name=root_name,
            parent=None,
            kind=NodeKind.DIRECTORY,
            category=category_for(root_name, is_dir=True),
            mtime_ns=_mtime_ns(root_stat),
            dev=int(root_stat.st_dev),
            ino=int(root_stat.st_ino),
            nlink=int(root_stat.st_nlink),
            flags=NodeFlags.NONE,
            children=[],
            root_path=real_root,
        )
        root_dev = int(root_stat.st_dev)
        all_nodes: list[FileNode] = [root]
        stack: list[tuple[FileNode, str]] = [(root, real_root)]
        visited_dirs: set[tuple[int, int]] = {(int(root_stat.st_dev), int(root_stat.st_ino))}
        hardlinks: dict[tuple[int, int], FileNode] = {}

        counters = {"files": 0, "dirs": 0, "errors": 0, "bytes": 0,
                    "symlinks": 0, "packages": 0, "skipped": 0}
        last_progress = 0.0

        def emit_progress(current: str, force: bool = False) -> None:
            nonlocal last_progress
            if progress is None:
                return
            now = time.monotonic()
            if not force and (now - last_progress) * 1000.0 < options.progress_interval_ms:
                return
            last_progress = now
            progress(
                ScanProgress(
                    files=counters["files"],
                    dirs=counters["dirs"],
                    bytes=counters["bytes"],
                    current_path=current,
                    elapsed_s=now - started,
                    errors=counters["errors"],
                )
            )

        def record_error(path: str, exc: OSError, owner: FileNode) -> None:
            counters["errors"] += 1
            owner.error_count += 1
            if len(errors) < options.keep_max_errors:
                errors.append(
                    ScanError(
                        path=path,
                        errno=getattr(exc, "errno", None),
                        message=getattr(exc, "strerror", None) or str(exc),
                        is_permission=getattr(exc, "errno", None) in _PERMISSION_ERRNOS,
                    )
                )

        def new_node(name: str, st: os.stat_result, parent: FileNode,
                     full_path: str, *, is_dir: bool = False,
                     is_package: bool = False, kind: NodeKind | None = None) -> FileNode:
            flags = NodeFlags.NONE
            if _hidden(name, st):
                flags |= NodeFlags.HIDDEN
            if is_package:
                kind = NodeKind.PACKAGE
                counters["packages"] += 1
            elif is_dir:
                kind = NodeKind.DIRECTORY
            node = FileNode(
                name=name,
                parent=parent,
                kind=kind or NodeKind.FILE,
                ext="" if is_dir else extension_of(name),
                category=category_for(
                    name, is_dir=is_dir, is_package=is_package, path=full_path
                ),
                mtime_ns=_mtime_ns(st),
                dev=int(st.st_dev),
                ino=int(st.st_ino),
                nlink=int(st.st_nlink),
                st_flags=int(getattr(st, "st_flags", 0)),
                flags=flags,
            )
            if is_dir:
                node.children = []
                counters["dirs"] += 1
            return node

        emit_progress(real_root, force=True)

        while stack:
            if cancel.is_set():
                break
            dir_node, dir_path = stack.pop()
            try:
                with os.scandir(dir_path) as iterator:
                    for entry in iterator:
                        if cancel.is_set():
                            break
                        entry_path = os.path.join(dir_path, entry.name)
                        try:
                            st = entry.stat(follow_symlinks=False)
                        except OSError as exc:
                            record_error(entry_path, exc, dir_node)
                            continue
                        mode = st.st_mode
                        try:
                            if stat_mod.S_ISLNK(mode):
                                node = new_node(
                                    entry.name, st, dir_node, entry_path,
                                    kind=NodeKind.SYMLINK,
                                )
                                node.logical_size = int(st.st_size)
                                node.allocated_size = _allocated_size(st)
                                node.total_logical = node.logical_size
                                node.total_allocated = node.allocated_size
                                node.total_unique_allocated = node.allocated_size
                                node.total_files = 1
                                counters["files"] += 1
                                counters["symlinks"] += 1
                                counters["bytes"] += node.logical_size
                                dir_node.children.append(node)  # type: ignore[union-attr]
                                all_nodes.append(node)
                            elif stat_mod.S_ISDIR(mode):
                                is_package = _is_package(entry.name)
                                if not options.cross_device and int(st.st_dev) != root_dev:
                                    node = new_node(
                                        entry.name, st, dir_node, entry_path,
                                        is_dir=True, is_package=is_package,
                                        kind=NodeKind.SKIPPED_MOUNT,
                                    )
                                    node.children = None
                                    counters["skipped"] += 1
                                    if len(errors) < options.keep_max_errors:
                                        errors.append(
                                            ScanError(
                                                path=entry_path,
                                                errno=errno_mod.EXDEV,
                                                message="Otro volumen no incluido (active «cruzar volúmenes»).",
                                            )
                                        )
                                else:
                                    node = new_node(
                                        entry.name, st, dir_node, entry_path,
                                        is_dir=True, is_package=is_package,
                                    )
                                    identity = (int(st.st_dev), int(st.st_ino))
                                    if identity in visited_dirs:
                                        errors.append(
                                            ScanError(
                                                path=entry_path,
                                                errno=errno_mod.ELOOP,
                                                message="Directorio ya visitado; se evita un ciclo.",
                                            )
                                        )
                                        node.children = None
                                        node.kind = NodeKind.SKIPPED_MOUNT
                                        counters["skipped"] += 1
                                    else:
                                        visited_dirs.add(identity)
                                        stack.append((node, entry_path))
                                dir_node.children.append(node)  # type: ignore[union-attr]
                                all_nodes.append(node)
                            elif stat_mod.S_ISREG(mode):
                                node = new_node(
                                    entry.name, st, dir_node, entry_path,
                                    kind=NodeKind.FILE,
                                )
                                node.logical_size = int(st.st_size)
                                node.allocated_size = _allocated_size(st)
                                node.total_logical = node.logical_size
                                node.total_allocated = node.allocated_size
                                unique = node.allocated_size
                                if int(st.st_nlink) > 1:
                                    key = (int(st.st_dev), int(st.st_ino))
                                    if key in hardlinks:
                                        node.flags |= NodeFlags.HARDLINK_DUP
                                        unique = 0
                                    else:
                                        hardlinks[key] = node
                                node.total_unique_allocated = unique
                                node.total_files = 1
                                if node.logical_size == 0:
                                    node.total_zero_files = 1
                                counters["files"] += 1
                                counters["bytes"] += node.logical_size
                                dir_node.children.append(node)  # type: ignore[union-attr]
                                all_nodes.append(node)
                            else:
                                node = new_node(
                                    entry.name, st, dir_node, entry_path,
                                    kind=NodeKind.OTHER,
                                )
                                node.logical_size = int(st.st_size)
                                node.allocated_size = _allocated_size(st)
                                node.total_logical = node.logical_size
                                node.total_allocated = node.allocated_size
                                node.total_unique_allocated = node.allocated_size
                                node.total_files = 1
                                counters["files"] += 1
                                counters["bytes"] += node.logical_size
                                dir_node.children.append(node)  # type: ignore[union-attr]
                                all_nodes.append(node)
                        except OSError as exc:
                            record_error(entry_path, exc, dir_node)
                        if counters["files"] % 128 == 0:
                            emit_progress(entry_path)
            except OSError as exc:
                record_error(dir_path, exc, dir_node)
            emit_progress(dir_path)

        # Agregados en post-orden: los hijos siempre aparecen después del padre.
        for node in reversed(all_nodes):
            children = node.children
            if children is None:
                continue
            if node.kind not in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
                continue
            node.total_logical = 0
            node.total_allocated = 0
            node.total_unique_allocated = 0
            node.total_files = 0
            node.total_dirs = 0
            node.total_zero_files = 0
            node.total_errors = node.error_count
            for child in children:
                node.total_logical += child.total_logical
                node.total_allocated += child.total_allocated
                node.total_unique_allocated += child.total_unique_allocated
                node.total_files += child.total_files
                if child.kind in (
                    NodeKind.DIRECTORY,
                    NodeKind.PACKAGE,
                    NodeKind.SKIPPED_MOUNT,
                ):
                    node.total_dirs += 1 + child.total_dirs
                else:
                    node.total_dirs += child.total_dirs
                node.total_zero_files += child.total_zero_files
                node.total_errors += child.total_errors

        elapsed = time.monotonic() - started
        cancelled = cancel.is_set()
        status = (
            ScanStatus.CANCELLED
            if cancelled
            else ScanStatus.PARTIAL
            if counters["errors"] > 0 or counters["skipped"] > 0
            else ScanStatus.COMPLETE
        )
        if counters["errors"] > 0 or counters["skipped"] > 0:
            root.flags |= NodeFlags.INCOMPLETE
        if cancelled:
            root.flags |= NodeFlags.INCOMPLETE

        volume_total: int | None = None
        volume_free: int | None = None
        try:
            vfs = os.statvfs(real_root)
            volume_total = int(vfs.f_blocks) * int(vfs.f_frsize)
            volume_free = int(vfs.f_bavail) * int(vfs.f_frsize)
        except OSError:
            pass

        stats = ScanStats(
            files=root.total_files,
            dirs=root.total_dirs,
            symlinks=counters["symlinks"],
            packages=counters["packages"],
            zero_files=root.total_zero_files,
            logical_bytes=root.total_logical,
            allocated_bytes=root.total_allocated,
            unique_allocated_bytes=root.total_unique_allocated,
            hardlink_groups=len(hardlinks),
            error_count=counters["errors"],
            skipped_mounts=counters["skipped"],
        )
        last_progress = 0.0
        emit_progress("", force=True)
        return ScanResult(
            root=root,
            root_path=real_root,
            stats=stats,
            errors=errors,
            status=status,
            elapsed_s=elapsed,
            volume_total=volume_total,
            volume_free=volume_free,
            all_nodes=all_nodes,
            options=options,
        )
