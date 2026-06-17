"""In-memory rolling time-series store for collected metrics."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Iterable

from ..models import MetricPoint


class TimeSeriesStore:
    """Thread-safe ring buffer of metric points keyed by (service, metric)."""

    def __init__(self, window: int = 600) -> None:
        self._window = window
        self._series: dict[tuple[str, str], deque[MetricPoint]] = defaultdict(
            lambda: deque(maxlen=window)
        )
        self._lock = threading.Lock()

    def add(self, point: MetricPoint) -> None:
        with self._lock:
            self._series[(point.service, point.metric)].append(point)

    def add_many(self, points: Iterable[MetricPoint]) -> None:
        for p in points:
            self.add(p)

    def values(self, service: str, metric: str) -> list[float]:
        with self._lock:
            return [p.value for p in self._series[(service, metric)]]

    def recent(self, service: str, metric: str, n: int = 50) -> list[MetricPoint]:
        with self._lock:
            return list(self._series[(service, metric)])[-n:]

    def latest(self, service: str, metric: str) -> MetricPoint | None:
        with self._lock:
            series = self._series[(service, metric)]
            return series[-1] if series else None

    def keys(self) -> list[tuple[str, str]]:
        with self._lock:
            return [k for k, v in self._series.items() if v]

    def services(self) -> list[str]:
        return sorted({s for s, _ in self.keys()})

    def metrics(self) -> list[str]:
        return sorted({m for _, m in self.keys()})

    def snapshot(self) -> dict[str, dict[str, float]]:
        """Latest value per service/metric, shaped for the dashboard."""
        out: dict[str, dict[str, float]] = defaultdict(dict)
        with self._lock:
            for (service, metric), series in self._series.items():
                if series:
                    out[service][metric] = round(series[-1].value, 3)
        return {k: dict(v) for k, v in out.items()}
