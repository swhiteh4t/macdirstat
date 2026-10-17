"""Barra de búsqueda y filtros."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..models.categories import CATEGORY_LABELS, CATEGORY_ORDER, Category
from ..services.filter_engine import FilterState


_MB = 1024 * 1024


def _parse_extensions(text: str) -> frozenset[str]:
    tokens = [token.strip().lstrip(".").casefold() for token in re.split(r"[,;\s]+", text)]
    return frozenset(token for token in tokens if token)


def _parse_patterns(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


class FilterBar(QWidget):
    filtersChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._updating = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(240)
        self._debounce.timeout.connect(self._emit_state)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 6)
        root.setSpacing(6)
        first = QHBoxLayout()
        first.setSpacing(7)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por nombre o extensión…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Buscar elementos por nombre o extensión")
        self.search.setToolTip("Busca por nombre; escribe .pdf para una extensión exacta")
        self.search.textChanged.connect(self._on_text)
        first.addWidget(self.search, 3)

        self.category_button = QToolButton()
        self.category_button.setText("Categorías")
        self.category_button.setPopupMode(QToolButton.InstantPopup)
        self.category_button.setToolTip("Filtrar por categorías de archivo")
        self.category_button.setAccessibleName("Filtrar por categorías")
        menu = QMenu(self.category_button)
        self._category_actions: dict[Category, object] = {}
        for category in CATEGORY_ORDER:
            action = menu.addAction(CATEGORY_LABELS[category])
            action.setCheckable(True)
            action.toggled.connect(self._on_categories)
            self._category_actions[category] = action
        menu.addSeparator()
        clear_categories = menu.addAction("Todas las categorías")
        clear_categories.triggered.connect(self._clear_categories)
        self.category_button.setMenu(menu)
        first.addWidget(self.category_button)

        self.extensions = QLineEdit()
        self.extensions.setPlaceholderText("Extensiones: pdf, jpg…")
        self.extensions.setClearButtonEnabled(True)
        self.extensions.setAccessibleName("Filtrar por extensiones")
        self.extensions.setToolTip("Lista separada por comas, sin el punto inicial")
        self.extensions.textChanged.connect(self._on_text)
        first.addWidget(self.extensions, 2)
        self.hidden = QCheckBox("Ocultos")
        self.hidden.setToolTip("Mostrar archivos y directorios ocultos")
        self.hidden.setChecked(True)
        self.hidden.toggled.connect(self._emit_state)
        first.addWidget(self.hidden)
        self.zero = QCheckBox("0 bytes")
        self.zero.setToolTip("Mostrar archivos de tamaño cero (no se dibujan en el mapa)")
        self.zero.setChecked(True)
        self.zero.toggled.connect(self._emit_state)
        first.addWidget(self.zero)
        root.addLayout(first)

        second = QHBoxLayout()
        second.setSpacing(7)
        second.addWidget(QLabel("Mín"))
        self.min_mb = QDoubleSpinBox()
        self.min_mb.setRange(0.0, 1_000_000.0)
        self.min_mb.setDecimals(2)
        self.min_mb.setSuffix(" MB")
        self.min_mb.setSpecialValueText("Sin mínimo")
        self.min_mb.setToolTip("Tamaño mínimo del archivo en MB; 0 = sin mínimo")
        self.min_mb.valueChanged.connect(self._emit_state)
        second.addWidget(self.min_mb)
        second.addWidget(QLabel("Máx"))
        self.max_mb = QDoubleSpinBox()
        self.max_mb.setRange(0.0, 1_000_000.0)
        self.max_mb.setDecimals(2)
        self.max_mb.setSuffix(" MB")
        self.max_mb.setSpecialValueText("Sin máximo")
        self.max_mb.setToolTip("Tamaño máximo del archivo en MB; 0 = sin máximo")
        self.max_mb.valueChanged.connect(self._emit_state)
        second.addWidget(self.max_mb)

        second.addWidget(QLabel("Excluir"))
        self.excluded = QLineEdit()
        self.excluded.setPlaceholderText(".git, node_modules…")
        self.excluded.setClearButtonEnabled(True)
        self.excluded.setToolTip("Patrones de directorios separados por comas")
        self.excluded.setAccessibleName("Directorios excluidos")
        self.excluded.textChanged.connect(self._on_text)
        second.addWidget(self.excluded, 2)

        second.addWidget(QLabel("Ficha mín."))
        self.min_area = QSpinBox()
        self.min_area.setRange(0, 200)
        self.min_area.setSuffix(" px²")
        self.min_area.setValue(6)
        self.min_area.setToolTip(
            "Los elementos cuya ficha sería menor se agrupan en «Otros»; no se pierden datos"
        )
        self.min_area.valueChanged.connect(self._on_min_area)
        second.addWidget(self.min_area)

        self.clear_button = QPushButton("Limpiar filtros")
        self.clear_button.clicked.connect(self.clear_filters)
        second.addWidget(self.clear_button)
        root.addLayout(second)

    # ---------------------------------------------------------------- public
    def state(self) -> FilterState:
        min_bytes = int(round(self.min_mb.value() * _MB))
        max_value = int(round(self.max_mb.value() * _MB))
        categories = frozenset(
            category for category, action in self._category_actions.items() if action.isChecked()
        )
        return FilterState(
            query=self.search.text().strip(),
            extensions=_parse_extensions(self.extensions.text()),
            categories=categories,
            min_bytes=max(0, min_bytes),
            max_bytes=max_value if max_value > 0 else None,
            show_hidden=self.hidden.isChecked(),
            show_zero=self.zero.isChecked(),
            excluded_dirs=_parse_patterns(self.excluded.text()),
            min_tile_area=float(self.min_area.value()),
        )

    def set_state(self, state: FilterState) -> None:
        self._updating = True
        try:
            self.search.setText(state.query)
            self.extensions.setText(", ".join(sorted(state.extensions)))
            for category, action in self._category_actions.items():
                action.setChecked(category in state.categories)
            self.min_mb.setValue(state.min_bytes / _MB)
            self.max_mb.setValue((state.max_bytes or 0) / _MB)
            self.hidden.setChecked(state.show_hidden)
            self.zero.setChecked(state.show_zero)
            self.excluded.setText(", ".join(state.excluded_dirs))
            self.min_area.setValue(int(round(state.min_tile_area)))
            self._update_category_button()
        finally:
            self._updating = False

    def clear_filters(self) -> None:
        area = self.min_area.value()
        self._updating = True
        try:
            self.search.clear()
            self.extensions.clear()
            for action in self._category_actions.values():
                action.setChecked(False)
            self.min_mb.setValue(0)
            self.max_mb.setValue(0)
            self.hidden.setChecked(True)
            self.zero.setChecked(True)
            self.excluded.clear()
            self.min_area.setValue(area)
            self._update_category_button()
        finally:
            self._updating = False
        self._emit_state()

    # --------------------------------------------------------------- events
    def _on_text(self) -> None:
        if not self._updating:
            self._debounce.start()

    def _on_min_area(self) -> None:
        if not self._updating:
            self._emit_state()

    def _on_categories(self) -> None:
        if self._updating:
            return
        self._update_category_button()
        self._emit_state()

    def _clear_categories(self) -> None:
        self._updating = True
        for action in self._category_actions.values():
            action.setChecked(False)
        self._updating = False
        self._update_category_button()
        self._emit_state()

    def _update_category_button(self) -> None:
        count = sum(1 for action in self._category_actions.values() if action.isChecked())
        self.category_button.setText("Categorías" if count == 0 else f"Categorías ({count})")

    def _emit_state(self) -> None:
        if self._updating:
            return
        self.filtersChanged.emit(self.state())
