#!/usr/bin/env python3
"""Crea un fixture sintético de N archivos para los benchmarks de MacDirStat.

Uso típico:

    python benchmarks/make_fixture.py --files 100000
    python benchmarks/make_fixture.py --files 100000 --root /ruta --clean

Genera ``--dirs`` carpetas con ``--files / --dirs`` archivos cada una, con
tamaños controlados por ``--seed``/``--max-bytes``, mide el tiempo de creación
y escribe un resumen JSON junto al fixture. No forma parte de pytest.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPO_ROOT / "benchmarks" / "tmp" / "fixture-100000"
INFO_PATH = REPO_ROOT / "benchmarks" / "tmp" / "fixture-info.json"

_EXTENSIONS = (".txt", ".log", ".jpg", ".png", ".mp4", ".zip", ".dmg", ".pdf", ".py", ".bin")


def build_fixture(root: Path, files: int, dirs: int, max_bytes: int, seed: int) -> dict:
    rng = random.Random(seed)
    before = time.monotonic()
    per_dir = max(1, files // dirs)
    remainder = files - per_dir * dirs
    total_bytes = 0
    created = 0
    zero_files = 0
    buffer = b"\x5a" * max_bytes

    for index in range(dirs):
        dir_path = root / f"dir-{index:03d}"
        dir_path.mkdir(parents=True, exist_ok=True)
        count = per_dir + (1 if index < remainder else 0)
        for file_index in range(count):
            ext = _EXTENSIONS[rng.randrange(len(_EXTENSIONS))]
            name = f"archivo-{file_index:05d}{ext}"
            path = dir_path / name
            if rng.random() < 0.2:
                size = 0
            else:
                size = rng.randint(1, max_bytes)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            try:
                if size:
                    os.write(fd, buffer[:size])
            finally:
                os.close(fd)
            created += 1
            total_bytes += size
            if size == 0:
                zero_files += 1
    elapsed = time.monotonic() - before
    return {
        "root": str(root),
        "files": created,
        "dirs": dirs,
        "zero_files": zero_files,
        "bytes_written": total_bytes,
        "seed": seed,
        "max_bytes": max_bytes,
        "creation_s": round(elapsed, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crea/limpia un fixture de benchmark.")
    parser.add_argument("--files", type=int, default=100000, help="número total de archivos")
    parser.add_argument("--dirs", type=int, default=100, help="número de carpetas")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="carpeta destino")
    parser.add_argument("--max-bytes", type=int, default=4096, help="tamaño máximo por archivo")
    parser.add_argument("--seed", type=int, default=20261017, help="semilla del generador")
    parser.add_argument("--clean", action="store_true", help="elimina el fixture y sale")
    args = parser.parse_args(argv)

    if args.files < 1 or args.dirs < 1 or args.files < args.dirs:
        parser.error("--files y --dirs deben ser ≥ 1 y --files ≥ --dirs")
    if args.max_bytes < 0:
        parser.error("--max-bytes no puede ser negativo")
    if args.max_bytes > 65536:
        parser.error("--max-bytes demasiado grande para un fixture de 100 000 archivos")

    root = args.root.expanduser().resolve()
    if args.clean:
        if root.exists():
            shutil.rmtree(root)
            print(f"Fixture eliminado: {root}")
        else:
            print(f"El fixture no existía: {root}")
        if INFO_PATH.exists():
            INFO_PATH.unlink()
        return 0

    if root.exists() and any(root.iterdir()):
        parser.error(f"{root} ya existe y no está vacío; usa --clean o --root")
    root.mkdir(parents=True, exist_ok=True)

    info = build_fixture(root, args.files, args.dirs, args.max_bytes, args.seed)
    INFO_PATH.parent.mkdir(parents=True, exist_ok=True)
    INFO_PATH.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(
        f"Fixture creado: {info['files']} archivos en {info['dirs']} carpetas "
        f"({info['bytes_written'] / 1e6:.1f} MB) en {info['creation_s']} s"
    )
    print(f"Ruta: {root}")
    print(f"Resumen: {INFO_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
