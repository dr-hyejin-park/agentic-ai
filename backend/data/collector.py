"""Simulated data source.

In production this would poll Prometheus, CloudWatch, a log pipeline, IoT
sensors, etc. Here it synthesizes realistic-looking telemetry for a few
services and can inject anomalies on demand so the full detect -> classify ->
treat pipeline can be demonstrated end to end.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from ..models import MetricPoint

# Each metric: (baseline, noise stddev, lower_is_better)
METRIC_PROFILES: dict[str, tuple[float, float]] = {
    "cpu_pct": (45.0, 4.0),
    "memory_pct": (60.0, 3.0),
    "latency_ms": (120.0, 12.0),
    "error_rate": (0.6, 0.25),       # percent of requests
    "request_rate": (850.0, 40.0),   # requests / sec
}

SERVICES = ["api-gateway", "payment-svc", "auth-svc", "search-svc"]


@dataclass
class _Injection:
    service: str
    metric: str
    kind: str          # "spike" | "dip" | "drift_up" | "drift_down" | "flatline"
    remaining: int     # ticks left
    magnitude: float


class Collector:
    """Generates a batch of metric points per tick."""

    def __init__(self, seed: int | None = 7) -> None:
        self._rng = random.Random(seed)
        self._t0 = time.time()
        self._injections: list[_Injection] = []
        # Treatments can dampen an active injection (simulating a real fix).
        self._dampen: dict[tuple[str, str], float] = {}

    # ---- anomaly injection (used by the demo + agent tools) ----------------

    def inject(self, service: str, metric: str, kind: str = "spike",
               duration: int = 12, magnitude: float = 6.0) -> str:
        self._injections.append(
            _Injection(service, metric, kind, duration, magnitude)
        )
        return f"injected {kind} on {service}.{metric} for {duration} ticks"

    def random_injection(self, probability: float = 0.12) -> str | None:
        if self._rng.random() > probability or self._injections:
            return None
        service = self._rng.choice(SERVICES)
        metric = self._rng.choice(list(METRIC_PROFILES))
        kind = self._rng.choice(["spike", "drift_up", "flatline", "dip"])
        return self.inject(service, metric, kind,
                           duration=self._rng.randint(8, 20),
                           magnitude=self._rng.uniform(4.0, 8.0))

    def dampen(self, service: str, metric: str, factor: float = 0.35) -> None:
        """Simulate a remediation reducing an anomaly's magnitude."""
        self._dampen[(service, metric)] = factor

    # ---- collection --------------------------------------------------------

    def collect(self) -> list[MetricPoint]:
        now = time.time()
        elapsed = now - self._t0
        points: list[MetricPoint] = []

        active: dict[tuple[str, str], _Injection] = {}
        for inj in self._injections:
            active[(inj.service, inj.metric)] = inj

        for service in SERVICES:
            # Slow diurnal-style wave so baselines gently move.
            wave = math.sin(elapsed / 40.0 + hash(service) % 7) * 2.0
            for metric, (base, noise) in METRIC_PROFILES.items():
                value = base + wave + self._rng.gauss(0, noise)
                inj = active.get((service, metric))
                if inj is not None:
                    value = self._apply(inj, base, noise, value)
                value = self._clamp(metric, value)
                points.append(MetricPoint(metric=metric, service=service,
                                          value=round(value, 3), ts=now))

        self._tick_injections()
        return points

    def _apply(self, inj: _Injection, base: float, noise: float, value: float) -> float:
        factor = self._dampen.get((inj.service, inj.metric), 1.0)
        mag = inj.magnitude * factor
        if inj.kind == "spike":
            return base + mag * noise * 3.0
        if inj.kind == "dip":
            return base - mag * noise * 2.5
        if inj.kind == "drift_up":
            progress = 1.0 - (inj.remaining / 20.0)
            return base + mag * noise * (1.0 + progress)
        if inj.kind == "drift_down":
            progress = 1.0 - (inj.remaining / 20.0)
            return base - mag * noise * (1.0 + progress)
        if inj.kind == "flatline":
            return base  # variance collapses to ~0
        return value

    def _tick_injections(self) -> None:
        for inj in self._injections:
            inj.remaining -= 1
        ended = {(i.service, i.metric) for i in self._injections if i.remaining <= 0}
        self._injections = [i for i in self._injections if i.remaining > 0]
        for key in ended:
            self._dampen.pop(key, None)

    @staticmethod
    def _clamp(metric: str, value: float) -> float:
        if metric in {"cpu_pct", "memory_pct"}:
            return max(0.0, min(100.0, value))
        if metric == "error_rate":
            return max(0.0, min(100.0, value))
        return max(0.0, value)
