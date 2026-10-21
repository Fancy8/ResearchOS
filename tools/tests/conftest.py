import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
os.environ["TEMP"] = os.environ["TMP"] = str(ROOT / "runtime/tmp")


def pytest_configure(config):
    target = (
        Path(config.option.basetemp).resolve()
        if config.option.basetemp
        else ROOT / "runtime/pytest-tools"
    )
    if target == ROOT or not target.is_relative_to(ROOT):
        raise pytest.UsageError("Tool test artifacts must remain inside the project")
    config.option.basetemp = target
