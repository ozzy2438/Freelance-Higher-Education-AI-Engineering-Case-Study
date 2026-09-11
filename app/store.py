from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "var" / "pilot.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(DB)
    cx.row_factory = sqlite3.Row
    cx.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY,
          case_id TEXT, arm TEXT, student_id TEXT,
          status TEXT, package TEXT, package_hash TEXT,
          destination TEXT, ticket_id TEXT, fault TEXT,
          created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT, kind TEXT, detail TEXT, at TEXT
        );
        CREATE TABLE IF NOT EXISTS approvals (
          run_id TEXT PRIMARY KEY,
          actor TEXT, action TEXT, package_hash TEXT,
          destination TEXT, at TEXT, used INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS tickets (
          id TEXT PRIMARY KEY,
          owner TEXT NOT NULL,
          idempotency_key TEXT UNIQUE NOT NULL,
          payload TEXT NOT NULL,
          complete INTEGER NOT NULL,
          created_at TEXT
        );
        """
    )
    # Seed foreign ticket for IDOR probes
    cx.execute(
        """INSERT OR IGNORE INTO tickets(id, owner, idempotency_key, payload, complete, created_at)
           VALUES ('TCK-OTHER', 'SYN-STU-999', 'seed-other', '{"subject_code":"HIDDEN99999"}', 1, ?)""",
        (_now(),),
    )
    cx.commit()
    return cx


def event(cx: sqlite3.Connection, run_id: str, kind: str, detail: dict | str) -> None:
    cx.execute(
        "INSERT INTO events(run_id, kind, detail, at) VALUES (?,?,?,?)",
        (run_id, kind, json.dumps(detail) if not isinstance(detail, str) else detail, _now()),
    )


def save_run(cx, run: dict) -> None:
    cx.execute(
        """INSERT INTO runs(id, case_id, arm, student_id, status, package, package_hash, destination, ticket_id, fault, created_at)
           VALUES (:id,:case_id,:arm,:student_id,:status,:package,:package_hash,:destination,:ticket_id,:fault,:created_at)""",
        run,
    )
    event(cx, run["id"], "created", {"arm": run["arm"], "status": run["status"]})
    cx.commit()


def get_run(cx, run_id: str) -> sqlite3.Row | None:
    return cx.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()


def set_status(cx, run_id: str, status: str, **extra) -> None:
    parts = ", ".join(f"{k}=?" for k in extra)
    vals = list(extra.values()) + [status, run_id]
    cx.execute(f"UPDATE runs SET {parts + ', ' if extra else ''}status=? WHERE id=?", vals)
    event(cx, run_id, "status", status)
    cx.commit()


class ApprovalError(Exception):
    pass


def approve(cx, run_id: str, actor: str, expected_hash: str) -> None:
    run = get_run(cx, run_id)
    if not run:
        raise ApprovalError("unknown_run")
    if run["package_hash"] != expected_hash:
        raise ApprovalError("hash_mismatch")
    if run["status"] != "awaiting_approval":
        raise ApprovalError("not_awaiting_approval")
    if not actor or actor.startswith("llm"):
        raise ApprovalError("actor_not_human")
    pkg = json.loads(run["package"])
    if not pkg.get("approval_required"):
        raise ApprovalError("approval_not_required")
    cx.execute(
        """INSERT INTO approvals(run_id, actor, action, package_hash, destination, at, used)
           VALUES (?,?,?,?,?,?,0)""",
        (run_id, actor, "create_ticket", expected_hash, run["destination"], _now()),
    )
    set_status(cx, run_id, "approved")
    event(cx, run_id, "approved", {"actor": actor, "package_hash": expected_hash})
    cx.commit()


class TicketError(Exception):
    def __init__(self, code: str, ticket_id: str | None = None):
        super().__init__(code)
        self.code = code
        self.ticket_id = ticket_id


def send_ticket(cx, owner: str, key: str, payload: dict, destination: str, fault: str | None) -> str:
    if destination not in ("mock://desk/taf", "mock://desk/eaf"):
        raise TicketError("destination_denied")
    existing = cx.execute("SELECT * FROM tickets WHERE idempotency_key=?", (key,)).fetchone()
    if existing:
        return existing["id"]
    tid = "TCK-" + uuid.uuid4().hex[:8]
    complete = 0 if fault == "partial_write" else 1
    body = dict(payload)
    if fault == "partial_write":
        body.pop("preferred_time", None)
        body["partial"] = True
    cx.execute(
        """INSERT INTO tickets(id, owner, idempotency_key, payload, complete, created_at)
           VALUES (?,?,?,?,?,?)""",
        (tid, owner, key, json.dumps(body), complete, _now()),
    )
    cx.commit()
    if fault == "timeout":
        raise TicketError("timeout", tid)
    return tid


def fetch_ticket(cx, owner: str, ticket_id: str | None = None, key: str | None = None) -> dict | None:
    if ticket_id:
        row = cx.execute("SELECT * FROM tickets WHERE id=? AND owner=?", (ticket_id, owner)).fetchone()
    elif key:
        row = cx.execute("SELECT * FROM tickets WHERE idempotency_key=? AND owner=?", (key, owner)).fetchone()
    else:
        return None
    if not row:
        return None
    return dict(row)
