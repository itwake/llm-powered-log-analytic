from __future__ import annotations

import os

import pytest

from scripts.full_stack_smoke import main


@pytest.mark.integration
def test_full_stack_smoke_runner() -> None:
    if os.getenv("LOGAN_RUN_FULL_STACK_SMOKE") != "true":
        pytest.skip("set LOGAN_RUN_FULL_STACK_SMOKE=true to run the full-stack smoke")

    assert main() == 0
