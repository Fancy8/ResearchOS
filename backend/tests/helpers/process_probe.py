"""Trusted, project-local crash probes. Never used by the application."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))


def write(directory, name, **values):
    # Replace atomically so the observer cannot read half a marker.
    temporary = directory / (name + ".tmp")
    temporary.write_text(json.dumps(values), encoding="utf-8")
    temporary.replace(directory / name)


def wait_for(path):
    deadline = time.monotonic() + 30
    while not path.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("PROBE_BARRIER_TIMEOUT")
        time.sleep(0.02)


mode, directory = sys.argv[1], Path(sys.argv[2]).resolve()
assert directory.is_relative_to(ROOT / "runtime")
if mode == "handles":
    import ctypes
    import gc
    import re
    from ctypes import wintypes

    from app.core.processes import ProcessGuardError, process_environment, run_contained

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetCurrentProcess.restype = wintypes.HANDLE
    api.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]

    def count():
        result = wintypes.DWORD()
        assert api.GetProcessHandleCount(api.GetCurrentProcess(), ctypes.byref(result))
        return result.value

    def fail_start():
        try:
            run_contained(
                [str(directory / "absent-private-name.exe")],
                cwd=ROOT,
                env=process_environment(directory),
                timeout=1,
            )
        except ProcessGuardError as error:
            assert re.fullmatch(r"PROCESS_START_FAILED_\d+", str(error))
        else:
            raise AssertionError("Missing executable started")

    fail_start()  # Warm imports before measuring process handles.
    gc.collect()
    before = count()
    for _ in range(40):
        fail_start()
    gc.collect()
    print(json.dumps({"before": before, "after": count(), "checked_failures": 40}))
elif mode == "leaf":
    write(directory, "leaf.json", pid=os.getpid())
    time.sleep(60)
elif mode in {"tree", "detached"}:
    write(directory, "tree.json", pid=os.getpid())
    subprocess.Popen(
        [sys.executable, __file__, "leaf", str(directory)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    wait_for(directory / "leaf.json")
    if mode == "tree":
        time.sleep(60)
elif mode in {"owner", "pg-owner", "scheduler-owner", "pdf-owner", "pdf-retry"}:
    from app.core.processes import process_environment, run_contained

    write(directory, "owner.json", pid=os.getpid())
    wait_for(directory / "allow")

    def started(pid):
        write(directory, "started.json", pid=pid)
        if mode in {"pg-owner", "pdf-owner"}:
            # Hold the reader while the real PG/PDF tool fills its output pipe.
            time.sleep(60)

    if mode == "pg-owner":
        from app.core.config import get_settings
        from app.recovery.backup import pg_tool

        pg_tool("pg_dump", ["--format=plain"], get_settings().backup_database_url, on_started=started)
    elif mode == "scheduler-owner":
        import base64

        from app.core.config import get_settings
        from app.core.storage import s3_client
        from app.recovery import backup, scheduler
        from app.recovery.catalog import BackupCatalog

        settings = get_settings()
        config = json.loads((directory / "probe.json").read_text(encoding="utf-8"))
        catalog = BackupCatalog(
            settings.backup_database_url, settings.s3_bucket, settings.control_secret, directory / "catalog"
        )
        original = backup.pg_tool

        def after_dump(*args, **kwargs):
            original(*args, **kwargs)
            write(directory, "dumped.json", completed=True)
            time.sleep(60)  # Real dump exists; snapshot and scheduler locks remain held.

        backup.pg_tool = after_dump
        scheduler.run_once(
            settings.backup_database_url,
            s3_client(),
            settings.s3_bucket,
            base64.b64decode(config["key"]),
            catalog=catalog,
            hour=0,
        )
    elif mode in {"pdf-owner", "pdf-retry"}:
        from app.workers import jobs

        config = json.loads((directory / "probe.json").read_text(encoding="utf-8"))
        if mode == "pdf-owner":
            original = jobs.run_contained

            def supervised(*args, **kwargs):
                return original(*args, **kwargs, on_started=started)

            jobs.run_contained = supervised
        jobs.parse_pdf(config["job_id"])
        write(directory, "completed.json", completed=True)
    else:
        run_contained(
            [sys.executable, __file__, "tree", str(directory)],
            cwd=ROOT,
            env=process_environment(directory),
            timeout=30,
            on_started=started,
        )
