#!/usr/bin/env python3
"""Incrementally archive an active NERDs xterm 'script' recording to the WSL host.

Operator-owned tool. Runs on the trusted Docker host, not in the participant
container. Does not add PostgreSQL credentials to the participant container.

Recording files are participant-accessible, so this is best-effort evidence,
not a tamper-proof audit stream. Do not use alone for high-integrity research.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from uuid import UUID

REMOTE_DIR = "/home/user/.nerds-cli-recordings"
NAME_RE = re.compile(r"^20[0-9]{6}T[0-9]{6}Z-[0-9]+\.(?:out|timing|commands\.jsonl)$")
CONTAINER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
MIN_FREE_BYTES = 512 * 1024 * 1024

LIST_CODE = r'''
import json, os, re
p = "/home/user/.nerds-cli-recordings"
valid = re.compile(r"^20[0-9]{6}T[0-9]{6}Z-[0-9]+\.(?:out|timing|commands\.jsonl)$")
items = []
if os.path.isdir(p):
    for ent in os.scandir(p):
        if valid.fullmatch(ent.name) and ent.is_file(follow_symlinks=False):
            items.append({"name": ent.name, "size": ent.stat(follow_symlinks=False).st_size})
print(json.dumps(sorted(items, key=lambda item: item["name"])))
'''
READ_CODE = r'''
import os, sys
p = os.path.join("/home/user/.nerds-cli-recordings", sys.argv[1])
if not os.path.isfile(p) or os.path.islink(p):
    sys.exit("recording missing or is a link")
with open(p, "rb") as stream:
    stream.seek(int(sys.argv[2]))
    sys.stdout.buffer.write(stream.read(int(sys.argv[3])))
'''


def run(command, timeout=25):
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=timeout,
                                   check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Command failed: {command[:3]!r}: {exc}") from exc
    if completed.returncode:
        err = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Command failed ({completed.returncode}): {err[:300]}")
    return completed.stdout


def check_assignment(container, session, task):
    full_id = run(["docker", "inspect", "--format", "{{.Id}}", container]).decode().strip()
    if not re.fullmatch(r"[a-f0-9]{64}", full_id):
        raise RuntimeError("Container ID could not be verified")
    sql = (
        "SELECT count(*) FROM fuzz_pilot.study_sessions s "
        "JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id "
        f"WHERE s.session_id='{session}'::uuid "
        f"AND t.task_run_id='{task}'::uuid "
        f"AND s.instance_id='{full_id[:12]}' "
        "AND s.status='active' "
        "AND t.status IN ('ready','active');"
    )
    count = run(["docker", "exec", "-u", "postgres", "devob-db-1",
                 "psql", "-d", "notebook", "-At", "-c", sql]).decode().strip()
    if count != "1":
        raise RuntimeError("The active database task is not assigned to this running container")
    return full_id[:12]


def remote_index(container):
    raw = run(["docker", "exec", container, "python3", "-c", LIST_CODE])
    files = json.loads(raw.decode("utf-8"))
    if not isinstance(files, list):
        raise RuntimeError("Unexpected remote recording listing")
    for item in files:
        if (not isinstance(item, dict) or
                not isinstance(item.get("name"), str) or
                not NAME_RE.fullmatch(item["name"]) or
                not isinstance(item.get("size"), int) or item["size"] < 0):
            raise RuntimeError("Invalid recording entry")
    return files


def ensure_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError("Archive destination is not a real directory")
    os.chmod(path, 0o700)


def sync_once(container, destination, chunk_size):
    files = remote_index(container)
    total = 0
    backlog = 0
    for item in files:
        name, remote_size = item["name"], item["size"]
        target = destination / name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise RuntimeError(f"Unsafe archive destination: {name}")
        local_size = target.stat().st_size if target.exists() else 0
        if local_size > remote_size:
            raise RuntimeError(f"Recording shrank or was replaced: {name}")
        if local_size < remote_size:
            if shutil.disk_usage(destination).free < MIN_FREE_BYTES:
                raise RuntimeError("Less than 512 MiB free in the archive filesystem")
            amount = min(remote_size - local_size, chunk_size)
            data = run(["docker", "exec", container, "python3", "-c",
                        READ_CODE, name, str(local_size), str(amount)])
            if not data:
                raise RuntimeError(f"Unable to read appended bytes from {name}")
            # Create a host-owned file; never replace already archived history.
            fd = os.open(str(target), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                if os.fstat(fd).st_size != local_size:
                    raise RuntimeError(f"Archive changed concurrently: {name}")
                with os.fdopen(fd, "ab", closefd=False) as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
            finally:
                os.close(fd)
            total += len(data)
            local_size += len(data)
        backlog += max(0, remote_size - local_size)
    return len(files), total, backlog


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True, help="Existing participant container name")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task-run-id", required=True)
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Seconds between polls (default: 5)")
    parser.add_argument("--max-chunk-mib", type=int, default=4,
                        help="Max read per file per poll (default: 4 MiB)")
    parser.add_argument("--archive-root", type=Path,
                        default=Path.home() / "nerds-pilot-backups" / "cli")
    args = parser.parse_args()
    try:
        session = str(UUID(args.session_id))
        task = str(UUID(args.task_run_id))
    except ValueError as exc:
        parser.error(f"Invalid UUID: {exc}")
    if not CONTAINER_RE.fullmatch(args.container):
        parser.error("Invalid Docker container name")
    if not (1 <= args.interval <= 300):
        parser.error("--interval must be between 1 and 300 seconds")
    if not (1 <= args.max_chunk_mib <= 32):
        parser.error("--max-chunk-mib must be between 1 and 32")

    os.umask(0o077)
    destination = args.archive_root.expanduser() / session / task
    ensure_directory(destination)
    instance = check_assignment(args.container, session, task)
    print(f"[{utc_now()}] Verified active task for container {instance}", flush=True)
    print(f"Archive: {destination}", flush=True)
    print("Collector running; Ctrl+C to stop. This is NOT tamper-proof logging.", flush=True)
    interval = args.interval
    chunk = args.max_chunk_mib * 1024 * 1024
    polls = 0
    copied_total = 0
    try:
        while True:
            # Recheck mapping before archiving each poll, to prevent task crossover.
            check_assignment(args.container, session, task)
            files, copied, pending = sync_once(args.container, destination, chunk)
            polls += 1
            copied_total += copied
            if copied or polls == 1 or polls % 12 == 0:
                print(f"[{utc_now()}] files={files} copied={copied}B "
                      f"pending={pending}B total_archived_this_run={copied_total}B", flush=True)
            time.sleep(1 if pending else interval)
    except KeyboardInterrupt:
        print(f"\n[{utc_now()}] Stopped by operator. Archive retained at {destination}",
              flush=True)
        return 0
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[{utc_now()}] COLLECTION STOPPED: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
