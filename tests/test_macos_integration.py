"""Pruebas de integración con macOS real (Papelera nativa).

No se ejecutan por defecto: `addopts` excluye el marcador `macos_integration`.
Se lanzan manualmente con:

    QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m macos_integration -v

Cada prueba limpia lo que mueve: si el archivo acaba en ~/.Trash, se elimina
de allí al terminar. Nunca se toca nada del disco del usuario.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

from app.models.file_node import NodeKind
from app.services.file_actions import FileActions, default_trash

pytestmark = [
    pytest.mark.macos_integration,
    pytest.mark.skipif(sys.platform != "darwin", reason="requiere macOS"),
    pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="como root la Papelera sería /var/root/.Trash",
    ),
]


def _remove_from_trash(name: str) -> None:
    candidate = Path.home() / ".Trash" / name
    try:
        if candidate.exists():
            candidate.unlink()
    except OSError:
        pass


def test_native_trash_api_available():
    from PySide6.QtCore import QFile

    assert QFile.supportsMoveToTrash(), "QFile no soporta moveToTrash en este sistema"


def test_default_trash_moves_file_and_cleans_up(tmp_path: Path):
    name = f"macdirstat-trash-{uuid.uuid4().hex}.txt"
    target = tmp_path / name
    target.write_text("prueba de papelera", encoding="utf-8")
    try:
        moved = default_trash(str(target))
        if not moved:
            pytest.skip("moveToTrash no disponible para esta ubicación (¿permisos TCC?)")
        assert not target.exists(), "el archivo debería haber salido de la carpeta temporal"
        assert (Path.home() / ".Trash" / name).exists(), "el archivo debería estar en ~/.Trash"
    finally:
        _remove_from_trash(name)


def test_file_actions_moves_scanned_node_to_trash(make_tree, scan_tree):
    name = f"macdirstat-trash-{uuid.uuid4().hex}.txt"
    root = make_tree({name: 16})
    result = scan_tree(root)
    node = next(
        child for child in result.root.children
        if child.name == name and child.kind is NodeKind.FILE
    )
    actions = FileActions(trash_fn=default_trash)
    try:
        outcome = actions.move_to_trash(node)
        if not outcome.ok:
            pytest.skip(f"moveToTrash no disponible para esta ubicación: {outcome.message}")
        assert not (root / name).exists()
        assert (Path.home() / ".Trash" / name).exists()
    finally:
        _remove_from_trash(name)
