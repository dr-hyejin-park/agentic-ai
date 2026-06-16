"""FastAPI application: REST API + dashboard for the anomaly-detection engine."""

from __future__ import annotations

import contextlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .agent.llm import agent
from .config import settings
from .engine import engine
from .monitoring.monitor import monitor

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    monitor.start()
    yield
    await monitor.stop()


app = FastAPI(title="Agentic AI Anomaly Detection", version="0.1.0", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str


class TreatRequest(BaseModel):
    action: str
    service: str
    metric: str = "*"


class InjectRequest(BaseModel):
    service: str
    metric: str
    kind: str = "spike"
    duration: int = 12
    magnitude: float = 6.0


@app.get("/")
def index():
    if FRONTEND.exists():
        return FileResponse(str(FRONTEND))
    return JSONResponse({"message": "Anomaly detection engine running. UI not found."})


@app.get("/api/health")
def health():
    rep = engine.health_report()
    rep["agent_online"] = agent.online
    rep["model"] = settings.agent_model if agent.online else "offline"
    return rep


@app.get("/api/anomalies")
def anomalies(limit: int = 25):
    return {"anomalies": engine.recent_anomalies(limit)}


@app.get("/api/incidents")
def incidents(include_resolved: bool = True, limit: int = 25):
    return {"incidents": engine.list_incidents(include_resolved, limit)}


@app.get("/api/metric")
def metric(service: str, metric: str, n: int = 30):
    return engine.query_metric(service, metric, n)


@app.get("/api/events")
def events(limit: int = 40):
    return {"events": engine.events(limit)}


@app.get("/api/actions")
def actions():
    return {"actions": [
        {"name": a.name, "risk": a.risk, "description": a.description}
        for a in engine.actions.all()
    ]}


@app.post("/api/ask")
def ask(req: AskRequest):
    return agent.ask(req.question)


@app.post("/api/treat")
def treat(req: TreatRequest):
    return engine.manual_treat(req.action, req.service, req.metric).to_dict()


@app.post("/api/inject")
def inject(req: InjectRequest):
    return {"result": engine.inject(req.service, req.metric, req.kind,
                                    req.duration, req.magnitude)}


@app.post("/api/incidents/{incident_id}/approve")
def approve(incident_id: str):
    return {"approved": engine.approve_incident(incident_id)}
