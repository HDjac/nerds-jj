#!/usr/bin/env python3
"""R2D.2 correction: preserve one Firefox window across views and fix focus.

This is a reversible, in-place source update of the running local Pilot 1
participant. Unlike a new image or VNC restart it leaves the GUI processes
and session data intact. A separate backup name is used so the earlier
Release 2D.2 rollback remains valid.
"""
import argparse
import subprocess
from pathlib import Path

LIVE = "nerds-pilot1-browser-r1-test"
HELPER = "/home/user/workspace_layout.py"
BACKUP = "/home/user/workspace_layout.py.r2d2-unify-before"
NEXT = "/home/user/workspace_layout.py.r2d2-unify-next"
RC = "/home/user/.config/openbox/rc.xml"
RC_BACKUP = RC + ".r2d2-unify-before"

CONFIG_PATCH = r"""
from pathlib import Path
import shutil
p=Path('/home/user/.config/openbox/rc.xml')
backup=Path(str(p)+'.r2d2-unify-before')
if not p.is_file():
    raise SystemExit('Openbox configuration unavailable')
if backup.exists():
    raise SystemExit('Openbox config backup already exists: refusing overwrite')
src=p.read_text(encoding='utf-8')
if '</applications>' not in src:
    raise SystemExit('Openbox applications section missing')
rules=[]
if 'class="XTerm"' not in src:
    rules.append('  <application class="XTerm"><decor>no</decor></application>')
if 'class="firefox-esr"' not in src:
    rules.append('  <application class="firefox-esr"><decor>no</decor></application>')
shutil.copy2(p,backup)
if rules:
    src=src.replace('</applications>','\n'.join(rules)+'\n</applications>',1)
    p.write_text(src,encoding='utf-8')
print('Openbox CLI/Firefox no-decoration rules configured')
"""

CONFIG_RESTORE = r"""
from pathlib import Path
import shutil
p=Path('/home/user/.config/openbox/rc.xml')
backup=Path(str(p)+'.r2d2-unify-before')
if backup.is_file():
    shutil.move(str(backup),str(p))
"""


def cmd(*args, capture=False):
    p = subprocess.run(args, check=True, text=True,
                       stdout=subprocess.PIPE if capture else None)
    return p.stdout.strip() if capture else None


def sh(script, capture=False):
    return cmd("docker", "exec", LIVE, "sh", "-ec", script, capture=capture)


def user(*argv):
    return cmd("docker", "exec", "-u", "user",
               "-e", "DISPLAY=:1",
               "-e", "XAUTHORITY=/home/user/.Xauthority",
               LIVE, *argv)


def validate():
    if cmd("docker", "inspect", "-f", "{{.State.Running}}", LIVE, capture=True) != "true":
        raise RuntimeError("Participant is not running")
    sh(f"test -f {HELPER} && test -f {RC}")
    sh("grep -q 'PILOT1_SPLIT_WORKSPACE_ENABLED=1' /home/user/services/api/run")
    manager = sh(
        "DISPLAY=:1 XAUTHORITY=/home/user/.Xauthority wmctrl -m | head -n 1",
        capture=True).lower()
    if "openbox" not in manager:
        raise RuntimeError("The active desktop is not Openbox")


def source_path():
    p = Path(__file__).resolve().parents[1] / "instance/workspace_layout.py"
    if not p.is_file():
        raise RuntimeError("Release 2D source file missing")
    contents = p.read_text(encoding="utf-8")
    for expected in ("_PRIMARY_FIREFOX_ID", "_focused_app_class", "divider_percent"):
        if expected not in contents:
            raise RuntimeError("Checkout is not updated: " + expected)
    return p


def apply():
    validate()
    source = source_path()
    sh(f"test ! -e {BACKUP} && test ! -e {NEXT}")
    sh(f"test ! -e {RC_BACKUP}")
    cmd("docker", "cp", str(source), f"{LIVE}:{NEXT}")
    sh(f"python3 -m py_compile {NEXT}")
    # Preserve task, GUI and existing web assets. Only reload the Flask API.
    try:
        sh(f"cp -p {HELPER} {BACKUP}; mv {NEXT} {HELPER}; chmod 644 {HELPER}")
        sh("sv restart /home/user/services/api")
        # Openbox's current settings are backed up before rules are added.
        user("python3", "-c", CONFIG_PATCH)
        user("openbox", "--reconfigure")
    except Exception:
        print("Correction was not fully applied; restoring previous files.", flush=True)
        try:
            user("python3", "-c", CONFIG_RESTORE)
            user("openbox", "--reconfigure")
        finally:
            sh(f"if [ -f {BACKUP} ]; then cp -p {BACKUP} {HELPER}; fi; "
               "sv restart /home/user/services/api")
        raise
    print("PASS: One stable Firefox window is selected across workspace layouts")
    print("PASS: Focus can recognize terminal and any Firefox window")
    print("PASS: Openbox native decoration rules updated (running windows may retain frames)")
    print("PASS: No container, VNC, Firefox, xterm, Task 2 or DB reset")
    print("Refresh Edge and select Split view / Restore windows.")
    print("Rollback: python3 scripts/r2d2_unify_live.py rollback")


def rollback():
    validate()
    before = sh(f"test -f {BACKUP} && echo yes || echo no", capture=True)
    if before != "yes":
        print("No active unified-window patch to roll back.")
        return
    user("python3", "-c", CONFIG_RESTORE)
    user("openbox", "--reconfigure")
    sh(f"cp -p {BACKUP} {HELPER}; mv {BACKUP} {BACKUP}.restored; "
       "sv restart /home/user/services/api")
    print("PASS: Previous R2D.2 layout/focus implementation restored")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("apply", "rollback"))
    args = parser.parse_args()
    try:
        {"apply": apply, "rollback": rollback}[args.action]()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
        parser.exit(1, f"STOP: {e}\n")
