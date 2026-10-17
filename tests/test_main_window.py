"""Pruebas de integración de la ventana principal (sección 8.4 del plan)."""

from __future__ import annotations

import os

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QStackedWidget

from app.main_window import MainWindow
from app.models.categories import CATEGORY_ORDER, Category
from app.models.file_node import METRIC_LABELS, NodeKind, ScanStatus, SizeMetric
from app.services.file_actions import FileActions
from app.services.settings_manager import SettingsManager
from app.treemap.layout_engine import TreemapMode


@pytest.fixture
def window(qtbot, qapp, tmp_path):
    settings = SettingsManager(QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))
    actions = FileActions(trash_fn=lambda path: True)
    win = MainWindow(settings=settings, file_actions=actions)
    qtbot.addWidget(win)
    win.resize(1100, 750)
    win.show()
    return win


def scan_and_wait(window, qtbot, path, timeout=20000):
    window.start_scan(str(path))
    qtbot.waitUntil(lambda: window._scan_result is not None, timeout=timeout)
    qtbot.waitUntil(lambda: window._snapshot is not None, timeout=timeout)
    return window._scan_result


def allocated_of(result, name: str) -> int:
    """Espacio asignado real del nodo con ese nombre (métrica por defecto)."""
    return next(n.total_allocated for n in result.root.walk() if n.name == name)


def build_fixture(make_tree):
    return make_tree(
        {
            "docs/informe.pdf": 5000,
            "docs/notas.txt": 1000,
            "docs/vacio.txt": 0,
            "media/pelicula.mov": 9000,
            "media/cancion.mp3": 3000,
            "raiz.txt": 500,
        }
    )


# ------------------------------------------------------------------ estado base

def test_starts_with_empty_state(window):
    assert "Listo" in window._status_summary.text()
    assert window._scan_result is None
    assert window._snapshot is None
    assert window.action_analyze.isEnabled()
    assert not window.action_cancel.isEnabled()
    assert not window.action_open.isEnabled()
    assert not window.action_trash.isEnabled()
    assert window._details._title.text() == "Sin selección"
    assert window.windowTitle().startswith("MacDirStat")


def test_window_title_after_scan(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    scan_and_wait(window, qtbot, root)
    assert window.windowTitle() == "MacDirStat — arbol"


# --------------------------------------------------------------------- escaneo

def test_scan_populates_all_views(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    result = scan_and_wait(window, qtbot, root)
    assert result.status is ScanStatus.COMPLETE
    assert window._snapshot.metric is SizeMetric.ALLOCATED
    assert window._snapshot.total_bytes == result.root.total_allocated
    assert window._snapshot.total_bytes >= 5000 + 1000 + 9000 + 3000 + 500
    assert window._tree_model.rowCount() > 0
    assert window._largest._model.rowCount() > 0
    assert "archivos" in window._status_summary.text()
    assert window.path_edit.text() == str(root)


def test_actions_during_scan(window, qtbot, make_tree):
    root = make_tree({f"d{i}/f{i}.bin": 100 for i in range(300)})
    window.start_scan(str(root))
    scanning_seen = window._scanning or window._scan_controller.is_running()
    assert scanning_seen
    window._cancel_scan()
    qtbot.waitUntil(lambda: window._scan_result is not None, timeout=20000)
    qtbot.waitUntil(lambda: not window._scanning, timeout=5000)
    assert window.action_analyze.isEnabled()


# ------------------------------------------------------------------- selección

def test_tree_selection_updates_details_and_treemap(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    scan_and_wait(window, qtbot, root)
    snapshot = window._snapshot
    media = next(c for c in snapshot.root.children if c.name == "media")
    index = window._tree_model.index_for_node(media)
    assert index.isValid()
    window._tree.setCurrentIndex(index)
    assert window._selected_node is media
    assert window._details._title.text() == "media"
    assert window._details._path.text() == media.path()
    assert window._treemap.selected_node is media


def test_treemap_selection_updates_tree_and_details(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    scan_and_wait(window, qtbot, root)
    qtbot.waitUntil(lambda: window._treemap.layout_result is not None, timeout=5000)
    tile = next(
        t for t in window._treemap.layout_result.tiles
        if t.node is not None and t.node.name == "pelicula.mov"
    )
    pos_x = int(tile.rect.x + tile.rect.w / 2)
    pos_y = int(tile.rect.y + tile.rect.h / 2)
    from PySide6.QtCore import QPoint

    qtbot.mouseClick(window._treemap, Qt.LeftButton, pos=QPoint(pos_x, pos_y))
    assert window._selected_node is tile.node
    assert window._details._title.text() == "pelicula.mov"
    current = window._tree.currentIndex()
    assert window._tree_model.node_at(current) is tile.node


def test_largest_selection_updates(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    scan_and_wait(window, qtbot, root)
    model = window._largest._model
    node = model.rows()[0]
    window._largest.select_node(node)
    assert window._selected_node is node
    assert window._details._title.text() == node.name


# ---------------------------------------------------------------- navegación

def test_zoom_and_back_with_breadcrumb(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    scan_result = scan_and_wait(window, qtbot, root)
    scan_root = scan_result.root
    docs = next(c for c in scan_root.children if c.name == "docs")
    window._zoom_node(docs)
    assert window._view_root is docs
    assert window._treemap.view_root is docs or window._treemap.view_root is None
    labels = [
        window._crumbs_layout.itemAt(i).widget().text()
        for i in range(window._crumbs_layout.count())
        if window._crumbs_layout.itemAt(i).widget() is not None
    ]
    assert any("docs" in text for text in labels)
    window._go_back()
    assert window._view_root is scan_root
    window._go_forward()
    assert window._view_root is docs
    window._go_home()
    assert window._view_root is scan_root
    window._go_up()
    assert window._view_root is scan_root  # ya estamos en la raíz del análisis


def test_view_modes_switch_stack(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    scan_and_wait(window, qtbot, root)
    window._set_view_mode("tree")
    assert window._stack.currentIndex() == 1
    window._set_view_mode("largest")
    assert window._stack.currentIndex() == 2
    window._set_view_mode("map")
    assert window._stack.currentIndex() == 0
    assert window.settings.view_mode == "map"


# -------------------------------------------------------------------- filtros

def test_filter_query_updates_snapshot_and_status(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    result = scan_and_wait(window, qtbot, root)
    window._filter_bar.search.setText("pelicula")
    qtbot.waitUntil(lambda: window._snapshot is not None and window._snapshot.is_filtered,
                    timeout=4000)
    assert window._snapshot.metric is SizeMetric.ALLOCATED
    assert window._snapshot.total_bytes == allocated_of(result, "pelicula.mov")
    assert "Mostrando" in window._status_summary.text()
    window._filter_bar.clear_filters()
    qtbot.waitUntil(lambda: window._snapshot is not None and not window._snapshot.is_filtered,
                    timeout=4000)
    assert window._snapshot.total_bytes == result.root.total_allocated


def test_filter_category_and_extension(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    result = scan_and_wait(window, qtbot, root)
    window._filter_bar.extensions.setText("pdf, txt")
    qtbot.waitUntil(lambda: window._snapshot is not None and window._snapshot.is_filtered,
                    timeout=4000)
    assert window._snapshot.total_bytes == (
        allocated_of(result, "informe.pdf")
        + allocated_of(result, "notas.txt")
        + allocated_of(result, "vacio.txt")
        + allocated_of(result, "raiz.txt")
    )


def test_metric_change_updates_labels(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    scan_and_wait(window, qtbot, root)
    window._change_metric(SizeMetric.ALLOCATED)
    assert window._metric is SizeMetric.ALLOCATED
    assert window._snapshot.metric is SizeMetric.ALLOCATED
    assert (
        window._tree_model.headerData(3, Qt.Horizontal)
        == METRIC_LABELS[SizeMetric.ALLOCATED]
    )
    window._change_metric(SizeMetric.LOGICAL)
    assert window._snapshot.metric is SizeMetric.LOGICAL


# -------------------------------------------------------------------- papelera

def test_trash_cancelled_does_not_mutate(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    result = scan_and_wait(window, qtbot, root)
    scan_root = result.root
    docs = next(c for c in scan_root.children if c.name == "docs")
    informe = next(c for c in docs.children if c.name == "informe.pdf")
    before_total = scan_root.total_logical
    window._ask_trash_confirmation = lambda node: False
    window._confirm_trash(informe)
    assert informe in docs.children
    assert scan_root.total_logical == before_total
    assert not window._scan_modified


def test_trash_confirmed_prunes_tree_and_updates_totals(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    result = scan_and_wait(window, qtbot, root)
    scan_root = result.root
    docs = next(c for c in scan_root.children if c.name == "docs")
    informe = next(c for c in docs.children if c.name == "informe.pdf")
    calls: list[str] = []

    def fake_trash(path: str) -> bool:
        calls.append(path)
        return True

    window.file_actions = FileActions(trash_fn=fake_trash)
    window._ask_trash_confirmation = lambda node: True
    window._confirm_trash(informe)
    assert calls == [informe.path()]
    assert informe not in docs.children
    assert window._scan_modified
    assert docs.total_files == 2  # quedan notas.txt y vacio.txt
    assert window._scan_result.root.total_logical == 5000 + 1000 + 9000 + 3000 + 500 - 5000
    assert window._banner.isVisible()
    assert "Papelera" in window._banner_label.text()


# ----------------------------------------------------------------- result parcial

@pytest.mark.skipif(os.geteuid() == 0, reason="root siempre puede leer")
def test_partial_result_shows_banner(window, qtbot, make_tree):
    root = make_tree({"privado/secreto.bin": 10, "publico.txt": 10})
    privado = root / "privado"
    os.chmod(privado, 0o000)
    try:
        result = scan_and_wait(window, qtbot, root)
    finally:
        os.chmod(privado, 0o755)
    assert result.status is ScanStatus.PARTIAL
    assert window._banner.isVisible()
    assert "parcial" in window._banner_label.text().lower()
    assert window._banner_details.isVisible()


# ---------------------------------------------------------------------- tema

def test_theme_switch_keeps_category_colors(window, qtbot):
    window._change_theme("dark")
    assert set(window._theme.categories) == set(CATEGORY_ORDER)
    window._change_theme("light")
    assert set(window._theme.categories) == set(CATEGORY_ORDER)
    assert window._treemap._theme is window._theme
    window._change_theme("system")


def test_treemap_mode_actions(window, qtbot, make_tree):
    root = build_fixture(make_tree)
    scan_and_wait(window, qtbot, root)
    window._change_treemap_mode(TreemapMode.CHILDREN)
    assert window.settings.treemap_mode is TreemapMode.CHILDREN
    assert window._treemap.mode is TreemapMode.CHILDREN
    window._change_treemap_mode(TreemapMode.SUBTREE)
    assert window._treemap.mode is TreemapMode.SUBTREE


def test_toggles_update_visibility(window, qtbot):
    window._toggle_details(False)
    assert window._details.isHidden()
    window._toggle_details(True)
    assert not window._details.isHidden()
    window._toggle_filters(False)
    assert window._filter_bar.isHidden()
    window._toggle_filters(True)
    assert not window._filter_bar.isHidden()
