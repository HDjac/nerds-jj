#!/usr/bin/env python3
"""Release 2C local-only participant frontend/API activation.

Only touches nerds-pilot1-browser-r1-test's /home/user/www and
/home/user/services/api/run. The Submit canary must already be activated.
Does not alter task files, session rows, Docker networks, credentials or images.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

LIVE = "nerds-pilot1-browser-r1-test"
SUBMIT = "nerds-pilot1-submit-r2b2-canary"
STAGE = "devob_instance:r2c-local-text-stage"
STAGE_ID = "sha256:ae2e57eb1166f168e768c8a2840f53de96e730401a336b09ad9bda8160d4b0d7"
BASE = Path.home() / "nerds-r2c-activation"
STATE_PATH = BASE / "participant-activation-state.json"
REPO = Path.home() / "nerds-r2c-provenance"
OLD_FLAG = "PILOT1_CLIPBOARD_TEXT_ENABLED=0"
NEW_FLAG = "PILOT1_CLIPBOARD_TEXT_ENABLED=1"

class Stop(RuntimeError):
    pass


def run(args, *, capture=True, check=True, stdin=None):
    p = subprocess.run(args, text=True, input=stdin,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None)
    if check and p.returncode:
        detail = ((p.stderr or "") + "\n" + (p.stdout or "")).strip()
        raise Stop("Command failed: " + " ".join(map(str, args[:4])) + "\n" + detail[-1200:])
    return p


def docker(*args, capture=True):
    return run(["docker", *args], capture=capture)


def inspect(name, kind="container"):
    data = docker(kind, "inspect", name).stdout
    return json.loads(data)[0]


def exec_in(command, capture=True):
    return docker("exec", LIVE, "sh", "-ec", command, capture=capture)


def assert_image():
    item = inspect(STAGE, kind="image")
    if item["Id"] != STAGE_ID:
        raise Stop("Unexpected R2C frontend image ID; expected " + STAGE_ID)
    print("PASS: Verified Release 2C frontend staging image")


def assert_repo():
    if not REPO.is_dir():
        raise Stop("Missing Release 2C worktree " + str(REPO))
    commit = run(["git", "-C", str(REPO), "rev-parse", "HEAD"]).stdout.strip()
    if not commit.startswith("56e0cfd"):
        raise Stop("Expected Release 2C commit 56e0cfd, got " + commit[:12])
    dirty = run(["git", "-C", str(REPO), "status", "--porcelain"]).stdout.strip()
    if dirty:
        raise Stop("Release 2C worktree is dirty; review before activation")
    print("PASS: Verified clean Release 2C source checkpoint")


def flags(name):
    c = inspect(name)
    return {k: v for k, v in (s.split("=", 1) for s in c["Config"].get("Env", []) if "=" in s)}


def preflight():
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text())
        raise Stop("Participant activation state already exists (" + state.get("phase", "?") + "). Use status/rollback, do not reapply.")
    assert_repo()
    assert_image()
    l = inspect(LIVE)
    s = inspect(SUBMIT)
    if not l["State"]["Running"] or not s["State"]["Running"]:
        raise Stop("Participant and Submit canary must both be running")
    fl = flags(SUBMIT)
    if (fl.get("PILOT1_CLIPBOARD_INGEST_ENABLED"), fl.get("PILOT1_CLIPBOARD_TEXT_ENABLED")) != ("1", "1"):
        raise Stop("Submit canary not yet text-enabled")
    cmd = exec_in("cat /home/user/services/api/run").stdout
    if cmd.count(OLD_FLAG) != 1 or NEW_FLAG in cmd:
        raise Stop("Participant API run script is not in expected metadata-only state")
    if "PILOT1_CLIPBOARD_INGEST_ENABLED=1" not in cmd:
        raise Stop("Participant API clipboard ingestion unexpectedly disabled")
    exec_in("test -f /home/user/www/index.html && test -x /home/user/services/api/run && sv status /home/user/services/api && sv status /home/user/services/novnc")
    print("PASS: Participant API and noVNC healthy; participant text flag OFF")
    print("PASS: Submit canary healthy with clipboard text flag ON")
    print("PASS: No participant changes made")


def save_state(state):
    BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
    os.chmod(temp, 0o600)
    os.replace(temp, STATE_PATH)


def read_state():
    if not STATE_PATH.is_file():
        raise Stop("No Release 2C participant activation state found")
    state = json.loads(STATE_PATH.read_text())
    if state.get("participant") != LIVE:
        raise Stop("State participant mismatch")
    tag = state.get("tag", "")
    if not re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", tag):
        raise Stop("Unexpected state tag")
    return state


def stage_assets(tag, backup):
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    docker("cp", LIVE + ":/home/user/www", str(backup / "www-original"))
    docker("cp", LIVE + ":/home/user/services/api/run", str(backup / "api-run-original"))
    original = (backup / "api-run-original").read_text()
    if original.count(OLD_FLAG) != 1 or NEW_FLAG in original:
        raise Stop("Unexpected API flags in backup; nothing deployed")
    new = backup / "api-run-r2c"
    new.write_text(original.replace(OLD_FLAG, NEW_FLAG, 1))
    new.chmod(0o755)

    stage_container = "nerds-r2c-extract-" + tag.lower()
    docker("create", "--name", stage_container, "--network", "none", STAGE)
    try:
        docker("cp", stage_container + ":/home/user/www", str(backup / "www-r2c"))
    finally:
        docker("rm", "-f", stage_container)

    if not (backup / "www-r2c" / "index.html").is_file():
        raise Stop("Staged frontend missing index.html")
    static = backup / "www-r2c" / "static" / "js"
    jss = list(static.glob("*.js"))
    if not jss:
        raise Stop("Staged frontend missing JS bundle")
    if not any(b"Clipboard privacy and study recording" in x.read_bytes() for x in jss):
        raise Stop("Text capture notice not found in staged JS; check frontend image")
    if not any(b"log-clipboard-event" in x.read_bytes() for x in jss):
        raise Stop("Clipboard telemetry endpoint not found in staged JS")
    print("PASS: Staged frontend contains clipboard telemetry and Release 2C notice")
    return new


def restore(state):
    tag = state["tag"]
    old_www = "/home/user/www-r2c-original-" + tag
    old_run = "/home/user/services/api/run-r2c-original-" + tag
    inactive_www = "/home/user/www-r2c-inactive-" + tag
    inactive_run = "/home/user/services/api/run-r2c-inactive-" + tag
    # The originals are *renamed* inside the participant so a rollback does
    # not depend on container recreation or a host-side Docker volume.
    shell = f'''
if [ -d '{old_www}' ]; then
  if [ -d /home/user/www ] && [ ! -e '{inactive_www}' ]; then
    mv /home/user/www '{inactive_www}'
  fi
  if [ ! -e /home/user/www ]; then mv '{old_www}' /home/user/www; fi
fi
if [ -f '{old_run}' ]; then
  if [ -f /home/user/services/api/run ] && [ ! -e '{inactive_run}' ]; then
    mv /home/user/services/api/run '{inactive_run}'
  fi
  if [ ! -e /home/user/services/api/run ]; then
    mv '{old_run}' /home/user/services/api/run
  fi
fi
sv restart /home/user/services/api
'''
    exec_in(shell)
    active = exec_in("cat /home/user/services/api/run").stdout
    if OLD_FLAG not in active or NEW_FLAG in active:
        raise Stop("Rollback did not restore metadata-only API flag")
    print("PASS: Participant frontend and API restored to prior version")
    print("PASS: Submit canary remains unchanged (text flag ON); frontend/API cannot send text")


def apply():
    preflight()
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    backup = BASE / ("participant-backup-" + tag)
    # Do not create a state until the staged artifacts and host backup are valid.
    new = stage_assets(tag, backup)
    state = {"participant": LIVE, "tag": tag, "backup": str(backup), "phase": "prepared",
             "stage_image": STAGE_ID}
    save_state(state)
    try:
        new_www = "/home/user/www-r2c-next-" + tag
        new_run = "/home/user/services/api/run-r2c-next-" + tag
        old_www = "/home/user/www-r2c-original-" + tag
        old_run = "/home/user/services/api/run-r2c-original-" + tag
        docker("cp", str(backup / "www-r2c"), LIVE + ":" + new_www)
        docker("cp", str(new), LIVE + ":" + new_run)
        exec_in(f"test -f '{new_www}/index.html' && test -f '{new_run}' && chmod 755 '{new_run}'")
        state["phase"] = "applying"
        save_state(state)
        exec_in(f"mv /home/user/www '{old_www}' && mv '{new_www}' /home/user/www && "
                f"mv /home/user/services/api/run '{old_run}' && mv '{new_run}' /home/user/services/api/run && "
                "sv restart /home/user/services/api")
        script = exec_in("cat /home/user/services/api/run").stdout
        if NEW_FLAG not in script or OLD_FLAG in script:
            raise Stop("Participant API flag did not activate")
        exec_in("sv status /home/user/services/api && sv status /home/user/services/novnc")
        # A deliberately invalid synthetic clipboard request must be rejected
        # by the enabled route with 409, not by a disabled 404. No DB insert.
        code = 'import time, urllib.request, urllib.error\nq=urllib.request.Request("http://127.0.0.1:60000/log-clipboard-event",data=b"{}",headers={"Content-Type":"application/json"},method="POST")\nfor attempt in range(12):\n    try:\n        urllib.request.urlopen(q,timeout=3)\n        raise SystemExit("Unexpected successful response to invalid clipboard payload")\n    except urllib.error.HTTPError as e:\n        print("Clipboard API probe status:",e.code)\n        raise SystemExit(0 if e.code == 409 else 1)\n    except (urllib.error.URLError, TimeoutError):\n        time.sleep(0.5)\nraise SystemExit("Participant API did not become ready after restart")'
        docker("exec", LIVE, "python3", "-c", code)
        state["phase"] = "active"
        save_state(state)
        print("PASS: Release 2C frontend deployed with updated clipboard notice")
        print("PASS: Participant Flask text flag enabled; existing task/workspace retained")
        print("PASS: No task database, participant container or Docker network changed")
        print("NEXT: Hard-refresh your logged-in NERDs browser tab (Ctrl+Shift+R)")
        print("ROLLBACK: python3 ~/nerds-r2c-activation/nerds_r2c_participant_activate.py rollback")
    except Exception:
        print("ERROR: Activation did not verify. Attempting participant rollback...", file=sys.stderr)
        try:
            restore(state)
            state["phase"] = "rolled_back"
            save_state(state)
        except Exception as exc:
            state["phase"] = "manual_review"
            save_state(state)
            print("STOP: Automatic rollback incomplete: " + str(exc), file=sys.stderr)
        raise


def status():
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    print("Activation phase:", state.get("phase", "not activated"))
    if state:
        print("Backup:", state.get("backup"))
    print("Participant:", inspect(LIVE)["State"]["Status"])
    print("Participant API:", exec_in("grep 'PILOT1_CLIPBOARD_TEXT_ENABLED=' /home/user/services/api/run").stdout.strip())
    print("Submit:", inspect(SUBMIT)["State"]["Status"])
    print("Submit text flag:", flags(SUBMIT).get("PILOT1_CLIPBOARD_TEXT_ENABLED", "?"))
    print(exec_in("sv status /home/user/services/api && sv status /home/user/services/novnc").stdout.strip())


def rollback():
    state = read_state()
    if state["phase"] == "rolled_back":
        print("PASS: Participant already rolled back")
        return
    if state["phase"] not in ("prepared", "applying", "active", "manual_review"):
        raise Stop("Unexpected activation state: " + state["phase"])
    restore(state)
    state["phase"] = "rolled_back"
    save_state(state)
    print("NEXT: Hard-refresh NERDs browser tab (Ctrl+Shift+R)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("preflight", "apply", "status", "rollback"))
    args = ap.parse_args()
    try:
        {"preflight": preflight, "apply": apply, "status": status, "rollback": rollback}[args.action]()
    except (Stop, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("STOP:", exc, file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
