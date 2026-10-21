"""Verify every exported original file and all domain relationship references.

This does not implement the future user-facing one-click import. It proves
that the P0 archive is structurally self-contained and reconstructible.
"""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

REFERENCES = {
    "workspace_id": "workspaces",
    "project_id": "projects",
    "thread_id": "research_threads",
    "paper_id": "papers",
    "paper_file_id": "paper_files",
    "evidence_id": "evidence",
    "hypothesis_id": "hypotheses",
    "decision_id": "research_decisions",
    "decision_revision_id": "decision_revisions",
    "note_id": "notes",
    "owner_user_id": "users",
    "created_by": "users",
    "actor_user_id": "users",
}


def verify(path):
    with ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == 1
        tables = {
            name: json.loads(archive.read(f"data/{name}.json"))
            for name in manifest["entities"]
        }
        for name, rows in tables.items():
            assert len(rows) == manifest["entities"][name], f"Count mismatch: {name}"
        indexes = {
            name: {row["id"] for row in rows if "id" in row}
            for name, rows in tables.items()
        }
        checks = 0
        for name, rows in tables.items():
            for row in rows:
                for column, target in REFERENCES.items():
                    if row.get(column) is not None:
                        assert row[column] in indexes[target], (
                            f"Broken relation: {name}.{column}"
                        )
                        checks += 1
        revisions = {
            (row["decision_id"], row["revision_no"])
            for row in tables["decision_revisions"]
        }
        for row in tables["research_decisions"]:
            assert (row["id"], row["current_revision"]) in revisions
        for row in tables["tasks"]:
            if row["decision_id"]:
                assert (row["decision_id"], row["source_revision_no"]) in revisions
        if manifest["include_files"]:
            uploaded = {
                row["id"]
                for row in tables["paper_files"]
                if row["upload_status"] == "uploaded"
            }
            assert uploaded == {item["paper_file_id"] for item in manifest["files"]} | {item["paper_file_id"] for item in manifest.get("missing_files", [])}
            for item in manifest["files"]:
                digest = hashlib.sha256()
                count = 0
                with archive.open(item["path"]) as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        count += len(chunk)
                assert (
                    count == item["size_bytes"] and digest.hexdigest() == item["sha256"]
                )
        for forbidden in (
            "data/auth_sessions.json",
            "data/auth_tokens.json",
            "data/api_idempotency_keys.json",
        ):
            assert forbidden not in archive.namelist()
        assert all("password_hash" not in row for row in tables["users"])
        return {
            "schema_version": 1,
            "entity_tables": len(tables),
            "relationship_checks": checks,
            "original_files_verified": len(manifest["files"]),
            "credentials_excluded": True,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.archive), ensure_ascii=False))
