# Implementation status

The scope remains all P0 functions and enterprise gates in the design. This is a
running implementation with verified milestones, not a completed release.
All source, references, runtime, credentials, cache and reports remain under
`<checkout>`.

## Verified implementation

- Local source evaluation/provenance, PostgreSQL 16.14, 36 typed ORM models
  (the original 35 plus a cleanup-only checkpoint table), nine Alembic revisions
  and separate application/cleanup/migration roles.
- Next.js/FastAPI, private S3 storage, Redis, Celery and transactional outbox.
  Launchers check both web and API readiness.
- Invitations, opaque sessions, CSRF/isolation, project/thread histories,
  hypotheses, immutable three-source decision snapshots and exact task provenance.
- PDF validation/isolated parsing, historical versions, metadata/retry interfaces,
  source-immutable evidence, scan/ambiguity fallback and rendered-text revalidation
  before highlighting. Browser checks verify highlights after zoom. PDF reads
  reject bytes that fail the retained source hash.
- PDF evidence drafts retain rendered file/page and selected thread independently
  of subsequent reading/navigation. Unknown outcomes replay an unchanged path/body/
  key; confirmed writes survive file-read failures. Published current versions are
  observed after worker completion, and stale page/text work is cancelled before
  capture. See evidence-state-acceptance.md for lifetime and verification limits.
- Association ownership/dependencies, project assets and note links; precise
  object/history navigation; scoped multi-type search pagination; full task editing.
- Task filters run before SQL pagination with scope-bound cursors and URL-restored
  conditions. Shared status actions retain failed request intent; both task-create
  entry points preserve idempotency/context, including an earlier decision revision.
  Task edits require explicit conflict comparison; replayed creation receipts cannot
  downgrade a newer confirmed task cache. See task-state-acceptance.md for limits.
- Decision basis editing and explicit conflict comparison. Browser revisions 1-4
  preserve the original decision and task source revision.
- Decision creation/revision share a controlled draft and stable unknown-outcome
  request. Successful receipts and later read failures are separated; comparison
  reads must succeed before an explicit rebase, including repeated conflicts.
  Source selection survives paging and missing list entries. See
  decision-state-acceptance.md for component lifetime and commit-time snapshot limits.
- Partial onboarding drafts/version conflicts/resume; structured note autosave,
  offline recovery, formulas, relations, trash and restore. Two-page conflict
  testing preserves input. A stale note-detail cache after restore was fixed.
- Explicit stage/preferences and validated scoped dashboard/pinned ordering.
- Persistent Redis authentication limits; expiring, purpose-separated single-use
  verification/reset links. Reset revokes sessions. Outbound envelopes are encrypted
  and delivered through the outbox. Local previews and actual queue/browser flows
  are verified. Real SMTP delivery remains unverified; production refuses previews.
- Controlled deletion with signed impact previews, password reauthentication,
  dependency checks, writer exclusion, dedicated cleanup role, session revocation,
  file/history/identity erasure and opaque receipts. Fault retry and signed identity
  ledger replay were tested. Isolated database/object restore also finishes pending
  deletions and anonymous receipts before opening access, including queued/running/
  failed requests. Cleanup credentials must route to the same isolated target;
  recovery storage is explicit. Real connection rejection/source-byte preservation
  are verified after SQL, object-hash and ledger-signature failures.
- An independent PostgreSQL deletion authority has three separately owned
  journal tables, four Alembic revisions and append-only/read-only runtime roles.
  Signed chains/current heads/reviewed activation detect omitted entries, missing
  tails and rollback behind a backup checkpoint. API acknowledgement requires a
  durable business intent and authority record; partial journal failures retain
  an opaque receipt and worker retry. Replay holds a stable current-head gate
  through a transactional final sanitation/CONNECT grant. Replacement deployments
  retain the logical source identity across database/bucket renaming.
  Local legacy inventory found five unreconstructible anonymous account receipts:
  the signed cutover floor rejects snapshots before 2026-10-15 04:32:42.840342 UTC.
  See deletion-journal-runbook.md. Local authority/business databases share a
  cluster; production endpoint/failure-domain, privileged rollback/witness and
  key/administrative isolation are not certified.
- ZIP export preserves 27 business tables, relationships, history and original
  files. A downloaded browser archive passed relation/hash/privacy checks. Snapshot
  deadlines, failed-package cleanup, corrupt/missing-source failure and deliberately
  removed unreferenced version markers have targeted tests.
- Core public response DTOs, machine-readable errors, deterministic OpenAPI and
  generated TypeScript types: 74 paths / 143 schemas. All 97 declared success
  responses have concrete schemas (95 JSON and two binary downloads), checked
  recursively for internal-only fields. Framework 404/405 use the error envelope;
  405/413/415 are declared. Frontend identity/dashboard/activity/onboarding types
  come from these contracts; unset onboarding fields remain absent.
- Cursor pagination across primary lists, histories, file versions and asset
  associations, with UI continuation/retained rows/retry and paged selectors.
  Title filtering runs server-side with literal escaping. Current project lookup
  resolves an older default independently of the first list page. Duplicate
  suggestions omit missing/deleting originals and link the exact matching version;
  list file summaries use one batched query and expose availability explicitly.
- Local verify script and hosted Windows CI configuration supplied. Hosted CI has
  not been run. Operations are documented in operating-local.md.
- Official npm advisory check identified one low-severity KaTeX trust-inheritance
  issue; the dependency is now pinned to 0.18.10, with three renderer security/
  ordinary formula regressions. A hash-matched old npm package fails the two
  security cases; the patched version passes all three. The official post-patch
  audit reports zero known npm advisories. The mirror's initial 404 is preserved
  as failed evidence. See dependency-security.md; Python/full security audits
  remain open.
- Periodic expiry/reconciliation uses dedicated cleanup credentials, singleton/
  nonblocking preservation locks, durable space/page rotation, grace periods and
  retryable storage failures. Aged unreferenced final/staging/export objects and
  domain-worker temporary files are reconciled while originals, active jobs,
  young/unknown objects and other database namespaces are preserved. Versioned
  pagination and prefix deletion include hidden versions/markers; local storage
  tests cover enabled/suspended versioning. The registered task runs in a real
  isolated queue worker. File deletion releases quota only after erasure, while
  new pending uploads reserve quota. See maintenance-runbook.md for exact limits.
- A separate backup operator now uses a SELECT-only, non-owner reader. Daily UTC
  slot catch-up, durable signed catalogs, independent process restart, backoff,
  ciphertext checks and policy-gated retention are implemented and tested with
  real PostgreSQL/object restores. Ordinary/interrupted-run temporary cleanup is
  scoped to catalog-owned paths. Development activation and live expiry remain
  disabled; key escrow/OS secret separation/production monitoring are not certified.
- Windows PDF/PG subprocesses now share bounded process-tree supervision with
  atomic creation-time Job membership, private environment whitelists, resource
  limits and sanitized failures. Real owner-kill/dump-retry/task-lease cases pass;
  the exact test scope and retained failures are in process-supervision.md.
  Linux supervision, full OS sandboxing and supported-platform daemon recovery remain gates;
  local solo Worker evidence is not an upstream-supported Windows production claim.
- Dispatcher now drives bounded independent Redis visibility recovery, isolates
  failures of recovery/outbox/expiry scheduling and supplies redacted read-only
  broker metadata. Real local solo-daemon kill, same-ID broker restoration,
  valid/expired business leases, duplicate publication prevention and maintenance
  of actual killed-parser remnants pass. See broker-recovery-runbook.md.

## Current evidence

Research creation recovery is being closed for the requested 2026-10-16 timed
pause. Three create routes now honor optional idempotency keys with actor/space/
operation/parent scope; unkeyed legacy API calls retain their original semantics.
New frontend entries persist original targets/body/key, freeze unknown outcomes,
retain known receipts across read failures and avoid seeding current caches from
old creation payloads. Research text is kept as a local draft, cleared by explicit
logout/account deletion; this is not metadata-only or encrypted browser storage.
See research-creation-handoff.md for exact limits and remaining checks.

The initial PostgreSQL suite had 7 failures/1 pass, then all eight passed in
10.49 seconds. Full backend **191 cases passed in 465.90 seconds**. Three browser
lost-response cases first created duplicate objects, then passed after the fix.
The expanded run had 10/11 passes; an early cache-test assertion now waits for the
second response/navigation before checking the preserved v2 cache. Full **76-case
browser regression passed in 368.47 seconds**, no skips/flaky/unexpected outcomes,
runner exit 0. Source/report hashes are in artifacts/research-creation-milestone.json.
Dedicated long-lived creation-lock competition, late logout/close outcomes,
corrupt-record/time-window and visual checks remain open. Goal confirmed **paused
at 14:52:54 Hong Kong**, 16 seconds after the requested 14:52:38 deadline. No new
development/tests ran during that delay; only requested handoff metadata was
updated after pausing. Code commit ecb1afe; no release completion.

Export recovery (2026-10-16) first reproduced a second real archive after a lost
creation response: the old UI changed both key and job ID after the first job had
finished. The new control durably retains the original options/key/job, serializes
same-origin tabs, separates acknowledgement from independent status reads, and
requires explicit new intent. Native downloads precheck the owned job and retain
API-error feedback in the current page. See export-state-acceptance.md.

A separate PostgreSQL case reproduced rejection of a records-only export whose
evidence source was unavailable. Full-file exports still fail; explicitly selected
records-only archives now retain immutable evidence/file identity and missing
source metadata without claiming PDF inclusion. Ten relevant backend cases passed
in 19.43 seconds. The earlier 182-case full pass (431.56 seconds) predates that
Worker correction and is retained separately. The final backend regression passed
**183 cases in 485.21 seconds**, exit 0. All **17 targeted browser cases passed in
83.18 seconds**, including actual native ZIP/PDF hash verification and the
records-only archive. The first full browser run had 63/64 passes: an old PDF
workflow still located the former direct download link. Its locator now follows
the prechecked button and keeps the actual ZIP-save assertion. A separate case
reproduced cached-job use with semantically inconsistent restored options. After
space/job/options guards, it and the full PDF workflow passed in **19.17 seconds**.
Their retained negatives are documented in export-state-acceptance.md. The final
types/build/restart passed, followed by **all 65 browser cases in 324.74 seconds**,
with no skipped, flaky or unexpected results, no runner global errors and exit 0.
This includes 18 new export cases and the original PDF-to-ZIP workflow. Desktop
and 390px screenshots were inspected with no page overflow in the tested fixture.
Source/report hashes, XML/JSON/HTML, actual native ZIP samples and project-local
browser/loopback observations are bound in artifacts/export-state-milestone.json.
25 tool cases, three formula cases, lint, format, contracts, migration/journal,
broker metadata and pin checks passed. Goal active; broader release gates remain.

On 2026-10-16 the user resumed the full goal. Upload recovery now persists a
metadata-only intent across initialization/content/completion, retains original
keys and file/target IDs, requires the original SHA-256/size on reselection and
serializes same-space tabs using Web Locks. Confirmed receipts survive later read
or local-save failures. Explicit duplicate reuse preserves the selected file
version; expiry and manual record clearing do not silently allocate another job.
See upload-recovery-acceptance.md for lifetime, clock and browser limits.

Five new PostgreSQL/storage fault cases first reproduced three failures, then
passed in **9.25 seconds** after the completion service fix. Full backend regression
passed **177 cases in 409.52 seconds**. Types/production build, contracts (74 paths /
143 schemas), Alembic drift/journal head, pins, broker metadata, lint, **25 tool
cases** and **three formula cases** also passed. Initial browser entry-path and
multipart-proxy failures are retained; after harness correction **12 upload cases
passed in 46.2 seconds**. With logout late-response and desktop/390px checks,
an intermediate 47-case run passed in 235.44 seconds. Following visual readability
and alignment corrections, types/build/restart passed again and **all 47 browser
cases passed in 233.23 seconds**, with no skipped, flaky or unexpected outcomes,
no runner global errors and exit code 0. Desktop/390px screenshots were inspected;
the changed control has no page horizontal overflow in this fixture. Source hashes,
final XML/JSON/HTML, profile/loopback observations and retained negative evidence
are bound in artifacts/upload-recovery-milestone.json. The goal remains active;
full release gates below remain open.

Before the requested 2026-10-15 pause, parse-retry state recovery passed the
related **two backend cases (5.15 seconds)** and **all 34 browser cases (190.65
seconds)** after types/build/restart. The new browser case uses a precisely scoped
synthetic failed-file status, then real HTTP/broker/parser work; lost responses
reuse job IDs and two explicit intents add exactly two jobs. No backend application,
schema or migration changed, so the preceding 172-case backend pass was not
rerun or presented as a fresh full regression. At that pause upload multi-stage
recovery remained open; the 2026-10-16 evidence above supersedes that historical
status. The pause handoff remains in 进度.md.

Evidence state acceptance (2026-10-15) passed **172 backend cases in 441.80
seconds**, including four new real storage/parser replay/rollback/concurrency
cases. One original PDF browser flow passed, followed by initial failures retained
in artifacts/evidence-state-initial and evidence-state-current-file-failure.
After current-file publication refresh was fixed, an intermediate **33 browser
cases** passed. With the final cancellation guards and rapid page/zoom checks,
types/build/service restart passed again, followed by **all 33 browser cases in
177.64 seconds**, no skips/flaky outcomes/global errors and runner exit 0. The backend
source was unchanged after its full pass and was not repeated for frontend fixes.
25 dependency-tool cases, three formula
cases, contracts, migration/journal, broker/pin and lint checks passed. Direct
Playwright runs now keep browser profiles under the project root; a live process
path was observed and the known prior system-TEMP profile was already absent.
Desktop/390px screenshots were inspected. Final source hashes, XML/JSON/HTML,
profile observation and retained negative evidence are referenced by
artifacts/evidence-state-milestone.json. This is not whole-product release completion.

Decision state acceptance (2026-10-15) has passed **168 backend cases in 466.30
seconds**, including four new PostgreSQL replay/concurrency/rollback cases. Its
eight targeted browser cases passed in 32.1 seconds. The first full browser run
had 24/25 passes: a renamed pagination button broke an existing workflow locator.
The original application button labels were restored without weakening that test;
types/build/service restart then passed again, followed by **all 25 browser cases
in 121.99 seconds**, with no skips or flaky outcomes. The backend source did not
change after its full regression, so that suite was not redundantly rerun. Contracts, lint,
25 dependency-tool cases, three formula cases, migration/journal and broker/pin
checks passed. Desktop/390px conflict screenshots were checked. Source hashes,
XML/JSON/HTML reports, the targeted success and first full-run failure are bound in
artifacts/decision-state-milestone.json. Details: decision-state-acceptance.md.
This is a verified product milestone, not release completion.

Task state acceptance (2026-10-15) passed **164 backend cases in 408.72 seconds**,
**25 dependency-tool cases** and the three formula-security checks. Contracts,
business Alembic drift, journal head/inventory, dependency pins and broker metadata
also passed. The unified attempt then had 16/17 browser passes due to an existing
test's overly broad text locator. After correcting both occurrences and adding
cache-version protection, frontend types/build/service restart passed again, and
the final full browser run passed **all 17 cases (about 1.6 minutes)**. The backend
did not change after its full regression, so it was not redundantly rerun.

Eight task browser cases include real committed writes with dropped responses,
same-key replay across dialog reopen, intent/version retention, explicit conflict
comparison, original decision-revision replay, an elapsed replay-window guard,
and preservation of a newer cached task while its detail read is held pending.
Desktop/390px screenshots include a long continuous title with no horizontal
overflow. Original selector failures/traces are retained. Final reports and source
hashes are bound in artifacts/task-state-milestone.json. Details and explicit limits:
[task-state-acceptance.md](task-state-acceptance.md). This does not close whole-product
UI/security/accessibility, production capacity or release gates.

The current 104 application/development versions now have exact approved binary
wheel hashes; bootstrap and all 29 audit-tool packages are pinned likewise.
134 lock entries map to 124 distinct verified wheel files (91,421,391 bytes).
An entirely new project-local Python environment installed them successfully and
passed the full **158 backend cases in 427.61 seconds**, including actual PDF
parsing and the latest isolated expiry test. **25 dependency-tool cases** pass;
actual pip rejected a modified wheel. Complete runtime/tooling audits cover 105/29
packages with no skips/findings, using a bounded credential-free child environment.
Source/manifest, installation, audit reporting and weekly CI definitions are in
python-dependency-delivery.md. Hosted execution and full clean-machine/platform
validation remain unverified. That dependency-delivery milestone made no frontend/
application-domain change; its earlier browser/build evidence is historical. The
task milestone above is the latest application verification.

The earlier broker/process composition first passed 15 cases in 59.38 seconds. Its
unified application regression passed **158 backend cases in 404.03 seconds** and
**nine browser cases (about one minute)**, plus the three formula checks, types,
build, contracts, both migration gates and broker metadata check. A prior run's
155 passes/two metadata-prefix failures are retained separately. Subsequent
test-harness isolation and post-pip-bootstrap CLI checks passed **three targeted
cases in 16.67 seconds**. Final lint, setup/verify PowerShell parsing, all 105
declared dependency pins and the old-pip drift rejection also passed.

PyPI auditing covered all 104 application/development lock entries, then the
complete 105-package runtime. The latter exposed six distinct pip 24.2 advisory
IDs (12 duplicate service records), fixed by hash-pinned pip 26.2.1. Re-audits of
all 105 runtime packages and the isolated audit environment report no known
advisories with no skipped packages. Application pins did not change. Detailed
scope, failed input/negative evidence and remaining supply-chain/platform gates
are in dependency-security.md; this is not a whole-system security certification.

The process-supervision change passed 12 targeted real-process cases in 28.83
seconds, including an isolated encrypted backup retry/restore and actual PDF task
owner termination/lease recovery. A separate eight-way, 24-child output-isolation
probe passed in 0.375 seconds; this is not a business capacity benchmark.

Before this broker/bootstrap change, the 2026-10-15 unified regression passed **152 API/PostgreSQL tests in
350.93 seconds** after process supervision and real crash/retry cases were added.
The restarted service code passed **nine browser cases (about 1.1 minutes)**,
including preservation of a pending deletion receipt. Three formula renderer
checks, frontend types/production build, lint, business Alembic drift, journal
head/inventory and deterministic contracts also passed. Contracts remain 74 paths /
143 schemas; business head is 0009, independent journal head l0004.

The final journal cases cover omitted/altered entries and tails, signed older
heads, append-only permissions, concurrent/deduplicated appends, frozen replay,
injected read/write failures, diagnostic mirror failure, empty-source operator
bootstrap, legacy snapshot floors, replacement source continuity and failure of
the final CONNECT grant. Main services were confirmed to listen only on loopback;
formal backup key initialization/scheduling remains disabled. Reports, screenshots,
traces and synthetic fixtures remain under artifacts/, including
deletion-journal-proof.json, process-containment-final.xml and
process-supervision-proof.json. This does not certify production failure domains,
owner-rollback witnesses or full platform/security acceptance.

## Outstanding release gates

- Complete page/status/error acceptance and continued contract compatibility;
  production-scale paging capacity and concurrent mutation behavior beyond the
  documented keyset semantics are not certified.
- Extended PDF samples, compatibility/accessibility and full endpoint security.
- Production-scale archive/database reconstruction and encrypted DB/object backup
  drills; live backup activation/key escrow/retention approval, unknown-namespace/operator temporary data,
  provider multipart remnants, large-tenant capacity and crash/lease/redelivery/
  large-export coverage. Domain orphan/temp reconciliation is implemented;
  production scale and additional providers are not certified.
- Load, interpreter/service-binary and supply-chain audits, scheduled dependency
  advisory refresh, production manifests/runbooks, clean-host/hosted CI and
  SMTP/provider validation, then the final F01-F15/AC01-AC15 release audit.

Small-fixture reconstruction and encrypted PostgreSQL/object backup restore now
pass in fresh isolated databases/buckets, including a deletion after the backup,
original API reads, session revocation and password recovery. See the local development journal (not distributed) and
`artifacts/backup-recovery-proof.json`. This does not certify production scale,
key escrow, production retention/scheduling or a security review of the backup container.
Migration ownership is now a non-superuser role distinct from cluster bootstrap.
Backup/cleanup contention is verified with actual concurrent workers/locks.
Recovery operations and failure behavior are documented in recovery-runbook.md.
Current-authority chain/head/inventory checks and the legacy cutover floor are
implemented and tested locally. An independently escrowed fresh witness against
authority-owner/full-service rollback, off-host operation, old-writer fencing and
production administrative isolation remain gates. A coherent authority rollback
newer than a backup's minimum cannot be ruled out by a local chain alone.

Backup retention is not configured by default; online deletion is reported
separately and backup erasure is not claimed. No real-user trial or external
production deployment has occurred. Enterprise release acceptance remains incomplete.


## Hosted CI verification — 2026-10-21

The [complete Windows hosted run](https://github.com/Fancy8/ResearchOS/actions/runs/39583284264) passed at `de5ee22d2b6105496aad1e213cf08e7e4ec81a8f` after setup, service startup, browser installation, and verification were kept in the same PowerShell process. The original later-step broker metadata check had returned `BROKER_STATUS_UNAVAILABLE`; after the change both the immediate setup probe and the verification probe succeeded.

Verified: 25 dependency-tool tests, 191 backend tests (one warning), 3 math-security tests, 76 browser tests, 105 approved runtime/bootstrap packages, 74 API paths and 143 schemas, migration drift/head checks, frontend typecheck and production build. The backend run took 235.34 seconds and the browser run 5.1 minutes. This establishes this hosted Windows run, not all production/platform or remaining enterprise release gates. See `docs/ci-verification.md` from the repository root.
