"""Bound the isolated advisory subprocess and retain only scoped artifacts."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.processes import process_environment, run_contained


def local(value):
    path = Path(value).resolve()
    if path == ROOT or not path.is_relative_to(ROOT):
        raise ValueError("AUDIT_PATH_OUTSIDE_PROJECT")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable, inventory, report = map(local, (args.python, args.input, args.report))
    if report.exists():
        raise ValueError("AUDIT_REPORT_MUST_BE_NEW")
    profile = ROOT / "runtime/audit-profile"
    for directory in (profile, profile / "Local", profile / "Roaming"):
        directory.mkdir(parents=True, exist_ok=True)
    result = run_contained(
        [
            str(executable),
            "-m",
            "pip_audit",
            "-r",
            str(inventory),
            "--no-deps",
            "--disable-pip",
            "--format=json",
            "--output",
            str(report),
            "--progress-spinner=off",
            "--cache-dir",
            str(ROOT / "runtime/cache/pip-audit-http"),
            "--timeout",
            "15",
        ],
        cwd=ROOT,
        env=process_environment(
            ROOT / "runtime/tmp",
            {
                "USERPROFILE": str(profile),
                "LOCALAPPDATA": str(profile / "Local"),
                "APPDATA": str(profile / "Roaming"),
            },
        ),
        timeout=600,
        output_limit=256 * 1024,
        memory_limit=512 * 1024 * 1024,
    )
    report.with_suffix(".stdout.log").write_bytes(result.stdout)
    report.with_suffix(".stderr.log").write_bytes(result.stderr)
    print(
        json.dumps(
            {"tool_exit_code": result.returncode, "report_created": report.is_file()}
        )
    )
    return result.returncode


if __name__ == "__main__":
    try:
        code = main()
    except Exception as error:  # noqa: BLE001 -- operator boundary cannot disclose process/network parameters
        print(
            json.dumps(
                {
                    "error_code": "AUDIT_PROCESS_FAILED",
                    "error_class": type(error).__name__,
                }
            )
        )
        code = 2
    raise SystemExit(code)
