# Third-party source provenance

All downloaded snapshots are kept in vendor/ for inspection; they are not
executed as the ResearchOS application. License texts are retained in licenses/.

| Upstream | Snapshot commit | License | Reuse |
| --- | --- | --- | --- |
| [FastAPI full-stack template](https://github.com/fastapi/full-stack-fastapi-template) | 7257e606cb94eada1dca40173e2b7f99dd549bc6 | MIT, copyright Sebastian Ramirez | backend configuration adapted; Alembic/pytest structure reviewed. SQLModel/React-Vite/JWT business stack replaced by the approved SQLAlchemy/Next.js/opaque-session design. |
| [Open Notebook](https://github.com/lfnovo/open-notebook) | a0f6f3081ae06328f0a451b3a3ef2959ca25721d | MIT, copyright Luis Novo | frontend/src/lib/utils.ts and frontend/src/components/ui/button.tsx copied with license retained; query client adapted to workspace-scoped caching and no implicit mutation retries. |

ResearchOS domain models, transactions, research-thread/decision histories and
object authorization are new application code based on the local design.
Open Notebook's SurrealDB, optional shared password, AI providers and podcasts
are not carried into the P0 product. No user research files are sent upstream.

Package dependency licenses remain their respective owners' terms. Frozen
package lockfiles and a release dependency inventory are maintained separately.

PDF.js 6.4.299 (Apache-2.0) contributes the distributed browser worker and the
scoped TextLayer stylesheet in frontend/src/components/pdf-text-layer.css.
The original license is retained as licenses/pdfjs-Apache-2.0.txt.

Mathematical note nodes use Tiptap mathematics 3.31.4 and KaTeX 0.18.10
(MIT package licenses retained in installed packages/lockfile). Rendering uses
`trust: false` and bounded macro expansion; JSON snapshots retain the LaTeX.
Implementation references: [Tiptap mathematics](https://tiptap.dev/docs/editor/extensions/nodes/mathematics)
and [KaTeX options](https://katex.org/docs/options).

Cryptography 50.0.2 supplies Fernet for small queued authentication envelopes.
Reference: [official Fernet documentation](https://cryptography.io/en/latest/fernet/).

Python installer bootstrap uses [pip 26.2.1](https://pypi.org/project/pip/26.2.1/)
(MIT), with the official universal wheel SHA-256 pinned in
backend/bootstrap-requirements.lock.txt. Isolated package advisory scans use
[pip-audit 2.10.1](https://pypi.org/project/pip-audit/2.10.1/) (Apache-2.0).
Their installed distributions retain upstream licenses; audit tool/runtime and
downloaded-wheel provenance remain under runtime/ and artifacts/.

Current Windows/CPython 3.12 application and audit wheels are individually pinned
in the three requirements locks and backend/dependency-artifacts.json, including
official release/download URLs and SHA-256 values. Downloaded distributions and
installed environments retain upstream license files. This artifact inventory
is not a complete license-compliance assessment.
