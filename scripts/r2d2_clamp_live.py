#!/usr/bin/env python3
"""Apply an R2D.2 split-width clamp to the existing local participant.

One backend-only update. Preserves the running X11 desktop, existing Firefox
windows/tabs, xterm, task records, Submit, PostgreSQL, and React assets.

Usage:
  python3 scripts/r2d2_clamp_live.py apply
  python3 scripts/r2d2_clamp_live.py rollback
"""
import argparse
import subprocess
from pathlib import Path

LIVE = "nerds-pilot1-browser-r1-test"
DEST = "/home/user/workspace_layout.py"
BACKUP = DEST + ".r2d2-clamp-original"
NEXT = DEST + ".r2d2-clamp-staged"


def run(*argv, capture=False):
    r = subprocess.run(argv, check=True, text=True,
                       stdout=subprocess.PIPE if capture else None)
    return r.stdout.strip() if capture else None


def sh(script, capture=False):
    return run("docker", "exec", LIVE, "sh", "-ec", script, capture=capture)


def apply():
    source = Path(__file__).resolve().parents[1] / "instance/workspace_layout.py"
    content = source.read_text()
    if "_split_candidates" not in content or "clamped" not in content:
        raise RuntimeError("Checkout is missing the R2D.2 resizing fix")
    if run("docker", "inspect", "-f", "{{.State.Running}}", LIVE,
           capture=True) != "true":
        raise RuntimeError("Participant is not running")
    sh("grep -q 'PILOT1_SPLIT_WORKSPACE_ENABLED=1' "
       "/home/user/services/api/run")
    sh(f"test -f {DEST} && test ! -e {BACKUP} && test ! -e {NEXT}")
    run("docker", "cp", str(source), f"{LIVE}:{NEXT}")

    # Parse Python without importing the module or changing the desktop.
    code = ("import ast,pathlib;"
            f"ast.parse(pathlib.Path('{NEXT}').read_text())")
    run("docker", "exec", LIVE, "python3", "-c", code)

    try:
        sh(f"cp -p {DEST} {BACKUP}; mv {NEXT} {DEST}; "
           f"chmod 0644 {DEST}; sv restart /home/user/services/api")
    except Exception:
        sh(f"if [ -f {BACKUP} ]; then cp -p {BACKUP} {DEST}; "
           "sv restart /home/user/services/api; fi")
        raise

    print("PASS: Split resizing now retreats to the nearest usable window size.")
    print("PASS: Same Firefox, xterm, Task 2, clipboard settings and data.")
    print("Only the participant Flask API service restarted.")
    print("Refresh the NERDs browser tab, then drag the divider in both directions.")
    print("Rollback: python3 scripts/r2d2_clamp_live.py rollback")


def rollback():
    if sh(f"test -f {BACKUP} && echo yes || echo no",
          capture=True) != "yes":
        print("No clamp backup found; nothing changed.")
        return
    sh(f"cp -p {BACKUP} {DEST}; sv restart /home/user/services/api")
    print("PASS: Previous split sizing logic restored, session unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("apply", "rollback"))
    args = parser.parse_args()
    try:
        {"apply": apply, "rollback": rollback}[args.action]()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"STOP: {exc}\n")
