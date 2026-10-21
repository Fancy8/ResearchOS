# P0 acceptance progress

All F01-F15, AC01-AC15 and enterprise gates remain in scope. Implemented screens
and smoke checks do not close the full release acceptance gate.

| Area | Current evidence | Remaining acceptance |
| --- | --- | --- |
| F01 identity | Sessions/CSRF/invitations/isolation, persistent throttling, verification/reset and real queue/browser links | Production SMTP and complete endpoint security |
| F02 onboarding | Partial draft/version/resume/idempotency; browser server-only interrupted resume | Extended offline/conflicting draft coverage |
| F03/F04 research | CRUD/archive/default/history; paged project assets/history; older default independent of first page | Complete status/history screen audit and production capacity |
| F05/F06 PDF | Private storage/queue; metadata/version/retry; source hashes; bounded Windows process tree; actual full solo-daemon kill, broker redelivery, both lease states, duplicate publication and killed-temp maintenance | Extended samples, version/retry UI, supported-production-platform supervision/daemon recovery, full OS sandbox/load |
| F07 evidence | Immutable sources, exact text/fallback/malformed rejection; browser highlight/zoom | Extended multi-page/coordinate/unavailable-source cases |
| F08 hypotheses | Explicit relations/revisions; edit/remove/history UI; numeric history paging and paged basis selectors | Extended relation/history states and production capacity |
| F09 decisions | Immutable snapshots; basis/conflict UI; browser revisions 1-4 and 25-version navigation; selections retained across pages | Complete basis/error audit and production capacity |
| F10 tasks | Exact provenance; edit/status/date/priority/detail browser checks; paged task list and project choices | Filters and failed-write UI |
| F11 dashboard | Real aggregation, explicit stage and validated scoped pinned order | Browser layout/concurrency/empty/failure cases |
| F12 notes | Autosave/offline/formulas/two-page conflict/trash; relations | Relation/formula snapshot/export and extended input coverage |
| F13 search | Literal escaping, scoped pagination and exact jumps; retained results on later failure; server title filter finds older library rows | Chinese short-query/data-volume load and complete result-state audit |
| F14 timeline | Transactional events and object/revision navigation | Full event schema and unavailable-target audit |
| F15 data | ZIP/deletion/faults; isolated archive and encrypted DB/original recovery; append-only independent current journal/head/inventory gates; checkpoint and legacy snapshot floor; pending receipt UI; transactional target reopening; expiry/orphan/temp reconciliation and quota release | Production-scale recovery, key/backup activation/retention/operator remnants, authority-owner rollback/fresh external witness/off-host recovery, crash/lease/large exports |
| Quality | Nine business and four journal migrations with separate roles; populated 0007-to-0008 upgrade drill; read-only scheduled backup operator/catalog/retention tests; actual killed operator dump cleanup/retry/restore; all 97 declared success response schemas and internal-field checks; generated types; local build/checks; CI configuration | Clean-host/hosted CI, complete status/error UI, security/load/backup activation/compatibility/deployment/runbooks |

Verified browser cases cover research core; PDF/evidence/hypothesis/decision/task/
source highlight/ZIP; note offline/formula/two-page conflict/trash/profile; task/
decision basis/conflict/search; account deletion; verification/password recovery.
See implementation-status.md for aggregate evidence and limits. Real-user trials
and external production deployment have not been performed.
