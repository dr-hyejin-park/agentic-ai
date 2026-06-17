"""Scenario-based playbook: map (pattern, metric) -> ordered action plan.

This is the "customized treatment per situation" core. The plan is chosen from
the anomaly's *pattern* and the *metric* it occurred on, so a CPU spike, a slow
memory leak, and a frozen sensor each get a different, appropriate response.
"""

from __future__ import annotations

from ..models import Anomaly, PatternType, Severity

# (pattern, metric) -> list of action names, in execution order.
# A "*" metric is the fallback for that pattern.
PLAYBOOK: dict[tuple[PatternType, str], list[str]] = {
    (PatternType.SPIKE, "cpu_pct"): ["scale_out"],
    (PatternType.SPIKE, "request_rate"): ["scale_out", "throttle_traffic"],
    (PatternType.SPIKE, "latency_ms"): ["scale_out"],
    (PatternType.SPIKE, "error_rate"): ["restart_service"],
    (PatternType.SPIKE, "*"): ["open_incident"],

    (PatternType.SUSTAINED_HIGH, "cpu_pct"): ["scale_out", "restart_service"],
    (PatternType.SUSTAINED_HIGH, "memory_pct"): ["clear_cache", "restart_service"],
    (PatternType.SUSTAINED_HIGH, "latency_ms"): ["scale_out", "failover"],
    (PatternType.SUSTAINED_HIGH, "error_rate"): ["restart_service", "failover"],
    (PatternType.SUSTAINED_HIGH, "*"): ["open_incident", "page_oncall"],

    (PatternType.DIP, "request_rate"): ["page_oncall"],
    (PatternType.DIP, "*"): ["open_incident"],
    (PatternType.SUSTAINED_LOW, "request_rate"): ["failover", "page_oncall"],
    (PatternType.SUSTAINED_LOW, "*"): ["open_incident", "page_oncall"],

    (PatternType.FLATLINE, "*"): ["restart_collector", "page_oncall"],
    (PatternType.CORRELATED, "*"): ["failover", "page_oncall", "open_incident"],
}


def plan_for(anomaly: Anomaly) -> list[str]:
    """Return the ordered action plan for an anomaly."""
    key = (anomaly.pattern, anomaly.metric)
    actions = PLAYBOOK.get(key) or PLAYBOOK.get((anomaly.pattern, "*")) or ["open_incident"]
    actions = list(actions)
    # Always page a human for criticals if not already in the plan.
    if anomaly.severity is Severity.CRITICAL and "page_oncall" not in actions:
        actions.append("page_oncall")
    return actions


def explain_plan(anomaly: Anomaly, actions: list[str]) -> str:
    return (f"Pattern '{anomaly.pattern.value}' on {anomaly.metric} "
            f"({anomaly.severity.value}) -> plan: {', '.join(actions)}")
