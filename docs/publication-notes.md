# Initial public source snapshot

This public repository starts with a source snapshot based on local development commit `6f80a53` (application changes through `ecb1afe`). Its initial public commit intentionally has no local development history.

Excluded: local runtime, credentials, databases, downloaded vendor snapshots, test artifacts, private original requirement/chat files under docs/sources/, local progress journals, and the local-only generated design page/builder. Original local files and history were preserved separately. Some design documents describe these historical inputs; they are not distributed with this snapshot.

Publication changes add the MIT license, contribution/security guidance, templates, and this README. Machine-specific checkout paths and npm cache configuration are normalized for public development. Domain code is unchanged. Third-party notices and license files are retained.

Pre-publication heuristic checks covered tracked files and historical blobs for common private-key/access-token formats and compared available local generated secrets without printing their values. This is not an exhaustive secret scan, license audit, security certification, or fresh-host validation. Historical test counts remain dated evidence.

Do not publish local artifacts or authentication/application-form details. Review hosted CI after the first push before treating it as validated.
