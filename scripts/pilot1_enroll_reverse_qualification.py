#!/usr/bin/env python3
"""Create an explicitly NONRANDOM Low-Yield-first Pilot 1 qualification session.

Trusted WSL host only; does not provision a container, release task files, or
issue a browser invitation. Normal pilot1_enroll.py remains fully randomized.
The resulting participant is test data: EXCLUDE it from research analysis.

Preview: python3 scripts/pilot1_enroll_reverse_qualification.py
Apply:   python3 scripts/pilot1_enroll_reverse_qualification.py --create --confirm-nonrandom-qualification

Never paste generated participant/session IDs into chat, issues, or GitHub.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
from uuid import UUID

from pilot1_enroll import SQL, DB_CONTAINER, DB_NAME

ORDER = "lowyield_first"
KIND = "r2d4_reverse_order_qualification"
SESSION_RE = re.compile(r"[0-9a-f-]{36}\Z")
PID_RE = re.compile(r"[0-9a-f]{24}\Z")


def private_directory() -> Path:
    """Require a private operator-owned directory before touching the DB."""
    root = Path.home() / "nerds-pilot-runtime" / "qualification-sessions"
    if root.is_symlink():
        raise RuntimeError("Qualification directory must not be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise RuntimeError("Qualification directory must be owned by operator, mode 0700")
    return root


def interpret_result(stdout: str, expected_pid: str) -> str:
    """Require exactly one committed enrollment row; never guess a session ID."""
    rows = [line for line in stdout.splitlines() if line.count("|") == 4]
    if len(rows) != 1:
        raise RuntimeError("Enrollment outcome ambiguous; inspect database before retrying")
    fields = rows[0].split("|")
    sid, pid, order, phase, status = fields
    if (pid != expected_pid or order != ORDER or phase != "pilot1"
            or status != "assigned" or not PID_RE.fullmatch(pid)):
        raise RuntimeError("Unexpected enrollment response; inspect DB, do not retry")
    try:
        if str(UUID(sid)) != sid:
            raise ValueError("Noncanonical session UUID")
    except ValueError as exc:
        raise RuntimeError("Invalid session UUID; inspect DB, do not retry") from exc
    return sid


def record_qualification(directory: Path, sid: str, pid: str) -> Path:
    """Create-only mode-0600 marker. Never overwrite another session's record."""
    if not SESSION_RE.fullmatch(sid) or not PID_RE.fullmatch(pid):
        raise RuntimeError("Invalid qualification session identifiers")
    target = directory / (sid + ".json")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({
                "qualification_kind": KIND,
                "session_id": sid,
                "participant_id": pid,
                "order_code": ORDER,
                "not_randomized": True,
                "exclude_from_research_analysis": True,
                "status": "enrolled_not_provisioned",
            }, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def enroll(participant_id: str) -> str:
    cmd = [
        "docker", "exec", "-u", "postgres", "-i", DB_CONTAINER,
        "psql", "-X", "-q", "-t", "-A", "-F", "|",
        "-v", "ON_ERROR_STOP=1",
        "-v", f"participant_id={participant_id}",
        "-v", f"order_code={ORDER}",
        "-d", DB_NAME,
    ]
    try:
        result = subprocess.run(
            cmd, input=SQL, text=True, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "Enrollment could have partially committed; inspect DB before retrying"
        ) from exc
    return interpret_result(result.stdout, participant_id)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--create", action="store_true",
        help="Create exactly one nonrandom Low-Yield-first qualification session",
    )
    parser.add_argument(
        "--confirm-nonrandom-qualification", action="store_true",
        help="Explicitly acknowledge this is test-only data, not randomized study enrollment",
    )
    args = parser.parse_args(argv)
    if args.confirm_nonrandom_qualification and not args.create:
        parser.error("Confirmation flag is only valid with --create")

    if not args.create:
        print("PREVIEW ONLY: no Docker, database or filesystem changes")
        print("Qualification order: lowyield_first (Task 1 lowyield_v1; Task 2 dense_v2)")
        print("Nonrandom test session: must be excluded from research analysis")
        print("To create: add --create --confirm-nonrandom-qualification")
        return 0

    if not args.confirm_nonrandom_qualification:
        parser.error("Use --confirm-nonrandom-qualification for a NONRANDOM test session")

    directory = private_directory()
    pid = secrets.token_hex(12)
    sid = enroll(pid)
    try:
        marker = record_qualification(directory, sid, pid)
    except (OSError, RuntimeError) as exc:
        print(
            "STOP: enrollment may be committed but its private qualification marker failed. "
            "DO NOT RETRY; inspect the database and private directory manually.",
            file=sys.stderr,
        )
        print(f"Marker failure category: {type(exc).__name__}", file=sys.stderr)
        return 2

    print("NONRANDOM QUALIFICATION ONLY — EXCLUDE FROM RESEARCH ANALYSIS")
    print(f"Participant ID: {pid}")
    print(f"Session ID:     {sid}")
    print(f"Order:          {ORDER}")
    print(f"Private marker: {marker}")
    print("Container: unassigned; no task released; no browser invitation issued")
    print("Store these identifiers privately. Do not publish them in chat or GitHub.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
