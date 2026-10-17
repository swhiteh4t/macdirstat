"""Ejecución del escaneo en un QThread y emisión de señales Qt."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..models.file_node import ScanOptions, ScanProgress, ScanResult, ScanStatus
from ..scanner import FileSystemScanner, RootScanError


class ScanWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    cancelled = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str, options: ScanOptions) -> None:
        super().__init__()
        self._path = path
        self._options = options
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        try:
            result = FileSystemScanner().scan(
                self._path,
                self._options,
                self._cancel,
                self.progress.emit,
            )
        except RootScanError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - el hilo no debe morir en silencio
            self.failed.emit(f"Error inesperado durante el análisis: {exc}")
            return
        if result.status is ScanStatus.CANCELLED:
            self.cancelled.emit(result)
        else:
            self.finished.emit(result)


class ScanController(QObject):
    """Orquesta un único escaneo a la vez y expone señales de alto nivel."""

    progress = Signal(object)   # ScanProgress
    finished = Signal(object)   # ScanResult
    cancelled = Signal(object)  # ScanResult parcial
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._pending: tuple[str, object] | None = None
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def start(self, path: str, options: ScanOptions | None = None) -> bool:
        if self._running or (self._thread is not None and self._thread.isRunning()):
            return False
        options = options or ScanOptions()
        self._thread = QThread(self)
        self._worker = ScanWorker(path, options)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.finished.connect(self._on_worker_done)
        self._worker.cancelled.connect(self._on_worker_done)
        self._worker.failed.connect(self._on_worker_failed)
        for signal in (self._worker.finished, self._worker.cancelled, self._worker.failed):
            signal.connect(self._thread.quit)
        self._thread.finished.connect(self._on_thread_finished)
        self._running = True
        self._pending = None
        self._thread.start()
        return True

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def shutdown(self, timeout_ms: int = 5000) -> None:
        self.cancel()
        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.wait(timeout_ms)
        self._running = False

    @Slot(object)
    def _on_worker_done(self, result: ScanResult) -> None:
        kind = "cancelled" if result.status is ScanStatus.CANCELLED else "finished"
        self._pending = (kind, result)

    @Slot(str)
    def _on_worker_failed(self, message: str) -> None:
        self._pending = ("failed", message)

    @Slot()
    def _on_thread_finished(self) -> None:
        self._running = False
        pending = self._pending
        self._pending = None
        worker = self._worker
        self._worker = None
        thread = self._thread
        self._thread = None
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        if pending is None:
            self.failed.emit("El análisis terminó sin resultado.")
        elif pending[0] == "failed":
            self.failed.emit(str(pending[1]))
        elif pending[0] == "cancelled":
            self.cancelled.emit(pending[1])
        else:
            self.finished.emit(pending[1])
