import hashlib
import json

import dependencies as subject
import pytest


@pytest.mark.parametrize(
    "text",
    [
        "sample>=1",
        "sample==1.*",
        "sample==1\nsample==1",
        "sample @ https://example.org/x.whl",
        "sample==1 --hash=sha256:bad",
        "sample==1; python_version>'3'",
        "-r another.txt",
    ],
)
def test_lock_rejects_ambiguous_unhashed_or_redirected_inputs(tmp_path, text):
    path = tmp_path / "bad.lock"
    path.write_text(text)
    with pytest.raises(ValueError):
        subject.read_lock(path)


@pytest.fixture
def audit_input(tmp_path):
    path = tmp_path / "inventory.txt"
    path.write_text("sample==1.0\n")
    return path


@pytest.mark.parametrize(
    "change",
    [
        "partial",
        "wrong_version",
        "skipped",
        "service_failure",
        "finding",
        "missing_vulns",
        "duplicate",
        "error_object",
    ],
)
def test_advisory_report_never_passes_incomplete_or_failed_scan(
    tmp_path, audit_input, change
):
    entry = {"name": "sample", "version": "1.0", "vulns": []}
    document, tool_exit = {"dependencies": [entry]}, 0
    if change == "partial":
        document["dependencies"] = []
    elif change == "wrong_version":
        entry["version"] = "2.0"
    elif change == "skipped":
        entry["skip_reason"] = "not on service"
    elif change == "service_failure":
        tool_exit = 2
    elif change == "finding":
        entry["vulns"] = [{"id": "same"}, {"id": "same"}]
    elif change == "missing_vulns":
        entry.pop("vulns")
    elif change == "duplicate":
        document["dependencies"].append(dict(entry))
    else:
        document["errors"] = ["upstream failed"]
    path = tmp_path / "report.json"
    path.write_text(json.dumps(document))
    try:
        result = subject.audit_summary(audit_input, path, tool_exit)
    except (ValueError, TypeError):
        return
    assert not result["passed"]
    if change == "finding":
        assert result["advisory_records"] == 2 and result["distinct_advisory_ids"] == 1


def test_complete_advisory_coverage_passes_and_does_not_mutate_raw_report(
    tmp_path, audit_input
):
    path = tmp_path / "report.json"
    original = json.dumps(
        {"dependencies": [{"name": "sample", "version": "1.0", "vulns": []}]}
    )
    path.write_text(original)
    assert subject.audit_summary(audit_input, path, 0)["passed"]
    assert path.read_text() == original


def test_corrupted_cached_wheel_fails_without_network_or_overwrite(
    tmp_path, monkeypatch
):
    digest = hashlib.sha256(b"approved").hexdigest()
    path = tmp_path / "sample-1.0-py3-none-any.whl"
    path.write_bytes(b"tampered")
    monkeypatch.setattr(subject, "WHEELS", tmp_path)
    monkeypatch.setattr(
        subject,
        "approved",
        lambda group: [{"filename": path.name, "sha256": digest, "size_bytes": 8}],
    )
    monkeypatch.setattr(
        subject,
        "open_public",
        lambda *args: pytest.fail(
            "Corrupt cache must not trigger a silent replacement"
        ),
    )
    with pytest.raises(ValueError, match="CACHED_WHEEL_CHANGED"):
        subject.download("application")
    assert path.read_bytes() == b"tampered"


def test_failed_download_cannot_publish_partial_or_bad_bytes(tmp_path, monkeypatch):
    import io

    item = {
        "filename": "sample-1.0-py3-none-any.whl",
        "sha256": hashlib.sha256(b"approved").hexdigest(),
        "size_bytes": 8,
        "url": "https://files.pythonhosted.org/sample.whl",
    }
    monkeypatch.setattr(subject, "WHEELS", tmp_path)
    monkeypatch.setattr(subject, "approved", lambda group: [item])
    monkeypatch.setattr(subject, "open_public", lambda *args: io.BytesIO(b"modified"))
    with pytest.raises(ValueError, match="DOWNLOAD_HASH_MISMATCH"):
        subject.download("application")
    assert not list(tmp_path.iterdir())


@pytest.fixture
def approval(tmp_path, monkeypatch):
    lock = tmp_path / "sample.lock"
    digest = hashlib.sha256(b"approved").hexdigest()
    lock.write_text(f"sample==1.0 --hash=sha256:{digest}\n")
    item = {
        "name": "sample",
        "version": "1.0",
        "sha256": digest,
        "filename": "sample-1.0-py3-none-any.whl",
        "size_bytes": 8,
        "url": "https://files.pythonhosted.org/sample.whl",
        "metadata_url": "https://pypi.org/pypi/sample/1.0/json",
    }
    document = {
        "format_version": 1,
        "target": "cpython-3.12-win_amd64",
        "locks": {
            "application": {
                "path": lock.relative_to(subject.ROOT).as_posix(),
                "sha256": subject.file_hash(lock),
                "artifacts": [item],
            }
        },
    }
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(subject, "LOCKS", {"application": lock})
    monkeypatch.setattr(subject, "MANIFEST", manifest)
    monkeypatch.setattr(subject, "platform_check", lambda: None)
    return lock, manifest, document, item


@pytest.mark.parametrize(
    "change",
    [
        "lock_bytes",
        "artifact_hash",
        "source_host",
        "wheel_identity",
        "missing_artifact",
    ],
)
def test_approval_rejects_changed_lock_provenance_or_artifact(approval, change):
    lock, manifest, document, item = approval
    if change == "lock_bytes":
        lock.write_text(lock.read_text() + "# changed\n")
    elif change == "artifact_hash":
        item["sha256"] = "0" * 64
    elif change == "source_host":
        item["url"] = "https://localhost/secret.whl"
    elif change == "wheel_identity":
        item["filename"] = "other-1.0-py3-none-any.whl"
    else:
        document["locks"]["application"]["artifacts"] = []
    manifest.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        subject.approved("application")


@pytest.mark.parametrize("duplicate", [False, True])
def test_runtime_inventory_rejects_undeclared_or_duplicate_packages(
    monkeypatch, duplicate
):
    from types import SimpleNamespace

    monkeypatch.setattr(subject, "approved", lambda group: [])
    monkeypatch.setattr(
        subject, "read_lock", lambda path: {"sample": {"version": "1.0"}}
    )
    monkeypatch.setattr(subject.metadata, "version", lambda name: "1.0")
    names = ["sample", "Sample" if duplicate else "unapproved-helper"]
    monkeypatch.setattr(
        subject.metadata,
        "distributions",
        lambda: [SimpleNamespace(metadata={"Name": name}) for name in names],
    )
    if duplicate:
        with pytest.raises(ValueError, match="DUPLICATE_INSTALLATION"):
            subject.versions(["application"])
    else:
        result = subject.versions(["application"])
        assert not result["matches"] and result["unexpected"] == ["unapproved-helper"]
