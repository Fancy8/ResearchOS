"""Pinned Windows wheel delivery and fail-closed advisory report verification."""

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata
from pathlib import Path
from uuid import uuid4

try:
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.tags import sys_tags
    from packaging.utils import canonicalize_name, parse_wheel_filename
    from packaging.version import Version
except ModuleNotFoundError as error:
    if error.name != "packaging":
        raise
    # Fresh environments have only the hash-pinned pip bootstrap at this stage.
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.specifiers import SpecifierSet
    from pip._vendor.packaging.tags import sys_tags
    from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename
    from pip._vendor.packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
LOCKS = {
    "application": ROOT / "backend/requirements.lock.txt",
    "bootstrap": ROOT / "backend/bootstrap-requirements.lock.txt",
    "audit": ROOT / "tools/audit-requirements.lock.txt",
}
MANIFEST = ROOT / "backend/dependency-artifacts.json"
WHEELS = ROOT / "runtime/wheels/cp312-win_amd64"


def local(path):
    path = Path(path).resolve()
    if path == ROOT or not path.is_relative_to(ROOT):
        raise ValueError("DEPENDENCY_PATH_OUTSIDE_PROJECT")
    return path


def platform_check():
    if (
        sys.platform != "win32"
        or sys.version_info[:2] != (3, 12)
        or struct.calcsize("P") != 8
    ):
        raise ValueError("DEPENDENCY_PLATFORM_NOT_VERIFIED")


def read_lock(path, *, require_hash=True):
    entries = {}
    for line in local(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.strip().split(" --hash=sha256:")
        requirement = Requirement(parts[0])
        pins = list(requirement.specifier)
        if (
            requirement.url
            or requirement.marker
            or requirement.extras
            or len(pins) != 1
            or pins[0].operator != "=="
            or "*" in pins[0].version
            or len(parts) > 2
        ):
            raise ValueError("DEPENDENCY_LOCK_NOT_EXACT")
        name = canonicalize_name(requirement.name)
        digest = parts[1] if len(parts) == 2 else None
        if name in entries or (
            digest is not None and not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise ValueError("DEPENDENCY_LOCK_INVALID")
        if require_hash and not digest:
            raise ValueError("DEPENDENCY_HASH_REQUIRED")
        entries[name] = {"name": name, "version": pins[0].version, "sha256": digest}
    if not entries:
        raise ValueError("DEPENDENCY_LOCK_EMPTY")
    return entries


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("DEPENDENCY_REDIRECT_NOT_ALLOWED")


def open_public(url, host):
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != host
        or parsed.username
        or parsed.password
    ):
        raise ValueError("DEPENDENCY_SOURCE_NOT_ALLOWED")
    return urllib.request.build_opener(NoRedirect()).open(url, timeout=30)


def select_wheel(document, entry):
    if (
        canonicalize_name(document["info"]["name"]) != entry["name"]
        or document["info"]["version"] != entry["version"]
    ):
        raise ValueError("DEPENDENCY_SOURCE_IDENTITY_MISMATCH")
    ranks = {tag: index for index, tag in enumerate(sys_tags())}
    candidates = []
    for item in document["urls"]:
        if item["packagetype"] != "bdist_wheel" or item.get("yanked"):
            continue
        name, version, _, tags = parse_wheel_filename(item["filename"])
        if name != entry["name"] or version != Version(entry["version"]):
            continue
        requires = item.get("requires_python")
        if requires and Version(
            ".".join(map(str, sys.version_info[:3]))
        ) not in SpecifierSet(requires):
            continue
        compatible = tags.intersection(ranks)
        if compatible:
            candidates.append(
                (min(ranks[tag] for tag in compatible), item["filename"], item)
            )
    if not candidates:
        raise ValueError("DEPENDENCY_COMPATIBLE_WHEEL_MISSING")
    item = min(candidates, key=lambda value: value[:2])[2]
    digest = item["digests"]["sha256"]
    if not re.fullmatch(r"[a-f0-9]{64}", digest) or (
        entry["sha256"] and entry["sha256"] != digest
    ):
        raise ValueError("DEPENDENCY_APPROVED_ARTIFACT_CHANGED")
    if Path(item["filename"]).name != item["filename"]:
        raise ValueError("DEPENDENCY_FILENAME_INVALID")
    return {
        "name": entry["name"],
        "version": entry["version"],
        "filename": item["filename"],
        "sha256": digest,
        "url": item["url"],
        "size_bytes": item["size"],
        "metadata_url": f"https://pypi.org/pypi/{entry['name']}/{entry['version']}/json",
    }


def refresh():
    platform_check()
    groups = {
        group: read_lock(path, require_hash=False) for group, path in LOCKS.items()
    }
    unique = {}
    for entries in groups.values():
        for name, entry in entries.items():
            key = (name, entry["version"])
            if (
                key in unique
                and unique[key]["sha256"]
                and entry["sha256"]
                and unique[key]["sha256"] != entry["sha256"]
            ):
                raise ValueError("DEPENDENCY_APPROVED_HASH_CONFLICT")
            if key not in unique or entry["sha256"]:
                unique[key] = entry

    def fetch(entry):
        url = f"https://pypi.org/pypi/{entry['name']}/{entry['version']}/json"
        with open_public(url, "pypi.org") as response:
            data = response.read(5_000_001)
        if len(data) > 5_000_000:
            raise ValueError("DEPENDENCY_METADATA_TOO_LARGE")
        return (entry["name"], entry["version"]), select_wheel(json.loads(data), entry)

    with ThreadPoolExecutor(max_workers=8) as pool:
        artifacts = dict(pool.map(fetch, unique.values()))
    manifest = {"format_version": 1, "target": "cpython-3.12-win_amd64", "locks": {}}
    # Fetch/validate every artifact before updating a tracked lock.
    documents = {}
    for group, entries in groups.items():
        selected = [
            artifacts[(name, entry["version"])]
            for name, entry in sorted(entries.items())
        ]
        text = "# CPython 3.12 / Windows x64; approved binary wheels only.\n"
        text += "".join(
            f"{item['name']}=={item['version']} --hash=sha256:{item['sha256']}\n"
            for item in selected
        )
        documents[group] = text
        manifest["locks"][group] = {
            "path": LOCKS[group].relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "artifacts": selected,
        }
    for group, text in documents.items():
        local(LOCKS[group]).write_text(text, encoding="utf-8", newline="\n")
    local(MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "locks": len(groups),
        "unique_artifacts": len(artifacts),
        "download_bytes": sum(item["size_bytes"] for item in artifacts.values()),
    }


def approved(group):
    platform_check()
    manifest = json.loads(local(MANIFEST).read_text(encoding="utf-8"))
    if (
        manifest["format_version"] != 1
        or manifest["target"] != "cpython-3.12-win_amd64"
    ):
        raise ValueError("DEPENDENCY_MANIFEST_INVALID")
    document = manifest["locks"][group]
    path = LOCKS[group]
    if (
        document["path"] != path.relative_to(ROOT).as_posix()
        or hashlib.sha256(path.read_bytes()).hexdigest() != document["sha256"]
    ):
        raise ValueError("DEPENDENCY_MANIFEST_LOCK_MISMATCH")
    entries = read_lock(path)
    artifacts = document["artifacts"]
    if len(artifacts) != len(entries) or len(
        {item["name"] for item in artifacts}
    ) != len(entries):
        raise ValueError("DEPENDENCY_MANIFEST_COVERAGE_MISMATCH")
    for item in artifacts:
        entry = entries.get(item["name"])
        if not entry or any(
            entry[key] != item[key] for key in ("name", "version", "sha256")
        ):
            raise ValueError("DEPENDENCY_MANIFEST_ARTIFACT_MISMATCH")
        filename = item["filename"]
        if (
            Path(filename).name != filename
            or not filename.endswith(".whl")
            or "\\" in filename
        ):
            raise ValueError("DEPENDENCY_FILENAME_INVALID")
        wheel_name, wheel_version, _, wheel_tags = parse_wheel_filename(filename)
        if (
            wheel_name != item["name"]
            or wheel_version != Version(item["version"])
            or not wheel_tags.intersection(set(sys_tags()))
            or not isinstance(item["size_bytes"], int)
            or item["size_bytes"] <= 0
        ):
            raise ValueError("DEPENDENCY_MANIFEST_WHEEL_MISMATCH")
        from urllib.parse import urlsplit

        parsed = urlsplit(item["url"])
        if (
            parsed.scheme != "https"
            or parsed.hostname != "files.pythonhosted.org"
            or parsed.username
            or parsed.password
        ):
            raise ValueError("DEPENDENCY_SOURCE_NOT_ALLOWED")
        if (
            item["metadata_url"]
            != f"https://pypi.org/pypi/{item['name']}/{item['version']}/json"
        ):
            raise ValueError("DEPENDENCY_METADATA_SOURCE_MISMATCH")
    return artifacts


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(group):
    artifacts = approved(group)
    directory = local(WHEELS)
    directory.mkdir(parents=True, exist_ok=True)

    def fetch(item):
        target = local(directory / item["filename"])
        if target.exists():
            if (
                target.stat().st_size != item["size_bytes"]
                or file_hash(target) != item["sha256"]
            ):
                raise ValueError("DEPENDENCY_CACHED_WHEEL_CHANGED")
            return
        temporary = local(directory / (item["filename"] + f"-{uuid4()}.part"))
        digest, total = hashlib.sha256(), 0
        try:
            with (
                open_public(item["url"], "files.pythonhosted.org") as response,
                temporary.open("xb") as stream,
            ):
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > item["size_bytes"]:
                        raise ValueError("DEPENDENCY_DOWNLOAD_SIZE_MISMATCH")
                    stream.write(chunk)
                    digest.update(chunk)
            if total != item["size_bytes"] or digest.hexdigest() != item["sha256"]:
                raise ValueError("DEPENDENCY_DOWNLOAD_HASH_MISMATCH")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch, artifacts))
    return {"group": group, "verified_wheels": len(artifacts)}


def versions(groups):
    entries = {}
    for group in groups:
        approved(group)
        for name, entry in read_lock(LOCKS[group]).items():
            if name in entries and entries[name]["version"] != entry["version"]:
                raise ValueError("DEPENDENCY_LOCK_CONFLICT")
            entries[name] = entry
    mismatched = []
    for name, entry in entries.items():
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None
        if installed != entry["version"]:
            mismatched.append(
                {"name": name, "expected": entry["version"], "installed": installed}
            )
    actual_names = [
        canonicalize_name(item.metadata["Name"]) for item in metadata.distributions()
    ]
    if len(actual_names) != len(set(actual_names)):
        raise ValueError("DEPENDENCY_DUPLICATE_INSTALLATION")
    unexpected = sorted(set(actual_names) - set(entries))
    return {
        "checked": len(entries),
        "matches": not mismatched and not unexpected,
        "mismatched": mismatched,
        "unexpected": unexpected,
    }


def export_inventory(destination):
    actual = {}
    for distribution in metadata.distributions():
        name = canonicalize_name(distribution.metadata["Name"])
        if name in actual:
            raise ValueError("DEPENDENCY_DUPLICATE_INSTALLATION")
        actual[name] = distribution.version
    output = local(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(
            "".join(f"{name}=={version}\n" for name, version in sorted(actual.items()))
        )
    return {"exported_packages": len(actual), "sha256": file_hash(output)}


def audit_summary(input_path, report_path, tool_exit):
    expected = read_lock(local(input_path), require_hash=False)
    report = json.loads(local(report_path).read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise TypeError("AUDIT_REPORT_INVALID")
    items = report.get("dependencies")
    if not isinstance(items, list):
        raise TypeError("AUDIT_REPORT_INVALID")
    if any(report.get(key) for key in ("error", "errors", "error_code")):
        raise ValueError("AUDIT_REPORT_CONTAINS_ERROR")
    actual, findings, skipped = {}, [], []
    for item in items:
        name = canonicalize_name(item["name"])
        if (
            name in actual
            or not isinstance(item.get("vulns", []), list)
            or ("vulns" not in item and not item.get("skip_reason"))
        ):
            raise ValueError("AUDIT_REPORT_INVALID")
        actual[name] = item.get("version")
        if item.get("skip_reason"):
            skipped.append(name)
        findings.extend(item.get("vulns", []))
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("id"), str)
        or not item["id"]
        for item in findings
    ):
        raise ValueError("AUDIT_REPORT_INVALID_FINDING")
    coverage = {name: entry["version"] for name, entry in expected.items()} == actual
    passed = tool_exit == 0 and coverage and not skipped and not findings
    return {
        "passed": passed,
        "tool_exit_code": tool_exit,
        "expected_packages": len(expected),
        "reported_packages": len(actual),
        "complete_coverage": coverage,
        "skipped_packages": skipped,
        "advisory_records": len(findings),
        "distinct_advisory_ids": len({item["id"] for item in findings}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["refresh", "download", "validate", "check", "export", "audit-report"],
    )
    parser.add_argument("--group", choices=list(LOCKS), default="application")
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--report")
    parser.add_argument("--tool-exit", type=int, default=2)
    args = parser.parse_args()
    if args.command == "refresh":
        result = refresh()
    elif args.command == "download":
        result = download(args.group)
    elif args.command == "validate":
        result = {"approved_lock_entries": sum(len(approved(group)) for group in LOCKS)}
    elif args.command == "check":
        result = versions(
            ["application", "bootstrap"]
            if args.group == "application"
            else [args.group]
        )
    elif args.command == "export":
        result = export_inventory(args.output)
    else:
        result = audit_summary(args.input, args.report, args.tool_exit)
        result["input_sha256"] = file_hash(local(args.input))
        result["raw_report_sha256"] = file_hash(local(args.report))
        result["raw_report"] = local(args.report).relative_to(ROOT).as_posix()
        if args.output:
            destination = local(args.output)
            if destination in {local(args.input), local(args.report)}:
                raise ValueError("AUDIT_RAW_EVIDENCE_MUST_BE_PRESERVED")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )
    print(json.dumps(result, sort_keys=True))
    return 1 if result.get("matches") is False or result.get("passed") is False else 0


if __name__ == "__main__":
    try:
        status = main()
    except Exception as error:  # noqa: BLE001 -- redact configuration/network/manifest failures at operator boundary
        print(
            json.dumps(
                {
                    "error_code": "DEPENDENCY_OPERATION_FAILED",
                    "error_class": type(error).__name__,
                }
            )
        )
        status = 2
    raise SystemExit(status)
