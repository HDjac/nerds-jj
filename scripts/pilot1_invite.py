#!/usr/bin/env python3
"""Operator-only Pilot 1 invitation generation. No participant-facing privileges.

Run from trusted WSL host with Docker CLI access; tokens are not stored in Git,
PostgreSQL, or Docker command arguments. URL fragments stay out of HTTP requests.

    python3 scripts/pilot1_invite.py --participant-id PID
    python3 scripts/pilot1_invite.py --participant-id PID --apply
"""
import argparse
import hashlib
import json
import re
import secrets
import subprocess
import sys
from urllib.parse import urlsplit

DB_CONTAINER = "devob-db-1"
DB_NAME = "notebook"
INSTANCE_IMAGE = "devob_instance:cli-pilot-protected"
PID_RE = re.compile(r"[0-9a-f]{24}\Z")
I_ID_RE = re.compile(r"[0-9a-f]{12}\Z")


def run(argv, stdin=None):
    p = subprocess.run(argv, input=stdin, text=True, capture_output=True, check=False)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or "Command failed")
    return p.stdout.strip()


def psql(sql, variables=None):
    argv = ["docker", "exec", "-i", "-u", "postgres", DB_CONTAINER,
            "psql", "-X", "-qAt", "-F", "|", "-v", "ON_ERROR_STOP=1"]
    for key, val in (variables or {}).items():
        argv.extend(["-v", f"{key}={val}"])
    argv.extend(["-d", DB_NAME])
    return run(argv, sql)


def read_target(pid):
    rows = psql(r"""
        SELECT s.session_id::text, s.status, s.instance_name, s.instance_id,
               t1.task_code, t1.status, t2.task_code, t2.status,
               t1.task_run_id::text, t2.task_run_id::text
        FROM fuzz_pilot.study_sessions s
        JOIN fuzz_pilot.participants p ON p.participant_id = s.participant_id
        JOIN fuzz_pilot.task_runs t1 ON t1.session_id = s.session_id AND t1.position = 1
        JOIN fuzz_pilot.task_runs t2 ON t2.session_id = s.session_id AND t2.position = 2
        WHERE s.participant_id = :'pid'
          AND s.study_phase = 'pilot1' AND s.enrollment_method = 'manual'
          AND s.attempt_number = 1 AND p.withdrawn_at IS NULL;
    """, {"pid": pid}).splitlines()
    if len(rows) != 1:
        raise RuntimeError("Expected exactly one enrolled Pilot 1 participant")
    bits = rows[0].split("|")
    if len(bits) != 10:
        raise RuntimeError("Unexpected database response")
    session, status, name, iid, first, first_status, second, second_status, first_id, second_id = bits
    if (status not in ("assigned", "active")
            or not ((first_status in ("ready", "active") and second_status == "locked")
                    or (first_status in ("completed", "skipped") and second_status in ("ready", "active")))
            or first == second or first not in ("dense_v2", "lowyield_v1")
            or not I_ID_RE.fullmatch(iid)
            or not re.fullmatch(r"nerds-pilot1-[a-z0-9-]+", name)):
        raise RuntimeError("Participant is not ready for a Pilot 1 invitation")
    obj = json.loads(run(["docker", "inspect", name]))[0]
    if (not obj["State"]["Running"] or obj["Id"][:12] != iid
            or obj["Config"]["Image"] != INSTANCE_IMAGE
            or obj["Config"].get("User") != "user"
            or obj["Config"].get("Labels", {}).get("nerds.study") != "pilot1"
            or "devob_instances" not in obj["NetworkSettings"]["Networks"]):
        raise RuntimeError("Database container assignment no longer matches Docker")
    return session, name, iid, first, first_status, second, second_status, status, first_id, second_id



def verify_participant_runtime(name, task, position, task_run_id):
    """Refuse invitations to participant desktops that cannot start their CLI."""
    from uuid import UUID
    if task not in ('dense_v2', 'lowyield_v1') or position not in (1, 2):
        raise RuntimeError('Invalid released task metadata')
    if str(UUID(task_run_id)) != task_run_id:
        raise RuntimeError('Invalid task-run UUID')
    remote = "\nimport json, os, re, stat, subprocess, sys, urllib.request\nexpected_code, expected_position, expected_id = sys.argv[1:]\nmetadata = '/opt/nerds/released-reference/active-task.json'\nwith open(metadata, encoding='utf-8') as fp:\n    obj = json.load(fp)\nif not (obj.get('task_code') == expected_code and\n        obj.get('position') == int(expected_position) and\n        obj.get('task_run_id') == expected_id and\n        obj.get('status') in ('ready', 'active')):\n    raise SystemExit('STOP: Active task metadata does not match PostgreSQL')\nif not os.path.isfile('/home/user/fuzz-study/work/Makefile'):\n    raise SystemExit('STOP: Fuzzing workspace is missing')\nrun = '/home/user/services/xterm/run'\nif not (os.path.isfile(run) and os.access(run, os.X_OK)):\n    raise SystemExit('STOP: xterm run script is not executable')\nfor service in ('vnc', 'novnc', 'xterm', 'firefox', 'api'):\n    result = subprocess.run(['sv', 'status', '/home/user/services/' + service],\n                            capture_output=True, text=True, timeout=8)\n    if result.returncode != 0 or not result.stdout.startswith('run:'):\n        raise SystemExit('STOP: '+service+' service is not running: '+result.stdout.strip())\nenv = dict(os.environ, DISPLAY=':1', XAUTHORITY='/home/user/.Xauthority')\nwindows = subprocess.run(['wmctrl', '-lx'], env=env,\n                         capture_output=True, text=True, timeout=8)\nif windows.returncode != 0 or 'xterm.xterm' not in windows.stdout.lower():\n    raise SystemExit('STOP: CLI window is not available on desktop')\nwith urllib.request.urlopen('http://127.0.0.1:60000/api/tasks', timeout=8) as reply:\n    data = json.load(reply)\nif (data.get('mode') != 'pilot1' or len(data.get('tasks', [])) != 1 or\n        data['tasks'][0].get('task_code') != expected_code):\n    raise SystemExit('STOP: Participant task API is not ready')\nprint('PASS: Participant desktop, CLI and task API are ready')\n"
    run(['docker', 'exec', name, 'python3', '-c', remote,
         task, str(position), task_run_id])

def apply_invite(pid, digest, minutes, iid):
    # Lock the study session while invalidating older unused invitations.
    # The token hash is interpolated with psql's SQL-safe quoted variables.
    rows = psql(r"""
        BEGIN;
        SELECT s.session_id
        FROM fuzz_pilot.study_sessions AS s
        WHERE s.participant_id = :'pid' AND s.instance_id = :'iid'
          AND s.study_phase = 'pilot1' AND s.status IN ('assigned', 'active')
        FOR UPDATE;

        UPDATE fuzz_pilot.invitation_tokens AS i
        SET revoked_at = now()
        WHERE i.session_id IN (
            SELECT s.session_id FROM fuzz_pilot.study_sessions AS s
            WHERE s.participant_id = :'pid' AND s.instance_id = :'iid'
        ) AND i.redeemed_at IS NULL AND i.revoked_at IS NULL;

        INSERT INTO fuzz_pilot.invitation_tokens(session_id, token_sha256, expires_at)
        SELECT s.session_id, :'digest', now() + make_interval(mins => :'minutes'::int)
        FROM fuzz_pilot.study_sessions s
        WHERE s.participant_id = :'pid' AND s.instance_id = :'iid'
          AND s.study_phase = 'pilot1' AND s.enrollment_method = 'manual'
          AND s.status IN ('assigned', 'active')
          AND (
              (EXISTS (SELECT 1 FROM fuzz_pilot.task_runs t
                       WHERE t.session_id = s.session_id AND t.position = 1
                         AND t.status IN ('ready', 'active'))
               AND EXISTS (SELECT 1 FROM fuzz_pilot.task_runs t
                           WHERE t.session_id = s.session_id AND t.position = 2
                             AND t.status = 'locked'))
              OR
              (EXISTS (SELECT 1 FROM fuzz_pilot.task_runs t
                       WHERE t.session_id = s.session_id AND t.position = 1
                         AND t.status IN ('completed', 'skipped'))
               AND EXISTS (SELECT 1 FROM fuzz_pilot.task_runs t
                           WHERE t.session_id = s.session_id AND t.position = 2
                             AND t.status IN ('ready', 'active')))
          )
        RETURNING invitation_id::text;
        COMMIT;
    """, {"pid": pid, "iid": iid, "digest": digest, "minutes": str(minutes)})
    uuids = re.findall(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", rows)
    # First UUID is session_id from SELECT, last is new invitation ID.
    if len(uuids) != 2:
        raise RuntimeError("Invitation insertion was not confirmed: inspect database before retrying")
    return uuids[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--participant-id", required=True)
    parser.add_argument("--minutes", type=int, default=15, help="Invitation TTL, 5..30 (default 15)")
    parser.add_argument("--base-url", default="https://127.0.0.1:18443",
                        help="Private test proxy base URL")
    parser.add_argument("--apply", action="store_true", help="Create invitation and print single-use link")
    args = parser.parse_args()
    if not PID_RE.fullmatch(args.participant_id):
        parser.error("participant ID must be 24 lowercase hexadecimal characters")
    if args.minutes not in range(5, 31):
        parser.error("--minutes must be 5..30")
    base = urlsplit(args.base_url)
    if (base.scheme != "https" or base.hostname not in ("127.0.0.1", "localhost")
            or base.username or base.password or base.path not in ("", "/")
            or base.query or base.fragment or base.port is None):
        parser.error("Pilot 1 local test base URL must be https://127.0.0.1:<port>")
    session, name, iid, first, first_status, second, second_status, status, first_id, second_id = read_target(args.participant_id)
    if first_status in ('ready', 'active'):
        released_code, released_position, released_id = first, 1, first_id
    else:
        released_code, released_position, released_id = second, 2, second_id
    verify_participant_runtime(name, released_code, released_position, released_id)
    print(f"Participant: {args.participant_id}\nSession: {session} [{status}]\n"
          f"Container: {name} ({iid})\nTasks: {first} ready, {second} locked")
    if not args.apply:
        print("DRY RUN: no invitation created. Add --apply.")
        return
    token = secrets.token_hex(32)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    inv_id = apply_invite(args.participant_id, digest, args.minutes, iid)
    print(f"Invitation created: {inv_id}\nExpires in: {args.minutes} minutes")
    print("SENSITIVE one-time URL; deliver privately, do not paste into chat/logs:")
    print(args.base_url.rstrip("/") + "/pilot1-login.php#" + token)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
