# Dependency security evidence

Checked locally on 2026-10-14. This is a bounded advisory check, not a full security certification.

- The configured Tencent mirror returned HTTP 404 for the npm advisory endpoint;
  `artifacts/npm-audit.json` is a failed audit, not a clean result.
- Retrying the official npm registry returned one low-severity KaTeX advisory,
  [GHSA-238p-pmpm-9mq7](https://github.com/KaTeX/KaTeX/security/advisories/GHSA-238p-pmpm-9mq7).
  The upstream advisory describes trust restrictions being bypassed when prototypes
  have already been polluted or the options prototype is attacker-controlled;
  it identifies 0.18.2 as the patched version. This does not establish that a
  prototype-pollution entry point exists in ResearchOS.
- Pinned KaTeX changed from 0.18.0 to 0.18.10, using the official registry and
  disabled package lifecycle scripts. Its commander dependency changed from
  8.3.0 to 15.0.0, requiring Node >=22.12.0. Local Node and CI configuration both
  use 26.1.0. Package lock integrity values are retained.
- `artifacts/npm-audit-public.json` retains the finding. The post-update official
  response `artifacts/npm-audit-after.json` reports zero known advisories and
  199 dependencies in its total metadata, with exit code 0. This is time-bound
  advisory database evidence; Python dependencies and the remaining security
  gates still need separate audits.

The three Node regression cases exercise polluted Object.prototype trust,
inherited renderer options, and ordinary accessible mathematics. The corrected
tests were also run against a separately extracted 0.18.0 npm package whose
integrity matches the original lock: two security cases failed and the normal
formula passed. On 0.18.10 all three pass. No generated javascript link was
executed. The original first probe accidentally used a read-only prototype
property; retain that failed output separately and use the corrected baseline.

Reports: `artifacts/math-trust-before.tap` (initial probe),
`artifacts/math-trust-before-corrected.tap` (valid old-package baseline), and
`artifacts/math-trust-after.tap` (patched tests). Downloaded baseline material is
under `runtime/security-baseline/`. All files remain under the project root.

`tools/verify.ps1` now runs `npm --prefix frontend run test:math-security` before
the production build. Formula browser acceptance continues to run in the normal
Playwright suite. Network audit failures must remain failures; do not accept an
empty or error-only response as zero vulnerabilities.

## Python package and installer audit, 2026-10-15

An isolated `runtime/audit-venv` runs pip-audit 2.10.1 against the PyPI advisory
service. Tool packages, caches, downloaded material and reports stay in this
project. It audits pinned input without dependency installation/resolution
(`--no-deps --disable-pip`), not with automatic fixes. References:
[pip-audit documentation](https://github.com/pypa/pip-audit),
[PyPI pip metadata](https://pypi.org/pypi/pip/24.2/json).

The application/development lock has **104 packages**: all 104 were queried,
none skipped, zero reported advisories, and no lock/runtime version drift.
That result initially missed **pip 24.2**, because ordinary freeze omits the
installer. Auditing actual installed metadata found **105 packages** and
**12 advisory records in pip, representing six distinct IDs**. Duplicates are
retained in the raw response and counted separately from distinct findings:

| PyPI advisory ID | Alias | Reported fixed release |
| --- | --- | --- |
| PYSEC-2026-1795 | CVE-2025-8869 | 25.3 |
| PYSEC-2026-1796 | CVE-2026-1703 | 26.0 |
| PYSEC-2026-2875 | CVE-2026-3219 | 26.1 |
| PYSEC-2026-2876 | CVE-2026-6357 | 26.1 |
| PYSEC-2026-196 | CVE-2026-8643 | 26.1.2 |
| PYSEC-2026-3721 | CVE-2026-13346 | 26.2 / 26.2.0 |

These are advisory-service results, not exploit reproduction or proof of an
exploitable ResearchOS endpoint. One attempted upstream GHSA URL returned 404;
the individual upstream advisory texts were not all independently verified.
Do not present the six service IDs as six independently reproduced defects.

The project installer is now **pip 26.2.1**, from its
[official PyPI release](https://pypi.org/project/pip/26.2.1/). The universal wheel
was downloaded from files.pythonhosted.org and matched the release metadata's
SHA-256 `71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e`.
`backend/bootstrap-requirements.lock.txt` pins this hash. Setup installs the
bootstrap with binary-only/hash enforcement before the application lock; the
project and isolated audit environments were upgraded from this verified wheel.
Both `pip check` runs passed. All 104 application/development versions stayed
unchanged; the shared system Python installation was not changed.

`tools/check_python_dependencies.py` checks both declared locks (105 pins),
including pip, during setup and verification. The live 105-pin check passes;
read-only metadata fault injection of the former pip version is rejected with
exit 1 and exactly that mismatch. Setup and verification PowerShell syntax
also passes. A full clean-host setup has not been executed by this audit.

Post-update PyPI scans cover **all 105 runtime packages and all 29 audit-tool
packages**, each with zero reported advisories, zero skipped packages and exit
0. A first runtime-inventory attempt failed on the lock's UTF-8 BOM and then
reached invalid audit input; its failure status is retained. The corrected
inventory reads UTF-8 with BOM handling and guards its exit before auditing.

Reports under artifacts/:

- `python-audit-initial.json`, `python-audit-coverage.json`: complete lock scan,
  lock digest and the omitted installer discovered in the actual environment.
- `python-audit-runtime.json`: raw 105-package negative baseline, including duplicates.
- `python-audit-runtime-input-failed-status.json`: failed input attempt, not a clean scan.
- `python-audit-runtime-after.json`, `python-audit-tooling-after.json` and their
  status files: complete post-fix scans; exact environment inputs are retained.
- `pip-bootstrap-source.json`, `pip-bootstrap-installed.json`,
  `python-bootstrap-drift-rejection.json`: wheel integrity, unchanged app pins
  and installer regression protection. Audit-tool pins are recorded in
  runtime/audit-requirements.lock.txt.

This completes a time-bound Python package advisory pass. It does not certify
interpreter/OS/service binaries, absence of unreported defects, source licenses,
malicious package behavior, runtime sandboxing or complete supply-chain security.
At that initial audit milestone the 104-package lock lacked distribution hashes.
The subsequent implementation in [python-dependency-delivery.md](python-dependency-delivery.md)
now pins exact wheels for application/bootstrap/audit tools, verifies delivery and
fresh installation, and supplies a complete-coverage audit entry point. A weekly
Python CI definition is provided; hosted execution/enforcement remains unverified.
Full endpoint/platform/interpreter review, npm refresh automation, repository trust
and production validation remain release gates.
