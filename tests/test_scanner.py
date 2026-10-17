"""Pruebas del escáner de sistemas de archivos (casos 1–13 y 18 del plan)."""

from __future__ import annotations

import os
import stat as stat_mod
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.models.file_node import (
    NodeFlags,
    NodeKind,
    ScanOptions,
    ScanStatus,
    SizeMetric,
)
from app.models.categories import Category
from app.scanner import FileSystemScanner, RootScanError


# ------------------------------------------------------------------ casos 1–5

def test_empty_directory(make_tree, scan_tree):
    root = make_tree({})
    result = scan_tree(root)
    assert result.status is ScanStatus.COMPLETE
    assert result.stats.files == 0
    assert result.stats.dirs == 0
    assert result.root.total_logical == 0
    assert result.root.children == []


def test_single_file(make_tree, scan_tree):
    root = make_tree({"hola.txt": 1234})
    result = scan_tree(root)
    assert result.stats.files == 1
    assert result.root.total_logical == 1234
    node = result.root.children[0]
    assert node.name == "hola.txt"
    assert node.kind is NodeKind.FILE
    assert node.logical_size == 1234
    assert node.total_files == 1
    assert node.path() == str(root / "hola.txt")


def test_zero_byte_files(make_tree, scan_tree):
    root = make_tree({"vacio1.bin": 0, "vacio2.bin": 0, "algo.txt": 10})
    result = scan_tree(root)
    assert result.stats.files == 3
    assert result.stats.zero_files == 2
    assert result.root.total_logical == 10


def test_size_accounting(make_tree, scan_tree):
    root = make_tree({"pequeno.txt": 10, "grande.bin": 5 * 1024 * 1024})
    result = scan_tree(root)
    assert result.stats.logical_bytes == 10 + 5 * 1024 * 1024
    allocated = result.stats.allocated_bytes
    assert allocated >= result.stats.logical_bytes // 2  # bloques reales del sistema
    unique = result.stats.unique_allocated_bytes
    assert unique == allocated  # sin enlaces duros, coinciden


def test_nested_directories(make_tree, scan_tree):
    root = make_tree(
        {
            "a/b/c/archivo.txt": 100,
            "a/otro.txt": 50,
            "raiz.txt": 25,
        }
    )
    result = scan_tree(root)
    assert result.stats.files == 3
    assert result.stats.dirs == 3  # a, b, c; la raíz no cuenta
    assert result.root.total_dirs == 3
    a = next(child for child in result.root.children if child.name == "a")
    assert a.total_files == 2
    assert a.total_logical == 150
    assert a.total_dirs == 2
    assert a.display_size(SizeMetric.LOGICAL) == 150
    b = next(child for child in a.children if child.name == "b")
    assert b.total_logical == 100
    assert b.total_dirs == 1


# ------------------------------------------------------------------ caso 6–7

def test_unicode_names(make_tree, scan_tree):
    root = make_tree(
        {
            "nota de reunión — café.txt": 5,
            "日本語のファイル.txt": 7,
            "emoji-😀.md": 9,
        }
    )
    result = scan_tree(root)
    names = {child.name for child in result.root.children}
    assert "nota de reunión — café.txt" in names
    assert "日本語のファイル.txt" in names
    assert "emoji-😀.md" in names
    assert result.root.total_logical == 21


def test_extensions_and_categories(make_tree, scan_tree):
    root = make_tree(
        {
            "foto.JPG": 10,
            "video.MOV": 10,
            "codigo.py": 10,
            "sin_extension": 10,
            "comprimido.tar.gz": 10,
        }
    )
    result = scan_tree(root)
    by_name = {child.name: child for child in result.root.children}
    assert by_name["foto.JPG"].ext == "jpg"
    assert by_name["foto.JPG"].category is Category.IMAGES
    assert by_name["video.MOV"].category is Category.VIDEO
    assert by_name["codigo.py"].category is Category.CODE
    assert by_name["sin_extension"].ext == ""
    assert by_name["sin_extension"].category is Category.OTHER
    assert by_name["comprimido.tar.gz"].ext == "tar.gz"
    assert by_name["comprimido.tar.gz"].category is Category.ARCHIVE


# ------------------------------------------------------------------ casos 8–9

def test_symlink_not_followed(make_tree, scan_tree):
    root = make_tree({"real/archivo.txt": 1000, "enlace": "symlink:real"})
    result = scan_tree(root)
    link = next(child for child in result.root.children if child.name == "enlace")
    assert link.kind is NodeKind.SYMLINK
    assert link.total_files == 1
    assert link.total_logical == link.logical_size  # tamaño del enlace, no del destino
    assert link.logical_size < 1000
    real = next(child for child in result.root.children if child.name == "real")
    assert real.total_logical == 1000
    assert result.stats.symlinks == 1


def test_symlink_cycle_does_not_recurse(make_tree, scan_tree):
    root = make_tree({"dir/archivo.txt": 10})
    # Enlace que apunta a la raíz: si el escáner lo siguiese, entraría en bucle.
    (root / "ciclo").symlink_to(root)
    (root / "dir" / "atras").symlink_to(root / "dir")
    result = scan_tree(root)
    assert result.status is ScanStatus.COMPLETE
    assert result.stats.files == 1 + 2  # archivo + dos enlaces
    assert result.stats.symlinks == 2


# ---------------------------------------------------------------------- caso 10

@pytest.mark.skipif(os.geteuid() == 0, reason="root siempre puede leer")
def test_permission_denied_is_recorded(make_tree, scan_tree):
    root = make_tree({"privado/secreto.txt": 10, "publico/visible.txt": 10})
    privado = root / "privado"
    os.chmod(privado, 0o000)
    try:
        result = scan_tree(root)
    finally:
        os.chmod(privado, 0o755)
    assert result.status is ScanStatus.PARTIAL
    assert result.stats.error_count >= 1
    assert any(error.is_permission for error in result.errors)
    assert result.root.flags & NodeFlags.INCOMPLETE
    # El resto del árbol sí se analizó.
    assert result.stats.files >= 1


# ---------------------------------------------------------------------- caso 11

class _BrokenEntry:
    """Entrada de directorio cuyo stat falla, simulando un archivo borrado."""

    def __init__(self, name: str) -> None:
        self.name = name

    def stat(self, follow_symlinks: bool = False):
        raise FileNotFoundError(2, "No such file or directory", self.name)


def test_file_disappears_mid_scan(make_tree, scan_tree, monkeypatch):
    root = make_tree({"borrado.txt": 10, "presente.txt": 20})
    real_scandir = os.scandir

    @contextmanager
    def fake_scandir(path):
        with real_scandir(path) as iterator:
            entries = list(iterator)
        wrapped = [
            _BrokenEntry(entry.name) if entry.name == "borrado.txt" else entry
            for entry in entries
        ]
        yield iter(wrapped)

    monkeypatch.setattr(os, "scandir", fake_scandir)
    result = scan_tree(root)
    assert result.status is ScanStatus.PARTIAL
    assert result.stats.error_count == 1
    assert any("borrado.txt" in error.path for error in result.errors)
    assert result.stats.files == 1
    assert result.root.total_logical == 20


# ---------------------------------------------------------------------- caso 13

def test_directory_aggregates(make_tree, scan_tree):
    root = make_tree(
        {
            "x/uno.bin": 100,
            "x/dos.bin": 200,
            "y/tres.bin": 300,
            "suelto.bin": 50,
        }
    )
    result = scan_tree(root)
    assert result.root.total_logical == 650
    assert result.root.total_files == 4
    x = next(child for child in result.root.children if child.name == "x")
    y = next(child for child in result.root.children if child.name == "y")
    assert x.total_logical == 300
    assert y.total_logical == 300
    # La suma de los hijos directos más los archivos sueltos da el total de la raíz.
    total = sum(child.total_logical for child in result.root.children)
    assert total == result.root.total_logical


# ---------------------------------------------------------------------- caso 18

def test_hardlink_policies(make_tree, scan_tree):
    root = make_tree({"original.bin": 4096})
    os.link(root / "original.bin", root / "duplicado.bin")
    result = scan_tree(root)
    assert result.stats.hardlink_groups == 1
    nodes = [child for child in result.root.children if child.kind is NodeKind.FILE]
    assert len(nodes) == 2
    duplicates = [node for node in nodes if node.is_hardlink_duplicate]
    originals = [node for node in nodes if not node.is_hardlink_duplicate]
    assert len(duplicates) == 1 and len(originals) == 1
    assert duplicates[0].total_unique_allocated == 0
    # En lógico/asignado ambas entradas cuentan; en único solo una.
    assert result.root.total_logical == 2 * 4096
    unique = result.root.display_size(SizeMetric.ALLOCATED_UNIQUE)
    allocated = result.root.display_size(SizeMetric.ALLOCATED)
    assert unique <= allocated
    assert unique == allocated // 2 or unique == allocated  # bloques del mismo inodo


# ------------------------------------------------------------------- paquetes

def test_package_scanned_and_marked(make_tree, scan_tree):
    root = make_tree({"App.app/Contents/info.txt": 512, "normal.txt": 5})
    result = scan_tree(root)
    package = next(child for child in result.root.children if child.name == "App.app")
    assert package.kind is NodeKind.PACKAGE
    assert package.category is Category.APPS
    assert result.stats.packages == 1
    # El interior se escanea: el paquete suma su contenido.
    assert package.total_logical == 512
    assert package.total_files == 1


# -------------------------------------------------------------------- raíz mala

def test_missing_root_raises(tmp_path):
    with pytest.raises(RootScanError):
        FileSystemScanner().scan(str(tmp_path / "no-existe"))


def test_file_as_root_raises(make_tree):
    root = make_tree({"archivo.txt": 1})
    with pytest.raises(RootScanError):
        FileSystemScanner().scan(str(root / "archivo.txt"))


# ------------------------------------------------------------------- progreso

def test_progress_reports_and_final_emission(make_tree, scan_tree):
    root = make_tree({"a/x.bin": 10, "b/y.bin": 20})
    events = []
    boolean_events = []
    result = FileSystemScanner().scan(
        str(root), ScanOptions(progress_interval_ms=0), progress=events.append
    )
    assert result.status is ScanStatus.COMPLETE
    assert events, "debe emitirse al menos un progreso"
    assert events[-1].current_path == ""  # emisión final forzada
    assert events[-1].files == 2
    assert boolean_events == []


def test_hidden_flag(make_tree, scan_tree):
    root = make_tree({".oculto.txt": 1, "visible.txt": 1})
    result = scan_tree(root)
    by_name = {child.name: child for child in result.root.children}
    assert by_name[".oculto.txt"].is_hidden
    assert not by_name["visible.txt"].is_hidden


def test_root_symlink_is_resolved(make_tree, scan_tree):
    real = make_tree({"real/datos.bin": 10}, name="real")
    link = real.parent / "enlace_raiz"
    link.symlink_to(real)
    result = FileSystemScanner().scan(str(link))
    assert Path(result.root_path).resolve() == real.resolve()
    assert result.stats.files == 1
