# Contributing

Open a focused issue describing the problem, reproduction, expected behavior, and environment. Use synthetic research data and remove credentials, cookies, invitation tokens, emails, and private PDFs from examples.

Before changing domain behavior, read AGENTS.md and the product, data, and API baselines. Preserve private-object authorization, immutable evidence/decision histories, and PostgreSQL constraints. Use Alembic for schema changes. Keep runtime, downloaded dependencies, and test reports out of Git.

Keep pull requests focused. Explain the user-visible change, validation actually run, and remaining limitations. Runtime and contract changes require relevant real PostgreSQL and browser/fault-case validation; documentation-only changes need link/content checks. See tools/verify.ps1 and the existing GitHub Actions workflows. Do not claim passing tests without a matching run.

AI-assisted contributions are welcome under the same review requirements. Maintainers review changes and decide releases. Contributions are offered under the repository MIT license, with existing third-party notices preserved.
