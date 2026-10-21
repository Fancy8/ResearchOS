"""Signed operator backup catalog, independent of database snapshots."""

import hashlib
import hmac
import json
import os
import shutil
import stat
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import make_url

from app.core.config import ROOT
from app.core.runtime_paths import runtime_namespace


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class BackupCatalog:
    @staticmethod
    def source_context(source_url, bucket):
        url = make_url(source_url)
        return {
            "database": url.database,
            "bucket": bucket,
            "endpoint": hashlib.sha256(f"{url.host}:{url.port or 5432}/{url.database}".encode()).hexdigest(),
        }

    def __init__(self, source_url, bucket, secret, directory=None):
        url = make_url(source_url)
        self.context = self.source_context(source_url, bucket)
        self.root = Path(directory) if directory else runtime_namespace("backups", url.database)
        self.secret = secret.encode()
        self.checked(self.root)
        for folder in (self.root, self.root / "records", self.root / "files", self.root / "work"):
            self.checked(folder).mkdir(parents=True, exist_ok=True)

    def checked(self, path):
        path = Path(path).absolute()
        if path.resolve() != path or not path.is_relative_to(ROOT) or path == ROOT:
            raise ValueError("BACKUP_CATALOG_PATH_INVALID")
        return path

    def file(self, identifier, suffix=".rosbak"):
        if suffix not in {".rosbak", ".part"}:
            raise ValueError("BACKUP_FILE_SUFFIX_INVALID")
        return self.checked(self.root / "files" / f"{UUID(str(identifier))}{suffix}")

    def workspace(self, identifier):
        return self.checked(self.root / "work" / str(UUID(str(identifier))))

    def sign(self, document):
        encoded = (
            b"researchos-backup-catalog-v1\0"
            + json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        )
        return hmac.new(self.secret, encoded, hashlib.sha256).hexdigest()

    def write(self, document):
        document = {**document, "context": self.context, "format_version": 1}
        record = self.checked(self.root / "records" / f"{UUID(document['id'])}.json")
        temporary = self.checked(record.with_name(f"{record.name}-{uuid4()}.tmp"))
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump({**document, "signature": self.sign(document)}, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, record)
        finally:
            temporary.unlink(missing_ok=True)

    def records(self):
        documents = []
        for path in sorted((self.root / "records").glob("*.json")):
            self.checked(path)
            document = json.loads(path.read_text(encoding="utf-8"))
            supplied = document.pop("signature", "")
            if (
                not supplied
                or not hmac.compare_digest(supplied, self.sign(document))
                or document.get("context") != self.context
                or document.get("format_version") != 1
                or str(UUID(document["id"])) != path.stem
            ):
                raise ValueError("BACKUP_CATALOG_INTEGRITY_FAILURE")
            documents.append(document)
        return documents

    def cleanup_work(self, identifier):
        partial = self.file(identifier, ".part")
        if partial.exists():
            if not stat.S_ISREG(partial.lstat().st_mode):
                raise ValueError("BACKUP_PARTIAL_TYPE_INVALID")
            partial.unlink()
        work = self.workspace(identifier)
        if work.exists():
            # Recursive disposal is limited to this exact, signed run's workspace.
            # Refuse links/junctions instead of traversing another storage tree.
            def validate(path):
                metadata = path.lstat()
                if (
                    path.resolve() != path.absolute()
                    or path.is_symlink()
                    or getattr(metadata, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                ):
                    raise ValueError("BACKUP_WORKSPACE_LINK_INVALID")
                if path.is_dir():
                    with os.scandir(path) as entries:
                        for entry in entries:
                            validate(Path(entry.path))

            validate(work)
            shutil.rmtree(work)

    def unregistered(self, records):
        registered = {self.file(row["id"]) for row in records}
        return sum(path not in registered for path in (self.root / "files").glob("*.rosbak"))

    def inspect(self, records, verify=False):
        errors, checked = [], 0
        for row in records:
            if row["status"] != "succeeded":
                continue
            path = self.file(row["id"])
            if not path.is_file() or path.stat().st_size != row["size_bytes"]:
                errors.append({"id": row["id"], "error_code": "BACKUP_FILE_MISSING_OR_SIZE_CHANGED"})
            elif verify:
                checked += 1
                if checksum(path) != row["sha256"]:
                    errors.append({"id": row["id"], "error_code": "BACKUP_CIPHERTEXT_HASH_CHANGED"})
        return {
            "hash_checked_files": checked,
            "file_errors": errors,
            "unregistered_files": self.unregistered(records),
        }
