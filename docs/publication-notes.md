# Initial public source snapshot

This public repository starts with a source snapshot based on local development commit `6f80a53` (application changes through `ecb1afe`). Its initial public commit intentionally has no local development history.

Excluded: local runtime, credentials, databases, downloaded vendor snapshots, test artifacts, private original requirement/chat files under docs/sources/, local progress journals, and the local-only generated design page/builder. Original local files and history were preserved separately. Some design documents describe these historical inputs; they are not distributed with this snapshot.

Publication changes add the MIT license, contribution/security guidance, templates, and this README. Machine-specific checkout paths and npm cache configuration are normalized for public development. Domain code is unchanged. Third-party notices and license files are retained.

Pre-publication heuristic checks covered tracked files and historical blobs for common private-key/access-token formats and compared available local generated secrets without printing their values. This is not an exhaustive secret scan, license audit, security certification, or fresh-host validation. Historical test counts remain dated evidence.

Do not publish local artifacts or authentication/application-form details. Review hosted CI after the first push before treating it as validated.

## Documentation presentation update — 2026-10-21

The public homepage now has a Chinese main edition, an English entry, original SVG cover/workflow assets, and guides for installation, the research walkthrough, documentation navigation, and the roadmap. Its information organization takes inspiration from Datawhale Hello-Agents; no reference project artwork or tutorial prose is copied, and no affiliation is implied.

The upstream distributed PDF.js worker is marked `linguist-vendored` for GitHub language statistics, preserving its content and license. Application code, dependencies, migrations, and runtime behavior are unchanged by this presentation update.

At review time, the three initial hosted runs had failed at the complete verification step, including `b34545c`. The homepage links actual Actions results and distinguishes them from dated local tests. This update does not resolve or certify that CI failure.

## Hosted failure resolved — 2026-10-21

The initial broker failure described above is historical. The [complete repair run](https://github.com/Fancy8/ResearchOS/actions/runs/39583284264) at `de5ee22` succeeded; see [CI verification](ci-verification.md). Original application and test assertions were retained.
