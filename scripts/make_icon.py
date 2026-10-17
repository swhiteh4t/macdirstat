"""Genera AppIcon.icns a partir de app.svg usando Qt + iconutil."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SPECS = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--svg", default=str(Path(__file__).resolve().parents[1] / "app/resources/icons/app.svg"))
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "build/AppIcon.icns"))
    args = parser.parse_args()
    app = QGuiApplication(sys.argv[:1])  # noqa: F841
    svg = Path(args.svg)
    if not svg.exists():
        print(f"Falta {svg}", file=sys.stderr)
        return 1
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        print("El SVG no es válido", file=sys.stderr)
        return 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        iconset = Path(temp_dir) / "AppIcon.iconset"
        iconset.mkdir()
        for name, size in SPECS:
            image = QImage(size, size, QImage.Format_ARGB32)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing, True)
            renderer.render(painter, QRectF(0, 0, size, size))
            painter.end()
            if not image.save(str(iconset / name), "PNG"):
                print(f"No se pudo generar {name}", file=sys.stderr)
                return 1
        if shutil.which("iconutil") is None:
            print("iconutil no está disponible (requiere macOS).", file=sys.stderr)
            return 1
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(output)], check=True)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
