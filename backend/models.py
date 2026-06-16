"""Shared domain models for the anomaly-detection engine."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {"info": 0, "warning": 1, "critical": 2}[self.value]


class PatternType(str, Enum):
    """Situational anomaly patterns the engine recognizes."""

    SPIKE = "spike"                  # sudden short-lived jump
    DIP = "dip"                      # sudden short-lived drop
    SUSTAINED_HIGH = "sustained_high"  # drift to an abnormally high level
    SUSTAINED_LOW = "sustained_low"    # drift to an abnormally low level
    FLATLINE = "flatline"            # variance collapses (stuck sensor / frozen service)
    CORRELATED = "correlated"        # several metrics anomalous at once (likely outage)
    UNKNOWN = "unknown"


@dataclass
class MetricPoint:
    metric: str
    service: str
    value: float
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Anomaly:
    metric: str
    service: str
    value: float
    score: float                    # how far from normal (e.g. z-score magnitude)
    severity: Severity
    pattern: PatternType
    detector: str
    baseline: float
    description: str
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        d["pattern"] = self.pattern.value
        return d


@dataclass
class TreatmentResult:
    action: str
    target: str
    status: str                     # "executed" | "pending_approval" | "skipped" | "failed"
    detail: str
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Incident:
    anomaly: Anomaly
    treatments: list[TreatmentResult] = field(default_factory=list)
    resolved: bool = False
    resolved_ts: Optional[float] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "resolved": self.resolved,
            "resolved_ts": self.resolved_ts,
            "anomaly": self.anomaly.to_dict(),
            "treatments": [t.to_dict() for t in self.treatments],
        }
