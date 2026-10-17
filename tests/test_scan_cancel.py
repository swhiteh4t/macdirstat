"""Pruebas de cancelación del escaneo (caso 12 del plan)."""

from __future__ import annotations

import threading

from app.models.file_node import ScanOptions, ScanStatus
from app.scanner import FileSystemScanner


def test_cancel_returns_partial_result(make_tree):
    root = make_tree({f"d{i}/f{i}.bin": 100 for i in range(50)})
    cancel = threading.Event()
    cancel.set()  # cancelado antes de empezar
    result = FileSystemScanner().scan(str(root), ScanOptions(), cancel)
    assert result.status is ScanStatus.CANCELLED
    # El resultado sigue siendo un árbol válido y utilizable.
    assert result.root is not None
    assert result.root.total_files >= 0


def test_cancel_mid_scan_stops_early(make_tree):
    root = make_tree({f"d{i}/f{i}.bin": 100 for i in range(200)})
    cancel = threading.Event()
    seen = {"files": 0}

    def on_progress(progress):
        seen["files"] = progress.files
        if progress.files >= 50:
            cancel.set()

    result = FileSystemScanner().scan(
        str(root), ScanOptions(progress_interval_ms=0), cancel, on_progress
    )
    assert result.status is ScanStatus.CANCELLED
    assert seen["files"] >= 50
    assert result.stats.files < 200  # no terminó el recorrido completo
    assert result.elapsed_s >= 0


def test_no_cancel_completes(make_tree):
    root = make_tree({f"d{i}/f{i}.bin": 10 for i in range(20)})
    result = FileSystemScanner().scan(str(root))
    assert result.status is ScanStatus.COMPLETE
    assert result.stats.files == 20
