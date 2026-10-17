"""Arranque de QApplication y recursos de la aplicación."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME, BUNDLE_ID, ORG_NAME, __version__


def resource_path(*parts: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent
    return base.joinpath(*parts)


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication(argv if argv is not None else sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORG_NAME)
    app.setOrganizationDomain(BUNDLE_ID)
    app.setQuitOnLastWindowClosed(True)
    icon_path = resource_path("resources", "icons", "app.svg")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    return app


def is_macos() -> bool:
    return sys.platform == "darwin"
