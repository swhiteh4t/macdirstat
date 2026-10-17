"""Pruebas del widget de treemap: clic, zoom, resize y tooltip (casos 16, 17, 19)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt

from app.models.file_node import NodeKind, SizeMetric
from app.services.filter_engine import FilterEngine, make_filter_state
from app.theme import build_theme
from app.treemap.layout_engine import TreemapMode
from app.treemap.treemap_widget import TreemapWidget

from helpers import make_snapshot, make_tree


@pytest.fixture
def widget(qtbot, qapp):
    widget = TreemapWidget()
    qtbot.addWidget(widget)
    widget.set_theme(build_theme(qapp))
    widget.resize(640, 420)
    widget.show()
    return widget


def wait_layout(widget, qtbot):
    qtbot.waitUntil(lambda: widget.layout_result is not None, timeout=3000)
    return widget.layout_result


def center_of(tile) -> QPoint:
    return QPoint(int(tile.rect.x + tile.rect.w / 2), int(tile.rect.y + tile.rect.h / 2))


def test_layout_is_computed(widget, qtbot):
    tree = make_tree({"a.bin": 5000, "b.bin": 1000, "c.bin": 500})
    widget.set_snapshot(make_snapshot(tree))
    result = wait_layout(widget, qtbot)
    assert result.tiles
    assert all(tile.rect.w > 0 and tile.rect.h > 0 for tile in result.tiles)


def test_click_selects_node_and_emits(widget, qtbot):
    tree = make_tree({"grande.bin": 9000, "pequeno.bin": 1000})
    widget.set_snapshot(make_snapshot(tree))
    result = wait_layout(widget, qtbot)
    tile = next(t for t in result.tiles if t.label == "grande.bin")
    with qtbot.waitSignal(widget.nodeSelected, timeout=2000) as blocker:
        qtbot.mouseClick(widget, Qt.LeftButton, pos=center_of(tile))
    assert blocker.args[0] is tile.node
    assert widget.selected_node is tile.node


def test_escape_clears_selection_and_emits(widget, qtbot):
    tree = make_tree({"a.bin": 1000})
    widget.set_snapshot(make_snapshot(tree))
    result = wait_layout(widget, qtbot)
    tile = result.tiles[0]
    qtbot.mouseClick(widget, Qt.LeftButton, pos=center_of(tile))
    assert widget.selected_node is tile.node
    with qtbot.waitSignal(widget.nodeSelected, timeout=2000) as blocker:
        qtbot.keyClick(widget, Qt.Key_Escape)
    assert blocker.args[0] is None
    assert widget.selected_node is None


def test_double_click_directory_requests_zoom(widget, qtbot):
    tree = make_tree({"docs": {"a.txt": 300, "b.txt": 200}, "foto.jpg": 5000})
    widget.set_snapshot(make_snapshot(tree))
    result = wait_layout(widget, qtbot)
    docs_tile = next(t for t in result.tiles if t.label == "docs")
    with qtbot.waitSignal(widget.zoomRequested, timeout=2000) as blocker:
        qtbot.mouseDClick(widget, Qt.LeftButton, pos=center_of(docs_tile))
    assert blocker.args[0] is docs_tile.node


def test_double_click_file_requests_open(widget, qtbot):
    tree = make_tree({"foto.jpg": 5000, "otro.txt": 100})
    widget.set_snapshot(make_snapshot(tree))
    result = wait_layout(widget, qtbot)
    tile = next(t for t in result.tiles if t.label == "foto.jpg")
    with qtbot.waitSignal(widget.openRequested, timeout=2000) as blocker:
        qtbot.mouseDClick(widget, Qt.LeftButton, pos=center_of(tile))
    assert blocker.args[0] is tile.node


def test_zoom_and_back_changes_root(widget, qtbot):
    tree = make_tree({"docs": {"a.txt": 3000, "b.txt": 1000}, "media": {"v.mov": 2000}})
    widget.set_snapshot(make_snapshot(tree))
    wait_layout(widget, qtbot)
    docs = next(c for c in tree.children if c.name == "docs")
    widget.set_view_root(docs)
    qtbot.waitUntil(
        lambda: widget.layout_result is not None
        and all(t.node is not tree for t in widget.layout_result.tiles),
        timeout=3000,
    )
    labels = {t.label for t in widget.layout_result.tiles}
    assert "a.txt" in labels and "b.txt" in labels
    widget.set_view_root(tree)
    qtbot.waitUntil(
        lambda: widget.layout_result is not None
        and any(t.node is tree.children[0] for t in widget.layout_result.tiles),
        timeout=3000,
    )


def test_resize_relayout(widget, qtbot):
    tree = make_tree({f"f{i}.bin": (i + 1) * 100 for i in range(8)})
    widget.set_snapshot(make_snapshot(tree))
    wait_layout(widget, qtbot)
    widget.resize(300, 200)
    qtbot.waitUntil(
        lambda: widget.layout_result is not None
        and widget.layout_result.request.rect.w <= 300.5,
        timeout=3000,
    )
    result = widget.layout_result
    total = sum(t.area for t in result.tiles)
    assert abs(total - 300 * 200) < 1.0


def test_tooltip_escapes_html(widget, qtbot):
    tree = make_tree({"<script>alert(1)</script>.txt": 1000})
    widget.set_snapshot(make_snapshot(tree))
    result = wait_layout(widget, qtbot)
    tile = result.tiles[0]
    tactic = widget._tooltip_html(tile)
    assert "<script>" not in tactic
    assert "&lt;script&gt;" in tactic
    assert "alert(1)" in tactic


def test_aggregate_selection_signal(widget, qtbot):
    spec = {f"diminuto{i}.txt": 10 for i in range(120)}
    tree = make_tree(spec)
    # Cada ficha mide ~2240 px²; con umbral 4000 todas se agrupan.
    widget.set_min_tile_area(4000.0)
    widget.set_snapshot(make_snapshot(tree))
    result = wait_layout(widget, qtbot)
    aggregate = next(t for t in result.tiles if t.is_aggregate)
    with qtbot.waitSignal(widget.aggregateSelected, timeout=2000) as blocker:
        qtbot.mouseClick(widget, Qt.LeftButton, pos=center_of(aggregate))
    nodes = blocker.args[0]
    assert len(nodes) == len(aggregate.grouped)


def test_keyboard_enter_zooms_directory(widget, qtbot):
    tree = make_tree({"docs": {"a.txt": 100}, "z.bin": 500})
    widget.set_snapshot(make_snapshot(tree))
    result = wait_layout(widget, qtbot)
    docs_tile = next(t for t in result.tiles if t.label == "docs")
    widget._select_tile(docs_tile)
    with qtbot.waitSignal(widget.zoomRequested, timeout=2000) as blocker:
        qtbot.keyClick(widget, Qt.Key_Return)
    assert blocker.args[0] is docs_tile.node


def test_empty_snapshot_message_no_crash(widget, qtbot):
    widget.set_snapshot(None)
    widget.repaint()
    qtbot.wait(50)
    assert widget.layout_result is None


def test_subtree_mode_paints_children(widget, qtbot):
    tree = make_tree(
        {
            "docs": {"largo_nombre_de_archivo.txt": 3000, "otro.txt": 1000},
            "media": {"v.mov": 2000},
        }
    )
    widget.set_mode(TreemapMode.SUBTREE)
    widget.set_snapshot(make_snapshot(tree))
    result = wait_layout(widget, qtbot)
    depths = {t.depth for t in result.tiles}
    assert len(depths) > 1
    widget.grab()  # no debe lanzar excepciones de pintado
