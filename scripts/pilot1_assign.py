#!/usr/bin/env python3
"""Pilot 1 operator-only assignment of an enrolled NERDs session to a container.

Requires Docker CLI access and the PostgreSQL container. Does not expose any web
endpoint or browser login. Run without --apply to preview the assignment.
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass

DB_CONTAINER = "devob-db-1"
DB_NAME = "notebook"
PID_RE = re.compile(r"^[0-9a-f]{24}$")
CONTAINER_RE = re.compile(r"^nerds-pilot1-[a-z0-9-]+$")
TASKS = {"dense_v2", "lowyield_v1"}


def command(argv):
    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Command failed ({result.returncode}): {argv[0]} {argv[1]}\n{error}")
    return result.stdout.strip()


def sql(query):
    return command([
        "docker", "exec", "-u", "postgres", DB_CONTAINER,
        "psql", "-X", "-qAt", "-F", "|", "-v", "ON_ERROR_STOP=1",
        "-d", DB_NAME, "-c", query,
    ])


@dataclass
class Assignment:
    session_id: str
    order_code: str
    status: str
    instance_id: str
    instance_name: str
    first_task: str
    first_status: str
    second_task: str
    second_status: str


def lookup(pid):
    # pid has been regex-validated and cannot contain SQL metacharacters.
    rows = sql(f"""
        SELECT s.session_id::text, s.order_code, s.status,
               COALESCE(s.instance_id, ''), COALESCE(s.instance_name, ''),
               t1.task_code, t1.status, t2.task_code, t2.status
        FROM fuzz_pilot.study_sessions AS s
        JOIN fuzz_pilot.task_runs AS t1
          ON t1.session_id = s.session_id AND t1.position = 1
        JOIN fuzz_pilot.task_runs AS t2
          ON t2.session_id = s.session_id AND t2.position = 2
        WHERE s.participant_id = '{pid}'
          AND s.study_phase = 'pilot1'
          AND s.enrollment_method = 'manual'
          AND s.attempt_number = 1;
    """)
    lines = rows.splitlines()
    if len(lines) != 1 or len(lines[0].split("|")) != 9:
        raise RuntimeError("Expected exactly one enrolled session with two task rows")
    a = Assignment(*lines[0].split("|"))
    expected = {
        "dense_first": ("dense_v2", "lowyield_v1"),
        "lowyield_first": ("lowyield_v1", "dense_v2"),
    }.get(a.order_code)
    if expected != (a.first_task, a.second_task):
        raise RuntimeError("Task rows do not match the randomized order")
    return a


def inspect_container(name):
    data = json.loads(command(["docker", "inspect", name]))
    if len(data) != 1:
        raise RuntimeError("Expected exactly one Docker container")
    item = data[0]
    if not item["State"]["Running"]:
        raise RuntimeError("Container is not running")
    if item["Config"]["Image"] != "devob_instance:cli-pilot-protected":
        raise RuntimeError("Container was not created from the protected Pilot 1 image")
    if item["Config"]["User"] != "user":
        raise RuntimeError("Container is not configured as the unprivileged user")
    if "devob_instances" not in item["NetworkSettings"]["Networks"]:
        raise RuntimeError("Container is not on the devob_instances network")
    if item["Config"].get("Labels", {}).get("nerds.study") != "pilot1":
        raise RuntimeError("Container is missing the nerds.study=pilot1 label")
    if item["Name"] != "/" + name:
        raise RuntimeError("Docker container name mismatch")
    return item["Id"][:12]


def verify_files(name):
    command([
        "docker", "exec", "-u", "user", name, "sh", "-ec",
        """
        test -r /home/user/fuzz-study/reference/Makefile
        test ! -w /home/user/fuzz-study/reference/Makefile
        test -w /home/user/fuzz-study/work/Makefile
        test -w /home/user/fuzz-study/runs
        test ! -r /opt/nerds/task-bundles/lowyield_v1/Makefile
        test ! -r /opt/nerds/task-bundles/dense_v2/Makefile
        """,
    ])


def claim(pid, instance_id, name):
    # Both participant ID and Docker identifiers have strict validation.
    returned = sql(f"""
        UPDATE fuzz_pilot.study_sessions AS s
        SET instance_id = '{instance_id}', instance_name = '{name}'
        WHERE s.participant_id = '{pid}'
          AND s.study_phase = 'pilot1'
          AND s.enrollment_method = 'manual'
          AND s.attempt_number = 1
          AND s.status = 'assigned'
          AND (
            s.instance_id IS NULL OR
            (s.instance_id = '{instance_id}' AND s.instance_name = '{name}')
          )
          AND EXISTS (
            SELECT 1 FROM fuzz_pilot.task_runs AS t
            WHERE t.session_id = s.session_id
              AND t.position = 1 AND t.status = 'locked'
          )
          AND EXISTS (
            SELECT 1 FROM fuzz_pilot.task_runs AS t
            WHERE t.session_id = s.session_id
              AND t.position = 2 AND t.status = 'locked'
          )
        RETURNING s.session_id::text;
    """)
    if not returned or len(returned.splitlines()) != 1:
        raise RuntimeError("Could not claim container for this assigned session")
    return returned


def provision(name, task):
    if task not in TASKS:
        raise RuntimeError("Unexpected task code; refusing to provision")
    # Only the two server-side, DB-validated task names can reach this script.
    root_script = f"""
        src=/opt/nerds/task-bundles/{task}
        base=/home/user/fuzz-study
        ref_parent=/opt/nerds/released-reference
        ref="$ref_parent/current"
        test -f "$src/Makefile"
        test -d "$base"
        test ! -L "$base"
        if test -e "$ref" || test -L "$ref" || test -n "$(ls -A "$base")"; then
            echo 'Workspace or reference is already populated; refusing overwrite' >&2
            exit 20
        fi
        install -d -o root -g root -m 0755 "$ref_parent"
        mkdir "$ref"
        cp -a "$src"/. "$ref"/
        chown -R root:root "$ref"
        chmod -R a+rX "$ref"
        chmod -R a-w "$ref"
        mkdir "$base/work" "$base/runs"
        cp -a "$src"/. "$base/work"/
        chown -R user:user "$base/work" "$base/runs"
        chmod -R u+rwX "$base/work"
        chmod 700 "$base/runs"
        ln -s "$ref" "$base/reference"
    """
    command(["docker", "exec", "-u", "root", name, "sh", "-eu", "-c", root_script])



def assigned_task_id(pid, instance_id, position, task, required_status):
    """Read DB-authoritative UUID for a safely bound task and lifecycle state."""
    from uuid import UUID
    if task not in TASKS or position not in (1, 2):
        raise RuntimeError('Invalid assigned task')
    if required_status not in ('locked', 'ready'):
        raise RuntimeError('Unexpected task status')
    task_id = sql(f"""
        SELECT t.task_run_id::text
        FROM fuzz_pilot.task_runs t
        JOIN fuzz_pilot.study_sessions s ON s.session_id = t.session_id
        WHERE s.participant_id = '{pid}'
          AND s.study_phase = 'pilot1'
          AND s.enrollment_method = 'manual'
          AND s.attempt_number = 1
          AND s.instance_id = '{instance_id}'
          AND s.status = 'assigned'
          AND t.position = {position}
          AND t.task_code = '{task}'
          AND t.status = '{required_status}';
    """).strip()
    try:
        if str(UUID(task_id)) != task_id:
            raise ValueError('Noncanonical UUID')
    except ValueError as exc:
        raise RuntimeError('Could not verify task-run UUID') from exc
    return task_id


def ensure_active_task_metadata(name, task_code, task_id):
    """Create-only metadata inside the participant container; reject mismatch."""
    from uuid import UUID
    if task_code not in TASKS or str(UUID(task_id)) != task_id:
        raise RuntimeError('Invalid release metadata')
    remote = "\nimport json, os, sys, tempfile\nroot = '/opt/nerds/released-reference'\nref = root + '/current'\ntarget = root + '/active-task.json'\nwork = '/home/user/fuzz-study/work'\nreference = '/home/user/fuzz-study/reference'\nif not (os.path.isdir(root) and os.path.isfile(ref + '/Makefile') and\n        os.path.isfile(work + '/Makefile') and\n        os.path.islink(reference) and os.path.realpath(reference) == ref):\n    raise SystemExit('STOP: Protected task workspace is not correctly provisioned')\nexpected = {'position': 1, 'task_code': sys.argv[1],\n            'task_run_id': sys.argv[2], 'status': 'ready'}\ndef check():\n    if os.path.islink(target) or not os.path.isfile(target):\n        raise SystemExit('STOP: Unexpected active task metadata file')\n    with open(target, encoding='utf-8') as fp:\n        existing = json.load(fp)\n    if existing != expected:\n        raise SystemExit('STOP: Existing task metadata disagrees with database')\nif os.path.lexists(target):\n    check()\nelse:\n    fd, stage = tempfile.mkstemp(prefix='.active-task-', dir=root)\n    try:\n        os.chmod(stage, 0o644)\n        with os.fdopen(fd, 'w', encoding='utf-8') as fp:\n            json.dump(expected, fp, sort_keys=True)\n            fp.flush()\n            os.fsync(fp.fileno())\n        try:\n            os.link(stage, target)\n        except FileExistsError:\n            pass\n    finally:\n        if os.path.exists(stage):\n            os.unlink(stage)\n    check()\nprint('PASS: Task 1 release metadata matches DB assignment')\n"
    command(['docker', 'exec', '-u', 'root', name,
             'python3', '-c', remote, task_code, task_id])

def mark_ready(pid, instance_id):
    returned = sql(f"""
        UPDATE fuzz_pilot.task_runs AS t
        SET status = 'ready'
        FROM fuzz_pilot.study_sessions AS s
        WHERE t.session_id = s.session_id
          AND s.participant_id = '{pid}'
          AND s.study_phase = 'pilot1'
          AND s.status = 'assigned'
          AND s.instance_id = '{instance_id}'
          AND t.position = 1 AND t.status = 'locked'
          AND EXISTS (
            SELECT 1 FROM fuzz_pilot.task_runs AS t2
            WHERE t2.session_id = s.session_id
              AND t2.position = 2 AND t2.status = 'locked'
          )
        RETURNING t.task_run_id::text;
    """)
    if not returned or len(returned.splitlines()) != 1:
        raise RuntimeError("Provisioned files, but could not mark the first task ready")
    return returned.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--participant-id", required=True)
    parser.add_argument("--container", default="nerds-pilot1-runtime")
    parser.add_argument("--apply", action="store_true", help="Bind container and provision task 1")
    args = parser.parse_args()

    if not PID_RE.fullmatch(args.participant_id):
        parser.error("Participant ID must be 24 lowercase hexadecimal characters")
    if not CONTAINER_RE.fullmatch(args.container):
        parser.error("Container must have a nerds-pilot1-* name")

    instance_id = inspect_container(args.container)
    a = lookup(args.participant_id)
    if a.status != "assigned":
        raise RuntimeError("Session is not in the assigned state")
    if a.instance_id and (a.instance_id, a.instance_name) != (instance_id, args.container):
        raise RuntimeError("Session is already bound to a different instance")
    if a.second_status != "locked":
        raise RuntimeError("Second task is not locked")

    print(f"Participant: {args.participant_id}")
    print(f"Session:     {a.session_id}")
    print(f"Container:   {args.container} ({instance_id})")
    print(f"Task 1:     {a.first_task} [{a.first_status}]")
    print(f"Task 2:     {a.second_task} [{a.second_status}]")

    if a.first_status == "ready":
        if a.instance_id != instance_id:
            raise RuntimeError("Ready task is not bound to this instance")
        verify_files(args.container)
        existing_id = assigned_task_id(args.participant_id, instance_id,
                                       1, a.first_task, 'ready')
        ensure_active_task_metadata(args.container, a.first_task, existing_id)
        print("Already assigned and provisioned; verified task metadata")
        return
    if a.first_status != "locked":
        raise RuntimeError("First task must be locked or ready")
    if not args.apply:
        print("DRY RUN: no database or container changes made; use --apply to proceed")
        return

    claim(args.participant_id, instance_id, args.container)
    print("Container bound to study session; task remains locked")
    provision(args.container, a.first_task)
    print("Task files provisioned")
    verify_files(args.container)
    task_id = mark_ready(args.participant_id, instance_id)
    ensure_active_task_metadata(args.container, a.first_task, task_id)
    final = lookup(args.participant_id)
    if final.first_status != "ready" or final.second_status != "locked":
        raise RuntimeError("Unexpected task statuses after provisioning")
    print("SUCCESS: task 1 is ready; task 2 remains locked; session remains assigned")
    print("No browser credentials issued; do not share a participant URL")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
