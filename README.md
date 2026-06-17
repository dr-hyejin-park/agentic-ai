# Sentinel — Agentic AI Anomaly Detection Engine

An autonomous engine that **collects telemetry, monitors it continuously, detects
anomalies, classifies them into situational patterns, and runs the matching
treatment playbook automatically** — with a natural-language dashboard where an
operator can ask what's happening and tell the engine to act.

```
collect ──▶ store ──▶ detect ──▶ classify ──▶ plan treatment ──▶ execute ──▶ auto-resolve
   ▲ Collector   ▲ TimeSeries  ▲ z-score /   ▲ pattern +     ▲ scenario      ▲ Action
   │ (telemetry) │  ring buffer│  EWMA /      │  severity      │  playbook     │  registry
   │             │             │  flatline    │                │               │
   └──────────────────────────── Natural-language agent (Claude + tools) ──────┘
```

## What it does

1. **Collect & monitor** — a background loop ingests metrics (`cpu_pct`,
   `memory_pct`, `latency_ms`, `error_rate`, `request_rate`) for four services
   every couple of seconds. (Swap `Collector` for Prometheus/CloudWatch/IoT in prod.)
2. **Detect** — three complementary detectors run per series:
   - **z-score** — points far from the rolling mean (transient spikes/dips)
   - **EWMA** — exponentially-weighted average, catches *sustained drift* early
   - **flatline** — collapsed variance (a stuck sensor or frozen service)
3. **Classify** — each detection becomes a *pattern*: `spike`, `dip`,
   `sustained_high`, `sustained_low`, `flatline`, or `correlated` (when several
   metrics on one service fire at once → likely outage), with a severity.
4. **Treat — customized per situation** — `treatment/playbook.py` maps
   `(pattern, metric)` to an ordered action plan, so a CPU spike (`scale_out`),
   a memory leak (`clear_cache → restart_service`), and a frozen sensor
   (`restart_collector → page_oncall`) each get the *right* response. Low-risk
   actions auto-execute; high-risk ones can require human approval.
5. **Report & converse** — a web dashboard shows live metrics, anomalies,
   incidents + the treatments applied, and an engine activity feed. A
   natural-language agent (Claude with tool use) answers questions and takes
   action on request.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # optional: add ANTHROPIC_API_KEY for the LLM agent
python run.py                 # open http://localhost:8000
```

The engine runs fully **without an API key** — the NL agent falls back to a
deterministic rule-based responder so the whole UI works offline. Add
`ANTHROPIC_API_KEY` to `.env` to enable the Claude-powered agent (default model
`claude-opus-4-8`, configurable via `AGENT_MODEL`).

### Try the scenario flow

Use the **Inject test scenario** panel (or ask the agent *"inject a flatline on
auth-svc memory_pct"*). Within a few ticks you'll see the anomaly detected, an
incident opened with its treatment plan, and — once the series recovers — the
incident auto-resolve in the activity feed.

Ask things like:
- *"What's the overall system health?"*
- *"List recent incidents and what treatments were applied"*
- *"What is latency_ms doing on search-svc?"*
- *"Scale out payment-svc"*

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Enables the Claude agent; offline rule-based agent if unset |
| `AGENT_MODEL` | `claude-opus-4-8` | Model for the NL agent |
| `MONITOR_INTERVAL` | `2.0` | Seconds between monitoring ticks |
| `REQUIRE_APPROVAL` | `0` | If `1`, high-risk treatments wait for human approval |

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | System status, snapshot, severity breakdown |
| `GET /api/anomalies` | Recently detected anomalies |
| `GET /api/incidents` | Incidents + treatments applied |
| `GET /api/metric?service=&metric=` | Recent time series for one series |
| `GET /api/events` | Engine activity log |
| `POST /api/ask` | Natural-language query → agent answer |
| `POST /api/treat` | Manually run a treatment action |
| `POST /api/inject` | Inject a synthetic anomaly |
| `POST /api/incidents/{id}/approve` | Approve a pending high-risk treatment |

## Layout

```
backend/
  config.py              env-driven settings
  models.py              Anomaly / Incident / Treatment domain types
  engine.py              orchestration: collect→detect→classify→treat→resolve
  data/        collector.py (telemetry source), store.py (time series)
  detection/   detectors.py (z-score/EWMA/flatline), classifier.py (pattern+severity)
  treatment/   actions.py (action registry), playbook.py (scenario→plan)
  monitoring/  monitor.py (background loop)
  agent/       tools.py (engine tools), llm.py (Claude agent + offline fallback)
  app.py                 FastAPI app + REST API
frontend/index.html      single-page dashboard
tests/test_engine.py     pipeline tests
```

## Tests

```bash
pip install pytest && pytest -q
```
