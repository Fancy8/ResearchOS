"""Verify declared runtime and installer pins, including pip omitted by freeze."""

import json

from dependencies import versions


def main():
    result = versions(["application", "bootstrap"])
    print(json.dumps(result, sort_keys=True))
    return 0 if result["matches"] else 1


if __name__ == "__main__":
    try:
        code = main()
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"error_code": "DEPENDENCY_INVENTORY_INVALID"}))
        code = 2
    raise SystemExit(code)
