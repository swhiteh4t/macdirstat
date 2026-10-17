"""Leyenda de colores del treemap."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QWidget

from ..models.categories import CATEGORY_LABELS, CATEGORY_ORDER, Category
from ..theme import ThemePalette


class LegendWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme: ThemePalette | None = None
        self._swatches: dict[str, QLabel] = {}
        layout = QGridLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(3)
        items: list[tuple[str, Category | None]] = [
            (CATEGORY_LABELS[category], category) for category in CATEGORY_ORDER
        ]
        items.extend([("Carpeta", None), ("Agrupados", None)])
        for index, (label, category) in enumerate(items):
            row, column = divmod(index, 6)
            cell = QHBoxLayout()
            cell.setSpacing(4)
            swatch = QLabel()
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet("border-radius: 2px; background: #8A94A6;")
            cell.addWidget(swatch)
            text = QLabel(label)
            text.setObjectName("Muted")
            font = text.font()
            font.setPointSizeF(max(8.0, font.pointSizeF() - 1.0))
            text.setFont(font)
            cell.addWidget(text)
            cell.addStretch(1)
            container = QWidget()
            container.setLayout(cell)
            layout.addWidget(container, row, column)
            key = category.value if category is not None else (
                "directory" if label == "Carpeta" else "aggregate"
            )
            self._swatches[key] = swatch
        self.setToolTip(
            "Color por categoría. Las carpetas usan un color neutro; "
            "«Agrupados» indica elementos unidos por el umbral de tamaño visible."
        )

    def set_theme(self, theme: ThemePalette) -> None:
        self._theme = theme
        for category in CATEGORY_ORDER:
            swatch = self._swatches.get(category.value)
            if swatch is not None:
                swatch.setStyleSheet(
                    f"border-radius: 2px; background: {theme.category_color(category).name()};"
                )
        if "directory" in self._swatches:
            self._swatches["directory"].setStyleSheet(
                f"border-radius: 2px; background: {theme.directory_header.name()};"
            )
        if "aggregate" in self._swatches:
            self._swatches["aggregate"].setStyleSheet(
                f"border-radius: 2px; background: {theme.aggregate.name()};"
            )
