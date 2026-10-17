"""Pruebas del gestor de preferencias (Fase 3)."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

from app.models.file_node import SizeMetric
from app.services.settings_manager import SettingsManager
from app.treemap.layout_engine import TreemapMode


def make_manager(tmp_path) -> SettingsManager:
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    return SettingsManager(settings)


def test_defaults(tmp_path):
    manager = make_manager(tmp_path)
    assert manager.last_folder == ""
    assert manager.theme == "system"
    assert manager.size_metric is SizeMetric.ALLOCATED
    assert manager.treemap_mode is TreemapMode.SUBTREE
    assert manager.show_hidden is True
    assert manager.show_zero is True
    assert manager.min_tile_area == 6.0
    assert manager.cross_device is False
    assert manager.top_n == 100
    assert manager.view_mode == "map"
    assert manager.filters_visible is True
    assert manager.details_visible is True


def test_roundtrip(tmp_path):
    manager = make_manager(tmp_path)
    manager.last_folder = "/Users/alguien/Documents"
    manager.theme = "dark"
    manager.size_metric = SizeMetric.ALLOCATED_UNIQUE
    manager.treemap_mode = TreemapMode.CHILDREN
    manager.show_hidden = False
    manager.show_zero = False
    manager.min_tile_area = 21.5
    manager.cross_device = True
    manager.top_n = 500
    manager.view_mode = "largest"
    manager.filters_visible = False
    manager.details_visible = False
    manager.sync()

    fresh = make_manager(tmp_path)
    assert fresh.last_folder == "/Users/alguien/Documents"
    assert fresh.theme == "dark"
    assert fresh.size_metric is SizeMetric.ALLOCATED_UNIQUE
    assert fresh.treemap_mode is TreemapMode.CHILDREN
    assert fresh.show_hidden is False
    assert fresh.show_zero is False
    assert fresh.min_tile_area == 21.5
    assert fresh.cross_device is True
    assert fresh.top_n == 500
    assert fresh.view_mode == "largest"
    assert fresh.filters_visible is False
    assert fresh.details_visible is False


def test_invalid_values_fall_back(tmp_path):
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    settings.setValue("theme", "fucsia")
    settings.setValue("size_metric", "inventada")
    settings.setValue("treemap_mode", "desconocido")
    settings.setValue("top_n", 33)
    settings.setValue("view_mode", "otra")
    settings.setValue("min_tile_area", 9999.0)
    settings.sync()
    manager = SettingsManager(settings)
    assert manager.theme == "system"
    assert manager.size_metric is SizeMetric.ALLOCATED
    assert manager.treemap_mode is TreemapMode.SUBTREE
    assert manager.top_n == 100
    assert manager.view_mode == "map"
    assert manager.min_tile_area == 400.0


def test_min_tile_area_never_negative(tmp_path):
    manager = make_manager(tmp_path)
    manager.min_tile_area = -5.0
    assert manager.min_tile_area == 0.0


def test_geometry_roundtrip(tmp_path):
    manager = make_manager(tmp_path)
    assert manager.window_geometry() is None
    assert manager.window_state() is None
    assert manager.splitter_state() is None
    geometry = QByteArray(b"geometria-de-prueba")
    state = QByteArray(b"estado")
    splitter = QByteArray(b"splitter")
    manager.save_window_geometry(geometry)
    manager.save_window_state(state)
    manager.save_splitter_state(splitter)
    manager.sync()
    fresh = make_manager(tmp_path)
    assert fresh.window_geometry() == geometry
    assert fresh.window_state() == state
    assert fresh.splitter_state() == splitter


def test_empty_geometry_returns_none(tmp_path):
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat)
    settings.setValue("window_geometry", QByteArray())
    settings.sync()
    manager = SettingsManager(settings)
    assert manager.window_geometry() is None
