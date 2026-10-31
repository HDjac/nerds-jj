#!/usr/bin/env python3
"""Import one *completed, bounded* LibFuzzer campaign from a NERDs CLI archive.

Pilot 1 host-side prototype: does not run in the participant container.
Requires the normal xterm output, timing, and Bash JSONL recordings.
Correlates exactly one `./fuzz_[abc] -runs=N` command per terminal session
with exactly one INITED/DONE pair. Fails closed if ambiguous. No crashes,
custom harnesses, multi-run terminal sessions, or shell-wrapper detection yet.

Times: started_at estimates first INITED output using `script` output timing;
ended_at uses the Bash completed-command observation. These are not exact
process lifecycle boundaries. Participant-originated records are not tamper-proof.
"""

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
from uuid import UUID, uuid5

TAG_PATTERN = re.compile(r"^20\d{6}T\d{6}Z-\d+$")
CONTAINER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
FUZZ_COMMAND = re.compile(r"^\s*(?:\./|/home/user/fuzz-study/work/)fuzz_([abc])(?:\s|$)")
METRIC_LINE = re.compile(rb"#(?P<runs>\d+)\s+(?P<kind>INITED|DONE)\b(?P<details>[^\r\n]*)")
MAX_TRANSCRIPT_BYTES = 32 * 1024 * 1024
MAX_TIMING_BYTES = 8 * 1024 * 1024
MAX_JSONL_BYTES = 4 * 1024 * 1024


def run(args, stdin=None):
    try:
        proc = subprocess.run(args, input=stdin, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Tool unavailable: {args[:3]}: {exc}") from exc
    if proc.returncode:
        raise RuntimeError(f"Tool failed: {args[:3]}: "
                           + proc.stderr.decode(errors="replace")[-500:])
    return proc.stdout.decode("utf-8", errors="replace").strip()


def verify_assignment(container, session_id, task_run_id):
    full_id = run(["docker", "inspect", "--format", "{{.Id}}", container])
    if not re.fullmatch(r"[a-f0-9]{64}", full_id):
        raise ValueError("Invalid Docker container ID")
    short = full_id[:12]
    sql = ("SELECT count(*) FROM fuzz_pilot.study_sessions s "
           "JOIN fuzz_pilot.task_runs t ON t.session_id = s.session_id "
           f"WHERE s.session_id = '{session_id}'::uuid "
           f"AND t.task_run_id = '{task_run_id}'::uuid "
           f"AND s.instance_id = '{short}' "
           "AND s.status = 'active' AND t.status IN ('ready','active');")
    count = run(["docker", "exec", "-u", "postgres", "devob-db-1", "psql",
                 "-X", "-At", "-d", "notebook", "-c", sql])
    if count != "1":
        raise RuntimeError("Container is not assigned to this active study session/task")
    return short


def read_archive_file(folder, tag, suffix, max_bytes):
    path = folder / (tag + suffix)
    if path.is_symlink() or not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
        raise ValueError(f"Unsafe archive entry: {path.name}")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"Archive entry too large for prototype: {path.name}")
    return path.read_bytes()


def find_command(jsonl, tag):
    matches = []
    for number, line in enumerate(jsonl.splitlines(), 1):
        try:
            item = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"Invalid JSONL line {number}") from exc
        if not isinstance(item, dict) or item.get("terminal_session") != tag:
            raise ValueError(f"Unexpected command record at line {number}")
        command = item.get("command")
        if not isinstance(command, str):
            raise ValueError(f"Malformed command at line {number}")
        match = FUZZ_COMMAND.match(command)
        if match:
            bounded = re.search(r"(?:^|\s)-runs=(\d+)(?=\s|$)", command)
            if not bounded or int(bounded.group(1)) < 1:
                raise ValueError("Only bounded -runs=N fuzzing commands are supported")
            if type(item.get("exit_status")) is not int:
                raise ValueError("Missing command exit status")
            if type(item.get("sequence")) is not int:
                raise ValueError("Missing command sequence")
            if not isinstance(item.get("occurred_at"), str):
                raise ValueError("Missing command completion timestamp")
            matches.append((item, match.group(1), int(bounded.group(1))))
    if len(matches) != 1:
        raise ValueError(f"Expected one bounded fuzz command in recording, found {len(matches)}. "
                         "Use a fresh CLI session for each prototype import.")
    return matches[0]


def parse_metrics(raw):
    text = raw.decode("ascii", errors="replace")
    values = {}
    for name in ("cov", "ft", "rss", "exec/s"):
        match = re.search(r"(?<![\w/])" + re.escape(name) + r":\s*(\d+)", text)
        if match:
            mapped_name = {"cov": "coverage", "ft": "features", "rss": "rss_mb",
                           "exec/s": "libfuzzer_reported_exec_per_second"}[name]
            values[mapped_name] = int(match.group(1))
    corpus = re.search(r"corp:\s*(\d+)/(\d+)b", text)
    if corpus:
        values["corpus_entries"] = int(corpus.group(1))
        values["corpus_bytes"] = int(corpus.group(2))
    for required in ("coverage", "features", "corpus_entries", "corpus_bytes"):
        if required not in values:
            raise ValueError(f"LibFuzzer line missing {required}: {text[:160]}")
    return values


def metric_pair(output):
    matches = list(METRIC_LINE.finditer(output))
    started = [x for x in matches if x.group("kind") == b"INITED"]
    finished = [x for x in matches if x.group("kind") == b"DONE"]
    if len(started) != 1 or len(finished) != 1 or finished[0].start() <= started[0].start():
        raise ValueError(f"Expected exactly one INITED/DONE pair, found "
                         f"{len(started)} INITED, {len(finished)} DONE")
    start, end = started[0], finished[0]
    initial = parse_metrics(start.group("details"))
    final = parse_metrics(end.group("details"))
    initial["executions"] = int(start.group("runs"))
    final["executions"] = int(end.group("runs"))
    return initial, final, start.start(), start.group(0), end.group(0)


def time_at_output_offset(timing, tag, byte_offset):
    # `script --log-out --log-timing` classic format: <delta seconds> <output bytes>.
    # Modern advanced format optionally prefixes each entry with 'O'.
    t0 = datetime.strptime(tag.split("-")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    seen = 0
    seconds = 0.0
    for number, line in enumerate(timing.decode("ascii", errors="strict").splitlines(), 1):
        fields = line.split()
        if len(fields) == 2:
            delay, length = fields
        elif len(fields) == 3 and fields[0] == "O":
            delay, length = fields[1:]
        else:
            raise ValueError(f"Unexpected script timing format at line {number}")
        try:
            delta, size = float(delay), int(length)
        except ValueError as exc:
            raise ValueError(f"Invalid timing entry at line {number}") from exc
        if delta < 0 or size < 0 or delta > 86400:
            raise ValueError(f"Unreasonable timing entry at line {number}")
        seconds += delta
        if seen <= byte_offset < seen + size:
            return t0 + timedelta(seconds=seconds)
        seen += size
    raise ValueError("INITED output not covered by script timing log; run collector again")


def build_campaign(archive, tag, task_id):
    output = read_archive_file(archive, tag, ".out", MAX_TRANSCRIPT_BYTES)
    timing = read_archive_file(archive, tag, ".timing", MAX_TIMING_BYTES)
    jsonl = read_archive_file(archive, tag, ".commands.jsonl", MAX_JSONL_BYTES)
    command, harness, run_limit = find_command(jsonl, tag)
    if command["exit_status"] != 0:
        raise ValueError("Prototype imports only completed campaigns with command exit status 0")
    initial, final, start_offset, init_line, done_line = metric_pair(output)
    if final["executions"] > run_limit:
        raise ValueError("DONE execution count exceeds requested -runs limit")
    started = time_at_output_offset(timing, tag, start_offset)
    ended = datetime.fromisoformat(command["occurred_at"].replace("Z", "+00:00"))
    if ended.tzinfo is None or ended < started:
        raise ValueError("Inconsistent command completion timestamp")
    campaign_id = str(uuid5(UUID(task_id), f"libfuzzer:{tag}:{command['sequence']}"))
    summary = {
        "campaign_id": campaign_id,
        "harness_id": harness,
        "status": "completed",
        "command_summary": command["command"],
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "config": {
            "requested_runs": run_limit,
            "initial_metrics": initial,
            "terminal_session": tag,
            "recording_file": tag + ".out",
            "command_sequence": command["sequence"],
            "capture_method": "bash_command_and_script_output_timing",
            "started_at_estimate": "first_INITED_output_from_script_timing",
            "ended_at_estimate": "bash_command_completed_at_prompt",
            "observed_fuzzer_excerpt_sha256": hashlib.sha256(init_line + b"\n" + done_line).hexdigest(),
        },
        "final_metrics": final,
        "event_key": f"campaign:{tag}:{command['sequence']}",
    }
    return summary


def apply_campaign(summary, instance, session, task):
    row = base64.b64encode(json.dumps(summary, separators=(",", ":"),
                                      ensure_ascii=True).encode()).decode("ascii")
    sql = f"""BEGIN;
DO $verify$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM fuzz_pilot.study_sessions s
   JOIN fuzz_pilot.task_runs t ON t.session_id = s.session_id
   WHERE s.session_id = '{session}'::uuid
     AND t.task_run_id = '{task}'::uuid
     AND s.instance_id = '{instance}'
     AND s.status = 'active' AND t.status IN ('ready','active')
   FOR SHARE OF s,t
 ) THEN RAISE EXCEPTION 'Assigned task changed'; END IF;
END $verify$;
WITH d AS (SELECT convert_from(decode('{row}', 'base64'),'UTF8')::jsonb AS j),
created AS (
 INSERT INTO fuzz_pilot.campaigns
 (campaign_id, task_run_id, harness_id, status, command_summary,
  config, final_metrics, started_at, ended_at)
 SELECT (j->>'campaign_id')::uuid, '{task}'::uuid,
        j->>'harness_id', j->>'status', j->>'command_summary',
        j->'config', j->'final_metrics',
        (j->>'started_at')::timestamptz, (j->>'ended_at')::timestamptz
 FROM d WHERE true ON CONFLICT (campaign_id) DO NOTHING RETURNING campaign_id
)
SELECT 'campaigns_inserted=' || COUNT(*) FROM created;
WITH d AS (SELECT convert_from(decode('{row}', 'base64'),'UTF8')::jsonb AS j),
created AS (
 INSERT INTO fuzz_pilot.events
 (session_id, task_run_id, campaign_id, event_type, event_source,
  occurred_at, event_key, payload)
 SELECT '{session}'::uuid, '{task}'::uuid, (j->>'campaign_id')::uuid,
        'libfuzzer_campaign_finished', 'cli',
        (j->>'ended_at')::timestamptz, j->>'event_key',
        jsonb_build_object('harness_id', j->>'harness_id',
             'final_metrics', j->'final_metrics',
             'terminal_session', j->'config'->>'terminal_session',
             'capture_method', j->'config'->>'capture_method')
 FROM d WHERE true ON CONFLICT (session_id, event_key) DO NOTHING RETURNING event_id
)
SELECT 'events_inserted=' || COUNT(*) FROM created;
COMMIT;
"""
    return run(["docker", "exec", "-i", "-u", "postgres", "devob-db-1",
                "psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-d",
                "notebook", "-f", "-"], sql.encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task-run-id", required=True)
    parser.add_argument("--tag", required=True,
                        help="Recording filename stem, e.g. 20261023T221241Z-2726")
    parser.add_argument("--archive-root", type=Path,
                        default=Path.home() / "nerds-pilot-backups" / "cli")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if not CONTAINER_PATTERN.fullmatch(args.container):
            parser.error("Invalid container name")
        if not TAG_PATTERN.fullmatch(args.tag):
            parser.error("Invalid recording tag")
        session = str(UUID(args.session_id))
        task = str(UUID(args.task_run_id))
        instance = verify_assignment(args.container, session, task)
        archive = args.archive_root.expanduser() / session / task
        if archive.is_symlink() or not archive.is_dir():
            raise ValueError("Archive directory missing or symlinked")
        row = build_campaign(archive, args.tag, task)
        print(f"Verified instance: {instance}")
        print(f"Campaign ID: {row['campaign_id']}")
        print(f"Harness: {row['harness_id']}; requested runs: {row['config']['requested_runs']}")
        print(f"Final metrics: {json.dumps(row['final_metrics'], sort_keys=True)}")
        print("Started (estimated):", row["started_at"])
        print("Ended (observed at prompt):", row["ended_at"])
        if args.apply:
            print(apply_campaign(row, instance, session, task))
        else:
            print("DRY RUN: no database changes; pass --apply to import")
        return 0
    except (RuntimeError, OSError, ValueError, UnicodeError) as exc:
        print("CAMPAIGN IMPORT FAILED:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
