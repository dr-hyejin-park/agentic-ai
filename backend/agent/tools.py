"""Tools the natural-language agent can call against the engine.

Each tool is a thin, typed wrapper over an engine operation. The same registry
is used both to advertise schemas to Claude and to dispatch tool calls.
"""

from __future__ import annotations

import json
from typing import Any

from ..engine import engine

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_health_report",
        "description": "Overall system health: status, open incidents, severity "
                       "breakdown, and the latest value of every metric.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_anomalies",
        "description": "List the most recently detected anomalies (newest first).",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "max items (default 15)"}},
        },
    },
    {
        "name": "list_incidents",
        "description": "List incidents and the treatments applied to each.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_resolved": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "query_metric",
        "description": "Recent time-series values + stats for one service/metric. "
                       "Services: api-gateway, payment-svc, auth-svc, search-svc. "
                       "Metrics: cpu_pct, memory_pct, latency_ms, error_rate, request_rate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "metric": {"type": "string"},
            },
            "required": ["service", "metric"],
        },
    },
    {
        "name": "trigger_treatment",
        "description": "Manually run a remediation action against a service. Actions: "
                       "scale_out, restart_service, clear_cache, throttle_traffic, "
                       "failover, restart_collector, page_oncall, open_incident.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "service": {"type": "string"},
                "metric": {"type": "string"},
            },
            "required": ["action", "service"],
        },
    },
    {
        "name": "approve_incident",
        "description": "Approve a treatment that is pending human approval, by incident id.",
        "input_schema": {
            "type": "object",
            "properties": {"incident_id": {"type": "string"}},
            "required": ["incident_id"],
        },
    },
    {
        "name": "inject_anomaly",
        "description": "Inject a synthetic anomaly for testing the pipeline. "
                       "kind: spike, dip, drift_up, drift_down, flatline.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "metric": {"type": "string"},
                "kind": {"type": "string"},
            },
            "required": ["service", "metric"],
        },
    },
]


def dispatch(name: str, args: dict[str, Any]) -> Any:
    if name == "get_health_report":
        return engine.health_report()
    if name == "list_anomalies":
        return engine.recent_anomalies(int(args.get("limit", 15)))
    if name == "list_incidents":
        return engine.list_incidents(
            include_resolved=bool(args.get("include_resolved", True)),
            n=int(args.get("limit", 15)),
        )
    if name == "query_metric":
        return engine.query_metric(args["service"], args["metric"])
    if name == "trigger_treatment":
        return engine.manual_treat(
            args["action"], args["service"], args.get("metric", "*")
        ).to_dict()
    if name == "approve_incident":
        ok = engine.approve_incident(args["incident_id"])
        return {"approved": ok}
    if name == "inject_anomaly":
        note = engine.inject(args["service"], args["metric"], args.get("kind", "spike"))
        return {"result": note}
    return {"error": f"unknown tool {name}"}


def dispatch_json(name: str, args: dict[str, Any]) -> str:
    return json.dumps(dispatch(name, args), default=str)
