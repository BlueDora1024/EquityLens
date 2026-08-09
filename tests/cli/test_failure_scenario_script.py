from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_failure_scenario_script_lists_ten_stable_scenarios() -> None:
    root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        (str(root / "scripts" / "run_failure_scenario.sh"), "--list"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.splitlines() == [
        "timeout-recovery",
        "repeated-429",
        "auth-fatal",
        "quota-fatal",
        "exactly-80-partial",
        "below-80-failure",
        "database-busy",
        "disk-blocked",
        "user-cancel",
        "ai-old-report",
    ]


def test_failure_scenario_script_runs_from_outside_repository(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "run_failure_scenario.sh"

    assert script.stat().st_mode & 0o111
    completed = subprocess.run(
        (str(script), "all"),
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    payloads = [
        json.loads(line)
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    assert [item["result"]["id"] for item in payloads] == [
        "timeout-recovery",
        "repeated-429",
        "auth-fatal",
        "quota-fatal",
        "exactly-80-partial",
        "below-80-failure",
        "database-busy",
        "disk-blocked",
        "user-cancel",
        "ai-old-report",
    ]
    assert all(
        item["result"]["scenario_assertions_passed"]
        for item in payloads
    )
