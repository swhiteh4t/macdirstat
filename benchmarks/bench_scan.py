#!/usr/bin/env python3
"""Benchmark de escaneo, layout, repintado y memoria de MacDirStat.

Uso típico (tras crear el fixture con make_fixture.py):

    python benchmarks/bench_scan.py --fixture benchmarks/tmp/fixture-100000
    python benchmarks/bench_scan.py --fixture <ruta> --paint 60

Mide: escaneo, latencia de cancelación, construcción del snapshot, layout en
modo subárbol y nivel, número de fichas, RSS máximo y (opcional, offscreen)
p95 de repintado con ~5 000 fichas. Escribe un informe Markdown y un JSON con
los datos crudos en benchmarks/tmp/. No forma parte de pytest.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.models.file_node import ScanOptions, ScanStatus, SizeMetric  # noqa: E402
from app.scanner.filesystem_scanner import FileSystemScanner  # noqa: E402
from app.services.filter_engine import FilterEngine, FilterState  # noqa: E402
from app.treemap.layout_engine import (  # noqa: E402
    LayoutRequest,
    Rect,
    TreemapLayoutEngine,
    TreemapMode,
)

DEFAULT_FIXTURE = REPO_ROOT / "benchmarks" / "tmp" / "fixture-100000"
TMP_DIR = REPO_ROOT / "benchmarks" / "tmp"


def rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    factor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
    return usage / factor


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def measure_scan(path: str) -> dict:
    scanner = FileSystemScanner()
    progress_times: list[float] = []
    progress_files: list[int] = []

    def on_progress(progress) -> None:
        progress_times.append(time.monotonic())
        progress_files.append(progress.files)

    started = time.monotonic()
    result = scanner.scan(path, ScanOptions(), progress=on_progress)
    elapsed = time.monotonic() - started
    gaps = [
        progress_times[i + 1] - progress_times[i] for i in range(len(progress_times) - 1)
    ]
    return {
        "scan_s": elapsed,
        "status": str(result.status),
        "files": result.stats.files,
        "dirs": result.stats.dirs,
        "errors": result.stats.error_count,
        "progress_events": len(progress_times),
        "progress_max_gap_s": max(gaps) if gaps else 0.0,
        "result": result,
    }


def measure_cancel(path: str, delay_s: float = 0.25) -> dict | None:
    cancel = threading.Event()
    box: dict = {}

    def run() -> None:
        started = time.monotonic()
        result = FileSystemScanner().scan(path, ScanOptions(), cancel=cancel)
        box["elapsed"] = time.monotonic() - started
        box["result"] = result

    timer = threading.Timer(delay_s, cancel.set)
    timer.daemon = True
    thread = threading.Thread(target=run, daemon=True)
    timer.start()
    thread.start()
    thread.join(timeout=300)
    timer.cancel()
    result = box.get("result")
    if result is None:
        return None
    if result.status is not ScanStatus.CANCELLED:
        return {"cancelled": False, "scan_s": box["elapsed"]}
    return {
        "cancelled": True,
        "scan_s": box["elapsed"],
        "latency_s": max(0.0, box["elapsed"] - delay_s),
    }


def measure_layouts(snapshot, result, width: float, height: float) -> dict:
    engine = TreemapLayoutEngine()
    out: dict = {}
    for name, mode in (("subtree", TreemapMode.SUBTREE), ("children", TreemapMode.CHILDREN)):
        request = LayoutRequest(
            root=result.root,
            snapshot=snapshot,
            rect=Rect(0.0, 0.0, width, height),
            mode=mode,
            min_tile_area=6.0,
        )
        best = None
        for _ in range(3):
            started = time.monotonic()
            layout = engine.layout(request)
            elapsed = time.monotonic() - started
            if best is None or elapsed < best:
                best = elapsed
        out[f"layout_{name}_s"] = best
        out[f"tiles_{name}"] = len(layout.tiles)
        out[f"truncated_{name}"] = layout.truncated
        out[f"aggregated_{name}"] = layout.aggregated_nodes
    area_10k, tiles_10k = shrink_min_tile_area(
        snapshot, result.root, width, height, target=10_000
    )
    request = LayoutRequest(
        root=result.root,
        snapshot=snapshot,
        rect=Rect(0.0, 0.0, width, height),
        mode=TreemapMode.SUBTREE,
        min_tile_area=area_10k,
    )
    best = None
    for _ in range(3):
        started = time.monotonic()
        layout = engine.layout(request)
        elapsed = time.monotonic() - started
        if best is None or elapsed < best:
            best = elapsed
    out["layout_subtree_10k_s"] = best
    out["tiles_subtree_10k"] = len(layout.tiles)
    out["min_tile_area_10k"] = area_10k
    return out


def shrink_min_tile_area(snapshot, root, width: float, height: float, target: int) -> tuple[float, int]:
    """Busca el menor ``min_tile_area`` cuya cantidad de fichas sea ≤ ``target``."""
    engine = TreemapLayoutEngine()

    def tiles_at(area: float) -> int:
        request = LayoutRequest(
            root=root,
            snapshot=snapshot,
            rect=Rect(0.0, 0.0, width, height),
            mode=TreemapMode.SUBTREE,
            min_tile_area=area,
        )
        return len(engine.layout(request).tiles)

    if tiles_at(6.0) <= target:
        return 6.0, tiles_at(6.0)
    lo, hi = 6.0, 12.0
    while tiles_at(hi) > target and hi < 6.0 * 2**12:
        lo, hi = hi, hi * 2.0
    for _ in range(12):
        mid = (lo + hi) / 2.0
        if tiles_at(mid) <= target:
            hi = mid
        else:
            lo = mid
    return hi, tiles_at(hi)


def measure_paint(snapshot, root, width: int, height: int, iterations: int) -> dict:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    from app.theme import apply_theme  # noqa: PLC0415
    from app.treemap.treemap_widget import TreemapWidget  # noqa: PLC0415

    app = QApplication.instance() or QApplication([])
    theme = apply_theme(app, "dark")

    def paint_with(min_tile_area: float) -> dict:
        from PySide6.QtGui import QPixmap  # noqa: PLC0415

        widget = TreemapWidget()
        widget.set_theme(theme)
        widget.set_min_tile_area(min_tile_area)
        widget.set_snapshot(snapshot)
        widget.set_view_root(root)
        widget.set_mode(TreemapMode.SUBTREE)
        widget.resize(width, height)
        widget.show()
        deadline = time.monotonic() + 120.0
        while widget.layout_result is None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        layout = widget.layout_result
        if layout is None:
            widget.deleteLater()
            return {"error": "layout no terminó", "min_tile_area": min_tile_area}
        target = QPixmap(width, height)
        for _ in range(5):  # calentamiento
            widget.render(target)
        samples: list[float] = []
        for _ in range(iterations):
            started = time.perf_counter()
            widget.render(target)
            samples.append((time.perf_counter() - started) * 1000.0)
        widget.deleteLater()
        app.processEvents()
        return {
            "tiles": len(layout.tiles),
            "min_tile_area": min_tile_area,
            "iterations": len(samples),
            "mean_ms": statistics.fmean(samples),
            "p95_ms": percentile(samples, 0.95),
            "min_ms": min(samples),
            "max_ms": max(samples),
        }

    configured = paint_with(6.0)
    area, target_tiles = shrink_min_tile_area(
        snapshot, root, float(width), float(height), target=5000
    )
    if abs(area - 6.0) < 1e-9:
        tuned = configured
    else:
        tuned = paint_with(area)
        tuned["note"] = (
            f"min_tile_area ajustado a {area:g} para {target_tiles} fichas (objetivo ≤ 5 000)"
        )
    return {"configured": configured, "for_5k_tiles": tuned}


def env_summary() -> dict:
    mac_version = platform.mac_ver()[0] or "?"
    return {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": f"macOS {mac_version} ({platform.machine()})",
        "python": platform.python_version(),
        "cpus": os.cpu_count(),
    }


def format_markdown(env: dict, fixture: dict, scan: dict, cancel: dict | None,
                    layout: dict, paint: dict | None) -> str:
    def fmt(value: float, unit: str = "s") -> str:
        return f"{value:.3f} {unit}"

    lines = [
        "# Benchmark de escaneo y layout — MacDirStat",
        "",
        f"- Fecha: {env['date']}",
        f"- Entorno: {env['platform']}, Python {env['python']}, {env['cpus']} CPUs",
        f"- Fixture: `{fixture['root']}` — {fixture['files']} archivos, "
        f"{fixture['dirs']} carpetas, {fixture['bytes_written'] / 1e6:.1f} MB lógicos "
        f"(creado en {fixture['creation_s']} s)",
        "",
        "| Medición | Valor |",
        "|---|---|",
        f"| Escaneo | {fmt(scan['scan_s'])} (estado {scan['status']}, "
        f"{scan['files']} archivos, {scan['errors']} errores) |",
        f"| Progreso de escaneo | {scan['progress_events']} eventos, "
        f"intervalo máximo {fmt(scan['progress_max_gap_s'])} |",
    ]
    if cancel and cancel.get("cancelled"):
        lines.append(
            f"| Cancelación | latencia {fmt(cancel['latency_s'])} "
            f"(cancel solicitada a los 0,25 s) |"
        )
    else:
        lines.append("| Cancelación | no medida (el escaneo terminó antes) |")
    lines += [
        f"| Snapshot de filtros | {fmt(layout['snapshot_s'])} |",
        f"| Layout subárbol completo | {fmt(layout['layout_subtree_s'])}, "
        f"{layout['tiles_subtree']} fichas, truncado={layout['truncated_subtree']} |",
        f"| Layout subárbol ~10 000 fichas | {fmt(layout['layout_subtree_10k_s'])}, "
        f"{layout['tiles_subtree_10k']} fichas, min área {layout['min_tile_area_10k']:g} |",
        f"| Layout nivel actual | {fmt(layout['layout_children_s'])}, "
        f"{layout['tiles_children']} fichas |",
        f"| RSS máximo tras escaneo | {layout['rss_scan_mb']:.0f} MB "
        f"(base {layout['rss_base_mb']:.0f} MB, delta {layout['rss_scan_mb'] - layout['rss_base_mb']:.0f} MB) |",
        f"| RSS máximo total | {layout['rss_peak_mb']:.0f} MB |",
    ]
    if paint:
        configured = paint["configured"]
        tuned = paint["for_5k_tiles"]
        if "error" not in configured:
            lines.append(
                f"| Repintado ({configured['tiles']} fichas, min área "
                f"{configured['min_tile_area']:g}) | media {configured['mean_ms']:.1f} ms, "
                f"p95 {configured['p95_ms']:.1f} ms, n={configured['iterations']} |"
            )
        if "error" not in tuned:
            note = tuned.get("note", "")
            suffix = f" — {note}" if note else ""
            lines.append(
                f"| Repintado ({tuned['tiles']} fichas objetivo ≤ 5 000) | media "
                f"{tuned['mean_ms']:.1f} ms, p95 {tuned['p95_ms']:.1f} ms, "
                f"n={tuned['iterations']}{suffix} |"
            )
    lines += [
        "",
        "Objetivos del plan: layout 10 000 fichas p95 ≤ 300 ms; repintado 5 000 "
        "fichas p95 ≤ 16 ms; memoria 100 000 nodos ≤ 300 MB; progreso ≤ 200 ms.",
        "",
    ]
    return "\n".join(line for line in lines if line is not None) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark de MacDirStat sobre un fixture.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--paint", type=int, default=0, metavar="N",
                        help="iteraciones de repintado offscreen (0 = omitir)")
    parser.add_argument("--out", type=Path, default=TMP_DIR / "bench-scan.md")
    parser.add_argument("--json", type=Path, default=TMP_DIR / "bench-scan.json")
    args = parser.parse_args(argv)

    fixture_path = args.fixture.expanduser().resolve()
    if not fixture_path.is_dir():
        parser.error(f"fixture no encontrado: {fixture_path} (crea uno con make_fixture.py)")

    info_path = TMP_DIR / "fixture-info.json"
    if info_path.exists():
        try:
            fixture = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            fixture = None
    else:
        fixture = None
    if not fixture or Path(fixture.get("root", "")) != fixture_path:
        files = dirs = 0
        for _, dirnames, filenames in os.walk(fixture_path):
            dirs += len(dirnames)
            files += len(filenames)
        fixture = {
            "root": str(fixture_path),
            "files": files,
            "dirs": dirs,
            "bytes_written": 0,
            "creation_s": 0.0,
        }

    env = env_summary()
    rss_base = rss_mb()
    print(f"Fixture: {fixture_path} ({fixture['files']} archivos)")
    print("Escaneando…")

    scan = measure_scan(str(fixture_path))
    result = scan.pop("result")
    rss_after_scan = rss_mb()

    snapshot_started = time.monotonic()
    snapshot = FilterEngine().build_snapshot(
        result, FilterState(), SizeMetric.LOGICAL, revision=1
    )
    if snapshot is None:
        raise RuntimeError("No se pudo construir el snapshot del filtro")
    snapshot_s = time.monotonic() - snapshot_started

    layouts = measure_layouts(snapshot, result, float(args.width), float(args.height))
    layouts["snapshot_s"] = snapshot_s

    print("Midiendo cancelación…")
    cancel = measure_cancel(str(fixture_path))

    paint = None
    if args.paint > 0:
        print(f"Midiendo repintado ({args.paint} iteraciones por variante)…")
        paint = measure_paint(snapshot, result.root, args.width, args.height, args.paint)

    layouts["rss_base_mb"] = rss_base
    layouts["rss_scan_mb"] = rss_after_scan
    layouts["rss_peak_mb"] = rss_mb()

    markdown = format_markdown(env, fixture, scan, cancel, layouts, paint)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")

    payload = {
        "env": env,
        "fixture": fixture,
        "scan": scan,
        "cancel": cancel,
        "layout": layouts,
        "paint": paint,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")

    print()
    print(markdown)
    print(f"Informe: {args.out}")
    print(f"Datos crudos: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
