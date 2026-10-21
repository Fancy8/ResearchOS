# ResearchOS: a guided tour

[English homepage](../README.md) · [中文首页](../README_ZH.md) · [Documentation map](README.md)

ResearchOS is an early-alpha research workspace for individuals who need to preserve the connection between a question, its evidence, a decision, and the work that follows. Its engineering focus is continuity: source files can change, interpretations evolve, and network requests fail, while earlier reasoning still needs to remain understandable.

## Choose a research scenario

| Scenario | A useful starting point | What you should be able to revisit |
| --- | --- | --- |
| Literature review | Create a thread for a focused question; attach papers and capture evidence | The source version and passage behind each interpretation |
| Method comparison | Connect supporting and opposing evidence to hypotheses | Why a candidate method was supported or challenged |
| Experiment planning | Record a decision and create a task from its exact revision | The reasoning available when the task was planned |
| Research review | Revisit revisions, linked notes, and activity; export an archive | How the question, evidence, and planned action developed |

These are uses of the current recordkeeping workflow. Scientific validity, experiment execution, and the assessment of evidence remain the researcher's responsibility.

## Follow one piece of evidence

Consider a synthetic PDF describing two training configurations. You capture a passage on page 3 and attach your interpretation to a research thread.

1. **Source identity:** the evidence refers to a particular paper-file version, with a page and anchor. A later file upload does not silently redirect that reference to the replacement PDF.
2. **Reasoning:** a hypothesis relates evidence to a statement you want to investigate. Supporting and opposing relationships make disagreement part of the research record.
3. **Decision context:** when recording a decision, its revision retains snapshots of the evidence, hypotheses, or notes used as context. Later edits do not rewrite what that earlier revision contained.
4. **Action provenance:** a task can point to the exact decision revision that motivated it. Reviewing the task can therefore recover its original rationale.
5. **Portable review:** exports carry manifests and checksums so archive contents can be inspected. An export is a research artifact; operational backup and recovery have separate procedures.

The useful distinction is between a source, your current interpretation, and a historical decision. ResearchOS gives these separate identities and update rules rather than flattening them into one editable note.

## Engineering choices behind the workflow

| Concern | Implemented approach | Where to inspect it |
| --- | --- | --- |
| Cross-workspace references | Server-side ownership checks and scoped relational constraints | [Data model](03-data-and-orm.md), [association/search tests](../backend/tests/test_associations_search.py) |
| Decision history | Revision-level context snapshots and task references | [Decision acceptance](decision-state-acceptance.md), [decision replay tests](../backend/tests/test_decision_replay.py) |
| Unknown creation outcomes | Original request intent plus transactionally stored idempotency receipts | [Creation recovery](research-creation-handoff.md), [backend replay tests](../backend/tests/test_research_creation_replay.py), [browser cases](../frontend/e2e/research-creation.spec.ts) |
| Background dispatch | PostgreSQL outbox, queue delivery, and worker recovery mechanisms | [Architecture](02-architecture.md), [broker recovery tests](../backend/tests/test_broker_recovery.py) |
| Source and export continuity | Versioned files and recovery protocols for interrupted operations | [Upload tests](../backend/tests/test_upload_recovery.py), [export recovery tests](../backend/tests/test_export_recovery.py) |
| Verifiable maintenance | Contracts, Alembic drift checks, real PostgreSQL tests, and browser verification | [Workflow](../.github/workflows/verify.yml), [recorded hosted run](ci-verification.md) |

This is enterprise-oriented engineering applied to an individual research product. Organizational tenancy, SSO, compliance certification, production SLAs, and a supported production deployment are not provided by the current alpha.

### What happens when a creation response is lost?

A request may commit successfully even when the browser does not receive its response. Retrying with a new identity could create a duplicate project, thread, or note.

The implemented browser flow preserves the original submission intent and key before sending. For supported creation endpoints, a retry with that same key and matching request retrieves the transactional receipt. The receipt confirms the resource identity; it does not replace newer detail data with an old creation response. API clients must supply the optional `Idempotency-Key` to use this behavior. Requests without it retain ordinary creation semantics.

Browser recovery drafts contain plaintext inputs. The dedicated multi-tab, late-response, and corrupt-record acceptance scope remains open; see the [handoff](research-creation-handoff.md) for precise evidence and remaining work.

## Explore the repository

| Path | What to look for |
| --- | --- |
| `frontend/src/` | Research workspace UI, API integration, private caching, and recovery flows |
| `frontend/e2e/` | Browser workflows and fault scenarios |
| `backend/` | API, domain persistence, background work, migrations, and tests |
| `contracts/` | Published API contract artifacts |
| `tools/` | Local setup, service supervision, verification, and maintenance commands |
| `docs/` | Product decisions, architecture, acceptance evidence, and operational runbooks |
| `licenses/` | Retained third-party license texts |

Start with [installation](getting-started.md), then the [synthetic walkthrough](research-walkthrough.md). Detailed engineering documents are currently mainly in Chinese. The English homepage and this tour provide an English entry point.

## Help shape the alpha

Useful contributions come from trying a specific path and reporting what happened:

- **Researchers:** try one question using a PDF you own; explain where evidence capture or decision review breaks your flow.
- **Developers:** reproduce setup, inspect one recovery path, or contribute a focused regression case.
- **Documentation contributors:** improve English guides, clarify prerequisites, or fix a reproducible installation gap.
- **Accessibility and PDF contributors:** report keyboard-navigation barriers or layout-specific anchor failures using synthetic material.

For a useful report, include your environment, exact steps, expected and observed behavior, and a minimal synthetic example. Keep credentials and private research material out of public reports. Use [Issues](https://github.com/Fancy8/ResearchOS/issues) for reproducible problems, [Discussions](https://github.com/Fancy8/ResearchOS/discussions) for workflow ideas, and the [contribution guide](../CONTRIBUTING.md) for changes. Disclose vulnerabilities through the [security policy](../SECURITY.md).
