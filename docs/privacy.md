# Privacy and data destinations

Synthetic identities only (`SYN-STU-*`). No real student records.

| Data | Hits LLM (when keyed) | Stored | Logs |
|---|---|---|---|
| Student header id | No | `runs.student_id` | run events |
| Request text | Yes, allowlisted fields later | `package` JSON | not raw by default in events |
| Retrieved excerpts | As DATA quotes | package.policy_refs | source ids |
| Approval actor | No | `approvals.actor` | approval event |
| Passwords / visas / medical | Must not be collected | — | — |

Events store kind + short detail. Ticket payloads are mock fields (subject code, issue type). Retention: local `var/pilot.db` for the pilot; delete with the workspace.

Identity assurance is **simulated**.
