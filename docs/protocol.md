# Study protocol (dry-run)

## Claim labels

| Label | Meaning |
|---|---|
| OBSERVED | Telemetry from this mock (states, hashes, IDOR blocks, verify). |
| DERIVED | Scripted minutes from `MINUTES` in `app/workflow.py`. |
| NOT MEASURED | Human review time, model quality, Jira, AWS cost, adoption. |

## Arms

All arms emit `Package`. B never writes. C writes only after `POST /runs/{id}/approve`.

## Staff-minute model (DERIVED)

| Path | Minutes |
|---|---|
| A complete | 2.0 |
| A incomplete | 10.0 |
| B (always rebuild) | 12.0 |
| C verified | 3.5 |
| C escalate / abstain / missing | 12.0 |
| C verify fail / unknown | 9.5 |
| Restricted / out of scope | 6.0 |

## Acceptance

In-scope A `form_ready` or in-scope C `verified`. Restricted cases are safety rows, not the productivity denominator.

## Knowledge

Excerpts in `data/sources/`, hashed at load. No runtime crawl. Synthetic adversarial fixture is not institutional policy.

## Keys still required

LLM provider, Jira sandbox, AWS. Until then: mocks only.
