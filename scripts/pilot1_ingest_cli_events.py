#!/usr/bin/env python3
"""Import archived NERDs Bash command JSONL into fuzz_pilot.events.

Host-only Pilot 1 tool. Requires trusted local Docker access; never install
inside a participant container. Defaults to read-only dry run. Use --apply.

The records are participant-originated best-effort observations, not audit proof.
Only complete newline-terminated JSONL records are ingested. Safe to rerun:
(session_id, event_key) is unique in PostgreSQL.
"""

import argparse
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from uuid import UUID

CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
FILE_RE = re.compile(r"^(20[0-9]{6}T[0-9]{6}Z-[0-9]+)\.commands\.jsonl$")
MAX_LINE = 256 * 1024
MAX_COMMAND = 128 * 1024


def run(cmd, *, stdin=None):
    try:
        result = subprocess.run(cmd, input=stdin, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not run {cmd[:3]}: {exc}") from exc
    if result.returncode:
        # Database error messages only; commands are transmitted via stdin.
        err = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"{' '.join(cmd[:3])} failed: {err[-800:]}")
    return result.stdout.decode("utf-8", errors="replace").strip()


def check_mapping(container, session_id, task_run_id):
    full_id = run(["docker", "inspect", "--format", "{{.Id}}", container])
    if not re.fullmatch(r"[0-9a-f]{64}", full_id):
        raise RuntimeError("Could not verify running container ID")
    instance = full_id[:12]
    sql = ("SELECT COUNT(*) FROM fuzz_pilot.study_sessions s "
           "JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id "
           f"WHERE s.session_id='{session_id}'::uuid "
           f"AND t.task_run_id='{task_run_id}'::uuid "
           f"AND s.instance_id='{instance}' "
           "AND s.status='active' AND t.status IN ('ready','active');")
    found = run(["docker", "exec", "-u", "postgres", "devob-db-1",
                 "psql", "-X", "-At", "-d", "notebook", "-c", sql])
    if found != "1":
        raise RuntimeError("Session/task is not active and assigned to this container")
    return instance


def parse_record(raw, filename, line_number, tag):
    if len(raw) > MAX_LINE:
        raise ValueError(f"{filename}:{line_number}: overlong JSONL line")
    try:
        record = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"{filename}:{line_number}: invalid JSON") from exc
    if not isinstance(record, dict):
        raise ValueError(f"{filename}:{line_number}: expected object")
    required = {
        "schema_version": 1,
        "event_type": "bash_command_completed",
        "capture_method": "bash_history_prompt_command",
        "terminal_session": tag,
    }
    if any(type(record.get(k)) is not type(v) or record.get(k) != v
           for k, v in required.items()):
        raise ValueError(f"{filename}:{line_number}: invalid command schema")
    if (type(record.get("sequence")) is not int or record["sequence"] < 1 or
            type(record.get("shell_pid")) is not int or record["shell_pid"] < 1 or
            type(record.get("exit_status")) is not int or not 0 <= record["exit_status"] <= 255):
        raise ValueError(f"{filename}:{line_number}: invalid command metadata")
    command = record.get("command")
    if not isinstance(command, str) or len(command.encode("utf-8")) > MAX_COMMAND:
        raise ValueError(f"{filename}:{line_number}: invalid/overlong command")
    occurred = record.get("occurred_at")
    if not isinstance(occurred, str) or len(occurred) > 64:
        raise ValueError(f"{filename}:{line_number}: missing timestamp")
    try:
        parsed = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Naive timestamp")
    except ValueError as exc:
        raise ValueError(f"{filename}:{line_number}: invalid timestamp") from exc
    # Stable source-position key allows idempotent re-import after interruption.
    event_key = f"cli:{tag}:{line_number}"
    return {
        "event_key": event_key,
        "occurred_at": occurred,
        "payload": {
            "command": command,
            "exit_status": record["exit_status"],
            "capture_method": record["capture_method"],
            "terminal_session": tag,
            "sequence": record["sequence"],
            "shell_pid": record["shell_pid"],
            "source_file": filename,
            "source_line": line_number,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
        },
    }


def archived_rows(archive):
    if archive.is_symlink() or not archive.is_dir():
        raise RuntimeError("Archive must be a real directory")
    for file in sorted(archive.iterdir()):
        match = FILE_RE.fullmatch(file.name)
        if not match:
            continue
        if file.is_symlink() or not stat.S_ISREG(file.stat(follow_symlinks=False).st_mode):
            raise RuntimeError(f"Archive has unsafe recording entry: {file.name}")
        with file.open("rb") as handle:
            for line_number, raw in enumerate(handle, start=1):
                # A collector may be appending this file. Import only records
                # with a complete newline; the next run picks up the remainder.
                if not raw.endswith(b"\n"):
                    break
                yield parse_record(raw, file.name, line_number, match.group(1))


def sql_for_batch(rows, session_id, task_run_id, instance_id):
    # The batch is encoded to prevent participant commands becoming SQL syntax.
    encoded = base64.b64encode(json.dumps(rows, ensure_ascii=True,
                                           separators=(",", ":")).encode()).decode("ascii")
    return f"""BEGIN;
DO $guard$
DECLARE matched INTEGER;
BEGIN
  SELECT COUNT(*) INTO matched FROM (
    SELECT 1 FROM fuzz_pilot.study_sessions s
    JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
    WHERE s.session_id='{session_id}'::uuid
      AND t.task_run_id='{task_run_id}'::uuid
      AND s.instance_id='{instance_id}'
      AND s.status='active' AND t.status IN ('ready','active')
    FOR SHARE OF s,t
  ) eligible;
  IF matched <> 1 THEN
    RAISE EXCEPTION 'Study session/task assignment changed; ingestion denied';
  END IF;
END $guard$;
WITH incoming AS (
  SELECT value AS item
  FROM jsonb_array_elements(
    convert_from(decode('{encoded}', 'base64'), 'UTF8')::jsonb
  ) AS entries(value)
), inserted AS (
  INSERT INTO fuzz_pilot.events
    (session_id, task_run_id, event_type, event_source,
     occurred_at, event_key, payload)
  SELECT '{session_id}'::uuid, '{task_run_id}'::uuid,
         'bash_command_completed', 'cli',
         (item->>'occurred_at')::timestamptz,
         item->>'event_key', item->'payload'
  FROM incoming
  ON CONFLICT (session_id, event_key) DO NOTHING
  RETURNING event_id
)
SELECT COUNT(*) FROM inserted;
COMMIT;
"""


def write_batch(rows, session_id, task_run_id, instance_id):
    sql = sql_for_batch(rows, session_id, task_run_id, instance_id)
    raw = run(["docker", "exec", "-i", "-u", "postgres", "devob-db-1",
               "psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1",
               "-d", "notebook", "-f", "-"], stdin=sql.encode())
    parts = [p.strip() for p in raw.splitlines() if p.strip()]
    try:
        return int(parts[-1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError(f"Unexpected PostgreSQL result: {raw[:200]}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task-run-id", required=True)
    parser.add_argument("--archive-root", type=Path,
                        default=Path.home() / "nerds-pilot-backups" / "cli")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--apply", action="store_true",
                        help="Write events to PostgreSQL (default: dry run)")
    args = parser.parse_args()
    if not CONTAINER_RE.fullmatch(args.container):
        parser.error("Invalid container name")
    if not 1 <= args.batch_size <= 500:
        parser.error("Batch size must be 1..500")
    try:
        session = str(UUID(args.session_id))
        task = str(UUID(args.task_run_id))
        archive = args.archive_root.expanduser() / session / task
        instance = check_mapping(args.container, session, task)
        attempted = inserted = 0
        pending = []
        for event in archived_rows(archive):
            pending.append(event)
            attempted += 1
            if len(pending) >= args.batch_size:
                if args.apply:
                    inserted += write_batch(pending, session, task, instance)
                pending.clear()
        if pending and args.apply:
            inserted += write_batch(pending, session, task, instance)
        print(f"Verified instance: {instance}")
        print(f"Archive: {archive}")
        print(f"Complete structured commands found: {attempted}")
        if args.apply:
            print(f"New PostgreSQL events inserted: {inserted}")
            print(f"Already ingested (or duplicate keys): {attempted - inserted}")
        else:
            print("DRY RUN: no PostgreSQL events added; pass --apply to ingest")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"INGEST FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
