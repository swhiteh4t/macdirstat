"""Acciones sobre archivos: abrir, Finder, portapapeles y Papelera segura."""

from __future__ import annotations

import os
import stat as stat_mod
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QFile, QObject, QProcess, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from ..models.file_node import FileNode, NodeKind

TrashFn = Callable[[str], bool]


def default_trash(path: str) -> bool:
    """Mueve a la Papelera de macOS mediante la API nativa de Qt."""
    try:
        return bool(QFile.moveToTrash(path))
    except (RuntimeError, OSError):
        return False


@dataclass(frozen=True, slots=True)
class ActionResult:
    ok: bool
    message: str = ""


class FileActions(QObject):
    error = Signal(str)

    def __init__(self, parent: QObject | None = None,
                 trash_fn: TrashFn | None = None) -> None:
        super().__init__(parent)
        self._trash_fn: TrashFn = trash_fn or default_trash

    def open_node(self, node: FileNode) -> ActionResult:
        path = node.path()
        if node.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
            return self.reveal(path)
        if not os.path.exists(path):
            message = "El elemento ya no existe."
            self.error.emit(message)
            return ActionResult(False, message)
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        if not ok:
            message = "macOS no pudo abrir el elemento con su aplicación predeterminada."
            self.error.emit(message)
            return ActionResult(False, message)
        return ActionResult(True)

    def reveal(self, path_or_node: FileNode | str) -> ActionResult:
        path = path_or_node.path() if isinstance(path_or_node, FileNode) else path_or_node
        if not os.path.exists(path):
            message = "El elemento ya no existe."
            self.error.emit(message)
            return ActionResult(False, message)
        result = QProcess.startDetached("open", ["-R", path])
        ok = result[0] if isinstance(result, tuple) else bool(result)
        if not ok:
            message = "No se pudo mostrar el elemento en Finder."
            self.error.emit(message)
            return ActionResult(False, message)
        return ActionResult(True)

    def copy_path(self, path_or_node: FileNode | str) -> ActionResult:
        path = path_or_node.path() if isinstance(path_or_node, FileNode) else path_or_node
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return ActionResult(False, "El portapapeles no está disponible.")
        clipboard.setText(path)
        return ActionResult(True)

    def validate_for_trash(self, node: FileNode) -> str | None:
        """Devuelve un mensaje de error si el nodo ya no coincide con el disco."""
        if node.parent is None:
            return "No se puede enviar a la Papelera la ubicación raíz del análisis."
        if node.kind is NodeKind.SKIPPED_MOUNT:
            return "Este elemento es un punto de montaje y no se puede mover a la Papelera."
        path = node.path()
        root_node = node
        while root_node.parent is not None:
            root_node = root_node.parent
        root = root_node.path()
        try:
            if os.path.commonpath([os.path.abspath(root), os.path.abspath(path)]) != os.path.abspath(root):
                return "La ruta quedó fuera de la ubicación analizada."
        except ValueError:
            return "La ruta no se puede validar."
        chain: list[FileNode] = []
        current: FileNode | None = node
        while current is not None:
            chain.append(current)
            current = current.parent
        for item in reversed(chain):
            try:
                st = os.lstat(item.path())
            except OSError:
                return "El elemento o uno de sus directorios ya no existe."
            if int(st.st_dev) != item.dev or int(st.st_ino) != item.ino:
                return "El elemento cambió desde que se analizó. Vuelve a analizar antes de borrarlo."
            is_link = stat_mod.S_ISLNK(st.st_mode)
            if item.kind is NodeKind.SYMLINK:
                if not is_link:
                    return "El enlace cambió desde que se analizó."
            elif item.kind in (NodeKind.DIRECTORY, NodeKind.PACKAGE):
                if not stat_mod.S_ISDIR(st.st_mode):
                    return "El tipo del elemento cambió desde que se analizó."
            elif item.kind is NodeKind.FILE:
                if not stat_mod.S_ISREG(st.st_mode):
                    return "El tipo del elemento cambió desde que se analizó."
        return None

    def move_to_trash(self, node: FileNode) -> ActionResult:
        problem = self.validate_for_trash(node)
        if problem:
            return ActionResult(False, problem)
        path = node.path()
        try:
            ok = self._trash_fn(path)
        except Exception as exc:  # noqa: BLE001 - la UI debe mostrar el fallo
            return ActionResult(False, f"No se pudo mover a la Papelera: {exc}")
        if not ok:
            return ActionResult(
                False,
                "macOS no pudo mover el elemento a la Papelera. "
                "Comprueba permisos y que el elemento siga existiendo.",
            )
        return ActionResult(True, "Elemento enviado a la Papelera.")
