#!/usr/bin/env python3
"""R2D.4 read-only CLI command-to-archive reconciliation.

For the existing Pilot 1 container, compare archived complete structured Bash
commands with PostgreSQL CLI events by stable event key, source-line SHA256 and
non-sensitive metadata. Check the existence of matching terminal .out/.timing
archives. Never print or change command text, transcripts, or participant IDs.

This checks archived-to-ingested completeness; it cannot prove capture of
unlogged shell activity or validate the semantics of all terminal output.

Usage: cd ~/nerds-r2d && python3 scripts/r2d4_cli_archive_audit.py
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
from uuid import UUID

from pilot1_ingest_cli_events import parse_record, FILE_RE

LIVE = "nerds-pilot1-browser-r1-test"
CONTAINER_ID = re.compile(r"^[a-f0-9]{64}$")
MAX_COMMANDS = 250000


def shell(*argv):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=45)
    if result.returncode:
        raise RuntimeError("Command failed: " + " ".join(argv[:5]) + "\n"
                           + (result.stderr or result.stdout)[-500:])
    return result.stdout.strip()


def db_rows(instance):
    sql = """
BEGIN TRANSACTION READ ONLY;
SELECT COALESCE(json_agg(row_to_json(q)), '[]'::json)::text
FROM (
 SELECT s.session_id::text, t.task_run_id::text, t.position, t.status,
        CASE WHEN t.position = 2 THEN (
          SELECT to_char(release.received_at AT TIME ZONE 'UTC',
                 'YYYYMMDD"T"HH24MISS"Z"')
          FROM fuzz_pilot.events release
          WHERE release.session_id=s.session_id
            AND release.task_run_id=t.task_run_id
            AND release.event_type='task_released'
            AND release.event_key='lifecycle:2:released'
          ORDER BY release.event_id LIMIT 1
        ) ELSE NULL END AS release_tag_floor,
        e.event_key, e.payload->>'source_sha256' AS source_sha256,
        e.payload->>'source_file' AS source_file,
        e.payload->>'source_line' AS source_line,
        e.payload->>'terminal_session' AS terminal_session,
        e.payload->>'sequence' AS sequence,
        e.payload->>'exit_status' AS exit_status
 FROM fuzz_pilot.study_sessions s
 JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
 LEFT JOIN fuzz_pilot.events e
   ON e.task_run_id=t.task_run_id
  AND e.session_id=s.session_id
  AND e.event_source='cli'
  AND e.event_type='bash_command_completed'
 WHERE s.instance_id='""" + instance + """'
 ORDER BY t.position, e.event_id
) q;
COMMIT;
"""
    raw = shell("docker", "exec", "-u", "postgres", "devob-db-1",
                "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
                "-d", "notebook", "-c", sql)
    # psql prints transaction tags alongside the JSON line.
    lines = [ln for ln in raw.splitlines() if ln.strip().startswith("[")]
    if len(lines) != 1:
        raise RuntimeError("Expected one read-only JSON result")
    data = json.loads(lines[0])
    if not isinstance(data, list):
        raise RuntimeError("Unexpected PostgreSQL result")
    return data


def normal_file(path):
    if path.is_symlink():
        raise ValueError("Symlinked archive file")
    stat_result = path.stat()
    if not stat.S_ISREG(stat_result.st_mode):
        raise ValueError("Non-regular archive file")
    return stat_result.st_size


def read_archive(folder):
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Command archive directory is missing or symlinked")
    records = {}
    tag_counts = defaultdict(int)
    incomplete_lines = 0
    for path in sorted(folder.iterdir()):
        if not FILE_RE.fullmatch(path.name):
            continue
        normal_file(path)
        tag = FILE_RE.fullmatch(path.name).group(1)
        with path.open("rb") as stream:
            for line_num, raw in enumerate(stream, 1):
                if not raw.endswith(b"\n"):
                    incomplete_lines += 1
                    break
                result = parse_record(raw, path.name, line_num, tag)
                if result["event_key"] in records:
                    raise ValueError("Repeated archive event key")
                records[result["event_key"]] = result
                tag_counts[tag] += 1
                if len(records) > MAX_COMMANDS:
                    raise ValueError("Too many command records in archive")
    missing_transcripts = 0
    missing_timing = 0
    for tag in tag_counts:
        for suffix in (".out", ".timing"):
            file = folder / (tag + suffix)
            try:
                size = normal_file(file)
                if size == 0:
                    raise ValueError("Empty recording")
            except (OSError, ValueError):
                if suffix == ".out":
                    missing_transcripts += 1
                else:
                    missing_timing += 1
    return records, incomplete_lines, missing_transcripts, missing_timing, len(tag_counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path,
                        default=Path.home() / "nerds-pilot-backups" / "cli")
    args = parser.parse_args()
    cid = shell("docker", "inspect", "-f", "{{.Id}}", LIVE)
    if not CONTAINER_ID.fullmatch(cid):
        raise RuntimeError("Existing Pilot 1 participant not identified")
    rows = db_rows(cid[:12])
    if not rows:
        raise RuntimeError("Current participant has no task records")
    tasks = defaultdict(list)
    for row in rows:
        position = row["position"]
        if position not in (1, 2):
            raise RuntimeError("Unexpected task position")
        tasks[position].append(row)

    # Compare any Task 2 archival copies from pre-release terminal sessions
    # to the actual Task 1 DB records before treating them as safely excluded.
    first_task_db = {
        row["event_key"]: row
        for row in tasks.get(1, [])
        if row.get("event_key") is not None
    }
    grand = defaultdict(int)
    print("READ-ONLY CLI COMMAND/ARCHIVE RECONCILIATION")
    print("No command text, transcripts, session IDs or hashes are shown.")
    for position in sorted(tasks):
        entries = tasks[position]
        first = entries[0]
        session = str(UUID(first["session_id"]))
        task = str(UUID(first["task_run_id"]))
        if any(e["session_id"] != session or e["task_run_id"] != task
               for e in entries):
            raise RuntimeError("Inconsistent task identifiers")
        root = args.archive_root.expanduser()
        folder = root / session / task
        try:
            if root.is_symlink() or not root.is_dir():
                raise ValueError("Command archive root is missing or symlinked")
            if (root / session).is_symlink() or folder.is_symlink():
                raise ValueError("Symlinked command archive path")
            archived, incomplete, missing_out, missing_timing, tags = read_archive(folder)
        except (ValueError, OSError) as err:
            print(f"Task {position}: ARCHIVE ERROR: {err}")
            grand["archive_errors"] += 1
            continue

        db_commands = {e["event_key"]: e for e in entries if e["event_key"] is not None}
        # Match the *trusted release boundary* used by pilot1_auto_ingest.py,
        # not the presence of all files copied from the shared terminal
        # recording directory into this task's archive.
        excluded = {}
        eligible = archived
        matched_prior_task = 0
        unmatched_prior_task = 0
        excluded_db_entries = 0
        release_floor = first.get("release_tag_floor")
        if position == 2:
            if not isinstance(release_floor, str) or not re.fullmatch(
                    r"20[0-9]{6}T[0-9]{6}Z", release_floor):
                raise RuntimeError("Task 2 has no verified DB release boundary")
            excluded = {
                key: event for key, event in archived.items()
                if event["payload"]["terminal_session"].split("-", 1)[0] < release_floor
            }
            eligible = {key: event for key, event in archived.items()
                        if key not in excluded}
            for key, event in excluded.items():
                prior = first_task_db.get(key)
                if prior is not None and prior.get("source_sha256") == (
                        event["payload"]["source_sha256"]):
                    matched_prior_task += 1
                else:
                    unmatched_prior_task += 1
            excluded_db_entries = len(set(db_commands) & set(excluded))
        db_keys, archive_keys = set(db_commands), set(eligible)
        common = db_keys & archive_keys
        mismatches = 0
        for key in common:
            db = db_commands[key]
            item = eligible[key]
            p = item["payload"]
            expected = {
                "source_sha256": p["source_sha256"],
                "source_file": p["source_file"],
                "source_line": str(p["source_line"]),
                "terminal_session": p["terminal_session"],
                "sequence": str(p["sequence"]),
                "exit_status": str(p["exit_status"]),
            }
            if any(db.get(k) != v for k, v in expected.items()):
                mismatches += 1

        missing_db = len(archive_keys - db_keys)
        missing_archive = len(db_keys - archive_keys)
        print(f"Task {position} ({first['status']}):")
        print(f"  DB commands: {len(db_keys)}; archived complete commands: {len(archived)}")
        if position == 2:
            print(f"  Archive commands before Task 2 release (excluded): {len(excluded)}")
            print(f"  Pre-release copies matching Task 1 DB and SHA256: {matched_prior_task}")
            print(f"  Unmatched pre-release copies (review): {unmatched_prior_task}")
            print(f"  Pre-release commands wrongly in Task 2 DB (review): {excluded_db_entries}")
            print(f"  Commands eligible for Task 2 ingestion: {len(eligible)}")
        print(f"  Matches: {len(common)-mismatches}; metadata/hash mismatches: {mismatches}")
        print(f"  Eligible archive commands not yet in DB: {missing_db}; DB without eligible archive: {missing_archive}")
        print(f"  Terminal sessions: {tags}; missing output archives: {missing_out}; missing timing archives: {missing_timing}")
        print(f"  Incomplete trailing JSONL lines: {incomplete}")
        for field, value in (
            ("excluded_pre_release", len(excluded)),
            ("verified_prior_task_copies", matched_prior_task),
            ("unmatched_prior_task", unmatched_prior_task),
            ("wrongly_task2_db", excluded_db_entries),
            ("matched", len(common)-mismatches),
            ("mismatched", mismatches),
            ("not_in_db", missing_db),
            ("not_in_archive", missing_archive),
            ("missing_out", missing_out),
            ("missing_timing", missing_timing),
            ("incomplete_lines", incomplete),
        ):
            grand[field] += value
    print("SUMMARY:", ", ".join(f"{k}={v}" for k, v in sorted(grand.items())))
    if (grand["archive_errors"] or grand["mismatched"] or
            grand["unmatched_prior_task"] or grand["wrongly_task2_db"] or
            grand["not_in_archive"] or grand["missing_out"] or grand["missing_timing"]):
        print("REVIEW REQUIRED: archived/ingested command evidence is incomplete or inconsistent.")
        return 1
    elif grand["not_in_db"] or grand["incomplete_lines"]:
        print("PENDING: some archived entries may still be awaiting collector ingestion.")
    else:
        print("PASS: archived complete Bash commands match stored DB events.")
    print("The Task 2 filter uses the same trusted release-tag floor as the host importer.")
    print("Scope: structured Bash commands only; unrelated shell subprocesses may not be logged.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError,
            subprocess.TimeoutExpired) as exc:
        print("STOP:", exc, file=sys.stderr)
        sys.exit(1)
