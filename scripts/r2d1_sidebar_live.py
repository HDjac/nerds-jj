#!/usr/bin/env python3
"""Reversible frontend-only sidebar update for the local R2D.1 participant.

Usage:
    python3 scripts/r2d1_sidebar_live.py apply
    python3 scripts/r2d1_sidebar_live.py rollback

Requires an image built as devob_instance:r2d1-sidebar from this checkout.
Preserves Flask API, clipboard flags, participant/task state, Submit and DB.
Only the frontend assets are replaced; noVNC is restarted to release its old web root.
"""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

LIVE = "nerds-pilot1-browser-r1-test"
DEFAULT_IMAGE = "devob_instance:r2d1-sidebar"
ACTIVE = "/home/user/www"
BACKUP = "/home/user/www-r2d1-before-sidebar-footer"
STAGED = "/home/user/www-r2d1-sidebar-staged"
POST = "/home/user/www-r2d1-after-sidebar-rollback"
NOVNC = "/home/user/services/novnc"


def cmd(*args, capture=False):
    result = subprocess.run(args, text=True, check=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def docker_shell(shell):
    cmd("docker", "exec", LIVE, "sh", "-ec", shell)


def check_live():
    state = cmd("docker", "inspect", "-f", "{{.State.Running}}", LIVE, capture=True)
    if state != "true":
        raise RuntimeError(f"Participant {LIVE} is not running")
    docker_shell("test -f /home/user/pilot1_task_descriptions.py && test -d /home/user/www")
    # The currently running R2D.1 API is intentionally not replaced by this script.


def staged_bundle_ok(root):
    html = (root / "index.html").read_text(encoding="utf-8")
    hit = re.search(r"static/js/main\.[a-zA-Z0-9_-]+\.js", html)
    if hit is None:
        raise RuntimeError("Staged React index does not reference a main bundle")
    bundle = (root / hit.group(0)).read_text(encoding="utf-8")
    checks = {
        "persistent task footer": "Skipping saves your work and ends this task." in bundle,
        "anonymous task view": "Task " in bundle and "Finish Task" in bundle,
        "redundant assignment removed": "Current assignment:" not in bundle,
        "R2C clipboard notice": "Clipboard privacy and study recording" in bundle,
    }
    for label, passed in checks.items():
        if not passed:
            raise RuntimeError("Staged frontend check failed: " + label)
    return hit.group(0)


def served_bundle():
    code = (
        "import re,urllib.request;"
        "h=urllib.request.urlopen('http://127.0.0.1:8888/',timeout=12)"
        ".read().decode('utf-8');"
        "m=re.search(r'static/js/main\\.[a-zA-Z0-9_-]+\\.js',h);"
        "print(m.group(0) if m else 'NOT_FOUND')"
    )
    return cmd("docker", "exec", LIVE, "python3", "-c", code, capture=True)


def apply(image):
    check_live()
    docker_shell(f"test ! -e {BACKUP} && test ! -e {STAGED}")
    with tempfile.TemporaryDirectory(prefix="nerds-r2d1-sidebar-") as tmp:
        root = Path(tmp) / "www"
        root.mkdir()
        created = cmd("docker", "create", "--network", "none",
                      "--entrypoint", "/bin/true", image, capture=True)
        try:
            cmd("docker", "cp", f"{created}:/home/user/www/.", str(root))
        finally:
            cmd("docker", "rm", created)
        bundle = staged_bundle_ok(root)
        cmd("docker", "cp", str(root), f"{LIVE}:{STAGED}")

    # Use a distinct backup path and refuse to overwrite it on a second run.
    # Failure recovery is local: if the swap/restart fails, restore old assets.
    try:
        docker_shell(
            f"test -d {ACTIVE} && test -d {STAGED}; "
            f"mv {ACTIVE} {BACKUP}; "
            f"mv {STAGED} {ACTIVE}; "
            f"sv restart {NOVNC}"
        )
        actual = served_bundle()
        if actual != bundle:
            raise RuntimeError(f"noVNC served {actual}, expected {bundle}")
    except Exception:
        print("Activation was not verified. Restoring previous frontend...")
        docker_shell(
            f"if [ -d {BACKUP} ]; then "
            f"if [ -d {ACTIVE} ]; then mv {ACTIVE} {STAGED}; fi; "
            f"mv {BACKUP} {ACTIVE}; sv restart {NOVNC}; fi"
        )
        raise
    print("PASS: Sidebar footer frontend active:", bundle)
    print("PASS: Existing participant, Flask API, task and data untouched")
    print("BACKUP:", BACKUP)
    print("ROLLBACK: python3 scripts/r2d1_sidebar_live.py rollback")


def rollback():
    check_live()
    # Restore only if the pre-footer backup still exists.
    docker_shell(f"test -d {BACKUP} && test ! -e {POST}")
    docker_shell(
        f"mv {ACTIVE} {POST}; "
        f"mv {BACKUP} {ACTIVE}; "
        f"sv restart {NOVNC}"
    )
    print("PASS: Previous R2D.1 frontend restored.")
    print("Saved newer frontend:", POST)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["apply", "rollback"])
    p.add_argument("--image", default=DEFAULT_IMAGE)
    a = p.parse_args()
    try:
        if a.action == "apply":
            apply(a.image)
        else:
            rollback()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        p.exit(1, f"STOP: {exc}\n")
