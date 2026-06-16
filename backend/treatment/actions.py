"""Treatment action registry.

Actions are the concrete remediations the engine can take. Each is tagged with
a risk level: low-risk actions auto-execute, high-risk ones can be gated behind
human approval (REQUIRE_APPROVAL). In a real deployment these handlers would
call Kubernetes, a cloud API, PagerDuty, etc. Here they simulate the effect and
optionally dampen the live anomaly so you can watch recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

RISK_LOW = "low"
RISK_HIGH = "high"


@dataclass
class Action:
    name: str
    risk: str
    description: str
    # handler(service, metric) -> human-readable detail string
    handler: Callable[[str, str], str]


class ActionRegistry:
    def __init__(self, collector=None) -> None:
        self._collector = collector
        self._actions: dict[str, Action] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        def _fix(detail: str, factor: float = 0.3):
            def handler(service: str, metric: str) -> str:
                if self._collector is not None:
                    self._collector.dampen(service, metric, factor)
                return detail.format(service=service, metric=metric)
            return handler

        self.register(Action(
            "scale_out", RISK_LOW,
            "Add replicas to absorb load",
            _fix("scaled out {service}: +2 replicas, load redistributing")))
        self.register(Action(
            "restart_service", RISK_HIGH,
            "Roll/restart the affected service",
            _fix("rolling restart issued for {service}")))
        self.register(Action(
            "clear_cache", RISK_LOW,
            "Flush caches to recover memory",
            _fix("flushed caches on {service}, memory reclaimed", factor=0.4)))
        self.register(Action(
            "throttle_traffic", RISK_LOW,
            "Apply rate limiting / shed load",
            _fix("rate limiting enabled on {service} to shed load")))
        self.register(Action(
            "failover", RISK_HIGH,
            "Fail over to a healthy region/replica",
            _fix("failed {service} over to standby")))
        self.register(Action(
            "restart_collector", RISK_LOW,
            "Restart the metric collector / sensor",
            _fix("metric collector for {service}.{metric} restarted", factor=0.2)))
        self.register(Action(
            "page_oncall", RISK_LOW,
            "Page the on-call engineer",
            lambda service, metric: f"on-call paged for {service}.{metric}"))
        self.register(Action(
            "open_incident", RISK_LOW,
            "Open a tracked incident ticket",
            lambda service, metric: f"incident ticket opened for {service}"))

    def register(self, action: Action) -> None:
        self._actions[action.name] = action

    def get(self, name: str) -> Optional[Action]:
        return self._actions.get(name)

    def all(self) -> list[Action]:
        return list(self._actions.values())
