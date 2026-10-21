"""Read-only broker metadata; no messages, connection URLs or credentials."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main():
    try:
        # Configuration validation may contain private input in its exception;
        # imports that initialize settings belong inside the redaction boundary.
        from app.workers.dispatcher import broker_state

        state = broker_state()
    except Exception:  # noqa: BLE001 -- operator boundary must redact driver/configuration failures
        print(json.dumps({"error_code": "BROKER_STATUS_UNAVAILABLE"}))
        return 2
    print(json.dumps(state, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
