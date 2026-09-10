from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from app.models import Category, FieldVal, Origin, Package, PolicyRef, Status

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEST = {"taf": "mock://desk/taf", "eaf": "mock://desk/eaf"}

RESTRICTED = re.compile(
    r"""(?ix)
    \b(student\s+visa|visa\s+status|\bCOE\b|confirmation\s+of\s+enrolment|
       scholarship|hardship|fee\s+waiver|refund|HELP\s+loan|Student\s+Learning\s+Entitlement|
       disciplinary|misconduct|academic\s+honesty|
       academic\s+adjustment\s+plan|\bAAP\b|health-related|
       special\s+consideration|special\s+circumstances|
       leave\s+of\s+absence|\bdefer(?:ral)?\b|passport|
       ignore\s+(your\s+)?(previous|institutional)\s+(instructions|rules)|
       send\s+this\s+student.?s\s+details\s+externally)
    """,
)

SUBJECT = re.compile(r"\b([A-Z]{4}\d{5})\b")
TOKEN = re.compile(r"[a-z0-9]+")


def _load_chunks() -> list[dict]:
    manifest = json.loads((DATA / "manifest.json").read_text())
    chunks = []
    for src in manifest["sources"]:
        raw = (DATA / src["file"]).read_text()
        parts = re.split(r"<!--\s*excerpt:([^\s]+)\s+tags:([^>]+)-->", raw)
        # parts[0] preamble, then (id, tags, body)*
        for i in range(1, len(parts), 3):
            body = parts[i + 2].strip()
            chunks.append(
                {
                    "source_id": src["id"],
                    "excerpt_id": parts[i].strip(),
                    "tags": [t.strip() for t in parts[i + 1].split(",")],
                    "text": body,
                    "sha256": hashlib.sha256(body.encode()).hexdigest()[:16],
                    "authority": src.get("authority"),
                    "url": src["url"],
                }
            )
    return chunks


CHUNKS = _load_chunks()


def classify(text: str) -> Category:
    if RESTRICTED.search(text):
        return Category.RESTRICTED
    t = text.lower()
    tt = any(w in t for w in ("timetable", "taf", "clash", "tutorial", "lecture", "waitlist", "class is full", "mytimetable"))
    en = any(w in t for w in ("enrol", "study plan", "eaf", "self-enrol", "census", "coordinator"))
    if tt and not en:
        return Category.TIMETABLE
    if en and not tt:
        return Category.ENROLMENT
    if tt and en:
        return Category.RESTRICTED  # mixed → fail-closed
    return Category.OUT_OF_SCOPE


def retrieve(query: str, k: int = 4) -> list[dict]:
    q = set(TOKEN.findall(query.lower()))
    scored = []
    df = {w: sum(w in TOKEN.findall(c["text"].lower()) for c in CHUNKS) for w in q}
    n = len(CHUNKS)
    for c in CHUNKS:
        toks = TOKEN.findall(c["text"].lower())
        tf = {w: toks.count(w) for w in q}
        score = sum((1 + math.log(1 + tf[w])) * math.log((n + 1) / (1 + df[w])) for w in q if tf[w])
        # keep synthetic fixture retrievable when named
        if "syn-inject" in c["excerpt_id"] and "adversarial" not in query.lower():
            score *= 0.05
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:k]]


def extract_fields(text: str, form: dict | None) -> dict[str, FieldVal]:
    """Accept values only from the ticket/form. Never invent."""
    fields: dict[str, FieldVal] = {}
    blob = text + " " + json.dumps(form or {})
    if m := SUBJECT.search(blob):
        fields["subject_code"] = FieldVal(value=m.group(1), origin=Origin.USER, quote=m.group(1))
    form = form or {}
    for k, v in form.items():
        if v in (None, "", "UNKNOWN") and k == "subject_code":
            continue
        if v in (None, ""):
            continue
        fields[k] = FieldVal(value=str(v), origin=Origin.USER, quote=str(v))
    t = text.lower()
    if "issue_type" not in fields:
        for pat, val in (
            (r"no classes available|all \w+ are full", "no_classes"),
            (r"mandatory|core subjects clash|core clash", "core_clash"),
            (r"back-to-back|finishes when|not a clash", "back_to_back"),
            (r"still has seats|how do i move|another tutorial", "swap"),
            (r"empty study plan|only shows the course title", "empty_plan"),
        ):
            if re.search(pat, t):
                fields["issue_type"] = FieldVal(value=val, origin=Origin.USER, quote=val)
                break
    if "action" not in fields:
        if "empty study plan" in t or fields.get("issue_type") and fields["issue_type"].value == "empty_plan":
            fields["action"] = FieldVal(value="empty_plan", origin=Origin.USER)
        elif re.search(r"last self-enrol|late enrol|eaf", t):
            fields["action"] = FieldVal(value="late_enrol", origin=Origin.USER)
    if "coordinator_approval" not in fields and re.search(r"coordinator.*approv|approv.*coordinator|have the pdf", t):
        fields["coordinator_approval"] = FieldVal(value="yes", origin=Origin.USER)
    if "faculty" not in fields and re.search(r"faculty of business and economics|\bfbe\b", t):
        fields["faculty"] = FieldVal(value="fbe", origin=Origin.USER)
    if "week" not in fields and (m := re.search(r"week\s+(\d)", t)):
        fields["week"] = FieldVal(value=m.group(1), origin=Origin.USER)
    if "class_type" not in fields:
        for ct in ("tutorial", "lecture", "seminar", "lab"):
            if ct in t:
                fields["class_type"] = FieldVal(value=ct, origin=Origin.USER, quote=ct)
                break
    if "preferred_time" not in fields and (m := re.search(r"(monday|tuesday|wednesday|thursday|friday)?\s*\d{1,2}(?::\d{2})?\s*(am|pm)", t, re.I)):
        fields["preferred_time"] = FieldVal(value=m.group(0).strip(), origin=Origin.USER, quote=m.group(0).strip())
    if "self_service_attempted" not in fields and re.search(r"already tried swapping|waitlist heart|used the waitlist", t):
        fields["self_service_attempted"] = FieldVal(value="yes", origin=Origin.USER)
    return fields


def _required(cat: Category, fields: dict[str, FieldVal]) -> list[str]:
    issue = (fields.get("issue_type") or FieldVal(origin=Origin.SYSTEM)).value
    action = (fields.get("action") or FieldVal(origin=Origin.SYSTEM)).value
    if cat is Category.TIMETABLE:
        if issue in ("swap", "back_to_back", "clash"):
            return ["subject_code", "issue_type"]
        return ["subject_code", "issue_type", "class_type", "preferred_time"]
    if cat is Category.ENROLMENT:
        if action == "empty_plan" or issue == "empty_plan":
            return ["action"]
        if action == "late_enrol":
            return ["subject_code", "action", "coordinator_approval"]
        return ["subject_code", "action"]
    return []


def _route(cat: Category, fields: dict[str, FieldVal], refs: list[PolicyRef]) -> tuple[str, str | None, bool]:
    """Returns routing, destination, conflict."""
    tags = {t for r in refs for t in r.tags}
    issue = (fields.get("issue_type") or FieldVal(origin=Origin.SYSTEM)).value
    action = (fields.get("action") or FieldVal(origin=Origin.SYSTEM)).value
    faculty = (fields.get("faculty") or FieldVal(origin=Origin.SYSTEM)).value
    week = int((fields.get("week") or FieldVal(value="0", origin=Origin.SYSTEM)).value or 0)
    if action == "late_enrol" and faculty == "fbe" and week >= 3:
        return "policy_conflict_human", None, True
    if faculty == "fbe" and "late_enrol_fbe" in tags and "late_enrol_generic" in tags:
        return "policy_conflict_human", None, True
    if cat is Category.TIMETABLE:
        if issue in ("no_classes", "core_clash"):
            return "taf_faculty", DEST["taf"], False
        return "self_service_mytimetable", None, False
    if cat is Category.ENROLMENT:
        if action in ("late_enrol", "empty_plan") or issue == "empty_plan":
            return "enrolment_assistance_form", DEST["eaf"], False
        return "self_service_myunimelb", None, False
    return "human_queue", None, False


def build_package(text: str, form: dict | None, arm: str) -> Package:
    cat = classify(text)
    trace = {"classifier": "deny_list+allowlist", "arm": arm}
    if cat in (Category.RESTRICTED, Category.OUT_OF_SCOPE):
        return Package(
            category=cat,
            summary="Request stopped. No retrieval, no write. Human queue only.",
            fields={},
            missing=[],
            policy_refs=[],
            routing="human_queue",
            escalation=True,
            approval_required=False,
            action_status=Status.STOP_HUMAN,
            destination=None,
            trace=trace,
        )
    refs_raw = retrieve(text)
    refs = [
        PolicyRef(
            source_id=c["source_id"],
            excerpt_id=c["excerpt_id"],
            quote=c["text"].replace("\n", " ")[:280],
            tags=c["tags"],
        )
        for c in refs_raw
        if c["authority"] != "synthetic_fixture" or "adversarial" in text.lower()
    ]
    # Still record that adversarial text was retrieved, as DATA only
    if any(c["excerpt_id"] == "syn-inject" for c in refs_raw):
        trace["retrieved_data_not_instructions"] = True
    fields = extract_fields(text, form)
    routing, dest, conflict = _route(cat, fields, refs)
    missing = [k for k in _required(cat, fields) if k not in fields or not fields[k].value]
    if conflict:
        status = Status.ABSTAINED
        dest = None
        summary = "Competing late-enrolment rules retrieved (generic 72-hour EAF vs FBE Week-3 cutoff). No write."
    elif missing:
        status = Status.NEED_FIELDS
        dest = None
        summary = "Known fields kept; unknown fields left unknown. No invented values."
    elif dest:
        status = Status.AWAITING_APPROVAL if arm == "agent" else (Status.FORM_READY if arm == "self_service" else Status.RAG_ONLY)
        summary = "Complete in-scope package. Write requires server-side approval for the agent arm."
    else:
        status = Status.FORM_READY if arm == "self_service" else Status.RAG_ONLY
        dest = None
        summary = "Self-service path. No service-desk write."
    if arm == "rag":
        status = Status.RAG_ONLY
        dest = None
    elif not dest and not missing and not conflict:
        status = Status.FORM_READY
    pkg = Package(
        category=cat,
        summary=summary,
        fields=fields,
        missing=missing,
        policy_refs=refs,
        routing=routing,
        escalation=conflict or bool(missing) or dest is None and cat != Category.TIMETABLE,
        approval_required=arm == "agent" and dest is not None and not missing and not conflict,
        action_status=status,
        destination=dest if arm == "agent" else None,
        trace=trace,
    )
    frozen = json.dumps(
        {
            "category": pkg.category,
            "fields": {k: v.value for k, v in pkg.fields.items()},
            "missing": pkg.missing,
            "routing": pkg.routing,
            "destination": pkg.destination,
        },
        sort_keys=True,
    )
    pkg.package_hash = hashlib.sha256(frozen.encode()).hexdigest()
    return pkg
