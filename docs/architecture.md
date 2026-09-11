# Architecture (30 seconds)

Synthetic request → `X-Student-Id` → deny-list then allowlist (timetable | enrolment | stop) → lexical retrieval over frozen public excerpts → server builds a package (known fields only) → if a write is proposed, SQLite records a pause → a human `X-Actor-Id` approves the exact hash → mock desk creates once (idempotency key) → read-back verify → executive page.

Supporting: append-only events, destination allowlist, owner-scoped fetches.

Not in this slice: LangGraph, vector DB, AWS, chat UI, real Jira.
