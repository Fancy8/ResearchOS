# ResearchOS

A research workspace for individual graduate researchers: connect research questions, papers, evidence, hypotheses, decisions, and tasks in a traceable workflow.

**Status: early alpha.** This repository follows an enterprise-oriented engineering process, but production release gates remain open. No production deployment, external adoption, or independent security certification is claimed. AI features and team collaboration are outside the current P0 scope.

## What is implemented

- Private workspaces and object-level authorization with revocable sessions.
- PDF upload and parsing, immutable source versions, and evidence anchors.
- Research threads, hypotheses, immutable decision revisions, and research tasks.
- Notes with mathematical content, conflict handling, and recovery drafts.
- Transactional idempotency and recovery for interrupted uploads, creation, and exports.
- Export manifests and source checksums; deletion and isolated backup/restore experiments.

The stack uses FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL, Next.js/React, Redis/Celery, and private S3-compatible storage. PostgreSQL is required.

## Development setup

The existing bootstrap targets **Windows and PowerShell**, Python 3.12, and Node.js 26.1.0. Inspect `tools/setup.ps1`, dependency lockfiles, and `tools/services-lock.json` before running: setup downloads dependencies and local service binaries. A fresh-host setup and hosted CI have not yet been independently verified.

```powershell
git clone https://github.com/Fancy8/ResearchOS.git
cd ResearchOS
./tools/setup.ps1
# On subsequent starts:
./tools/start-services.ps1
./tools/start.ps1
# Generate a local invitation; this does not send email:
./runtime/venv/Scripts/python.exe ./tools/invite.py your-email@example.com
```

Open http://localhost:3000/login and http://127.0.0.1:58000/api/docs after startup. Services bind to loopback. Generated credentials, databases, logs, caches, and downloaded binaries belong under ignored `runtime/`. Test reports belong under ignored `artifacts/`.

```powershell
./tools/verify.ps1
```

Verification uses dedicated real PostgreSQL databases and local object storage. Do not point it at production data. Read [local operations](docs/operating-local.md) before administration or recovery operations. The storage launcher contains fixed local-development credentials; replace these and review service isolation before any non-loopback deployment.

## Engineering evidence and remaining work

At source commit `ecb1afe`, local validation on 2026-10-16 recorded 191 backend tests and 76 browser tests passing. These are historical local results, not a claim about the current GitHub Actions run. Public CI results must be checked separately. The public snapshot is based on local commit `6f80a53`, with publication-only documentation, exclusions, and path normalization described in [publication notes](docs/publication-notes.md).

Remaining work includes full page/error/accessibility acceptance, broader PDF compatibility, multi-tab and late-response recovery cases, fresh-host/hosted CI, production platform isolation, supply-chain review, independent recovery witnesses, capacity tests, SMTP/provider verification, and production backup key escrow/retention. Browser recovery drafts contain plaintext research inputs. Windows Celery solo operation is a local development arrangement. Formal backup scheduling and production deployment are not enabled by this release.

## Documentation and contributions

- [Product requirements and acceptance mapping](docs/01-product-baseline.md)
- [Architecture](docs/02-architecture.md), [data and ORM](docs/03-data-and-orm.md), [API contract](docs/04-api-contract.md)
- [Implementation status](docs/implementation-status.md) and [creation recovery handoff](docs/research-creation-handoff.md)
- [Contributing](CONTRIBUTING.md), [security reporting](SECURITY.md), [third-party notices](THIRD_PARTY_NOTICES.md)

Most detailed design documents are currently in Chinese. Contributions to reproducible setup, fault recovery, authorization testing, accessibility, and English documentation are welcome. Project development has used AI-assisted tools; maintainers remain responsible for review and release decisions.

## License

Original ResearchOS code is available under the [MIT License](LICENSE). Copied/adapted code and PDF.js retain their own notices and license terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and `licenses/`. No user research library, private design conversations, local credentials, or runtime binaries are included.
