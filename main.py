"""Punto de entrada de MacDirStat."""

from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtCore import QTimer

from app import APP_NAME
from app.application import create_application
from app.main_window import MainWindow


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="macdirstat", description=APP_NAME)
    parser.add_argument("--scan", metavar="CARPETA", help="analizar esta carpeta al arrancar")
    parser.add_argument("--smoke-test", action="store_true",
                        help="abrir la ventana y cerrarla automáticamente")
    parser.add_argument("--screenshot", metavar="PNG",
                        help="guardar una captura de la ventana y salir")
    parser.add_argument("--delay-ms", type=int, default=0,
                        help="retraso antes de la captura o del cierre")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    app = create_application(sys.argv[:1])
    window = MainWindow()
    window.show()
    delay = args.delay_ms or (2200 if args.scan else 700)
    if args.scan:
        QTimer.singleShot(0, lambda: window.start_scan(os.path.abspath(args.scan)))
    if args.screenshot:
        target = os.path.abspath(args.screenshot)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)

        def capture() -> None:
            pixmap = window.grab()
            if not pixmap.save(target, "PNG"):
                print(f"No se pudo guardar la captura en {target}", file=sys.stderr)
            app.quit()

        QTimer.singleShot(delay, capture)
    elif args.smoke_test:
        QTimer.singleShot(delay, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
