# Testing whether governed AI agents can reduce rework in student-service operations without weakening accuracy, privacy or human control

Independent Higher Education AI Engineering case study. Public University of Melbourne timetable and enrolment pages. Synthetic cases. Mock service desk. **Not** commissioned university work, **not** a production deployment, **not** evidence of staff adoption or realised cash savings.

## 1. Business problem

Student timetable and enrolment requests often arrive incomplete or mis-routed. Staff rework happens *before* the underlying issue is solved: missing subject codes, TAFs lodged when a swap was available, late-enrolment rules that conflict across faculties.

Hypothesis (not assumed fact): a governed agent can cut that preparation rework on ambiguous, multi-step requests. A well-designed form may still win on complete, in-policy cases.

## 2. Intervention

Three arms, **same cases, same frozen sources, same package schema**:

| Arm | What it does | Writes to a desk? |
|---|---|---|
| A Structured self-service | Required fields and deterministic routing | No |
| B RAG assistant | Natural language + cited excerpts | No |
| C Governed agent | Classify → retrieve → fill known fields only → **human approval outside the model** → mock ticket → read-back verify | Yes, after approval |

The agent prepares a **request package**. It does not decide visas, fees, hardship, AAP/disability, discipline, or admissions.

## 3. Comparison design

Primary KPI: **Active staff minutes per accepted service request**.

- **Accepted (A):** in-scope and form-complete (`form_ready`).
- **Accepted (C):** in-scope and `approve → send → verify`.
- **Accepted (B):** none by design (no writes). B is compared on minutes and whether missing fields/sources are identified.
- Coverage (accepted / in-scope) is always shown so abstention cannot inflate the KPI.
- Minutes are a **scripted model** (`app/workflow.py`), not timed staff. Dry-run values are not organisational KPIs.

## 4. Measured results

Dry-run of the mock (scripted minutes, **DERIVED**, not timed staff):

| Metric | Self-service (A) | RAG (B) | Agent (C) |
|---|---|---|---|
| Staff minutes / accepted request | 2.0 | — | 3.5 |
| Accepted count | 9 | 0 | 5 |
| Coverage (accepted / in-scope) | 0.69 | 0.00 | 0.38 |

On this synthetic set the **form beats the agent** on complete in-policy requests. That is a legitimate outcome. B never writes, so accepted is 0 by design. Reproduce: `python -m app.study` then `GET /`.

Live LLM/Jira/AWS numbers: **NOT MEASURED** until keys exist.


## 5. Economic conclusion

Not yet. No realised cash savings are claimed. Capacity released ≠ cash saved.

## 6. Governance

- Restricted topics: classify → stop → human. No retrieve, no write.
- Approval is a SQLite row bound to `package_hash`. The model has no approve tool. Edits change the hash.
- Ticket fetch is `WHERE owner = :student_id` from `X-Student-Id`, not from the prompt.
- Retrieved text is data. Destinations are allowlisted (`mock://desk/taf|eaf`).
- LLM and Jira keys are **not** wired. Adapters are mocks until keys are supplied.

## 7. Architecture

Student request → identity header → scope gate → frozen excerpts → package validator → pause → human approval → mock desk → verify → event log → executive page.

No LangGraph, no pgvector, no AWS in this slice.

## 8. Reproduction

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m app.study
uvicorn app.main:app --port 8000
# open http://127.0.0.1:8000
```

Identity is simulated: `X-Student-Id`, `X-Actor-Id`.

## 9. Technical stack

Python 3.12, FastAPI, Pydantic, SQLite. Retrieval is lexical over frozen Markdown excerpts. Knowledge domain: University of Melbourne public coursework pages (documentation quality only — no operational judgement about the university).
