"""`ruff check app/` is the first command AGENTS.md and README give, and no
workflow runs it. It exited 1 on an untouched tree for months (58 findings),
so the chained `&& pytest` never ran. Keep it green from the test suite."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]


def _ruff() -> str | None:
    return shutil.which("ruff", path=str(Path(sys.executable).parent)) or shutil.which("ruff")


def test_ruff_check_app_passes():
    ruff = _ruff()
    if not ruff:
        pytest.skip("ruff not installed (it is in the dev extra)")
    result = subprocess.run(
        [ruff, "check", "app/", "--output-format", "concise", "--no-cache"],
        cwd=SERVER, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
