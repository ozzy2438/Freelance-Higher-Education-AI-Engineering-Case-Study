from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from app.controls import build_package
from app.models import Arm, CLAIM, Status
from app import store, workflow
from app import llm as llm_mod

DATA = Path(__file__).resolve().parent.parent / "data" / "cases_dev.json"


def run_study(simulate_approval: bool = True) -> dict:
    llm_mod.session.update(calls=0, prompt_tokens=0, completion_tokens=0, usd=0.0, model=None)
    llm_mod._cache.clear()
    cases = json.loads(DATA.read_text())["cases"]
    cx = store.connect()
    rows = []
    for case in cases:
        sid = case.get("student_id", "SYN-STU-001")
        for arm in Arm:
            prep = workflow.prepare(case, arm, sid, cx)
            pkg = prep["package"]
            final = pkg.action_status
            write = None
            if arm is Arm.C and pkg.approval_required and simulate_approval:
                store.approve(cx, prep["run_id"], "staff-pilot-simulated", pkg.package_hash)
                write = workflow.execute_write(prep["run_id"], sid, cx)
                st = write.get("status")
                final = Status.VERIFIED if write.get("ok") else Status(st) if st in Status._value2member_map_ else Status.FAILED
            if case["id"] == "SYN-SEC-02":
                idor = workflow.probe_idor(sid, "TCK-OTHER")
            else:
                idor = None
            mins = workflow.staff_minutes(arm, pkg, final)
            acc = workflow.accepted(arm, pkg, final)
            rows.append(
                {
                    "case_id": case["id"],
                    "type": case["type"],
                    "arm": arm.value,
                    "category": pkg.category.value,
                    "routing": pkg.routing,
                    "status": final.value,
                    "missing": pkg.missing,
                    "escalation": pkg.escalation,
                    "minutes": mins,
                    "accepted": acc,
                    "hash": pkg.package_hash[:10],
                    "idor_blocked": None if idor is None else idor["blocked"],
                    "write": write,
                    "llm_usd": (pkg.trace.get("llm") or {}).get("usd"),
                    "llm_cache": (pkg.trace.get("llm") or {}).get("cache"),
                }
            )
    by_arm: dict[str, list] = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)

    def rollup(arm: str) -> dict:
        rs = by_arm[arm]
        in_scope = [r for r in rs if r["category"] in ("timetable", "enrolment")]
        acc = [r for r in rs if r["accepted"]]
        total_min = sum(r["minutes"] for r in rs)
        return {
            "n": len(rs),
            "in_scope": len(in_scope),
            "accepted": len(acc),
            "staff_minutes_total": round(total_min, 2),
            "staff_minutes_per_accepted": None if not acc else round(sum(r["minutes"] for r in acc) / len(acc), 2),
            "staff_minutes_per_case": round(total_min / len(rs), 2),
            "first_pass_ready": sum(1 for r in in_scope if r["status"] in ("form_ready", "verified", "rag_only") and not r["missing"]),
            "escalation": sum(1 for r in rs if r["status"] in ("stop_human", "abstained", "need_fields")),
            "coverage_accepted_over_inscope": None if not in_scope else round(len(acc) / len(in_scope), 2),
        }

    out = {
        "claim": CLAIM,
        "kpi_note": "Primary KPI uses accepted requests only AND is reported next to coverage so abstention cannot silently look like productivity.",
        "llm": dict(llm_mod.session),
        "arms": {a.value: rollup(a.value) for a in Arm},
        "rows": rows,
    }
    Path(store.DB).parent.joinpath("study_report.json").write_text(json.dumps(out, indent=2))
    return out


def report_html() -> str:
    path = Path(store.DB).parent / "study_report.json"
    if not path.exists():
        data = run_study()
    else:
        data = json.loads(path.read_text())
    arms = data["arms"]

    def cell(arm, key):
        v = arms[arm][key]
        return "—" if v is None else v

    rows = "".join(
        f"<tr><td>{r['case_id']}</td><td>{r['arm']}</td><td>{r['category']}</td>"
        f"<td>{r['status']}</td><td>{r['minutes']}</td><td>{'yes' if r['accepted'] else 'no'}</td></tr>"
        for r in data["rows"]
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Executive view</title>
<style>
body{{font:16px/1.45 system-ui;max-width:960px;margin:2rem auto;padding:0 1rem;color:#111}}
.banner{{background:#111;color:#fff;padding:.75rem 1rem;margin-bottom:1.5rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}
td,th{{border:1px solid #ddd;padding:.4rem .5rem;text-align:left}}
th{{background:#f4f4f4}}
.muted{{color:#555}}
</style></head><body>
<div class="banner">{CLAIM}</div>
<h1>Can a governed agent reduce student-service rework?</h1>
<p>Independent case study on University of Melbourne <em>public</em> timetable and enrolment guidance. Synthetic cases. Mock service desk. Not a university deployment.</p>
<h2>What we tested</h2>
<p>Two workflows: class timetable / allocation support, and enrolment process support. Three arms on the same cases: structured form (A), RAG without writes (B), governed agent with human approval (C).</p>
<table>
<tr><th>Metric</th><th>Self-service (A)</th><th>RAG (B)</th><th>Agent (C)</th></tr>
<tr><td>Staff minutes / accepted request</td><td>{cell('self_service','staff_minutes_per_accepted')}</td><td>{cell('rag','staff_minutes_per_accepted')}</td><td>{cell('agent','staff_minutes_per_accepted')}</td></tr>
<tr><td>Accepted count (denominator)</td><td>{cell('self_service','accepted')}</td><td>{cell('rag','accepted')}</td><td>{cell('agent','accepted')}</td></tr>
<tr><td>Staff minutes / all cases</td><td>{cell('self_service','staff_minutes_per_case')}</td><td>{cell('rag','staff_minutes_per_case')}</td><td>{cell('agent','staff_minutes_per_case')}</td></tr>
<tr><td>In-scope cases</td><td>{cell('self_service','in_scope')}</td><td>{cell('rag','in_scope')}</td><td>{cell('agent','in_scope')}</td></tr>
<tr><td>Coverage (accepted / in-scope)</td><td>{cell('self_service','coverage_accepted_over_inscope')}</td><td>{cell('rag','coverage_accepted_over_inscope')}</td><td>{cell('agent','coverage_accepted_over_inscope')}</td></tr>
<tr><td>Escalations / incomplete / abstain</td><td>{cell('self_service','escalation')}</td><td>{cell('rag','escalation')}</td><td>{cell('agent','escalation')}</td></tr>
</table>
<p class="muted">Minutes are a published scripted model, not timed staff. RAG accepted count is 0 by design (no writes). LLM summaries on B/C: model <code>{(data.get('llm') or {}).get('model') or 'off'}</code>, calls {(data.get('llm') or {}).get('calls', 0)}, cost USD {round((data.get('llm') or {}).get('usd') or 0, 6)} (OBSERVED token bill). Staff minutes remain DERIVED. Not organisational KPIs.</p>
<h2>Where the agent should not win</h2>
<p>Complete in-policy swap/self-enrol cases should favour the form. Mixed visa/AAP requests must stop. FBE Week-3 vs generic late-enrolment must abstain. Ticket reads are owner-scoped in code.</p>
<h2>Case log</h2>
<table><tr><th>Case</th><th>Arm</th><th>Category</th><th>Status</th><th>Min</th><th>Accepted</th></tr>{rows}</table>
<p class="muted">Technical traces: <code>GET /runs/{{id}}</code>. Reproduce: <code>python -m app.study</code>.</p>
</body></html>"""


if __name__ == "__main__":
    print(json.dumps(run_study(), indent=2))
