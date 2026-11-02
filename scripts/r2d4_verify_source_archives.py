#!/usr/bin/env python3
"""Read-only source archive verification for the existing NERDs Pilot 1 participant.

Check DB artifact pointers against ~/nerds-pilot-backups: path safety, actual
bytes/size/SHA256, ZIP integrity, and source-observation references. Never
display source content or modify DB, archives, tasks, or participant.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from uuid import UUID
import zipfile

LIVE = "nerds-pilot1-browser-r1-test"
SHA = re.compile(r"^[a-f0-9]{64}$")
MAX_BYTES = 128 * 1024 * 1024


def execute(*argv):
    proc = subprocess.run(argv, text=True, capture_output=True, timeout=40)
    if proc.returncode:
        raise RuntimeError("Command failed: " + " ".join(argv[:4])
                           + ": " + (proc.stderr or proc.stdout)[-600:])
    return proc.stdout.strip()


def db_rows(instance):
    sql = """
SELECT COALESCE(json_agg(row_to_json(item)), '[]'::json)::text
FROM (
 SELECT t.position, s.session_id::text AS session_id,
        t.task_run_id::text AS task_run_id,
        a.artifact_kind, a.storage_key, a.sha256, a.size_bytes,
        (SELECT count(*) FROM fuzz_pilot.events e
         WHERE e.task_run_id=t.task_run_id AND e.session_id=s.session_id
           AND e.event_type IN ('source_baseline_captured','source_change_detected')
           AND e.payload->>
              CASE WHEN a.artifact_kind='source_snapshot'
                   THEN 'snapshot_storage_key' ELSE 'diff_storage_key' END
              = a.storage_key
        ) AS source_references
 FROM fuzz_pilot.study_sessions s
 JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
 JOIN fuzz_pilot.artifacts a ON a.task_run_id=t.task_run_id
 WHERE s.instance_id='""" + instance + """'
   AND a.artifact_kind IN ('source_snapshot','source_diff')
 ORDER BY t.position, a.artifact_kind, a.storage_key
) item;
"""
    raw = execute("docker", "exec", "-u", "postgres", "devob-db-1",
                  "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
                  "-d", "notebook", "-c", sql)
    result = json.loads(raw)
    if not isinstance(result, list):
        raise RuntimeError("Unexpected artifact query response")
    return result


def verify(root, item):
    kind = item["artifact_kind"]
    session = str(UUID(item["session_id"]))
    task = str(UUID(item["task_run_id"]))
    suffix, folder = ((".zip", "snapshots") if kind == "source_snapshot"
                      else (".patch", "diffs"))
    raw_key = item["storage_key"]
    if not isinstance(raw_key, str):
        raise ValueError("Missing archive key")
    rel = PurePosixPath(raw_key)
    if (kind not in ("source_snapshot", "source_diff")
        or rel.is_absolute() or ".." in rel.parts
        or len(rel.parts) != 5
        or rel.parts[:4] != ("sources", session, task, folder)
        or rel.suffix != suffix):
        raise ValueError("Unsafe or unexpected storage key")
    if (type(item["size_bytes"]) is not int or item["size_bytes"] < 1
        or not isinstance(item["sha256"], str)
        or not SHA.fullmatch(item["sha256"])):
        raise ValueError("Invalid DB size/checksum")
    if item["source_references"] < 1:
        raise ValueError("No matching source event references artifact")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Archive root not found or symlinked")
    path = root
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Symlink inside archive path")
    mode = path.stat()
    if not stat.S_ISREG(mode.st_mode) or not 0 < mode.st_size <= MAX_BYTES:
        raise ValueError("Archive file missing or invalid")
    if mode.st_size != item["size_bytes"]:
        raise ValueError("Archive size mismatch")
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != item["sha256"]:
        raise ValueError("Archive SHA256 mismatch")
    if kind == "source_snapshot":
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if not names or len(names) != len(set(names)):
                raise ValueError("Empty/duplicate snapshot entries")
            for name in names:
                p = PurePosixPath(name)
                if p.is_absolute() or ".." in p.parts or "\\" in name:
                    raise ValueError("Unsafe ZIP entry")
            if z.testzip() is not None:
                raise ValueError("Snapshot ZIP CRC mismatch")
    return item["source_references"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path,
                        default=Path.home() / "nerds-pilot-backups")
    args = parser.parse_args()
    cid = execute("docker", "inspect", "-f", "{{.Id}}", LIVE)
    if not SHA.fullmatch(cid):
        raise RuntimeError("Participant container ID unavailable")
    rows = db_rows(cid[:12])
    if not rows:
        raise RuntimeError("No source artifacts found for the current participant")
    root = args.archive_root.expanduser()
    print("READ-ONLY SOURCE ARCHIVE VERIFICATION")
    print("Archive root:", root)
    failure = 0
    for row in rows:
        position = row.get("position", "?")
        kind = row.get("artifact_kind", "?")
        try:
            references = verify(root, row)
            print(f"Task {position} | {kind} | PASS | {references} source event(s)")
        except (ValueError, KeyError, TypeError, OSError,
                zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            failure += 1
            print(f"Task {position} | {kind} | FAIL | {exc}")
    print(f"Verified: {len(rows)-failure}/{len(rows)} artifact files")
    if failure:
        print("Archive integrity unresolved; no files modified.")
        return 1
    print("Stored files match DB sizes/checksums and source-event references.")
    print("This does not prove every intermediate source edit was captured.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.TimeoutExpired,
            json.JSONDecodeError) as exc:
        print("STOP:", exc, file=sys.stderr)
        sys.exit(1)
