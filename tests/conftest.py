"""Configuración compartida de la suite de pruebas.

Debe fijar `QT_QPA_PLATFORM=offscreen` antes de que pytest-qt cree la
QApplication, de modo que la suite funcione sin pantalla ni sesión gráfica.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import stat
from pathlib import Path
from typing import Callable

import pytest

from app.models.file_node import ScanOptions, ScanResult
from app.scanner import FileSystemScanner


@pytest.fixture
def make_tree(tmp_path: Path) -> Callable[..., Path]:
    """Crea un árbol de archivos a partir de un diccionario.

    Claves: rutas relativas ("docs/a.txt"). Valores:
    - int: tamaño en bytes (contenido "x" * n)
    - "dir": directorio vacío
    - "symlink:<destino relativo>": enlace simbólico
    """

    def _build(spec: dict[str, object], name: str = "arbol") -> Path:
        root = tmp_path / name
        root.mkdir(parents=True, exist_ok=True)
        for rel, value in spec.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if value == "dir":
                path.mkdir(exist_ok=True)
            elif isinstance(value, str) and value.startswith("symlink:"):
                path.symlink_to(root / value.split(":", 1)[1])
            else:
                path.write_bytes(b"x" * int(value))  # type: ignore[arg-type]
        return root

    return _build


@pytest.fixture
def scan_tree() -> Callable[..., ScanResult]:
    """Ejecuta el escáner real sobre una ruta con opciones opcionales."""

    def _scan(path: Path, **option_kwargs) -> ScanResult:
        options = ScanOptions(**option_kwargs) if option_kwargs else None
        return FileSystemScanner().scan(str(path), options)

    return _scan


@pytest.fixture(autouse=True)
def _restore_permissions():
    """Restaura permisos de escritura de rutas temporales tras cada test."""
    created: list[Path] = []
    yield created
    for path in created:
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass


def make_stat(mode: int, *, size: int = 0, dev: int = 1, ino: int = 1,
              nlink: int = 1, blocks: int = 0, flags: int = 0):
    """stat_result sintético para pruebas unitarias sin tocar el disco."""

    class _Stat:
        st_mode = mode
        st_size = size
        st_dev = dev
        st_ino = ino
        st_nlink = nlink
        st_blocks = blocks
        st_flags = flags
        st_mtime_ns = 1_700_000_000_000_000_000

    return _Stat()


def is_dir_mode() -> int:
    return stat.S_IFDIR | 0o755


def is_file_mode() -> int:
    return stat.S_IFREG | 0o644
