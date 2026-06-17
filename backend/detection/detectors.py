"""Statistical anomaly detectors.

Each detector takes the recent value history for one series and returns a
(is_anomaly, score, baseline, reason) tuple. Detectors are intentionally
lightweight and dependency-free so the engine runs anywhere.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass
class Detection:
    is_anomaly: bool
    score: float          # magnitude of deviation (higher = more anomalous)
    baseline: float
    reason: str
    detector: str


def _mean_std(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return (values[0] if values else 0.0), 0.0
    return statistics.fmean(values), statistics.pstdev(values)


def zscore_detector(values: list[float], threshold: float = 3.0) -> Detection:
    """Flags points far from the rolling mean (robust to gentle drift)."""
    if len(values) < 10:
        return Detection(False, 0.0, values[-1] if values else 0.0, "warming up", "zscore")
    history, current = values[:-1], values[-1]
    mean, std = _mean_std(history)
    if std < 1e-9:
        return Detection(False, 0.0, mean, "no variance", "zscore")
    score = abs(current - mean) / std
    return Detection(
        is_anomaly=score >= threshold,
        score=round(score, 2),
        baseline=round(mean, 3),
        reason=f"{score:.1f}σ from mean {mean:.1f}",
        detector="zscore",
    )


def ewma_detector(values: list[float], span: int = 12, threshold: float = 3.0) -> Detection:
    """Exponentially-weighted moving average — catches sustained drift early."""
    if len(values) < 15:
        return Detection(False, 0.0, values[-1] if values else 0.0, "warming up", "ewma")
    alpha = 2.0 / (span + 1)
    ewma = values[0]
    resid: list[float] = []
    for v in values:
        ewma = alpha * v + (1 - alpha) * ewma
        resid.append(v - ewma)
    std = statistics.pstdev(resid) or 1e-9
    score = abs(values[-1] - ewma) / std
    return Detection(
        is_anomaly=score >= threshold,
        score=round(score, 2),
        baseline=round(ewma, 3),
        reason=f"{score:.1f}σ from EWMA {ewma:.1f}",
        detector="ewma",
    )


def flatline_detector(values: list[float], window: int = 12) -> Detection:
    """Detects collapsed variance — a stuck sensor or frozen service."""
    if len(values) < window:
        return Detection(False, 0.0, values[-1] if values else 0.0, "warming up", "flatline")
    recent = values[-window:]
    long_std = statistics.pstdev(values) or 1e-9
    recent_std = statistics.pstdev(recent)
    ratio = recent_std / long_std
    is_flat = ratio < 0.05 and long_std > 0.5
    return Detection(
        is_anomaly=is_flat,
        score=round((0.05 - ratio) * 100, 2) if is_flat else 0.0,
        baseline=round(statistics.fmean(recent), 3),
        reason=f"variance collapsed to {ratio:.1%} of normal",
        detector="flatline",
    )


# Detectors run in priority order; the first to fire wins for a given series.
DETECTORS = [flatline_detector, ewma_detector, zscore_detector]


def run_detectors(values: list[float]) -> Detection | None:
    best: Detection | None = None
    for fn in DETECTORS:
        d = fn(values)
        if d.is_anomaly and (best is None or d.score > best.score):
            best = d
    return best
