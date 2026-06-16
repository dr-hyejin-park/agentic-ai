"""Natural-language agent over the engine.

Uses Claude with tool use to answer operator questions and take action. When no
API key is configured it degrades to a deterministic rule-based responder so the
UI still works fully offline.
"""

from __future__ import annotations

import json

from ..config import settings
from .tools import TOOL_SCHEMAS, dispatch, dispatch_json

SYSTEM_PROMPT = """\
You are the operator copilot for an autonomous anomaly-detection engine that \
monitors microservices (api-gateway, payment-svc, auth-svc, search-svc) across \
metrics cpu_pct, memory_pct, latency_ms, error_rate, and request_rate.

The engine already detects anomalies, classifies them into patterns (spike, dip, \
sustained_high, sustained_low, flatline, correlated outage), and runs treatment \
playbooks automatically. Your job is to answer questions about what is happening \
and, when asked, take action through your tools.

Guidance:
- Always ground answers in tool results; call tools rather than guessing.
- Lead with the bottom line (current status / what you found), then detail.
- When the user asks you to fix, scale, restart, or test something, use the \
appropriate tool, then confirm what you did and the observed effect.
- Be concise and concrete. Reference services, metrics, and numbers."""

MAX_ITERS = 6


class Agent:
    def __init__(self) -> None:
        self._client = None
        if settings.llm_enabled:
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            except Exception:
                self._client = None

    @property
    def online(self) -> bool:
        return self._client is not None

    def ask(self, question: str) -> dict:
        if self._client is None:
            return self._offline(question)
        try:
            return self._ask_claude(question)
        except Exception as exc:
            fallback = self._offline(question)
            fallback["note"] = f"LLM error, used offline mode: {exc}"
            return fallback

    # ---- Claude tool-use loop ---------------------------------------------

    def _ask_claude(self, question: str) -> dict:
        messages = [{"role": "user", "content": question}]
        tool_trace: list[dict] = []

        kwargs = dict(
            model=settings.agent_model,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        # Claude Fable 5 declines benign requests less gracefully without a
        # fallback, so opt into a server-side fallback when that model is used.
        create = self._client.messages.create
        use_beta = settings.agent_model.startswith("claude-fable")
        if use_beta:
            create = self._client.beta.messages.create
            kwargs["betas"] = ["server-side-fallback-2026-06-01"]
            kwargs["fallbacks"] = [{"model": "claude-opus-4-8"}]

        for _ in range(MAX_ITERS):
            response = create(**kwargs)
            if response.stop_reason == "refusal":
                return {"answer": "Request was declined by the safety system.",
                        "tools_used": tool_trace, "online": True}
            if response.stop_reason != "tool_use":
                text = "".join(b.text for b in response.content if b.type == "text")
                return {"answer": text.strip(), "tools_used": tool_trace, "online": True}

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                out = dispatch_json(block.name, dict(block.input))
                tool_trace.append({"tool": block.name, "input": dict(block.input)})
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": out,
                })
            messages.append({"role": "user", "content": results})
            kwargs["messages"] = messages

        return {"answer": "Stopped after reaching the tool-call limit.",
                "tools_used": tool_trace, "online": True}

    # ---- offline rule-based responder -------------------------------------

    def _offline(self, question: str) -> dict:
        q = question.lower()
        trace: list[dict] = []

        def used(name, args=None):
            trace.append({"tool": name, "input": args or {}})

        if any(w in q for w in ["health", "status", "overall", "how are", "전체", "상태", "건강"]):
            used("get_health_report")
            rep = dispatch("get_health_report", {})
            answer = (
                f"System status: {rep['status'].upper()}. "
                f"{rep['open_incidents']} open incident(s) of {rep['total_incidents']} total; "
                f"{rep['total_anomalies']} anomalies detected so far. "
                f"Severity breakdown: {rep['severity_breakdown'] or 'none'}. "
                f"Monitoring {len(rep['services'])} services on {len(rep['metrics'])} metrics."
            )
            return {"answer": answer, "tools_used": trace, "online": False}

        if any(w in q for w in ["incident", "treat", "action", "remediat", "조치", "인시던트"]):
            used("list_incidents")
            incidents = dispatch("list_incidents", {"limit": 5})
            if not incidents:
                return {"answer": "No incidents recorded yet.", "tools_used": trace, "online": False}
            lines = []
            for inc in incidents:
                a = inc["anomaly"]
                acts = ", ".join(f"{t['action']}({t['status']})" for t in inc["treatments"])
                state = "resolved" if inc["resolved"] else "open"
                lines.append(f"- [{state}] {a['service']}.{a['metric']} {a['pattern']} "
                             f"({a['severity']}) -> {acts}")
            return {"answer": "Recent incidents:\n" + "\n".join(lines),
                    "tools_used": trace, "online": False}

        if any(w in q for w in ["anomal", "이상"]):
            used("list_anomalies")
            anomalies = dispatch("list_anomalies", {"limit": 8})
            if not anomalies:
                return {"answer": "No anomalies detected recently.", "tools_used": trace, "online": False}
            lines = [f"- {a['severity'].upper()} {a['description']} "
                     f"[{a['pattern']}, score {a['score']}]" for a in anomalies]
            return {"answer": "Recent anomalies:\n" + "\n".join(lines),
                    "tools_used": trace, "online": False}

        # Try to resolve a service/metric mention into a metric query.
        services = ["api-gateway", "payment-svc", "auth-svc", "search-svc"]
        metrics = ["cpu_pct", "memory_pct", "latency_ms", "error_rate", "request_rate"]
        svc = next((s for s in services if s in q), None)
        met = next((m for m in metrics if m.split("_")[0] in q or m in q), None)
        if svc and met:
            used("query_metric", {"service": svc, "metric": met})
            res = dispatch("query_metric", {"service": svc, "metric": met})
            return {"answer": (f"{svc}.{met}: current {res['current']}, "
                               f"range [{res['min']}, {res['max']}], "
                               f"anomalous now: {res['anomalous_now']}."),
                    "tools_used": trace, "online": False}

        return {
            "answer": ("Offline mode (no ANTHROPIC_API_KEY). Try: 'system health', "
                       "'recent anomalies', 'recent incidents', or 'cpu_pct on payment-svc'."),
            "tools_used": trace,
            "online": False,
        }


agent = Agent()
