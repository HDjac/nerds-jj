#!/usr/bin/env python3
"""NERDs Pilot 1: trusted-host CLI archive + event/campaign/crash importer.

Run only on the WSL Docker host. Requires these sibling scripts:
  pilot1_collect_cli.py (UPDATED version that collects .commands.jsonl)
  pilot1_ingest_cli_events.py
  pilot1_import_campaign_multi.py (backspace-aware version)
  pilot1_import_crash_campaign.py

Conservative scope: direct ./fuzz_[abc] commands, completed runs with LibFuzzer
DONE and exit=0, and AddressSanitizer crashes with a matching logged crash-
artifact in /home/user/fuzz-study/work. Ambiguous, interrupted, or incomplete
runs are NOT classified automatically. Manual review is required.

All imported objects are associated with the host-verified active session/task,
not with participant-provided IDs. Existing PostgreSQL data is never replaced.
Terminal/command evidence originates in a participant-writable container and is
best-effort observation, not an independently trusted audit trail.
"""

import argparse
from contextlib import contextmanager
import fcntl
from datetime import datetime
import tempfile
import subprocess
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from uuid import UUID, uuid5

import pilot1_collect_cli as collector
import pilot1_ingest_cli_events as command_events
import pilot1_import_campaign_multi as completed_importer
import pilot1_import_crash_campaign as crash_importer

TAG_RE = re.compile(r"^20\d{6}T\d{6}Z-\d+$")
FUZZ_COMMAND = re.compile(r"^\s*(?:\./|/home/user/fuzz-study/work/)fuzz_([abc])(?:\s|$)")
CRASH_REFERENCE = re.compile(rb"Test unit written to (?:\./)?(crash-[a-f0-9]{40})(?=\s|\r|\n|$)")
ASAN_HEADER = re.compile(rb"ERROR: AddressSanitizer:\s+([a-z0-9_-]+)")
ASAN_SUMMARY = re.compile(rb"SUMMARY: AddressSanitizer:\s+([a-z0-9_-]+)")
REQUIRED_COLLECTOR_SUFFIX = ".commands.jsonl"


def log(msg):
    print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}", flush=True)


def validate_collector():
    if not collector.NAME_RE.fullmatch("20261023T221241Z-2726.commands.jsonl"):
        raise RuntimeError(
            "pilot1_collect_cli.py is outdated and does not sync commands.jsonl. "
            "Install the updated collector from this package before proceeding."
        )
    if "commands\\.jsonl" not in collector.LIST_CODE:
        raise RuntimeError("Remote collector listing does not include commands.jsonl")


def archived_tag_files(archive):
    tags = set()
    for path in archive.iterdir():
        if not path.name.endswith(REQUIRED_COLLECTOR_SUFFIX):
            continue
        tag = path.name[:-len(REQUIRED_COLLECTOR_SUFFIX)]
        if not TAG_RE.fullmatch(tag):
            raise ValueError(f"Unexpected structured recording name: {path.name}")
        if path.is_symlink() or not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
            raise ValueError(f"Unsafe structured recording file: {path.name}")
        tags.add(tag)
    return sorted(tags)



def authoritative_task_recording_floor(session, task):
    """Return minimum recorder start-tag for task 2 from a DB-authored release.

    Task 1 has no lower bound. Task 2 must have exactly one task_released
    event with the expected key. Never use participant clock/request contents
    as the authority for this task boundary.
    """
    # Both identifiers have already been parsed as UUIDs by main().
    query = f"""
SELECT t.position::text || '|' || COALESCE((
  SELECT to_char(e.received_at AT TIME ZONE 'UTC',
                 'YYYYMMDD"T"HH24MISS"Z"')
    FROM fuzz_pilot.events e
   WHERE e.task_run_id=t.task_run_id
     AND e.session_id=t.session_id
     AND e.event_type='task_released'
     AND e.event_key='lifecycle:2:released'
   ORDER BY e.event_id ASC LIMIT 1
), '')
FROM fuzz_pilot.task_runs t
WHERE t.task_run_id='{task}'::uuid
  AND t.session_id='{session}'::uuid;
"""
    result = subprocess.run(
        ['docker', 'exec', '-u', 'postgres', 'devob-db-1', 'psql',
         '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-d', 'notebook', '-c', query],
        capture_output=True, text=True, timeout=20, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError('Cannot verify task recording boundary: ' +
                           result.stderr[-600:])
    rows = result.stdout.strip().splitlines()
    if len(rows) != 1 or '|' not in rows[0]:
        raise RuntimeError('Expected exactly one task recording boundary row')
    position, floor = rows[0].split('|', 1)
    if position == '1' and not floor:
        return None
    if position == '2' and re.fullmatch(r'20[0-9]{6}T[0-9]{6}Z', floor):
        return floor
    raise RuntimeError('Invalid task position or missing task-2 release event')


@contextmanager
def task_recording_view(archive, floor):
    """Provide only recordings started after this task was released.

    Raw recordings remain in the original archive. Hardlinks inside a private,
    short-lived directory form a filtered read-only-by-convention ingest view.
    The old first-task data is never deleted or reassigned.
    """
    if floor is None:
        yield archive
        return
    if not re.fullmatch(r'20[0-9]{6}T[0-9]{6}Z', floor):
        raise ValueError('Invalid recorder timestamp boundary')
    suffixes = ('.commands.jsonl', '.out', '.timing')
    with tempfile.TemporaryDirectory(prefix='.task-ingest-', dir=archive) as dirname:
        view = Path(dirname)
        for source in archive.iterdir():
            for suffix in suffixes:
                if not source.name.endswith(suffix):
                    continue
                tag = source.name[:-len(suffix)]
                if not TAG_RE.fullmatch(tag) or tag.split('-', 1)[0] < floor:
                    break
                if source.is_symlink() or not stat.S_ISREG(source.stat(follow_symlinks=False).st_mode):
                    raise ValueError('Unsafe recording file in task archive: ' + source.name)
                os.link(source, view / source.name)
                break
        yield view


def read_tag(archive, tag):
    fn = completed_importer.read_archive_file
    output = fn(archive, tag, ".out", completed_importer.MAX_TRANSCRIPT_BYTES)
    timing = fn(archive, tag, ".timing", completed_importer.MAX_TIMING_BYTES)
    jsonl = fn(archive, tag, ".commands.jsonl", completed_importer.MAX_JSONL_BYTES)
    return output, timing, jsonl


def completed_commands(jsonl, tag):
    """Read completed Bash observations; ignore incomplete tail and other commands."""
    commands = []
    lines = jsonl.splitlines(keepends=True)
    for lineno, raw in enumerate(lines, 1):
        if not raw.endswith(b"\n") and lineno == len(lines):
            break
        try:
            item = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"Malformed JSONL at {tag}:{lineno}") from exc
        if not isinstance(item, dict) or item.get("terminal_session") != tag:
            raise ValueError(f"Invalid terminal session in JSONL at {tag}:{lineno}")
        command = item.get("command")
        match = FUZZ_COMMAND.match(command) if isinstance(command, str) else None
        if not match:
            continue
        seq, rc, occured = item.get("sequence"), item.get("exit_status"), item.get("occurred_at")
        if type(seq) is not int or seq < 1 or type(rc) is not int or not isinstance(occured, str):
            raise ValueError(f"Incomplete fuzz command record at {tag}:{lineno}")
        try:
            ended = datetime.fromisoformat(occured.replace("Z", "+00:00"))
            if ended.tzinfo is None:
                raise ValueError("Naive timestamp")
        except ValueError as exc:
            raise ValueError(f"Bad fuzz command timestamp at {tag}:{lineno}") from exc
        commands.append((item, match.group(1)))
    if any(a[0]["sequence"] >= b[0]["sequence"] for a,b in zip(commands, commands[1:])):
        raise ValueError(f"Out-of-order commands in {tag}")
    return commands


def normalize_edited_echo(segment):
    """Undo xterm's repeated printable-character backspace/space/backspace echoes.

    In a run of adjacent edits the *second* erase has no directly preceding
    printable character until the first erase is processed. Repeat to a fixed
    point with a strict safety cap. This reconstruction is only used to check
    an exact recorded-command echo; raw evidence is not changed.
    """
    erase = re.compile(rb"[\x20-\x7e]\x08 \x08")
    for _ in range(256):
        normalized = erase.sub(b"", segment)
        if normalized == segment:
            return segment
        segment = normalized
    raise ValueError("Terminal contains an excessive chain of Backspace edits; manual review")


def read_campaigns(archive, tag, task):
    """Return verified campaigns and deferred reasons from a possibly active recording.

    Correlate by sequence AND echoed command (not by INITED order alone).
    We use at most as many INITED lines as completed structured commands. If an
    unfinished fuzzer produces an extra INITED, it is not imported.
    """
    output, timing, jsonl = read_tag(archive, tag)
    commands = completed_commands(jsonl, tag)
    initials = [m for m in crash_importer.METRIC.finditer(output) if m.group("kind") == b"INITED"]
    results, deferred = [], []
    if len(initials) < len(commands):
        return [], [f"{tag}: {len(commands)} completed fuzz command(s), but only "
                    f"{len(initials)} INITED records collected; retry after transcript sync"]
    prev_outcome_end = 0
    for idx, (entry, harness) in enumerate(commands):
        initial = initials[idx]
        start = initial.start()
        next_start = initials[idx+1].start() if idx+1 < len(initials) else len(output)
        if next_start <= start:
            raise ValueError("Non-increasing INITED positions")
        echo = entry["command"].encode("utf-8")
        prefix = output[prev_outcome_end:start]
        if echo not in prefix and echo not in normalize_edited_echo(prefix):
            deferred.append(f"{tag}: sequence {entry['sequence']} harness={harness}: "
                            "invocation echo not uniquely matched before INITED; manual review")
            # We cannot safely use a later outcome until this ambiguity is resolved.
            break
        segment = output[start:next_start]
        try:
            started = completed_importer.time_at_output_offset(timing, tag, start)
        except ValueError as exc:
            deferred.append(f"{tag}: sequence {entry['sequence']}: timing pending ({exc})")
            break
        ended = datetime.fromisoformat(entry["occurred_at"].replace("Z", "+00:00"))
        if ended < started:
            deferred.append(f"{tag}: sequence {entry['sequence']}: inconsistent time; review")
            break
        metrics = list(crash_importer.METRIC.finditer(segment))
        if not metrics or metrics[0].group("kind") != b"INITED":
            deferred.append(f"{tag}: sequence {entry['sequence']}: missing initial metrics")
            break
        done = [m for m in metrics if m.group("kind") == b"DONE"]
        errors = list(ASAN_HEADER.finditer(segment))
        if len(done) > 1 or len(errors) > 1:
            deferred.append(f"{tag}: sequence {entry['sequence']}: ambiguous outcomes; manual review")
            break
        outcome = None
        if done and (not errors or done[0].start() < errors[0].start()):
            if entry["exit_status"] != 0:
                deferred.append(f"{tag}: sequence {entry['sequence']}: DONE with nonzero exit; manual review")
                break
            # Completion requires both DONE and clean shell exit. A -runs bound is optional
            # because a time-bounded LibFuzzer invocation may also end with DONE.
            last = done[0]
            final = completed_importer.parse_metrics(last.group("details"))
            initial_metrics = completed_importer.parse_metrics(metrics[0].group("details"))
            initial_metrics["executions"] = int(metrics[0].group("runs"))
            final["executions"] = int(last.group("runs"))
            if final["executions"] < initial_metrics["executions"]:
                raise ValueError("Decreasing LibFuzzer executions")
            bounded = re.search(r"(?:^|\s)-runs=(\d+)(?=\s|$)", entry["command"])
            if bounded and final["executions"] > int(bounded.group(1)):
                raise ValueError("Reported executions exceed requested -runs limit")
            outcome = {
                "kind": "completed", "status": "completed", "harness_id": harness,
                "command_summary": entry["command"],
                "started_at": started.isoformat(), "ended_at": ended.isoformat(),
                "config": {
                    "requested_runs": int(bounded.group(1)) if bounded else None,
                    "initial_metrics": initial_metrics,
                    "terminal_session": tag, "recording_file": tag+".out",
                    "command_sequence": entry["sequence"],
                    "capture_method": "bash_command_and_script_output_timing",
                    "started_at_estimate": "first_INITED_output_from_script_timing",
                    "ended_at_estimate": "bash_command_completed_at_prompt",
                    "observed_fuzzer_excerpt_sha256": hashlib.sha256(
                        metrics[0].group(0) + b"\n" + last.group(0)).hexdigest(),
                },
                "final_metrics": final,
            }
            # Next invocation must be after this command's DONE.
            prev_outcome_end = start + last.end()
        elif errors and not done:
            if entry["exit_status"] == 0:
                deferred.append(f"{tag}: sequence {entry['sequence']}: ASan report but zero exit; review")
                break
            asan = errors[0].group(1).decode("ascii")
            reports_after = segment[errors[0].start():]
            summary = ASAN_SUMMARY.search(reports_after)
            if not summary or summary.group(1).decode("ascii") != asan:
                deferred.append(f"{tag}: sequence {entry['sequence']}: incomplete ASan report")
                break
            # An artifact is linked only when the fuzzer itself emitted its filename.
            artifact_match = CRASH_REFERENCE.search(segment[errors[0].end():])
            if not artifact_match:
                deferred.append(f"{tag}: sequence {entry['sequence']}: ASan crash but no verified "
                                "root-workspace crash artifact reference; manual import required")
                break
            artifact = artifact_match.group(1).decode("ascii")
            before_report = segment[:errors[0].start()]
            last_metrics = [m for m in crash_importer.METRIC.finditer(before_report)
                            if m.group("kind") != b"DONE"]
            if not last_metrics:
                deferred.append(f"{tag}: sequence {entry['sequence']}: no usable crash metrics")
                break
            first = last_metrics[0]
            last = last_metrics[-1]
            final = completed_importer.parse_metrics(last.group("details"))
            initial_metrics = completed_importer.parse_metrics(first.group("details"))
            initial_metrics["executions"] = int(first.group("runs"))
            final["executions"] = int(last.group("runs"))
            final["observation_kind"] = last.group("kind").decode("ascii")
            final["is_final_fuzzer_metric"] = False
            if final["executions"] < initial_metrics["executions"]:
                raise ValueError("Decreasing LibFuzzer executions before crash")
            line_match = re.search(rb"\bsrc/([\w./-]+\.c):(\d+)(?::\d+)?", reports_after)
            write_match = re.search(rb"WRITE of size (\d+)", reports_after)
            timer = re.search(r"(?:^|\s)-max_total_time=(\d+)(?=\s|$)", entry["command"])
            outcome = {
                "kind": "crash", "status": "crashed", "harness_id": harness,
                "command_summary": entry["command"],
                "started_at": started.isoformat(), "ended_at": ended.isoformat(),
                "artifact": artifact,
                "config": {
                    "terminal_session": tag, "recording_file": tag+".out",
                    "command_sequence": entry["sequence"],
                    "requested_max_total_time_s": int(timer.group(1)) if timer else None,
                    "initial_metrics": initial_metrics,
                    "capture_method": "bash_command_and_script_output_timing",
                    "started_at_estimate": "first_INITED_output_from_script_timing",
                    "ended_at_estimate": "bash_command_completed_at_prompt",
                    "sanitizer_type": asan,
                    "write_size_bytes": int(write_match.group(1)) if write_match else None,
                    "fault_source": line_match.group(1).decode("ascii") if line_match else None,
                    "fault_source_line": int(line_match.group(2)) if line_match else None,
                    "command_exit_status": entry["exit_status"],
                },
                "final_metrics": final,
            }
            prev_outcome_end = start + errors[0].start() + summary.end()
        else:
            deferred.append(f"{tag}: sequence {entry['sequence']}: no verified DONE/ASan outcome "
                            f"(exit={entry['exit_status']}); not imported")
            # Still allow a later candidate to be associated only when a new echoed invocation
            # is present, but lack of an outcome boundary is ambiguous, so stop this recording.
            break
        outcome["campaign_id"] = str(uuid5(UUID(task), f"libfuzzer:{tag}:{entry['sequence']}"))
        outcome["event_key"] = f"campaign:{tag}:{entry['sequence']}"
        results.append(outcome)
    return results, deferred


def db_campaign_summary(campaign_id, session, task):
    # Inputs are UUID-validated by the caller. This is host-side DB access only.
    sql = ("SELECT harness_id || E'\\t' || status || E'\\t' || "
           "COALESCE(command_summary,'') FROM fuzz_pilot.campaigns "
           f"WHERE campaign_id='{campaign_id}'::uuid AND task_run_id='{task}'::uuid;")
    result = completed_importer.run([
        "docker", "exec", "-u", "postgres", "devob-db-1", "psql", "-X", "-At", "-d", "notebook", "-c", sql
    ])
    if not result:
        return None
    fields = result.split("\t", 2)
    if len(fields) != 3:
        raise RuntimeError("Ambiguous campaign database record")
    return fields


def ingest_events(archive, session, task, instance, do_apply):
    events = list(command_events.archived_rows(archive))
    if not do_apply:
        return len(events), 0
    inserted = 0
    for offset in range(0, len(events), 100):
        inserted += command_events.write_batch(events[offset:offset+100], session, task, instance)
    return len(events), inserted


def import_campaign(candidate, container, instance, session, task, root, apply):
    existing = db_campaign_summary(candidate["campaign_id"], session, task)
    if existing is not None:
        if existing != [candidate["harness_id"], candidate["status"], candidate["command_summary"]]:
            raise RuntimeError(f"Conflicting existing campaign ID {candidate['campaign_id']}; stopping")
        # Already ingested. Crash archive integrity still needs independent verification
        # by the artifact importer; don't change the existing record.
        return "existing"
    if not apply:
        return "dry-run"
    summary = {key: value for key, value in candidate.items() if key not in ("kind", "artifact")}
    if candidate["kind"] == "completed":
        completed_importer.apply_campaign(summary, instance, session, task)
        return "imported"
    if candidate["kind"] == "crash":
        artifact = candidate["artifact"]
        rel = Path("artifacts") / session / task / candidate["campaign_id"] / artifact
        digest, size = crash_importer.archive_crash(container, artifact, root / rel)
        crash_importer.apply(summary, instance, session, task, rel.as_posix(), digest, size)
        return f"imported, crash artifact {size}B sha256={digest[:12]}..."
    raise RuntimeError(f"Unexpected candidate kind {candidate['kind']}")


def run_cycle(args, destination, state):
    instance = collector.check_assignment(args.container, args.session_id, args.task_run_id)
    count, copied, remaining = collector.sync_once(args.container, destination,
                                                      args.max_chunk_mib * 1024 * 1024)
    signature = tuple((p.name, p.stat().st_size) for p in sorted(destination.iterdir())
                      if p.is_file() and not p.is_symlink())
    if signature == state.get("last_signature"):
        return count, copied, remaining, 0, 0, []
    results = []
    with task_recording_view(destination, state.get("tag_floor")) as view:
        # Both command-event ingestion AND fuzzing campaign import must use the
        # exact same task-filtered view to prevent cross-task attribution.
        events_count, events_inserted = ingest_events(
            view, args.session_id, args.task_run_id, instance, args.apply)
        for tag in archived_tag_files(view):
            if not all((view / (tag + suffix)).is_file()
                       for suffix in (".out", ".timing", ".commands.jsonl")):
                continue
            candidates, deferred = read_campaigns(view, tag, args.task_run_id)
            for item in candidates:
                action = import_campaign(item, args.container, instance, args.session_id,
                                         args.task_run_id, args.archive_root, args.apply)
                if action != "existing" or args.once:
                    results.append(f"{tag} harness={item['harness_id']} {item['status']}: {action}")
            # Only repeat new deferrals; avoid printing the same large error every poll.
            for problem in deferred:
                if problem not in state.setdefault("warned", set()):
                    results.append("REVIEW: " + problem)
                    state["warned"].add(problem)
    state["last_signature"] = signature if remaining == 0 else None
    return count, copied, remaining, events_count, events_inserted, results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--container", required=True)
    p.add_argument("--session-id", required=True)
    p.add_argument("--task-run-id", required=True)
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--max-chunk-mib", type=int, default=4)
    p.add_argument("--archive-root", type=Path, default=Path.home() / "nerds-pilot-backups")
    p.add_argument("--once", action="store_true", help="Run exactly one archive/import cycle")
    p.add_argument("--apply", action="store_true", help="Enable database insertions and crash copy")
    args = p.parse_args()
    try:
        args.session_id, args.task_run_id = str(UUID(args.session_id)), str(UUID(args.task_run_id))
        if not collector.CONTAINER_RE.fullmatch(args.container):
            p.error("Invalid Docker container name")
        if not (1 <= args.interval <= 300 and 1 <= args.max_chunk_mib <= 32):
            p.error("Invalid --interval or --max-chunk-mib")
        validate_collector()
        os.umask(0o077)
        args.archive_root = args.archive_root.expanduser()
        destination = args.archive_root / "cli" / args.session_id / args.task_run_id
        collector.ensure_directory(destination)
        state = {"tag_floor": authoritative_task_recording_floor(args.session_id,
                                                                   args.task_run_id)}
        if state["tag_floor"]:
            log("Recording boundary for task 2: " + state["tag_floor"] +
                " (older terminal recordings excluded from event/campaign ingestion)")
        lock_path = destination / ".pilot1-auto.lock"
        if lock_path.is_symlink():
            raise RuntimeError("Unsafe lock file")
        with open(lock_path, "a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Another automatic importer is already running for this task") from exc
            log(f"Archive: {destination}")
            log("Mode: " + ("IMPORT" if args.apply else "DRY RUN (archive transfer only, no DB writes)"))
            while True:
                count, copied, pending, events, inserted, outcomes = run_cycle(args, destination, state)
                if args.once or copied or inserted or outcomes:
                    log(f"recording_files={count} archived={copied}B pending={pending}B "
                        f"complete_cli_events={events} new_cli_events={inserted}")
                    for item in outcomes:
                        log(item)
                if args.once:
                    break
                time.sleep(1 if pending else args.interval)
        return 0
    except KeyboardInterrupt:
        log("Stopped by operator; existing DB records and archives retained")
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"AUTO INGEST STOPPED: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
