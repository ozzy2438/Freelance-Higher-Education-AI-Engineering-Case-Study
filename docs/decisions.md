# Decision log

Append-only. Supervisor review (five models) directed this slice.

## 2026-09-10 — Scope and stack

- University of Melbourne public coursework pages only (TAF, swap, enrolment, EAF, MPF1294 excerpts). Not a claim that Melbourne operations are inefficient. Stop 1 AI Assistant is not evaluated.
- Cut LangGraph, Postgres/pgvector, AWS, chat UI, pytest tree.
- State machine + SQLite + lexical retrieval.
- Jira, if added later, is a sandbox **surrogate**, not Melbourne's desk. Contract: `data/service_contract.yaml`.

## 2026-09-10 — Controls

- Every enterprise write needs human approval bound to package hash, destination, run id, actor from `X-Actor-Id`.
- Unknown fields stay unknown. Package fields originate from ticket/form text only.
- Restricted/mixed intent: fail-closed, no retrieve, no write.
- FBE Week-3 vs generic 72-hour EAF: abstain (policy conflict).
- Hidden evaluation set is **not** in this repo.

## 2026-09-10 — KPI honesty

- Scripted staff minutes, labelled dry-run.
- Report minutes/accepted **and** coverage **and** minutes/all cases.
- Do not convert minutes to dollars.

## 2026-09-11 — OpenAI nano for B/C summaries only

- Model `gpt-5-nano` (cheapest list price). Key in `.env`, never committed.
- Code still owns classify, fields, routing, approval, destinations.
- LLM drafts a grounded summary after the scope gate. Restricted/out-of-scope and arm A skip the API.
- Identical ticket+quotes reuse one cached call (B and C share).
