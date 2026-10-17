"""Paleta visual y colores por categoría, con soporte claro/oscuro."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from .models.categories import Category


_LIGHT_CATEGORIES: dict[Category, str] = {
    Category.DOCUMENTS: "#3E6FA3",
    Category.IMAGES: "#2E8A74",
    Category.VIDEO: "#7A5AA6",
    Category.AUDIO: "#B7791F",
    Category.ARCHIVE: "#B24C4C",
    Category.APPS: "#9A7B00",
    Category.CODE: "#2B7A8A",
    Category.SYSTEM: "#6B7280",
    Category.OTHER: "#8A94A6",
}

_DARK_CATEGORIES: dict[Category, str] = {
    Category.DOCUMENTS: "#6FA8DC",
    Category.IMAGES: "#5CC8A8",
    Category.VIDEO: "#B49BE0",
    Category.AUDIO: "#E0A458",
    Category.ARCHIVE: "#E07A7A",
    Category.APPS: "#D4B84A",
    Category.CODE: "#62B6C7",
    Category.SYSTEM: "#8C97A8",
    Category.OTHER: "#AAB4C4",
}


@dataclass(frozen=True, slots=True)
class ThemePalette:
    dark: bool
    window: QColor
    surface: QColor
    surface_alt: QColor
    text: QColor
    muted: QColor
    border: QColor
    accent: QColor
    warning: QColor
    error: QColor
    success: QColor
    directory: QColor
    directory_header: QColor
    aggregate: QColor
    categories: dict[Category, QColor]

    def category_color(self, category: Category) -> QColor:
        return self.categories.get(category, self.categories[Category.OTHER])

    @staticmethod
    def contrasting_text(background: QColor) -> QColor:
        # Luminancia relativa aproximada (sRGB).
        r, g, b = background.redF(), background.greenF(), background.blueF()
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return QColor("#101418") if luminance > 0.58 else QColor("#F7F9FC")


def _is_dark(app: QApplication) -> bool:
    hints = app.styleHints()
    try:
        return hints.colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return app.palette().color(QPalette.Window).lightness() < 128


def build_theme(app: QApplication) -> ThemePalette:
    dark = _is_dark(app)
    palette = app.palette()
    window = palette.color(QPalette.Window)
    base = palette.color(QPalette.Base)
    text = palette.color(QPalette.Text)
    muted = QColor(text)
    muted.setAlpha(150)
    border = QColor(text)
    border.setAlpha(45)
    if dark:
        surface = QColor("#1C222B")
        surface_alt = QColor("#232B36")
        directory = QColor("#2B3543")
        directory_header = QColor("#39485A")
        aggregate = QColor("#59667A")
        accent = QColor("#5FA8FF")
        warning = QColor("#E5A84B")
        error = QColor("#E57575")
        success = QColor("#6CC59A")
    else:
        surface = QColor("#F7F9FC")
        surface_alt = QColor("#EDF1F7")
        directory = QColor("#DCE3EC")
        directory_header = QColor("#C8D3E0")
        aggregate = QColor("#B7C1CE")
        accent = QColor("#1D6FB8")
        warning = QColor("#A86A00")
        error = QColor("#B03A3A")
        success = QColor("#2F7D5A")
    sources = _DARK_CATEGORIES if dark else _LIGHT_CATEGORIES
    categories = {category: QColor(value) for category, value in sources.items()}
    return ThemePalette(
        dark=dark,
        window=window,
        surface=surface,
        surface_alt=surface_alt,
        text=text,
        muted=muted,
        border=border,
        accent=accent,
        warning=warning,
        error=error,
        success=success,
        directory=directory,
        directory_header=directory_header,
        aggregate=aggregate,
        categories=categories,
    )


def stylesheet_for(theme: ThemePalette) -> str:
    hover = "rgba(255,255,255,0.10)" if theme.dark else "rgba(0,0,0,0.055)"
    pressed = "rgba(255,255,255,0.16)" if theme.dark else "rgba(0,0,0,0.10)"
    selected = theme.accent.name()
    return f"""
    QToolBar {{
        border: 0;
        spacing: 6px;
        padding: 4px 6px;
    }}
    QToolBar::separator {{
        background: {theme.border.name(QColor.HexArgb)};
        width: 1px;
        margin: 5px 4px;
    }}
    QToolButton {{
        border: 0;
        border-radius: 6px;
        padding: 5px 8px;
    }}
    QToolButton:hover {{ background: {hover}; }}
    QToolButton:pressed {{ background: {pressed}; }}
    QToolButton:checked {{
        background: {theme.accent.name()};
        color: #FFFFFF;
    }}
    QToolButton::menu-indicator {{ image: none; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        border: 1px solid {theme.border.name(QColor.HexArgb)};
        border-radius: 6px;
        padding: 4px 6px;
        background: {theme.surface_alt.name()};
        selection-background-color: {selected};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {theme.accent.name()};
    }}
    QTreeView, QTableView {{
        border: 1px solid {theme.border.name(QColor.HexArgb)};
        border-radius: 8px;
        background: {theme.surface.name()};
        alternate-background-color: {theme.surface_alt.name()};
        selection-background-color: {selected};
        selection-color: #FFFFFF;
        outline: 0;
    }}
    QHeaderView::section {{
        background: {theme.surface_alt.name()};
        border: 0;
        border-bottom: 1px solid {theme.border.name(QColor.HexArgb)};
        padding: 5px 6px;
        font-weight: 600;
    }}
    QFrame#DetailsPanel {{
        background: {theme.surface.name()};
        border: 1px solid {theme.border.name(QColor.HexArgb)};
        border-radius: 10px;
    }}
    QLabel#DetailsTitle {{ font-size: 17px; font-weight: 600; }}
    QLabel#SectionTitle {{ font-weight: 600; }}
    QLabel#Muted {{ color: {theme.muted.name(QColor.HexArgb)}; }}
    QLabel#Banner {{
        background: {theme.surface_alt.name()};
        border: 1px solid {theme.border.name(QColor.HexArgb)};
        border-radius: 8px;
        padding: 7px 10px;
    }}
    QStatusBar {{ border-top: 1px solid {theme.border.name(QColor.HexArgb)}; }}
    QProgressBar {{
        border: 0;
        border-radius: 3px;
        background: {theme.surface_alt.name()};
        max-height: 6px;
    }}
    QProgressBar::chunk {{ background: {theme.accent.name()}; border-radius: 3px; }}
    QSplitter::handle {{ background: transparent; }}
    """


def apply_theme(app: QApplication, preference: str = "system") -> ThemePalette:
    if preference in ("light", "dark"):
        try:
            app.styleHints().setColorScheme(
                Qt.ColorScheme.Light if preference == "light" else Qt.ColorScheme.Dark
            )
        except (AttributeError, RuntimeError):
            pass
    theme = build_theme(app)
    app.setStyleSheet(stylesheet_for(theme))
    return theme
