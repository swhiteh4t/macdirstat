"""Pruebas de categorías y extensiones (caso 7 del plan)."""

from __future__ import annotations

import pytest

from app.models.categories import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    Category,
    categories_for_extension,
    category_for,
    extension_of,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("foto.jpg", "jpg"),
        ("foto.jpeg", "jpeg"),
        ("foto.HEIC", "heic"),
        ("video.MOV", "mov"),
        ("código.PY", "py"),
        ("sin_extension", ""),
        ("archivo.", ""),
        (".gitignore", ""),
        (".DS_Store", ""),
        ("copia.tar.gz", "tar.gz"),
        ("backup.TAR.BZ2", "tar.bz2"),
        ("nombres.rar.rar", "rar"),
        ("archivo.COMPRIMIDO.tar.xz", "tar.xz"),
    ],
)
def test_extension_of(name, expected):
    assert extension_of(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("foto.jpg", Category.IMAGES),
        ("foto.JPG", Category.IMAGES),
        ("foto.jpeg", Category.IMAGES),
        ("IMG_1234.HEIC", Category.IMAGES),
        ("informe.pdf", Category.DOCUMENTS),
        ("notas.md", Category.DOCUMENTS),
        ("película.mov", Category.VIDEO),
        ("canción.MP3", Category.AUDIO),
        ("paquete.zip", Category.ARCHIVE),
        ("paquete.dmg", Category.ARCHIVE),
        ("copia.tar.gz", Category.ARCHIVE),
        ("copia.tar.bz2", Category.ARCHIVE),
        ("script.py", Category.CODE),
        ("estilo.css", Category.CODE),
        ("biblioteca.dylib", Category.SYSTEM),
        ("Makefile", Category.CODE),
        ("CMakeLists.txt", Category.CODE),
        ("Dockerfile", Category.CODE),
        (".zshrc", Category.CODE),
        ("desconocido.xyz123", Category.OTHER),
        ("sin_extension", Category.OTHER),
    ],
)
def test_category_for_files(name, expected):
    assert category_for(name) is expected


def test_category_for_directories_and_packages():
    assert category_for("carpeta", is_dir=True) is Category.OTHER
    assert category_for("App.app", is_package=True) is Category.APPS
    assert category_for("Vista.framework", is_package=True) is Category.APPS


def test_system_paths():
    assert category_for("datos.bin", path="/System/Library/datos.bin") is Category.SYSTEM
    assert category_for("datos.bin", path="/usr/bin/datos.bin") is Category.SYSTEM
    assert category_for("datos.bin", path="/Users/alguien/datos.bin") is Category.OTHER
    # Una extensión conocida gana al prefijo del sistema.
    assert category_for("foto.jpg", path="/System/foto.jpg") is Category.IMAGES


def test_categories_for_extension_helper():
    assert categories_for_extension("jpg") is Category.IMAGES
    assert categories_for_extension("desconocida") is Category.OTHER


def test_category_metadata_is_complete():
    for category in CATEGORY_ORDER:
        assert category in CATEGORY_LABELS
        assert CATEGORY_LABELS[category]
    assert len(set(CATEGORY_LABELS.values())) == len(CATEGORY_ORDER)
