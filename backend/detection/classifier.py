"""Classify a raw detection into a situational pattern + severity.

The pattern drives which treatment playbook runs, so this is where shape
("a brief spike" vs "a sustained climb" vs "a frozen series") is turned into
something the remediation layer can act on.
"""

from __future__ import annotations

import statistics

from .detectors import Detection
from ..models import PatternType, Severity


def _direction(values: list[float], baseline: float) -> int:
    return 1 if values and values[-1] >= baseline else -1


def _is_sustained(values: list[float], baseline: float, window: int = 6) -> bool:
    """True if the last `window` points stay on one side of the baseline."""
    if len(values) < window:
        return False
    tail = values[-window:]
    above = sum(1 for v in tail if v > baseline)
    return above >= window - 1 or above <= 1


def classify(detection: Detection, values: list[float]) -> PatternType:
    if detection.detector == "flatline":
        return PatternType.FLATLINE

    up = _direction(values, detection.baseline) > 0
    sustained = _is_sustained(values, detection.baseline)

    if sustained:
        return PatternType.SUSTAINED_HIGH if up else PatternType.SUSTAINED_LOW
    return PatternType.SPIKE if up else PatternType.DIP


def severity_for(score: float, pattern: PatternType) -> Severity:
    # Sustained patterns and flatlines are inherently more serious than a
    # single transient spike, so they escalate at a lower score.
    escalate = pattern in {
        PatternType.SUSTAINED_HIGH,
        PatternType.SUSTAINED_LOW,
        PatternType.FLATLINE,
        PatternType.CORRELATED,
    }
    if score >= 6.0 or (escalate and score >= 4.0):
        return Severity.CRITICAL
    if score >= 3.0:
        return Severity.WARNING
    return Severity.INFO


def describe(metric: str, service: str, pattern: PatternType,
             value: float, baseline: float) -> str:
    shape = {
        PatternType.SPIKE: "spiked above",
        PatternType.DIP: "dropped below",
        PatternType.SUSTAINED_HIGH: "is sustained well above",
        PatternType.SUSTAINED_LOW: "is sustained well below",
        PatternType.FLATLINE: "has flatlined near",
        PatternType.CORRELATED: "is anomalous (correlated outage) near",
        PatternType.UNKNOWN: "deviated from",
    }[pattern]
    return (f"{service}.{metric} {shape} its baseline "
            f"(now {value:.1f}, baseline {baseline:.1f})")
