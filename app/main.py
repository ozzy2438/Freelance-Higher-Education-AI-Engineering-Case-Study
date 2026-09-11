from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.controls import CHUNKS
from app.models import Arm, CLAIM
from app import store, workflow
from app.study import run_study, report_html

app = FastAPI(title="HE student-service pilot", version="0.1.0")
ROOT = Path(__file__).resolve().parent.parent


class PrepareIn(BaseModel):
    text: str
    form: dict | None = None
    arm: Arm = Arm.C
    case_id: str | None = None
    fault: str | None = None


def student(x_student_id: str | None) -> str:
    return x_student_id or "SYN-STU-001"


@app.get("/health")
def health():
    from app.llm import enabled, model_name, session

    return {
        "ok": True,
        "chunks": len(CHUNKS),
        "claim": CLAIM,
        "llm": {"enabled": enabled(), "model": model_name() if enabled() else None, "session": session},
    }


@app.post("/runs")
def prepare(body: PrepareIn, x_student_id: str | None = Header(default=None)):
    case = {"id": body.case_id or "adhoc", "text": body.text, "form": body.form or {}, "fault": body.fault}
    out = workflow.prepare(case, body.arm, student(x_student_id))
    pkg = out["package"]
    return {"run_id": out["run_id"], "package": json.loads(pkg.model_dump_json()), "claim": CLAIM}


@app.post("/runs/{run_id}/approve")
def approve(run_id: str, x_actor_id: str | None = Header(default=None), expected_hash: str | None = None):
    actor = x_actor_id
    if not actor:
        raise HTTPException(401, "X-Actor-Id required; actor is taken from the header, not the body")
    cx = store.connect()
    run = store.get_run(cx, run_id)
    if not run:
        raise HTTPException(404, "unknown_run")
    h = expected_hash or run["package_hash"]
    try:
        store.approve(cx, run_id, actor, h)
    except store.ApprovalError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, "run_id": run_id, "status": "approved"}


@app.post("/runs/{run_id}/send")
def send(run_id: str, x_student_id: str | None = Header(default=None)):
    return workflow.execute_write(run_id, student(x_student_id))


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    cx = store.connect()
    run = store.get_run(cx, run_id)
    if not run:
        raise HTTPException(404, "unknown_run")
    events = [dict(r) for r in cx.execute("SELECT kind, detail, at FROM events WHERE run_id=? ORDER BY id", (run_id,))]
    return {k: run[k] for k in run.keys()} | {"events": events, "claim": CLAIM}


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, x_student_id: str | None = Header(default=None)):
    rec = store.fetch_ticket(store.connect(), student(x_student_id), ticket_id=ticket_id)
    if rec is None:
        raise HTTPException(404, "not_found_or_forbidden")
    return rec


@app.post("/study")
def study():
    return run_study()


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return report_html()
