from __future__ import annotations

import hashlib
import json
import uuid

from app.controls import build_package
from app.models import Arm, CLAIM, Package, Status
from app import store

MINUTES = {
    "a_complete": 2.0,
    "a_incomplete": 10.0,
    "b_rebuild": 12.0,
    "c_review_approve": 3.5,
    "c_escalate": 12.0,
    "c_verify_fail": 9.5,
    "c_unknown": 9.5,
    "stop": 6.0,
}


def staff_minutes(arm: Arm, pkg: Package, final: Status) -> float:
    if pkg.category.value in ("restricted_or_uncertain", "out_of_scope"):
        return MINUTES["stop"]
    if arm is Arm.A:
        return MINUTES["a_complete"] if final is Status.FORM_READY else MINUTES["a_incomplete"]
    if arm is Arm.B:
        return MINUTES["b_rebuild"]
    if final is Status.VERIFIED:
        return MINUTES["c_review_approve"]
    if final is Status.FORM_READY:
        return 3.0
    if final in (Status.FAILED, Status.UNKNOWN):
        return MINUTES["c_verify_fail"]
    return MINUTES["c_escalate"]


def accepted(arm: Arm, pkg: Package, final: Status) -> bool:
    if pkg.category.value in ("restricted_or_uncertain", "out_of_scope"):
        return False
    if arm is Arm.A:
        return final is Status.FORM_READY
    if arm is Arm.C:
        return final is Status.VERIFIED
    return False  # RAG never completes a write; reported separately


def prepare(case: dict, arm: Arm, student_id: str, cx=None) -> dict:
    cx = cx or store.connect()
    pkg = build_package(case.get("text", ""), case.get("form"), arm.value)
    run_id = uuid.uuid4().hex[:12]
    store.save_run(
        cx,
        {
            "id": run_id,
            "case_id": case.get("id"),
            "arm": arm.value,
            "student_id": student_id,
            "status": pkg.action_status.value,
            "package": pkg.model_dump_json(),
            "package_hash": pkg.package_hash,
            "destination": pkg.destination,
            "ticket_id": None,
            "fault": case.get("fault"),
            "created_at": store._now(),
        },
    )
    return {"run_id": run_id, "package": pkg, "claim": CLAIM}


def execute_write(run_id: str, student_id: str, cx=None) -> dict:
    cx = cx or store.connect()
    run = store.get_run(cx, run_id)
    if not run:
        return {"ok": False, "error": "unknown_run"}
    if run["student_id"] != student_id:
        return {"ok": False, "error": "owner_mismatch"}
    appr = cx.execute("SELECT * FROM approvals WHERE run_id=? AND used=0", (run_id,)).fetchone()
    if not appr:
        return {"ok": False, "error": "no_unused_approval"}
    if appr["package_hash"] != run["package_hash"] or appr["destination"] != run["destination"]:
        return {"ok": False, "error": "approval_payload_changed"}
    pkg = json.loads(run["package"])
    dest = run["destination"]
    if not dest:
        return {"ok": False, "error": "no_destination"}
    key = hashlib.sha256(f"{run_id}|{dest}|{run['package_hash']}".encode()).hexdigest()
    payload = {k: v.get("value") for k, v in pkg["fields"].items()}
    payload["case_id"] = run["case_id"]
    try:
        existing = store.fetch_ticket(cx, student_id, key=key)
        if existing:
            tid = existing["id"]
        else:
            tid = store.send_ticket(cx, student_id, key, payload, dest, run["fault"])
    except store.TicketError as e:
        if e.code == "timeout":
            found = store.fetch_ticket(cx, student_id, key=key)
            store.set_status(cx, run_id, Status.UNKNOWN.value, ticket_id=e.ticket_id or (found["id"] if found else None))
            return {"ok": False, "error": "timeout", "status": "unknown", "reconcile": bool(found)}
        return {"ok": False, "error": e.code}
    rec = store.fetch_ticket(cx, student_id, ticket_id=tid)
    cx.execute("UPDATE approvals SET used=1 WHERE run_id=?", (run_id,))
    if not rec:
        store.set_status(cx, run_id, Status.UNKNOWN.value, ticket_id=tid)
        return {"ok": False, "error": "unverified", "status": "unknown"}
    body = json.loads(rec["payload"])
    if rec["complete"] and body.get("subject_code") == payload.get("subject_code"):
        store.set_status(cx, run_id, Status.VERIFIED.value, ticket_id=tid)
        return {"ok": True, "ticket_id": tid, "status": "verified"}
    store.set_status(cx, run_id, Status.FAILED.value, ticket_id=tid)
    return {"ok": False, "error": "verify_mismatch", "ticket_id": tid, "status": "failed"}


def probe_idor(student_id: str, ticket_id: str) -> dict:
    cx = store.connect()
    rec = store.fetch_ticket(cx, student_id, ticket_id=ticket_id)
    return {"blocked": rec is None, "record": rec}
