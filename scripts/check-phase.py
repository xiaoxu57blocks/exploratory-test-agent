#!/usr/bin/env python3
"""
check-phase — confirm an upstream pipeline phase wrote what it owes the next phase.

The /test-tickets orchestrator runs this between phase invocations so a
silent "agent said done but didn't actually write the file" failure stops
the pipeline early instead of poisoning downstream agents.

Usage:
  scripts/check-phase.py --run-id 2026-05-08_1524_SUP-7623 --phase fetch
  scripts/check-phase.py --run-id 2026-05-08_1524_SUP-7623 --phase triage
  scripts/check-phase.py --run-id 2026-05-08_1524_SUP-7623 --phase spec --unit unit-1
  scripts/check-phase.py --run-id 2026-05-08_1524_SUP-7623 --phase execute --unit unit-1

Exit codes:
  0  the phase's expected files exist and (where applicable) pass schema validation
  1  files missing or invalid
  2  bad arguments
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = REPO_ROOT / "artifacts"
VALIDATOR = REPO_ROOT / "scripts" / "validate-artifact.py"


def die(code: int, msg: str) -> None:
    print(f"check-phase: {msg}", file=sys.stderr)
    sys.exit(code)


def must_exist(path: Path, description: str) -> None:
    if not path.exists():
        die(1, f"{description} missing: {path}")
    if path.stat().st_size == 0:
        die(1, f"{description} is empty: {path}")


def must_validate(kind: str, path: Path) -> None:
    rc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--kind", kind, "--path", str(path), "--quiet"],
    ).returncode
    if rc != 0:
        die(1, f"validation failed for {path} (kind={kind}); see stderr above")


def check_fetch(run_dir: Path) -> None:
    fetch = run_dir / "01-fetch.json"
    must_exist(fetch, "fetch artifact")
    # No schema yet for fetch — sanity check the structure instead.
    data = json.loads(fetch.read_text())
    if "tickets" not in data or not data["tickets"]:
        die(1, f"{fetch}: 'tickets' missing or empty")


def check_triage(run_dir: Path) -> None:
    must_exist(run_dir / "01-fetch.json", "fetch artifact (prerequisite)")
    triage = run_dir / "02-triage.json"
    must_exist(triage, "triage artifact")
    data = json.loads(triage.read_text())
    if "test_units" not in data:
        die(1, f"{triage}: 'test_units' missing")


def check_spec(run_dir: Path, unit: str | None) -> None:
    must_exist(run_dir / "02-triage.json", "triage artifact (prerequisite)")
    if not unit:
        die(2, "--unit <unit-id> required for --phase spec")
    md = run_dir / f"03-spec-{unit}.md"
    js = run_dir / f"03-spec-{unit}.json"
    must_exist(md, "spec markdown")
    must_exist(js, "spec sidecar JSON")
    must_validate("spec", js)


def check_execute(run_dir: Path, unit: str | None) -> None:
    if not unit:
        die(2, "--unit <unit-id> required for --phase execute")
    must_exist(run_dir / f"03-spec-{unit}.json", "spec sidecar (prerequisite)")
    udir = run_dir / f"04-run-{unit}"
    if not udir.is_dir():
        die(1, f"unit run directory missing: {udir}")
    result = udir / "result.json"
    trace = udir / "trace.jsonl"
    must_exist(result, "result.json")
    must_exist(trace, "trace.jsonl")
    must_validate("result", result)
    must_validate("trace", trace)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--run-id", required=True)
    p.add_argument("--phase", required=True, choices=["fetch", "triage", "spec", "execute"])
    p.add_argument("--unit", help="unit id, required for --phase spec or execute")
    args = p.parse_args()

    run_dir = ARTIFACTS / args.run_id
    if not run_dir.is_dir():
        die(1, f"run dir missing: {run_dir}")

    if args.phase == "fetch":
        check_fetch(run_dir)
    elif args.phase == "triage":
        check_triage(run_dir)
    elif args.phase == "spec":
        check_spec(run_dir, args.unit)
    elif args.phase == "execute":
        check_execute(run_dir, args.unit)

    print(f"ok phase={args.phase} run={args.run_id}" + (f" unit={args.unit}" if args.unit else ""))
    sys.exit(0)


if __name__ == "__main__":
    main()
