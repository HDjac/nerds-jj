#!/usr/bin/env python3
"""R2D.4: read-only Pilot 1 fuzzer outcome evidence check.

Runs the existing importer parser WITHOUT --apply, then reports only aggregate
recognized/uncertain outcomes and completed Bash-command exit statuses. No raw
terminal text, command text, participant identifiers, paths or code is printed.
No PostgreSQL rows or archive files are changed.
"""
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import UUID

from pilot1_auto_ingest import (
    authoritative_task_recording_floor, archived_tag_files,
    read_tag, completed_commands, read_campaigns,
)

LIVE = "nerds-pilot1-browser-r1-test"


def query(sql):
    proc = subprocess.run(
        ["docker", "exec", "-u", "postgres", "devob-db-1",
         "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
         "-d", "notebook", "-c", sql],
        capture_output=True, text=True, timeout=35)
    if proc.returncode:
        raise RuntimeError("Read-only database query failed: " + proc.stderr[-400:])
    return proc.stdout.strip()


def active_task():
    proc = subprocess.run(
        ["docker", "inspect", "-f", "{{.Id}}", LIVE],
        capture_output=True, text=True, timeout=15)
    if proc.returncode or not re.fullmatch(r"[a-f0-9]{64}", proc.stdout.strip()):
        raise RuntimeError("Current participant container cannot be verified")
    instance = proc.stdout.strip()[:12]
    rows = query(
        "SELECT COALESCE(json_agg(row_to_json(r)),'[]'::json)::text FROM "
        "(SELECT s.session_id::text, t.task_run_id::text,t.position,t.status "
        "FROM fuzz_pilot.study_sessions s "
        "JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id "
        f"WHERE s.instance_id='{instance}' AND s.status='active' "
        "AND t.status IN ('ready','active') ORDER BY t.position) r;")
    data = json.loads(rows)
    if len(data) != 1:
        raise RuntimeError("Expected exactly one active/ready participant task")
    item = data[0]
    return str(UUID(item["session_id"])), str(UUID(item["task_run_id"])), item["position"]


def main():
    session, task, position = active_task()
    base = Path.home() / "nerds-pilot-backups" / "cli"
    folder = base / session / task
    if (base.is_symlink() or folder.is_symlink() or
            not folder.is_dir()):
        raise RuntimeError("Task command archive is missing or unsafe")
    floor = authoritative_task_recording_floor(session, task)
    tags = [tag for tag in archived_tag_files(folder)
            if floor is None or tag.split("-", 1)[0] >= floor]

    fuzzer_commands = 0
    outcomes = Counter()
    exits = Counter()
    deferred = Counter()
    parse_errors = 0
    for tag in tags:
        try:
            _, _, jsonl = read_tag(folder, tag)
            commands = completed_commands(jsonl, tag)
            fuzzer_commands += len(commands)
            for entry, _ in commands:
                status = entry["exit_status"]
                exits["exit_zero" if status == 0 else
                      "exit_130" if status == 130 else
                      "exit_143" if status == 143 else
                      "other_nonzero"] += 1
            verified, uncertain = read_campaigns(folder, tag, task)
            outcomes.update(row["status"] for row in verified)
            for line in uncertain:
                if "no verified DONE/ASan outcome" in line:
                    deferred["no_verified_outcome"] += 1
                elif "only" in line and "INITED" in line:
                    deferred["missing_inited"] += 1
                elif "invocation echo" in line:
                    deferred["ambiguous_command_echo"] += 1
                elif "timing pending" in line:
                    deferred["transcript_timing_pending"] += 1
                elif "ASan" in line:
                    deferred["asan_evidence_incomplete"] += 1
                else:
                    deferred["other_requires_review"] += 1
        except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
            parse_errors += 1

    summary = query(
        "SELECT COALESCE(json_object_agg(status, n)::text, '{}') FROM "
        "(SELECT status, count(*) AS n FROM fuzz_pilot.campaigns "
        f"WHERE task_run_id='{task}'::uuid GROUP BY status) stats;")
    print("READ-ONLY FUZZER OUTCOME EVIDENCE")
    print(f"Active task position: {position}; eligible terminal sessions: {len(tags)}")
    print(f"Completed direct fuzz commands in structured archive: {fuzzer_commands}")
    for key in ("exit_zero", "exit_130", "exit_143", "other_nonzero"):
        print(f"  {key}: {exits[key]}")
    for key in ("completed", "crashed", "stopped"):
        print(f"Parser recognizes {key}: {outcomes[key]}")
    for key in ("no_verified_outcome", "missing_inited",
                "ambiguous_command_echo", "transcript_timing_pending",
                "asan_evidence_incomplete", "other_requires_review"):
        print(f"Deferred {key}: {deferred[key]}")
    print(f"Sessions with parser errors: {parse_errors}")
    print("Database campaigns by status:", summary)
    print("No database or archive changes were made.")
    print("NOTE: nonzero shell exit alone does not prove a participant interruption.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, TypeError,
            json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print("STOP:", exc, file=sys.stderr)
        sys.exit(1)
