#!/usr/bin/env python3
"""Host-side Pilot 1 importer for one verified LibFuzzer ASan crash.

Requires the archived `script` terminal transcript, timing, completed Bash command,
and the crash input in the assigned participant container. Stores the binary artifact
outside Docker, then transactionally links it to a PostgreSQL campaign + event.

This is a constrained Pilot 1 importer for direct fuzz_[abc] commands with one
uniquely attributable sanitizer crash per requested harness per recording. It
fails closed on ambiguous evidence. It does NOT establish reproducibility or
capture every possible shell/process behavior.
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
from uuid import UUID, uuid5

from pilot1_import_campaign_multi import (
    CONTAINER_PATTERN, TAG_PATTERN, MAX_TRANSCRIPT_BYTES,
    MAX_TIMING_BYTES, MAX_JSONL_BYTES, read_archive_file,
    time_at_output_offset, parse_metrics, run, verify_assignment,
)

FUZZ_COMMAND = re.compile(r"^\s*(?:\./|/home/user/fuzz-study/work/)fuzz_([abc])(?:\s|$)")
METRIC = re.compile(rb"#(?P<runs>\d+)\s+(?P<kind>INITED|NEW|REDUCE|pulse|RELOAD|DONE)\b(?P<details>[^\r\n]*)")
ASAN = re.compile(rb"ERROR: AddressSanitizer:\s+(?P<type>[a-z0-9_-]+)")
ARTIFACT = re.compile(r"^crash-[a-f0-9]{40}$")


def find_command(jsonl, tag, harness):
    matches = []
    lines = jsonl.splitlines(keepends=True)
    for number, raw in enumerate(lines, 1):
        if not raw.endswith(b"\n") and number == len(lines):
            break
        try:
            entry = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"Invalid command record line {number}") from exc
        if not isinstance(entry, dict) or entry.get("terminal_session") != tag:
            raise ValueError(f"Invalid terminal session in command line {number}")
        command = entry.get("command")
        match = FUZZ_COMMAND.match(command) if isinstance(command, str) else None
        if match is None or match.group(1) != harness:
            continue
        if type(entry.get("sequence")) is not int or entry["sequence"] < 1:
            raise ValueError("Missing command sequence")
        if type(entry.get("exit_status")) is not int:
            raise ValueError("Missing command exit status")
        if not isinstance(entry.get("occurred_at"), str):
            raise ValueError("Missing command timestamp")
        matches.append(entry)
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one fuzz_{harness} command in recording; found {len(matches)}")
    if matches[0]["exit_status"] == 0:
        raise ValueError("Crash command has successful exit status; manual review required")
    return matches[0]


def parse_crash(archive, tag, harness, task_id):
    output = read_archive_file(archive, tag, ".out", MAX_TRANSCRIPT_BYTES)
    timing = read_archive_file(archive, tag, ".timing", MAX_TIMING_BYTES)
    jsonl = read_archive_file(archive, tag, ".commands.jsonl", MAX_JSONL_BYTES)
    command = find_command(jsonl, tag, harness)

    reports = list(ASAN.finditer(output))
    if len(reports) != 1:
        raise ValueError(f"Expected exactly one ASan report in transcript, found {len(reports)}")
    report = reports[0]
    asan_type = report.group("type").decode("ascii")
    if asan_type != "heap-buffer-overflow":
        raise ValueError(f"Unexpected sanitizer finding: {asan_type}; needs separate review")

    initials = [m for m in METRIC.finditer(output)
                if m.group("kind") == b"INITED" and m.start() < report.start()]
    if not initials:
        raise ValueError("No preceding LibFuzzer INITED record")
    initial = initials[-1]
    preceding_done = [m for m in METRIC.finditer(output)
                      if m.group("kind") == b"DONE" and m.start() < initial.start()]
    before_start = preceding_done[-1].end() if preceding_done else 0
    segment = output[before_start:initial.start()]
    echo = command["command"].encode("utf-8")
    # Xterm/Bash echo can include a printable character that was subsequently erased.
    normalized = re.sub(rb"[\x20-\x7e]\x08 \x08", b"", segment)
    if echo not in segment and echo not in normalized:
        raise ValueError("Fuzz invocation not present between preceding DONE and INITED")
    if len([m for m in METRIC.finditer(output[before_start:initial.start()])
            if m.group("kind") == b"INITED"]) != 0:
        raise ValueError("Ambiguous additional INITED record")

    between = output[initial.start():report.start()]
    if any(m.group("kind") == b"DONE" for m in METRIC.finditer(between)):
        raise ValueError("DONE appeared before sanitizer report; not an interrupted campaign")
    metric_lines = list(METRIC.finditer(between))
    if not metric_lines or metric_lines[0].group("kind") != b"INITED":
        raise ValueError("Missing INITED metrics for crash campaign")
    last = metric_lines[-1]
    initial_metrics = parse_metrics(metric_lines[0].group("details"))
    initial_metrics["executions"] = int(metric_lines[0].group("runs"))
    last_metrics = parse_metrics(last.group("details"))
    last_metrics["executions"] = int(last.group("runs"))
    last_metrics["observation_kind"] = last.group("kind").decode("ascii")
    last_metrics["is_final_fuzzer_metric"] = False
    if last_metrics["executions"] < initial_metrics["executions"]:
        raise ValueError("Observed execution count decreased")

    # Verify a summary and relevant program stack frame after the sanitizer report.
    suffix = output[report.start():]
    if b"SUMMARY: AddressSanitizer: heap-buffer-overflow" not in suffix:
        raise ValueError("ASan report lacks a matching SUMMARY line")
    function = re.search(rb"in (bridge_unpack_record)\s+[^\r\n]*src/codec\.c:(\d+)", suffix)
    if function is None:
        raise ValueError("Expected target-code stack frame is missing")
    write = re.search(rb"WRITE of size (\d+)", suffix)
    if write is None:
        raise ValueError("Missing ASan write-size evidence")

    started = time_at_output_offset(timing, tag, initial.start())
    ended = datetime.fromisoformat(command["occurred_at"].replace("Z", "+00:00"))
    if ended.tzinfo is None or ended < started:
        raise ValueError("Inconsistent command and transcript timestamps")
    campaign_id = str(uuid5(UUID(task_id), f"libfuzzer:{tag}:{command['sequence']}"))
    summary = {
        "campaign_id": campaign_id,
        "harness_id": harness,
        "status": "crashed",
        "command_summary": command["command"],
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "config": {
            "terminal_session": tag,
            "recording_file": tag + ".out",
            "command_sequence": command["sequence"],
            "requested_max_total_time_s": int(re.search(r"(?:^|\s)-max_total_time=(\d+)(?:\s|$)", command["command"]).group(1))
                if re.search(r"(?:^|\s)-max_total_time=(\d+)(?:\s|$)", command["command"]) else None,
            "initial_metrics": initial_metrics,
            "capture_method": "bash_command_and_script_output_timing",
            "started_at_estimate": "first_INITED_output_from_script_timing",
            "ended_at_estimate": "bash_command_completed_at_prompt",
            "sanitizer_type": asan_type,
            "write_size_bytes": int(write.group(1)),
            "fault_function": "bridge_unpack_record",
            "fault_source_line": int(function.group(2)),
            "command_exit_status": command["exit_status"],
        },
        "final_metrics": last_metrics,
        "event_key": f"campaign:{tag}:{command['sequence']}",
    }
    return summary


def artifact_source(name):
    if not ARTIFACT.fullmatch(name):
        raise ValueError("Invalid crash artifact name")
    return f"/home/user/fuzz-study/work/{name}"


def archive_crash(container, name, dest):
    source = artifact_source(name)
    remote_digest = run(["docker", "exec", container, "sha256sum", source]).split()[0]
    if not re.fullmatch(r"[a-f0-9]{64}", remote_digest):
        raise ValueError("Invalid source digest")
    if dest.exists():
        if dest.is_symlink() or not dest.is_file():
            raise ValueError("Unsafe existing artifact path")
        local_digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if remote_digest != local_digest:
            raise ValueError("Existing archive artifact differs from container source")
        return local_digest, dest.stat().st_size
    dest.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(dest.parent, 0o700)
    import tempfile
    with tempfile.TemporaryDirectory(prefix=".crash-import-", dir=dest.parent) as tmpdir:
        tmp = Path(tmpdir) / name
        run(["docker", "cp", f"{container}:{source}", str(tmp)])
        if tmp.is_symlink() or not tmp.is_file():
            raise ValueError("Unsafe copied artifact")
        if tmp.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Crash artifact unexpectedly large")
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        if digest != remote_digest:
            raise ValueError("Crash artifact changed during copy; retry")
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    return remote_digest, dest.stat().st_size


def apply(summary, instance, session, task, storage_key, sha, size):
    # Treat source-derived strings as data, not SQL. UUIDs and digest are validated.
    payload = dict(summary)
    payload.update({"storage_key": storage_key, "sha256": sha, "size_bytes": size})
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=True,
                                           separators=(",", ":")).encode()).decode("ascii")
    sql = f"""BEGIN;
DO $verify$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM fuzz_pilot.study_sessions s
   JOIN fuzz_pilot.task_runs t ON t.session_id = s.session_id
   WHERE s.session_id = '{session}'::uuid AND t.task_run_id = '{task}'::uuid
     AND s.instance_id = '{instance}' AND s.status = 'active'
     AND t.status IN ('ready','active') FOR SHARE OF s,t
 ) THEN RAISE EXCEPTION 'Assigned task changed'; END IF;
END $verify$;
WITH d AS (SELECT convert_from(decode('{encoded}','base64'),'UTF8')::jsonb AS j)
INSERT INTO fuzz_pilot.campaigns
 (campaign_id, task_run_id, harness_id, status, command_summary,
  config, final_metrics, started_at, ended_at)
SELECT (j->>'campaign_id')::uuid, '{task}'::uuid, j->>'harness_id',
       j->>'status', j->>'command_summary', j->'config', j->'final_metrics',
       (j->>'started_at')::timestamptz, (j->>'ended_at')::timestamptz
FROM d WHERE true ON CONFLICT (campaign_id) DO NOTHING;
WITH d AS (SELECT convert_from(decode('{encoded}','base64'),'UTF8')::jsonb AS j)
INSERT INTO fuzz_pilot.events
 (session_id, task_run_id, campaign_id, event_type, event_source,
  occurred_at, event_key, payload)
SELECT '{session}'::uuid, '{task}'::uuid, (j->>'campaign_id')::uuid,
 'libfuzzer_campaign_crashed', 'cli', (j->>'ended_at')::timestamptz,
 j->>'event_key', jsonb_build_object(
 'harness_id',j->>'harness_id', 'sanitizer_type', j->'config'->>'sanitizer_type',
 'artifact_sha256', j->>'sha256', 'last_observed_metrics', j->'final_metrics',
 'terminal_session', j->'config'->>'terminal_session')
FROM d WHERE true ON CONFLICT (session_id, event_key) DO NOTHING;
WITH d AS (SELECT convert_from(decode('{encoded}','base64'),'UTF8')::jsonb AS j)
INSERT INTO fuzz_pilot.artifacts
 (task_run_id, campaign_id, artifact_kind, storage_key, sha256, size_bytes)
SELECT '{task}'::uuid, (j->>'campaign_id')::uuid, 'crash',
 j->>'storage_key', j->>'sha256', (j->>'size_bytes')::bigint
FROM d WHERE true ON CONFLICT (storage_key) DO NOTHING;
DO $verify$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM fuzz_pilot.campaigns WHERE campaign_id = '{summary['campaign_id']}'::uuid
     AND task_run_id = '{task}'::uuid AND harness_id = '{summary['harness_id']}' AND status = 'crashed')
 THEN RAISE EXCEPTION 'Campaign conflict'; END IF;
 IF NOT EXISTS (SELECT 1 FROM fuzz_pilot.artifacts WHERE storage_key = '{storage_key}'
     AND task_run_id = '{task}'::uuid AND campaign_id = '{summary['campaign_id']}'::uuid
     AND sha256 = '{sha}' AND size_bytes = {size})
 THEN RAISE EXCEPTION 'Artifact conflict'; END IF;
END $verify$;
COMMIT;
"""
    return run(["docker", "exec", "-i", "-u", "postgres", "devob-db-1",
                "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-d", "notebook",
                "-f", "-"], sql.encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task-run-id", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--harness", choices=["a", "b", "c"], default="c")
    parser.add_argument("--artifact", required=True, help="crash-<40 hex> basename")
    parser.add_argument("--archive-root", type=Path,
                        default=Path.home() / "nerds-pilot-backups")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if not CONTAINER_PATTERN.fullmatch(args.container) or not TAG_PATTERN.fullmatch(args.tag):
            parser.error("Invalid container name or recording tag")
        session, task = str(UUID(args.session_id)), str(UUID(args.task_run_id))
        artifact_source(args.artifact)
        instance = verify_assignment(args.container, session, task)
        root = args.archive_root.expanduser()
        archive = root / "cli" / session / task
        if archive.is_symlink() or not archive.is_dir():
            raise ValueError("Archived CLI recording not available")
        summary = parse_crash(archive, args.tag, args.harness, task)
        dest_rel = Path("artifacts") / session / task / summary["campaign_id"] / args.artifact
        dest = root / dest_rel
        print(f"Verified assignment: {instance}")
        print(f"Crash: harness={args.harness}, type={summary['config']['sanitizer_type']}, "
              f"exit={summary['config']['command_exit_status']}")
        print(f"Last observed metrics: {json.dumps(summary['final_metrics'], sort_keys=True)}")
        print(f"Campaign ID: {summary['campaign_id']}")
        print(f"Crash artifact: {dest}")
        if args.apply:
            digest, size = archive_crash(args.container, args.artifact, dest)
            print(f"Archived {size} bytes; SHA-256={digest}")
            print(apply(summary, instance, session, task, dest_rel.as_posix(), digest, size))
            print("Campaign, crash event and artifact linked; no task status changed")
        else:
            print("DRY RUN: no artifact copied and no database changes")
        return 0
    except (RuntimeError, OSError, ValueError, UnicodeError) as exc:
        print("CRASH IMPORT FAILED:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
