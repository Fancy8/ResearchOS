"""Download project-local development services and record their provenance."""

import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runtime"


def download(url, destination):
    if not destination.exists():
        partial = destination.with_suffix(".partial")
        with (
            urllib.request.urlopen(url, timeout=60) as response,
            partial.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        partial.rename(destination)
    with destination.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    manifest = []
    lock = json.loads((ROOT / "tools/services-lock.json").read_text(encoding="utf-8"))
    asset = lock["redis"]
    archive = RUN / asset["filename"]
    checksum = download(asset["url"], archive)
    assert asset["sha256"] == checksum, "Redis archive digest mismatch"
    destination = RUN / "redis"
    destination.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            assert (
                (destination / item.filename)
                .resolve()
                .is_relative_to(destination.resolve())
            )
        bundle.extractall(destination)
    manifest.append(
        {
            "component": "redis-windows",
            "url": asset["url"],
            "sha256": checksum,
            "usage": "local development only; Linux service required for production",
        }
    )
    asset = lock["seaweedfs"]
    archive = RUN / asset["filename"]
    checksum = download(asset["url"], archive)
    assert asset["sha256"] == checksum, "SeaweedFS archive digest mismatch"
    destination = RUN / "seaweedfs"
    destination.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            assert (
                (destination / item.filename)
                .resolve()
                .is_relative_to(destination.resolve())
            )
        bundle.extractall(destination)
    manifest.append(
        {
            "component": "seaweedfs",
            "url": asset["url"],
            "sha256": checksum,
            "usage": "project-local persistent private S3-compatible object store",
        }
    )
    (RUN / "services-provenance.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print("Redis and SeaweedFS downloaded under project runtime", flush=True)


if __name__ == "__main__":
    main()
