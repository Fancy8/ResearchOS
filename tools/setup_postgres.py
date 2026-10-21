"""Project-local PostgreSQL binaries. No machine-wide installation or service."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
LOCK = json.loads((ROOT / "tools/services-lock.json").read_text(encoding="utf-8"))[
    "postgresql"
]
VERSION = LOCK["version"]
URL = LOCK["url"]


def setup():
    RUNTIME.mkdir(exist_ok=True)
    archive = RUNTIME / f"postgresql-{VERSION}.zip"
    binaries = RUNTIME / "postgresql" / "pgsql" / "bin"
    if not binaries.joinpath("postgres.exe").exists():
        if not archive.exists():
            partial = archive.with_suffix(".partial")
            print(f"Downloading PostgreSQL {VERSION} into project runtime", flush=True)
            with (
                urllib.request.urlopen(URL, timeout=60) as response,
                partial.open("wb") as output,
            ):
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            partial.rename(archive)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != LOCK["sha256"]:
                raise ValueError(
                    "PostgreSQL archive digest differs from reviewed baseline"
                )
        destination = RUNTIME / "postgresql"
        destination.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                resolved = (destination / member.filename).resolve()
                if not resolved.is_relative_to(destination.resolve()):
                    raise ValueError("Unsafe archive path")
            # Only runtime files, not GUI/admin tooling or installers.
            for member in bundle.infolist():
                if member.filename.startswith(
                    ("pgsql/bin/", "pgsql/lib/", "pgsql/share/")
                ):
                    bundle.extract(member, destination)
        print("PostgreSQL binaries extracted", flush=True)
    version = subprocess.check_output(
        [str(binaries / "postgres.exe"), "--version"], text=True
    ).strip()
    record = {
        "source": URL,
        "version": version,
        "sha256": hashlib.file_digest(archive.open("rb"), "sha256").hexdigest(),
    }
    (RUNTIME / "postgresql-provenance.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )
    print(version, flush=True)


if __name__ == "__main__":
    os.environ["TEMP"] = str(RUNTIME / "tmp")
    os.environ["TMP"] = os.environ["TEMP"]
    setup()
