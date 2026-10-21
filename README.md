# ResearchOS

A research workspace for individual graduate researchers: connect research questions, papers, evidence, hypotheses, decisions, and tasks in a traceable workflow.

**Status: early alpha.** This repository follows an enterprise-oriented engineering process, but production release gates remain open. No production deployment, external adoption, or independent security certification is claimed. AI features and team collaboration are outside the current P0 scope.

## Project purpose / 项目用途

ResearchOS helps an individual researcher keep the connection between **what they read, why they reached a conclusion, and what they plan to do next**. It is intended for literature reviews, tracking research questions, recording evidence-backed hypotheses, and turning decisions into tasks.

面向个人硕博生和研究者，把“研究问题 → 文献证据 → 假设 → 决策 → 任务”串起来。适合在阅读多篇论文后整理依据、回顾判断过程，以及安排下一步验证。论文文件版本和决策修订保留历史，便于回看当时的依据。当前以个人研究记录为核心；AI 自动分析和多人协作属于后续范围。

For a concrete walkthrough, see [the usage example](#usage-example--使用示例) below.

## What is implemented

- Private workspaces and object-level authorization with revocable sessions.
- PDF upload and parsing, immutable source versions, and evidence anchors.
- Research threads, hypotheses, immutable decision revisions, and research tasks.
- Notes with mathematical content, conflict handling, and recovery drafts.
- Transactional idempotency and recovery for interrupted uploads, creation, and exports.
- Export manifests and source checksums; deletion and isolated backup/restore experiments.

The stack uses FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL, Next.js/React, Redis/Celery, and private S3-compatible storage. PostgreSQL is required.

## Supported systems / 支持系统

| Environment | Current status |
| --- | --- |
| Windows x64 + PowerShell | Current local development/bootstrap target. The approved Python wheel lock requires **64-bit CPython 3.12**. Historical local validation is described below. |
| Linux / macOS | No supported bootstrap or platform validation yet. The existing launchers and service binaries target Windows; platform-specific provisioning is required. |
| Browser | Automated local browser coverage uses Playwright Chromium. Firefox, Safari, and mobile-device compatibility have not been established. |
| Production hosting | Not yet supported as a validated release. Production platform isolation, deployment, and operations gates remain open. |

## Installation / 安装方式

### Prerequisites

Install Git, **64-bit CPython 3.12**, **Node.js 26.1.0 with npm**, and PowerShell. Make `git`, `python`, `node`, and `npm` available in your terminal. Python 3.13 or another platform cannot use the current approved Windows CPython 3.12 wheel lock. Initial setup requires network access to download the pinned dependencies and local service binaries.

```powershell
git --version
python --version
node --version
npm --version
```

The existing bootstrap targets **Windows and PowerShell**, Python 3.12, and Node.js 26.1.0. Inspect `tools/setup.ps1`, dependency lockfiles, and `tools/services-lock.json` before running: setup downloads dependencies and local service binaries. A fresh-host setup and hosted CI have not yet been independently verified.

### Install and start

```powershell
git clone https://github.com/Fancy8/ResearchOS.git
cd ResearchOS
./tools/setup.ps1
# Generate a local invitation; this does not send email:
./runtime/venv/Scripts/python.exe ./tools/invite.py your-email@example.com
```

Open http://localhost:3000/login and http://127.0.0.1:58000/api/docs after startup. Services bind to loopback. Generated credentials, databases, logs, caches, and downloaded binaries belong under ignored `runtime/`. Test reports belong under ignored `artifacts/`.

Use your own email in the invitation command. On the login page, switch to registration and enter that same email, the generated invitation token, your display name, and a password of at least 12 characters. Follow onboarding, then sign in to your workspace. The invitation command prints a token locally; it does not send an email. Do not publish the token.

首次安装：检查依赖版本 → 克隆代码 → 运行 `setup.ps1` → 为自己的邮箱生成邀请码 → 打开登录页并切换注册 → 完成引导。脚本会准备本地 PostgreSQL、对象存储、队列、数据库迁移和应用。运行环境保存在项目目录，不需要另行安装全局数据库服务。

On subsequent starts, run these commands from the repository directory:

```powershell
./tools/start-services.ps1
./tools/start.ps1
```

### Verify the development environment

```powershell
./tools/verify.ps1
```

Verification uses dedicated real PostgreSQL databases and local object storage. Do not point it at production data. Read [local operations](docs/operating-local.md) before administration or recovery operations. The storage launcher contains fixed local-development credentials; replace these and review service isolation before any non-loopback deployment.

## Usage example / 使用示例

The following is a **fictional walkthrough**, not a published study or a preloaded dataset. Use a small, text-based PDF that you created or have permission to upload; scanned-PDF OCR is not provided.

示例目标：记录“学习率对模型收敛的影响”这一研究问题，从阅读依据安排下一步实验。

| Record | Example content |
| --- | --- |
| Project / 课题 | 学习率与收敛行为 |
| Research thread / 研究线索 | 更小的学习率是否能减少训练后期的震荡？ |
| Paper and evidence / 文献与证据 | 上传自己的示例 PDF，选择其中一段文字并保存为带来源定位的证据。 |
| Hypothesis / 待验证假设 | 较小学习率可能降低训练后期震荡，但可能增加收敛所需步数。 |
| Decision / 研究决策 | 依据当前证据，先安排对照实验，并记录假设与局限。 |
| Task / 科研任务 | 固定数据、模型和随机种子，比较两个学习率并记录损失曲线。 |

1. Create the project and a research thread with the question above.
2. Upload your sample PDF to the paper library, wait for parsing, and open the paper.
3. Save a passage as evidence with its source location, and associate it with the research thread.
4. Record the hypothesis and a decision with the relevant evidence. Treat the hypothesis as unverified.
5. Create a task from the decision. After doing the experiment, record the outcome and revise the decision as needed; earlier decision revisions retain their historical context.
6. Review the links between the question, evidence, decision, and task. Use the workspace export to inspect the archive and manifest when you need a portable record.

Expected result: you can trace a planned action back to the decision and the source evidence behind it. The steps illustrate record keeping; they do not establish the scientific hypothesis. Detailed product behavior and acceptance criteria are in [the product baseline](docs/01-product-baseline.md).

## Engineering evidence and remaining work

At source commit `ecb1afe`, local validation on 2026-10-16 recorded 191 backend tests and 76 browser tests passing. These are historical local results, not a claim about the current GitHub Actions run. Public CI results must be checked separately. The public snapshot is based on local commit `6f80a53`, with publication-only documentation, exclusions, and path normalization described in [publication notes](docs/publication-notes.md).

Remaining work includes full page/error/accessibility acceptance, broader PDF compatibility, multi-tab and late-response recovery cases, fresh-host/hosted CI, production platform isolation, supply-chain review, independent recovery witnesses, capacity tests, SMTP/provider verification, and production backup key escrow/retention. Browser recovery drafts contain plaintext research inputs. Windows Celery solo operation is a local development arrangement. Formal backup scheduling and production deployment are not enabled by this release.

## Documentation and contributions

Use [Issues](https://github.com/Fancy8/ResearchOS/issues) for reproducible bugs and concrete feature requests. Use [Discussions](https://github.com/Fancy8/ResearchOS/discussions) for setup questions, research-workflow ideas, and general feedback. Both channels are public; use synthetic examples and keep private research material out of posts. For vulnerabilities, follow [the security policy](SECURITY.md).

- [Product requirements and acceptance mapping](docs/01-product-baseline.md)
- [Architecture](docs/02-architecture.md), [data and ORM](docs/03-data-and-orm.md), [API contract](docs/04-api-contract.md)
- [Implementation status](docs/implementation-status.md) and [creation recovery handoff](docs/research-creation-handoff.md)
- [Contributing](CONTRIBUTING.md), [security reporting](SECURITY.md), [third-party notices](THIRD_PARTY_NOTICES.md)

Most detailed design documents are currently in Chinese. Contributions to reproducible setup, fault recovery, authorization testing, accessibility, and English documentation are welcome. Project development has used AI-assisted tools; maintainers remain responsible for review and release decisions.

## License

Original ResearchOS code is available under the [MIT License](LICENSE). Copied/adapted code and PDF.js retain their own notices and license terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and `licenses/`. No user research library, private design conversations, local credentials, or runtime binaries are included.
