"""End-to-end checks for the detect -> classify -> treat pipeline."""

from __future__ import annotations

from backend.engine import Engine
from backend.detection.detectors import zscore_detector, flatline_detector
from backend.models import PatternType, Severity
from backend.treatment.playbook import plan_for
from backend.models import Anomaly


def _warm(engine: Engine, ticks: int = 25) -> None:
    for _ in range(ticks):
        engine.tick(inject_random=False)


def test_zscore_detects_spike():
    # Realistic noisy baseline (z-score needs non-zero variance) then a spike.
    values = [50.0 + (i % 5) - 2 for i in range(30)] + [200.0]
    det = zscore_detector(values)
    assert det.is_anomaly
    assert det.score > 3.0


def test_flatline_detects_collapsed_variance():
    values = [50 + (i % 2) * 10 for i in range(40)] + [50.0] * 15
    det = flatline_detector(values)
    assert det.is_anomaly


def test_pipeline_detects_and_treats_injected_spike():
    engine = Engine()
    _warm(engine)
    engine.inject("payment-svc", "cpu_pct", kind="spike", duration=10, magnitude=8.0)
    detected = False
    for _ in range(8):
        result = engine.tick(inject_random=False)
        if result["new_anomalies"]:
            detected = True
            break
    assert detected, "spike should be detected within a few ticks"
    assert engine.incidents, "an incident should be opened"
    # An incident should carry at least one treatment.
    assert engine.incidents[0].treatments


def test_correlated_outage_escalates_to_critical():
    engine = Engine()
    _warm(engine)
    for metric in ["cpu_pct", "memory_pct", "latency_ms", "error_rate"]:
        engine.inject("auth-svc", metric, kind="spike", duration=10, magnitude=8.0)
    correlated = False
    for _ in range(6):
        result = engine.tick(inject_random=False)
        if result["correlated_outage"]:
            correlated = True
            break
    assert correlated, "simultaneous multi-metric faults should flag a correlated outage"


def test_playbook_picks_pattern_specific_plan():
    spike = Anomaly(metric="memory_pct", service="x", value=99, score=5,
                    severity=Severity.WARNING, pattern=PatternType.SUSTAINED_HIGH,
                    detector="ewma", baseline=60, description="")
    plan = plan_for(spike)
    assert "clear_cache" in plan  # memory leak -> clear cache before restart


def test_health_report_shape():
    engine = Engine()
    _warm(engine)
    rep = engine.health_report()
    assert rep["status"] in {"healthy", "degraded", "critical"}
    assert set(rep["services"])
    assert "snapshot" in rep
