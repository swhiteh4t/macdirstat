"""Preferencias persistentes con QSettings."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

from .. import APP_NAME, ORG_NAME
from ..models.file_node import SizeMetric
from ..treemap.layout_engine import TreemapMode


class SettingsManager:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings(ORG_NAME, APP_NAME)

    # ---------------------------------------------------------------- basics
    def value(self, key: str, default=None):
        return self._settings.value(key, default)

    def set_value(self, key: str, value) -> None:
        self._settings.setValue(key, value)

    def sync(self) -> None:
        self._settings.sync()

    def _bool(self, key: str, default: bool) -> bool:
        value = self._settings.value(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().casefold() in ("1", "true", "yes", "on")
        return bool(value)

    # ------------------------------------------------------------ propiedades
    @property
    def last_folder(self) -> str:
        return str(self._settings.value("last_folder", "", type=str) or "")

    @last_folder.setter
    def last_folder(self, value: str) -> None:
        self._settings.setValue("last_folder", value)

    @property
    def theme(self) -> str:
        value = str(self._settings.value("theme", "system", type=str) or "system")
        return value if value in ("system", "light", "dark") else "system"

    @theme.setter
    def theme(self, value: str) -> None:
        self._settings.setValue("theme", value if value in ("system", "light", "dark") else "system")

    @property
    def size_metric(self) -> SizeMetric:
        raw = str(self._settings.value("size_metric", SizeMetric.ALLOCATED.value, type=str) or "")
        try:
            return SizeMetric(raw)
        except ValueError:
            return SizeMetric.ALLOCATED

    @size_metric.setter
    def size_metric(self, value: SizeMetric) -> None:
        self._settings.setValue("size_metric", SizeMetric(value).value)

    @property
    def treemap_mode(self) -> TreemapMode:
        raw = str(self._settings.value("treemap_mode", TreemapMode.SUBTREE.value, type=str) or "")
        try:
            return TreemapMode(raw)
        except ValueError:
            return TreemapMode.SUBTREE

    @treemap_mode.setter
    def treemap_mode(self, value: TreemapMode) -> None:
        self._settings.setValue("treemap_mode", TreemapMode(value).value)

    @property
    def show_hidden(self) -> bool:
        return self._bool("show_hidden", True)

    @show_hidden.setter
    def show_hidden(self, value: bool) -> None:
        self._settings.setValue("show_hidden", bool(value))

    @property
    def show_zero(self) -> bool:
        return self._bool("show_zero", True)

    @show_zero.setter
    def show_zero(self, value: bool) -> None:
        self._settings.setValue("show_zero", bool(value))

    @property
    def min_tile_area(self) -> float:
        try:
            value = float(self._settings.value("min_tile_area", 6.0))
        except (TypeError, ValueError):
            return 6.0
        return max(0.0, min(value, 400.0))

    @min_tile_area.setter
    def min_tile_area(self, value: float) -> None:
        self._settings.setValue("min_tile_area", max(0.0, min(float(value), 400.0)))

    @property
    def cross_device(self) -> bool:
        return self._bool("cross_device", False)

    @cross_device.setter
    def cross_device(self, value: bool) -> None:
        self._settings.setValue("cross_device", bool(value))

    @property
    def top_n(self) -> int:
        try:
            value = int(self._settings.value("top_n", 100))
        except (TypeError, ValueError):
            return 100
        return value if value in (20, 50, 100, 500) else 100

    @top_n.setter
    def top_n(self, value: int) -> None:
        self._settings.setValue("top_n", int(value))

    @property
    def view_mode(self) -> str:
        value = str(self._settings.value("view_mode", "map", type=str) or "map")
        return value if value in ("map", "tree", "largest") else "map"

    @view_mode.setter
    def view_mode(self, value: str) -> None:
        self._settings.setValue("view_mode", value if value in ("map", "tree", "largest") else "map")

    @property
    def filters_visible(self) -> bool:
        return self._bool("filters_visible", True)

    @filters_visible.setter
    def filters_visible(self, value: bool) -> None:
        self._settings.setValue("filters_visible", bool(value))

    @property
    def details_visible(self) -> bool:
        return self._bool("details_visible", True)

    @details_visible.setter
    def details_visible(self, value: bool) -> None:
        self._settings.setValue("details_visible", bool(value))

    # ------------------------------------------------------------- geometría
    def window_geometry(self) -> QByteArray | None:
        value = self._settings.value("window_geometry")
        return value if isinstance(value, QByteArray) and not value.isEmpty() else None

    def save_window_geometry(self, geometry: QByteArray) -> None:
        self._settings.setValue("window_geometry", geometry)

    def window_state(self) -> QByteArray | None:
        value = self._settings.value("window_state")
        return value if isinstance(value, QByteArray) and not value.isEmpty() else None

    def save_window_state(self, state: QByteArray) -> None:
        self._settings.setValue("window_state", state)

    def splitter_state(self) -> QByteArray | None:
        value = self._settings.value("splitter_state")
        return value if isinstance(value, QByteArray) and not value.isEmpty() else None

    def save_splitter_state(self, state: QByteArray) -> None:
        self._settings.setValue("splitter_state", state)
