"""Pruebas del motor de layout squarified (caso 16 y invariantes del plan)."""

from __future__ import annotations

import math

import pytest

from app.models.file_node import FileNode
from app.treemap.layout_engine import (
    HitIndex,
    LayoutRequest,
    Rect,
    Tile,
    TreemapLayoutEngine,
    TreemapMode,
)

from helpers import make_snapshot, make_tree


def layout_of(root: FileNode, rect: Rect = Rect(0, 0, 800, 600),
              mode: TreemapMode = TreemapMode.CHILDREN,
              min_tile_area: float = 0.0) -> list[Tile]:
    request = LayoutRequest(
        root=root, snapshot=make_snapshot(root), rect=rect,
        mode=mode, min_tile_area=min_tile_area,
    )
    return TreemapLayoutEngine().layout(request).tiles


def _children_of(root: FileNode, tiles: list[Tile], parent: FileNode) -> list[Tile]:
    return [t for t in tiles if t.node is not None and t.node.parent is parent]


# ------------------------------------------------------------- invariantes

def test_all_rects_inside_bounds():
    tree = make_tree({f"f{i}.bin": (i + 1) * 1000 for i in range(12)})
    rect = Rect(0, 0, 640, 480)
    tiles = layout_of(tree, rect)
    assert tiles
    for tile in tiles:
        assert tile.rect.x >= -1e-9
        assert tile.rect.y >= -1e-9
        assert tile.rect.right <= rect.right + 1e-6
        assert tile.rect.bottom <= rect.bottom + 1e-6
        assert tile.rect.w > 0 and tile.rect.h > 0


def test_no_overlap_between_siblings():
    tree = make_tree({f"f{i}.bin": (i + 1) * 500 for i in range(20)})
    tiles = layout_of(tree, mode=TreemapMode.CHILDREN)
    for i, a in enumerate(tiles):
        for b in tiles[i + 1:]:
            overlap_w = min(a.rect.right, b.rect.right) - max(a.rect.x, b.rect.x)
            overlap_h = min(a.rect.bottom, b.rect.bottom) - max(a.rect.y, b.rect.y)
            assert overlap_w <= 1e-6 or overlap_h <= 1e-6, (
                f"solapamiento entre {a.label} y {b.label}"
            )


def test_area_proportional_to_size():
    tree = make_tree({"grande.bin": 8000, "medio.bin": 1500, "pequeno.bin": 500})
    rect = Rect(0, 0, 1000, 500)
    tiles = layout_of(tree, rect)
    total = sum(t.size for t in tiles)
    area_total = rect.area
    for tile in tiles:
        expected = tile.size / total * area_total
        assert math.isclose(tile.area, expected, rel_tol=1e-6, abs_tol=1e-6)


def test_area_sum_equals_rect():
    tree = make_tree({f"f{i}.bin": (i * i + 1) * 111 for i in range(15)})
    rect = Rect(0, 0, 733, 511)
    tiles = layout_of(tree, rect)
    assert math.isclose(sum(t.area for t in tiles), rect.area, rel_tol=1e-6)


def test_deterministic_layout():
    tree = make_tree({f"f{i:02d}.bin": ((i * 7) % 13 + 1) * 100 for i in range(30)})
    first = layout_of(tree)
    second = layout_of(tree)
    assert len(first) == len(second)
    for a, b in zip(first, second, strict=True):
        assert a.label == b.label
        assert (a.rect.x, a.rect.y, a.rect.w, a.rect.h) == (
            b.rect.x, b.rect.y, b.rect.w, b.rect.h
        )


def test_dominant_file_matches_share():
    tree = make_tree({"enorme.bin": 900_000, "a.bin": 100, "b.bin": 100})
    rect = Rect(0, 0, 500, 500)
    tiles = layout_of(tree, rect)
    enorme = next(t for t in tiles if t.label == "enorme.bin")
    share = enorme.area / rect.area
    assert math.isclose(share, 900_000 / 900_200, rel_tol=1e-4)


def test_equal_sizes_grid_like():
    tree = make_tree({f"f{i}.bin": 1000 for i in range(16)})
    rect = Rect(0, 0, 400, 400)
    tiles = layout_of(tree, rect)
    areas = [t.area for t in tiles]
    assert math.isclose(min(areas), max(areas), rel_tol=1e-6)
    assert math.isclose(sum(areas), rect.area, rel_tol=1e-6)


def test_zero_and_empty_tree():
    tree = make_tree({})
    assert layout_of(tree) == []
    tree_zero = make_tree({"a.bin": 0, "b.bin": 0})
    assert layout_of(tree_zero) == []


# ------------------------------------------------------------- agregación

def test_aggregation_preserves_sum_and_membership():
    spec = {"grande.bin": 500_000}
    spec.update({f"pequeno{i}.bin": 10 for i in range(200)})
    tree = make_tree(spec)
    rect = Rect(0, 0, 800, 600)
    tiles = layout_of(tree, rect, min_tile_area=36.0)
    aggregate = [t for t in tiles if t.is_aggregate]
    assert len(aggregate) == 1
    agg = aggregate[0]
    assert agg.label == "Otros (200)"
    assert agg.size == 200 * 10
    assert len(agg.grouped) == 200
    total_size = sum(t.size for t in tiles)
    assert total_size == 500_000 + 200 * 10  # no se pierde ni se duplica tamaño
    names = {t.label for t in tiles}
    assert "grande.bin" in names and agg.label in names


def test_no_aggregation_when_all_visible():
    tree = make_tree({"a.bin": 1000, "b.bin": 1000})
    tiles = layout_of(tree, min_tile_area=1.0)
    assert all(not t.is_aggregate for t in tiles)


def test_aggregate_hit_and_tooltip_support():
    spec = {f"f{i}.bin": 100 for i in range(50)}
    tree = make_tree(spec)
    tiles = layout_of(tree, Rect(0, 0, 200, 100), min_tile_area=500.0)
    agg = next(t for t in tiles if t.is_aggregate)
    assert set(agg.grouped) == set(tree.children)  # misma identidad, sin perder nodos
    assert agg.node is None


# ------------------------------------------------------------- hit testing

def test_hit_test_finds_tile():
    tree = make_tree({"a.bin": 3000, "b.bin": 1000})
    rect = Rect(0, 0, 400, 300)
    tiles = layout_of(tree, rect)
    index = HitIndex(tiles, rect)
    for tile in tiles:
        cx = tile.rect.x + tile.rect.w / 2
        cy = tile.rect.y + tile.rect.h / 2
        hit = index.hit_test(cx, cy)
        assert hit is not None and hit.node is tile.node


def test_hit_test_outside_returns_none():
    tree = make_tree({"a.bin": 1000})
    rect = Rect(0, 0, 100, 100)
    tiles = layout_of(tree, rect)
    index = HitIndex(tiles, rect)
    assert index.hit_test(-5, -5) is None
    assert index.hit_test(200, 200) is None


def test_hit_test_grid_same_as_linear():
    spec = {f"f{i}.bin": (i % 7 + 1) * 137 for i in range(120)}
    tree = make_tree(spec)
    rect = Rect(0, 0, 640, 480)
    tiles = layout_of(tree, rect)
    linear = HitIndex(tiles, rect, force_grid=False)
    grid = HitIndex(tiles, rect, force_grid=True)
    for x in range(0, 640, 17):
        for y in range(0, 480, 13):
            a = linear.hit_test(x + 0.5, y + 0.5)
            b = grid.hit_test(x + 0.5, y + 0.5)
            assert (a is None) == (b is None)
            if a is not None:
                assert a.node is b.node


# ------------------------------------------------------------- modo subárbol

def test_subtree_children_inside_parent():
    tree = make_tree(
        {
            "docs": {"a.txt": 3000, "b.txt": 1000},
            "media": {"foto.jpg": 2000, "video.mov": 5000},
        }
    )
    tiles = layout_of(tree, mode=TreemapMode.SUBTREE)
    docs_dir = next(t for t in tiles if t.label == "docs")
    docs_children = _children_of(tree, tiles, docs_dir.node)
    assert docs_children, "el directorio debe dibujar sus hijos en modo subárbol"
    for child in docs_children:
        assert child.rect.x >= docs_dir.rect.x - 1e-6
        assert child.rect.y >= docs_dir.rect.y - 1e-6
        assert child.rect.right <= docs_dir.rect.right + 1e-6
        assert child.rect.bottom <= docs_dir.rect.bottom + 1e-6


def test_subtree_level_proportionality():
    docs = {"a.txt": 3000, "b.txt": 1000}
    tree = make_tree({"docs": docs, "media": {"foto.jpg": 4000}})
    tiles = layout_of(tree, mode=TreemapMode.SUBTREE)
    doc_tile = next(t for t in tiles if t.label == "docs")
    children = _children_of(tree, tiles, doc_tile.node)
    assert children
    # El área de los hijos es proporcional a sus tamaños.
    total = sum(t.size for t in children)
    area = sum(t.area for t in children)
    for child in children:
        expected = child.size / total * area
        assert math.isclose(child.area, expected, rel_tol=1e-6, abs_tol=1e-6)


def test_subtree_collapses_tiny_directories():
    spec = {"grande.bin": 1_000_000}
    spec.update({f"d{i}/f.bin": 100 for i in range(30)})
    tree = make_tree(spec)
    tiles = layout_of(tree, Rect(0, 0, 400, 300), mode=TreemapMode.SUBTREE,
                      min_tile_area=25.0)
    # Los directorios diminutos se agrupan en una ficha «Otros».
    assert any(t.is_aggregate for t in tiles)


def test_tile_count_and_max():
    spec = {f"d{i}": {f"f{j}.bin": 10 + j for j in range(10)} for i in range(50)}
    tree = make_tree(spec)
    request = LayoutRequest(
        root=tree, snapshot=make_snapshot(tree), rect=Rect(0, 0, 600, 400),
        mode=TreemapMode.SUBTREE, min_tile_area=4.0, max_tiles=100,
    )
    result = TreemapLayoutEngine().layout(request)
    assert len(result.tiles) <= 100
