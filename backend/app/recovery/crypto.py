"""Versioned streaming backup container using authenticated AES-GCM frames."""

import hashlib
import json
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"ROSBAK01"
CHUNK = 4 * 1024 * 1024


def encrypt_file(source, target, key):
    if len(key) != 32:
        raise ValueError("BACKUP_KEY_MUST_BE_32_BYTES")
    header = MAGIC + os.urandom(16)
    cipher, digest, total, counter = AESGCM(key), hashlib.sha256(), 0, 0
    created = False
    try:
        with source.open("rb") as reader, target.open("xb") as writer:
            created = True
            writer.write(header)

            def frame(flag, data):
                nonlocal counter
                nonce = os.urandom(12)
                associated = header + struct.pack(">QB", counter, flag)
                encrypted = nonce + cipher.encrypt(nonce, data, associated)
                writer.write(struct.pack(">BI", flag, len(encrypted)))
                writer.write(encrypted)
                counter += 1

            while chunk := reader.read(CHUNK):
                digest.update(chunk)
                total += len(chunk)
                frame(0, chunk)
            frame(1, json.dumps({"chunks": counter, "bytes": total, "sha256": digest.hexdigest()}).encode())
            writer.flush()
            os.fsync(writer.fileno())
    except Exception:
        if created:
            target.unlink(missing_ok=True)
        raise


def decrypt_file(source, target, key):
    cipher, digest, total, counter = AESGCM(key), hashlib.sha256(), 0, 0
    created = False
    try:
        with source.open("rb") as reader, target.open("xb") as writer:
            created = True
            header = reader.read(24)
            if len(header) != 24 or header[:8] != MAGIC:
                raise ValueError("INVALID_BACKUP_FORMAT")
            while True:
                frame_header = reader.read(5)
                if len(frame_header) != 5:
                    raise ValueError("INCOMPLETE_BACKUP")
                flag, size = struct.unpack(">BI", frame_header)
                if flag not in {0, 1} or not 28 <= size <= CHUNK + 28:
                    raise ValueError("INVALID_BACKUP_FRAME")
                encrypted = reader.read(size)
                if len(encrypted) != size:
                    raise ValueError("INCOMPLETE_BACKUP")
                plain = cipher.decrypt(
                    encrypted[:12], encrypted[12:], header + struct.pack(">QB", counter, flag)
                )
                if flag == 1:
                    footer = json.loads(plain)
                    if footer != {
                        "chunks": counter,
                        "bytes": total,
                        "sha256": digest.hexdigest(),
                    } or reader.read(1):
                        raise ValueError("BACKUP_INTEGRITY_FAILURE")
                    break
                writer.write(plain)
                digest.update(plain)
                total += len(plain)
                counter += 1
            writer.flush()
            os.fsync(writer.fileno())
    except Exception:
        if created:
            target.unlink(missing_ok=True)
        raise
