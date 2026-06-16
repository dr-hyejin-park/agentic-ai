"""The anomaly-detection engine: collect -> detect -> classify -> treat.

Holds all engine state (time series, anomalies, incidents) and exposes the
operations both the monitoring loop and the natural-language agent act on.
"""

from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict

from .config import settings
from .data.collector import Collector
from .data.store import TimeSeriesStore
from .detection.classifier import classify, describe, severity_for
from .detection.detectors import run_detectors
from .models import Anomaly, Incident, PatternType, Severity, TreatmentResult
from .treatment.actions import RISK_HIGH, ActionRegistry
from .treatment.playbook import explain_plan, plan_for


class Engine:
    def __init__(self) -> None:
        self.store = TimeSeriesStore(window=settings.history_window)
        self.collector = Collector()
        self.actions = ActionRegistry(collector=self.collector)
        self._lock = threading.Lock()
        self.anomalies: list[Anomaly] = []
        self.incidents: list[Incident] = []
        self.event_log: list[str] = []
        self.tick_count = 0
        # Suppress duplicate alerts for the same series for a short cooldown.
        self._cooldown: dict[tuple[str, str], float] = {}
        self.cooldown_secs = 15.0

    # ---- main pipeline -----------------------------------------------------

    def tick(self, inject_random: bool = True) -> dict:
        """Run one monitoring cycle and return a summary of what happened."""
        if inject_random:
            note = self.collector.random_injection()
            if note:
                self._log(f"[sim] {note}")

        points = self.collector.collect()
        self.store.add_many(points)
        self.tick_count += 1

        new_anomalies = self._detect()
        correlated = self._correlate(new_anomalies)
        incidents = [self._treat(a) for a in new_anomalies]

        self._auto_resolve()

        return {
            "tick": self.tick_count,
            "collected": len(points),
            "new_anomalies": [a.to_dict() for a in new_anomalies],
            "correlated_outage": correlated,
            "incidents_opened": [i.id for i in incidents],
        }

    def _detect(self) -> list[Anomaly]:
        found: list[Anomaly] = []
        now = time.time()
        for service, metric in self.store.keys():
            key = (service, metric)
            if now - self._cooldown.get(key, 0) < self.cooldown_secs:
                continue
            values = self.store.values(service, metric)
            det = run_detectors(values)
            if det is None:
                continue
            pattern = classify(det, values)
            severity = severity_for(det.score, pattern)
            point = values[-1]
            anomaly = Anomaly(
                metric=metric, service=service, value=point,
                score=det.score, severity=severity, pattern=pattern,
                detector=det.detector, baseline=det.baseline,
                description=describe(metric, service, pattern, point, det.baseline),
            )
            self._cooldown[key] = now
            with self._lock:
                self.anomalies.append(anomaly)
            found.append(anomaly)
            self._log(f"[detect] {anomaly.severity.value.upper()} {anomaly.description}")
        return found

    def _correlate(self, new_anomalies: list[Anomaly]) -> list[str]:
        """If multiple metrics on one service fire together, flag an outage."""
        by_service: dict[str, list[Anomaly]] = defaultdict(list)
        for a in new_anomalies:
            by_service[a.service].append(a)
        correlated = []
        for service, group in by_service.items():
            if len(group) >= 3:
                for a in group:
                    a.pattern = PatternType.CORRELATED
                    a.severity = Severity.CRITICAL
                correlated.append(service)
                self._log(f"[correlate] CRITICAL correlated outage on {service} "
                          f"({len(group)} metrics)")
        return correlated

    def _treat(self, anomaly: Anomaly) -> Incident:
        plan = plan_for(anomaly)
        self._log(f"[plan] {explain_plan(anomaly, plan)}")
        incident = Incident(anomaly=anomaly)
        for action_name in plan:
            incident.treatments.append(self._execute(action_name, anomaly))
        with self._lock:
            self.incidents.append(incident)
        return incident

    def _execute(self, action_name: str, anomaly: Anomaly) -> TreatmentResult:
        action = self.actions.get(action_name)
        if action is None:
            return TreatmentResult(action_name, anomaly.service, "failed",
                                   "unknown action")
        gated = settings.require_approval and action.risk == RISK_HIGH
        if gated:
            self._log(f"[treat] PENDING APPROVAL {action_name} on {anomaly.service}")
            return TreatmentResult(action_name, anomaly.service, "pending_approval",
                                   f"{action.description} (awaiting human approval)")
        detail = action.handler(anomaly.service, anomaly.metric)
        self._log(f"[treat] executed {action_name}: {detail}")
        return TreatmentResult(action_name, anomaly.service, "executed", detail)

    def _auto_resolve(self) -> None:
        """Mark incidents resolved once their series returns to normal."""
        now = time.time()
        for inc in self.incidents:
            if inc.resolved:
                continue
            if any(t.status == "pending_approval" for t in inc.treatments):
                continue
            values = self.store.values(inc.anomaly.service, inc.anomaly.metric)
            det = run_detectors(values)
            settled = now - inc.ts > self.cooldown_secs
            if det is None and settled:
                inc.resolved = True
                inc.resolved_ts = now
                self._log(f"[resolve] incident {inc.id} on "
                          f"{inc.anomaly.service}.{inc.anomaly.metric} recovered")

    # ---- operations the agent + API call ----------------------------------

    def manual_treat(self, action_name: str, service: str, metric: str = "*") -> TreatmentResult:
        action = self.actions.get(action_name)
        if action is None:
            return TreatmentResult(action_name, service, "failed", "unknown action")
        detail = action.handler(service, metric)
        self._log(f"[manual] executed {action_name} on {service}: {detail}")
        return TreatmentResult(action_name, service, "executed", detail)

    def approve_incident(self, incident_id: str) -> bool:
        for inc in self.incidents:
            if inc.id != incident_id:
                continue
            changed = False
            for t in inc.treatments:
                if t.status == "pending_approval":
                    action = self.actions.get(t.action)
                    if action:
                        t.detail = action.handler(inc.anomaly.service, inc.anomaly.metric)
                        t.status = "executed"
                        changed = True
            if changed:
                self._log(f"[approve] incident {inc.id} approved and executed")
            return changed
        return False

    def inject(self, service: str, metric: str, kind: str = "spike",
               duration: int = 12, magnitude: float = 6.0) -> str:
        note = self.collector.inject(service, metric, kind, duration, magnitude)
        self._log(f"[inject] {note}")
        return note

    # ---- reporting ---------------------------------------------------------

    def health_report(self) -> dict:
        open_inc = [i for i in self.incidents if not i.resolved]
        sev_counts = Counter(i.anomaly.severity.value for i in open_inc)
        status = "healthy"
        if sev_counts.get("critical"):
            status = "critical"
        elif sev_counts.get("warning"):
            status = "degraded"
        return {
            "status": status,
            "tick": self.tick_count,
            "services": self.store.services(),
            "metrics": self.store.metrics(),
            "open_incidents": len(open_inc),
            "total_incidents": len(self.incidents),
            "total_anomalies": len(self.anomalies),
            "severity_breakdown": dict(sev_counts),
            "snapshot": self.store.snapshot(),
        }

    def recent_anomalies(self, n: int = 25) -> list[dict]:
        with self._lock:
            return [a.to_dict() for a in self.anomalies[-n:][::-1]]

    def list_incidents(self, include_resolved: bool = True, n: int = 25) -> list[dict]:
        with self._lock:
            items = self.incidents if include_resolved else [
                i for i in self.incidents if not i.resolved]
        return [i.to_dict() for i in items[-n:][::-1]]

    def query_metric(self, service: str, metric: str, n: int = 30) -> dict:
        pts = self.store.recent(service, metric, n)
        values = [p.value for p in pts]
        det = run_detectors(self.store.values(service, metric))
        return {
            "service": service,
            "metric": metric,
            "points": [p.to_dict() for p in pts],
            "current": values[-1] if values else None,
            "min": round(min(values), 3) if values else None,
            "max": round(max(values), 3) if values else None,
            "anomalous_now": det is not None,
        }

    def events(self, n: int = 40) -> list[str]:
        return self.event_log[-n:][::-1]

    def _log(self, msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        with self._lock:
            self.event_log.append(f"{stamp} {msg}")
            if len(self.event_log) > 500:
                self.event_log = self.event_log[-500:]


engine = Engine()
