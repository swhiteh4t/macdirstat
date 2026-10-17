"""Construcción asíncrona de snapshots de filtros para volúmenes grandes."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..models.file_node import ScanResult, SizeMetric
from ..services.filter_engine import FilterEngine, FilterSnapshot, FilterState


class _SnapshotSignals(QObject):
    done = Signal(int, object)


class _SnapshotTask(QRunnable):
    def __init__(self, generation: int, result: ScanResult, state: FilterState,
                 metric: SizeMetric, signals: _SnapshotSignals) -> None:
        super().__init__()
        self._generation = generation
        self._result = result
        self._state = state
        self._metric = metric
        self._signals = signals

    def run(self) -> None:
        try:
            snapshot = FilterEngine().build_snapshot(
                self._result,
                self._state,
                self._metric,
                revision=self._generation,
            )
        except Exception:  # noqa: BLE001
            snapshot = None
        self._signals.done.emit(self._generation, snapshot)


class SnapshotController(QObject):
    ready = Signal(int, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tasks: dict[int, tuple[_SnapshotTask, _SnapshotSignals]] = {}

    def submit(self, generation: int, result: ScanResult, state: FilterState,
               metric: SizeMetric) -> None:
        signals = _SnapshotSignals()
        task = _SnapshotTask(generation, result, state, metric, signals)
        signals.done.connect(self._on_done)
        self._tasks[generation] = (task, signals)
        QThreadPool.globalInstance().start(task)

    def _on_done(self, generation: int, snapshot: FilterSnapshot | None) -> None:
        self._tasks.pop(generation, None)
        self.ready.emit(generation, snapshot)

    def active(self) -> bool:
        return bool(self._tasks)
