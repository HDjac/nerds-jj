#!/usr/bin/env python3
"""Switch only the live local VNC window manager Matchbox -> Openbox.

One-time R2D.2 workstation change. This *restarts the VNC display and its GUI
clients*, so use between fuzzing campaigns. Database, task and container are
not replaced. A copy of the old VNC service run script is retained.
"""
import argparse
import subprocess
import time
from pathlib import Path

LIVE = "nerds-pilot1-browser-r1-test"
SCRIPT = "/home/user/services/vnc/run"
BACKUP = "/home/user/services/vnc/run-before-r2d2-openbox"
STAGED = "/home/user/services/vnc/run-r2d2-openbox-next"


def cmd(*args, output=False, check=True):
    proc = subprocess.run(args, text=True, check=check,
                          stdout=subprocess.PIPE if output else None)
    return proc.stdout.strip() if output else proc.returncode


def shell(code, output=False):
    return cmd("docker", "exec", LIVE, "sh", "-ec", code, output=output)


def wm_name():
    return shell(
        "DISPLAY=:1 XAUTHORITY=/home/user/.Xauthority "
        "wmctrl -m 2>/dev/null | head -n 1", output=True)


def restart_vnc():
    shell("sv restart /home/user/services/vnc")
    last = ""
    for _ in range(20):
        time.sleep(1)
        last = wm_name()
        if last.startswith("Name: openbox") or last.startswith("Name: matchbox"):
            return last
    return last


def install():
    existing = cmd("docker", "exec", LIVE, "sh", "-ec",
                   "command -v openbox >/dev/null", check=False)
    if existing == 0:
        return
    print("Installing Openbox into the running local container.", flush=True)
    cmd("docker", "exec", "-u", "0", LIVE, "sh", "-ec",
        "apt-get update && DEBIAN_FRONTEND=noninteractive "
        "apt-get install -y --no-install-recommends openbox")
    shell("command -v openbox >/dev/null")


def activate():
    running = cmd("docker", "inspect", "-f", "{{.State.Running}}",
                  LIVE, output=True)
    if running != "true":
        raise RuntimeError("Participant container is not running")
    existing = wm_name()
    print("Current desktop:", existing, flush=True)
    if "openbox" in existing:
        print("ALREADY ACTIVE: Openbox. No VNC restart needed.")
        return
    if "matchbox" not in existing:
        raise RuntimeError("Unexpected running window manager; no changes made")
    shell(f"test ! -e {BACKUP} && test ! -e {STAGED}")
    install()  # If download fails, do not touch VNC startup.

    local = Path(__file__).resolve().parents[1] / "instance/services/vnc/run"
    if not local.is_file() or "openbox --sm-disable" not in local.read_text():
        raise RuntimeError("Checkout does not have the expected R2D.2 startup script")
    cmd("docker", "cp", str(local), f"{LIVE}:{STAGED}")
    shell(f"cp -p {SCRIPT} {BACKUP}; mv {STAGED} {SCRIPT}; chmod 0755 {SCRIPT}")
    try:
        actual = restart_vnc()
        if not actual.startswith("Name: openbox"):
            raise RuntimeError(f"Openbox did not start; window manager: {actual!r}")
    except Exception:
        print("Openbox startup unverified, restoring previous Matchbox VNC script.", flush=True)
        shell(f"cp -p {BACKUP} {SCRIPT}; chmod 0755 {SCRIPT}")
        restart_vnc()
        raise

    print("PASS: VNC desktop running under Openbox", flush=True)
    print("Existing task and PostgreSQL data were not modified.")
    print("Existing Firefox/xterm GUI sessions were restarted with the display.")
    print("NEXT: python3 scripts/r2d2_live.py apply")
    print("WM rollback: python3 scripts/r2d2_openbox_live.py rollback")


def rollback():
    shell(f"test -f {BACKUP}")
    current = wm_name()
    if current.startswith("Name: matchbox"):
        print("ALREADY RESTORED: Matchbox is active.")
        return
    shell(f"cp -p {BACKUP} {SCRIPT}; chmod 0755 {SCRIPT}")
    actual = restart_vnc()
    if not actual.startswith("Name: matchbox"):
        raise RuntimeError(f"Could not confirm Matchbox restart: {actual}")
    print("PASS: Matchbox window manager restored; participant task/data unchanged.")
    print("If split mode is still active, use: python3 scripts/r2d2_live.py rollback")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["apply", "rollback", "status"])
    args = parser.parse_args()
    try:
        if args.action == "apply":
            activate()
        elif args.action == "rollback":
            rollback()
        else:
            print("Window manager:", wm_name())
            print("VNC service:", shell("sv status /home/user/services/vnc", output=True))
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"STOP: {exc}\n")
