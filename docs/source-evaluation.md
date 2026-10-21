# Open-source evaluation

Evaluation date: 2026-10-13. Source code and licenses were inspected locally.

Open Notebook is the closest product reference: sources, notebooks, notes,
Next.js and FastAPI. It uses SurrealDB and emphasizes AI interaction, rather
than ResearchOS's PostgreSQL constraints, individual workspaces, evidence and
immutable decision histories. Reusing its entire backend would retain a
different product and security model. We therefore reuse portable UI components
and query-client patterns while implementing our own domain services.

The official FastAPI template provides useful environment validation, migration
and testing patterns. Its current snapshot uses SQLModel, a React/Vite UI and JWT,
and requires a newer Python version than this machine. We adapt the configuration
pattern to Python 3.12, SQLAlchemy 2.0, Next.js and revocable opaque sessions.

Both inspected snapshots carry MIT licenses; exact commits, copied files and
retained notices are listed in ../THIRD_PARTY_NOTICES.md. Downloading these
repositories does not make their AGENTS or historical chat files our instructions.

Portable PostgreSQL 16.14 binaries were downloaded from EDB into runtime/;
runtime/postgresql-provenance.json records the URL, version and archive SHA-256.
This hash records the obtained artifact and is not a substitute for independent
vendor signature verification. These local development binaries are not a
production deployment or redistributed release.
