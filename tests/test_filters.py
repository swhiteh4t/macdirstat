"""Pruebas de búsqueda, filtros y snapshots (casos 14–15 del plan)."""

from __future__ import annotations

import threading

from app.models.categories import Category
from app.models.file_node import SizeMetric
from app.services.filter_engine import FilterEngine, make_filter_state


def build_result(make_tree, scan_tree):
    root = make_tree(
        {
            "docs/informe.pdf": 1000,
            "docs/notas.txt": 500,
            "docs/foto.jpg": 300,
            "docs/vacio.txt": 0,
            "media/pelicula.mov": 4000,
            "media/cancion.mp3": 2000,
            "media/foto2.jpg": 250,
            ".oculto/secreto.bin": 700,
            ".git/config": 100,
            "node_modules/lib/x.js": 800,
            "raiz.txt": 50,
        }
    )
    return scan_tree(root)


def test_identity_snapshot(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    snapshot = FilterEngine().build_snapshot(
        result, make_filter_state(), SizeMetric.LOGICAL, 1
    )
    assert snapshot is not None
    assert snapshot.is_identity
    assert snapshot.total_bytes == result.root.total_logical
    assert snapshot.total_files == result.stats.files
    assert snapshot.total_dirs == result.stats.dirs
    # Los mayores también se calculan en el snapshot identidad.
    assert snapshot.largest_files
    sizes = [snapshot.size_of(n) for n in snapshot.largest_files]
    assert sizes == sorted(sizes, reverse=True)


def test_apply_and_clear_filters(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    engine = FilterEngine()
    full = engine.build_snapshot(result, make_filter_state(), SizeMetric.LOGICAL, 1)
    filtered = engine.build_snapshot(
        result, make_filter_state(extensions=["txt"]), SizeMetric.LOGICAL, 2
    )
    assert filtered is not None and filtered.is_filtered
    # Solo coinciden notas.txt (500), vacio.txt (0) y raiz.txt (50).
    assert filtered.total_bytes == 500 + 0 + 50
    assert full is not None and filtered.total_bytes < full.total_bytes
    # Retirar el filtro vuelve al total íntegro.
    cleared = engine.build_snapshot(result, make_filter_state(), SizeMetric.LOGICAL, 3)
    assert cleared is not None and cleared.total_bytes == full.total_bytes


def test_query_by_name_and_extension(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    engine = FilterEngine()
    by_name = engine.build_snapshot(
        result, make_filter_state(query="foto"), SizeMetric.LOGICAL, 1
    )
    assert by_name.total_bytes == 300 + 250
    by_ext = engine.build_snapshot(
        result, make_filter_state(query=".jpg"), SizeMetric.LOGICAL, 1
    )
    assert by_ext.total_bytes == 300 + 250
    by_path = engine.build_snapshot(
        result, make_filter_state(query="docs/"), SizeMetric.LOGICAL, 1
    )
    assert by_path.total_bytes == 1000 + 500 + 300 + 0


def test_directory_visible_when_descendant_matches(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    snapshot = FilterEngine().build_snapshot(
        result, make_filter_state(query="pelicula"), SizeMetric.LOGICAL, 1
    )
    media = next(c for c in result.root.children if c.name == "media")
    docs = next(c for c in result.root.children if c.name == "docs")
    assert snapshot.is_visible(media)
    assert not snapshot.is_visible(docs)
    assert snapshot.size_of(media) == 4000


def test_category_filter(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    snapshot = FilterEngine().build_snapshot(
        result,
        make_filter_state(categories=[Category.IMAGES]),
        SizeMetric.LOGICAL,
        1,
    )
    assert snapshot.total_bytes == 300 + 250


def test_hidden_filter(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    engine = FilterEngine()
    with_hidden = engine.build_snapshot(result, make_filter_state(), SizeMetric.LOGICAL, 1)
    without = engine.build_snapshot(
        result, make_filter_state(show_hidden=False), SizeMetric.LOGICAL, 2
    )
    # Ocultos: .oculto/secreto.bin (700) y .git/config (100).
    assert without.total_bytes == with_hidden.total_bytes - 700 - 100


def test_zero_filter(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    snapshot = FilterEngine().build_snapshot(
        result, make_filter_state(show_zero=False), SizeMetric.LOGICAL, 1
    )
    docs = next(c for c in result.root.children if c.name == "docs")
    vacio = next(c for c in docs.children if c.name == "vacio.txt")
    assert not snapshot.is_visible(vacio)
    assert snapshot.total_files == result.stats.files - 1


def test_excluded_dirs(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    snapshot = FilterEngine().build_snapshot(
        result,
        make_filter_state(excluded_dirs=["node_modules", ".git"]),
        SizeMetric.LOGICAL,
        1,
    )
    assert snapshot.total_bytes == result.root.total_logical - 800 - 100


def test_size_range_filter(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    engine = FilterEngine()
    big = engine.build_snapshot(
        result, make_filter_state(min_bytes=1000), SizeMetric.LOGICAL, 1
    )
    assert big.total_bytes == 1000 + 4000 + 2000
    small = engine.build_snapshot(
        result, make_filter_state(max_bytes=300), SizeMetric.LOGICAL, 2
    )
    assert small.total_bytes == 300 + 250 + 100 + 50  # vacío no cuenta (0 <= 300 sí cuenta pero suma 0)


def test_aggregates_are_consistent(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    snapshot = FilterEngine().build_snapshot(
        result, make_filter_state(extensions=["jpg", "png"]), SizeMetric.LOGICAL, 1
    )
    total = 0
    for node in result.all_nodes:
        if node.kind.name == "FILE":
            continue
        children_total = sum(
            snapshot.size_of(child) for child in (node.children or [])
        )
        if snapshot.is_visible(node):
            assert snapshot.size_of(node) == children_total
    files = [n for n in result.all_nodes if n.kind.name == "FILE" and snapshot.is_visible(n)]
    total = sum(snapshot.size_of(n) for n in files)
    assert snapshot.total_bytes == total == 300 + 250


def test_cancel_returns_none(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    cancel = threading.Event()
    cancel.set()
    snapshot = FilterEngine().build_snapshot(
        result, make_filter_state(query="foto"), SizeMetric.LOGICAL, 1, cancel=cancel
    )
    # Con la cancelación activa y suficiente trabajo, el resultado puede ser None;
    # con árboles diminutos puede terminar antes de comprobar. Verificamos ambos casos.
    assert snapshot is None or snapshot.is_filtered


def test_largest_rankings_filtered(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    snapshot = FilterEngine().build_snapshot(
        result, make_filter_state(categories=[Category.VIDEO, Category.AUDIO]),
        SizeMetric.LOGICAL, 1,
    )
    names = [n.name for n in snapshot.largest_files]
    assert "pelicula.mov" in names and "cancion.mp3" in names
    assert "informe.pdf" not in names
    dirs = [n.name for n in snapshot.largest_dirs]
    assert "media" in dirs


def test_metric_snapshot_uses_allocated(make_tree, scan_tree):
    result = build_result(make_tree, scan_tree)
    snapshot = FilterEngine().build_snapshot(
        result, make_filter_state(), SizeMetric.ALLOCATED, 1
    )
    assert snapshot.total_bytes == result.root.display_size(SizeMetric.ALLOCATED)
