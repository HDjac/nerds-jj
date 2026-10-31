#!/usr/bin/env python3
"""Issue/revoke a short-lived, LOCAL-ONLY NERDs Pilot 1 proxy test cookie.

Run on the trusted WSL host with Docker access; never expose as a web endpoint.
The plaintext secret goes only in a mode-0600 curl cookie file under
~/.local/share/nerds-pilot1/. PostgreSQL receives only its SHA-256 digest.

Examples:
    python3 scripts/pilot1_issue_test_session.py --participant-id PID
    python3 scripts/pilot1_issue_test_session.py --participant-id PID --apply
    python3 scripts/pilot1_issue_test_session.py --participant-id PID --revoke
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time

DB_CONTAINER = "devob-db-1"
DB_NAME = "notebook"
CONTAINER_NAME = "nerds-pilot1-runtime"
INSTANCE_IMAGE = "devob_instance:cli-pilot-protected"
PID_RE = re.compile(r"[0-9a-f]{24}\Z")
INSTANCE_RE = re.compile(r"[0-9a-f]{12}\Z")


def run(argv, input_text=None):
    result = subprocess.run(argv, input=input_text, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} command failed:\n{result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def psql(statement, *, variables=None):
    cmd = ["docker", "exec", "-i", "-u", "postgres", DB_CONTAINER,
           "psql", "-X", "-qAt", "-F", "|", "-v", "ON_ERROR_STOP=1"]
    for key, value in (variables or {}).items():
        cmd.extend(["-v", f"{key}={value}"])
    cmd.extend(["-d", DB_NAME])
    return run(cmd, input_text=statement)


def inspect_instance():
    obj = json.loads(run(["docker", "inspect", CONTAINER_NAME]))[0]
    short_id = obj["Id"][:12]
    if not INSTANCE_RE.fullmatch(short_id):
        raise RuntimeError("Invalid Docker instance ID")
    if (not obj["State"]["Running"] or obj["Config"]["Image"] != INSTANCE_IMAGE
            or obj["Config"]["User"] != "user"
            or obj["Config"].get("Labels", {}).get("nerds.study") != "pilot1"
            or "devob_instances" not in obj["NetworkSettings"]["Networks"]):
        raise RuntimeError("Running container does not match protected Pilot 1 configuration")
    return short_id


def find_session(pid, instance_id):
    result = psql(r"""
        SELECT s.session_id::text, s.status, t1.status, t2.status
        FROM fuzz_pilot.study_sessions AS s
        JOIN fuzz_pilot.participants AS p ON p.participant_id = s.participant_id
        JOIN fuzz_pilot.task_runs AS t1 ON t1.session_id = s.session_id AND t1.position = 1
        JOIN fuzz_pilot.task_runs AS t2 ON t2.session_id = s.session_id AND t2.position = 2
        WHERE s.participant_id = :'pid'
          AND s.attempt_number = 1
          AND s.study_phase = 'pilot1'
          AND s.enrollment_method = 'manual'
          AND s.instance_id = :'iid'
          AND s.instance_name = :'container'
          AND p.withdrawn_at IS NULL;
    """, variables={"pid": pid, "iid": instance_id, "container": CONTAINER_NAME})
    rows = result.splitlines()
    if len(rows) != 1 or len(rows[0].split("|")) != 4:
        raise RuntimeError("Expected one enrolled, provisioned study session")
    session_id, session_status, task1, task2 = rows[0].split("|")
    if session_status not in ("assigned", "active") or task1 not in ("ready", "active") or task2 != "locked":
        raise RuntimeError("Session/task state is not eligible for a test cookie")
    return session_id, session_status, task1, task2


def private_dir():
    directory = Path.home() / ".local" / "share" / "nerds-pilot1"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise RuntimeError(f"Private credential directory must be owned by you and mode 0700: {directory}")
    return directory


def issue(pid, iid, minutes):
    token = secrets.token_hex(32)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    directory = private_dir()
    cookie_path = directory / f"{pid}.cookies"
    fd, tmp_name = tempfile.mkstemp(prefix=".pending-", dir=directory)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as cookie:
            os.fchmod(cookie.fileno(), 0o600)
            expiry = int(time.time()) + minutes * 60 - 15  # Slightly shorter than DB TTL.
            cookie.write("# Netscape HTTP Cookie File\n")
            cookie.write(f"127.0.0.1\tFALSE\t/\tTRUE\t{expiry}\t__Host-nerds_session\t{token}\n")

        response = psql(r"""
            BEGIN;
            WITH eligible AS (
                SELECT s.session_id
                FROM fuzz_pilot.study_sessions AS s
                JOIN fuzz_pilot.participants AS p ON p.participant_id = s.participant_id
                WHERE s.participant_id = :'pid'
                  AND s.attempt_number = 1
                  AND s.study_phase = 'pilot1'
                  AND s.enrollment_method = 'manual'
                  AND s.instance_id = :'iid'
                  AND s.instance_name = :'container'
                  AND s.status IN ('assigned', 'active')
                  AND p.withdrawn_at IS NULL
                  AND EXISTS (
                      SELECT 1 FROM fuzz_pilot.task_runs t
                      WHERE t.session_id = s.session_id AND t.position = 1
                        AND t.status IN ('ready', 'active')
                  )
                  AND EXISTS (
                      SELECT 1 FROM fuzz_pilot.task_runs t
                      WHERE t.session_id = s.session_id AND t.position = 2
                        AND t.status = 'locked'
                  )
                FOR UPDATE OF s
            ),
            invalidated AS (
                UPDATE fuzz_pilot.auth_sessions AS a
                SET revoked_at = now()
                WHERE a.session_id IN (SELECT session_id FROM eligible)
                  AND a.revoked_at IS NULL
                RETURNING a.auth_session_id
            ),
            activated AS (
                UPDATE fuzz_pilot.study_sessions AS s
                SET status = 'active', started_at = COALESCE(s.started_at, now())
                FROM eligible AS e
                WHERE s.session_id = e.session_id
                RETURNING s.session_id
            )
            INSERT INTO fuzz_pilot.auth_sessions (session_id, secret_sha256, expires_at)
            SELECT a.session_id, :'digest', now() + make_interval(mins => :'minutes'::int)
            FROM activated AS a
            RETURNING auth_session_id::text, session_id::text;
            COMMIT;
        """, variables={"pid": pid, "iid": iid, "container": CONTAINER_NAME,
                       "digest": digest, "minutes": str(minutes)})
        rows = [line for line in response.splitlines() if len(line.split("|")) == 2]
        if len(rows) != 1:
            raise RuntimeError("Database did not confirm exactly one issued auth session; inspect DB before retrying")
        os.replace(tmp_path, cookie_path)
        os.chmod(cookie_path, 0o600)
        print(f"Test auth session created for participant {pid}")
        print(f"Auth session ID: {rows[0].split('|')[0]}")
        print(f"Valid for up to {minutes} minutes; prior test credentials revoked")
        print(f"Private curl cookie file: {cookie_path}")
        print("Secret not printed. This is NOT a tester enrollment/login link.")
    finally:
        tmp_path.unlink(missing_ok=True)


def revoke(pid, iid):
    output = psql(r"""
        UPDATE fuzz_pilot.auth_sessions AS a
        SET revoked_at = now()
        WHERE a.revoked_at IS NULL
          AND a.session_id IN (
              SELECT s.session_id FROM fuzz_pilot.study_sessions s
              WHERE s.participant_id = :'pid'
                AND s.instance_id = :'iid'
                AND s.instance_name = :'container'
                AND s.study_phase = 'pilot1'
          )
        RETURNING auth_session_id::text;
    """, variables={"pid": pid, "iid": iid, "container": CONTAINER_NAME})
    cookie_path = private_dir() / f"{pid}.cookies"
    cookie_path.unlink(missing_ok=True)
    print(f"Revoked {len(output.splitlines()) if output else 0} test credential(s); local cookie file deleted")
    print("Study session/task status unchanged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--participant-id", required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--apply", action="store_true", help="Issue a real local-only test credential")
    modes.add_argument("--revoke", action="store_true", help="Revoke credentials and delete local cookie file")
    parser.add_argument("--minutes", type=int, default=30)
    args = parser.parse_args()
    if not PID_RE.fullmatch(args.participant_id):
        parser.error("Participant ID must be 24 lowercase hexadecimal characters")
    if not 5 <= args.minutes <= 120:
        parser.error("--minutes must be between 5 and 120")
    iid = inspect_instance()
    session_id, status, first, second = find_session(args.participant_id, iid)
    print(f"Session {session_id} | container {iid} | session {status} | tasks {first}, {second}")
    if args.revoke:
        revoke(args.participant_id, iid)
    elif args.apply:
        issue(args.participant_id, iid, args.minutes)
    else:
        print("DRY RUN: no changes. Add --apply to create a short-lived local test credential.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, IndexError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
