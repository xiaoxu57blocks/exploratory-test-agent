#!/usr/bin/env python3
"""
get-fixture — ensure a named fixture PDF is present in the local cache.

Why this is a script:
- Drive folder enumeration + downloading is deterministic IO.
- Caching prevents re-downloading on every /create-case run.
- Keeps the agent out of base64 / curl bookkeeping.

Cache layout:
  fixtures/
    cache/                  # gitignored; populated on demand
      <name>.pdf
    manifest.json           # checked-in; maps fixture name -> drive file id

Usage:
  scripts/get-fixture.py --name "Incident_Report.pdf"
    -> ensures fixtures/cache/Incident_Report.pdf exists, prints absolute path

  scripts/get-fixture.py --copy-to <dest-dir> --name "Incident_Report.pdf"
    -> as above, then copies the cached file into <dest-dir>

  scripts/get-fixture.py --list
    -> prints names known to manifest.json + presence-in-cache flag

Errors are JSON on stdout with `{"ok": false, "stage": "...", "msg": "..."}`
so the calling agent can route on them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "fixtures" / "cache"
MANIFEST_PATH = REPO_ROOT / "fixtures" / "manifest.json"


def emit(d: dict, exit_code: int = 0) -> None:
    print(json.dumps(d))
    sys.exit(exit_code)


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        emit({"ok": False, "stage": "manifest", "msg": f"manifest.json not found at {MANIFEST_PATH}"}, 2)
    return json.loads(MANIFEST_PATH.read_text())


def download_drive_file(file_id: str, dest: Path) -> int:
    """Download a Drive file by id via the OAuth helper script. Returns size in bytes."""
    helper = REPO_ROOT / "scripts" / "google-drive.py"
    if not helper.exists():
        emit({
            "ok": False,
            "stage": "missing_helper",
            "msg": f"{helper} not found — needed for OAuth-authenticated Drive downloads.",
        }, 3)
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(helper), "download", "--file-id", file_id, "--out", str(dest)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # Surface the helper's stderr verbatim so the caller can see the auth/api error
        # (notably exit code 4 — "no cached token; run `auth` first").
        emit({
            "ok": False,
            "stage": "drive_helper_failed",
            "file_id": file_id,
            "exit_code": proc.returncode,
            "stderr": proc.stderr.strip(),
            "stdout": proc.stdout.strip(),
            "hint": "If exit_code == 4, run: scripts/google-drive.py auth",
        }, 3)
    if not dest.exists() or dest.stat().st_size == 0:
        emit({"ok": False, "stage": "drive_helper_no_output", "file_id": file_id, "msg": "helper returned 0 but the output file is missing/empty"}, 3)
    return dest.stat().st_size


def ensure(name: str) -> dict:
    cached = CACHE_DIR / name
    if cached.exists() and cached.stat().st_size > 0:
        return {
            "ok": True,
            "name": name,
            "path": str(cached),
            "size": cached.stat().st_size,
            "from_cache": True,
        }

    manifest = load_manifest()
    entry = manifest.get(name)
    if not entry:
        emit({
            "ok": False,
            "stage": "manifest_lookup",
            "name": name,
            "known": sorted(manifest.keys()),
            "msg": f"'{name}' not in fixtures/manifest.json. Known fixtures: {sorted(manifest.keys())}.",
        }, 2)

    file_id = entry.get("drive_file_id")
    if not file_id:
        emit({
            "ok": False,
            "stage": "manifest_entry",
            "name": name,
            "msg": "manifest entry has no drive_file_id",
        }, 2)

    size = download_drive_file(file_id, cached)
    return {
        "ok": True,
        "name": name,
        "path": str(cached),
        "size": size,
        "from_cache": False,
        "drive_file_id": file_id,
    }


def cmd_list() -> None:
    manifest = load_manifest()
    rows = []
    for name, entry in sorted(manifest.items()):
        if name.startswith("_") or not isinstance(entry, dict):
            continue
        cached = CACHE_DIR / name
        rows.append({
            "name": name,
            "drive_file_id": entry.get("drive_file_id"),
            "covers_event_types": entry.get("covers_event_types", []),
            "in_cache": cached.exists() and cached.stat().st_size > 0,
            "cache_path": str(cached) if cached.exists() else None,
        })
    print(json.dumps({"ok": True, "fixtures": rows}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--name", help="fixture name as listed in fixtures/manifest.json")
    p.add_argument("--copy-to", type=Path, help="copy the resolved fixture into this directory")
    p.add_argument("--list", action="store_true", help="list known fixtures + cache state")
    args = p.parse_args()

    if args.list:
        cmd_list()
        return

    if not args.name:
        emit({"ok": False, "stage": "args", "msg": "either --name or --list required"}, 2)

    result = ensure(args.name)

    if args.copy_to:
        args.copy_to.mkdir(parents=True, exist_ok=True)
        target = args.copy_to / args.name
        shutil.copy2(result["path"], target)
        result["copied_to"] = str(target)

    emit(result, 0)


if __name__ == "__main__":
    main()
