#!/usr/bin/env python3
"""Reversible R2D.2 UI-polish update for the *already-active* local split study.

Only replaces /home/user/www and /home/user/workspace_layout.py; the
participant, its active task, API startup flags, CLI, Firefox, DB, and Submit
stay in place. API and noVNC services restart to load those files.
"""
import argparse
import re
import subprocess
import tempfile
import time
from pathlib import Path

LIVE = "nerds-pilot1-browser-r1-test"
IMAGE = "devob_instance:r2d2-polish"
BASE = "/home/user/.r2d2-polish"
WWW = "/home/user/www"
LAYOUT = "/home/user/workspace_layout.py"
RC = "/home/user/.config/openbox/rc.xml"
RC_BACKUP = RC + ".r2d2-polish-backup"
RC_WAS_NEW = RC + ".r2d2-polish-was-new"


def run(*args, capture=False):
    p = subprocess.run(args, text=True, check=True,
                       stdout=subprocess.PIPE if capture else None)
    return p.stdout.strip() if capture else None


def sh(source, capture=False):
    return run("docker", "exec", LIVE, "sh", "-ec", source, capture=capture)


def as_user(*args):
    return run("docker", "exec", "-u", "user", "-e", "DISPLAY=:1",
               "-e", "XAUTHORITY=/home/user/.Xauthority", LIVE, *args)


def prepare():
    running = run("docker", "inspect", "-f", "{{.State.Running}}",
                  LIVE, capture=True)
    if running != "true":
        raise RuntimeError("Local participant container is not running")
    sh("test -f /home/user/workspace_layout.py && test -d /home/user/www")
    sh("grep -q 'PILOT1_SPLIT_WORKSPACE_ENABLED=1' /home/user/services/api/run")
    wm = sh("DISPLAY=:1 XAUTHORITY=/home/user/.Xauthority wmctrl -m | head -n 1",
            capture=True).lower()
    if "openbox" not in wm:
        raise RuntimeError("Expected the active Openbox desktop")
    run("docker", "image", "inspect", IMAGE, capture=True)


def bundle_in(root):
    html = (root / "index.html").read_text(encoding="utf-8")
    match = re.search(r"static/js/main\.[A-Za-z0-9_-]+\.js", html)
    if not match:
        raise RuntimeError("Built index.html has no main bundle")
    js = (root / match.group(0)).read_text(encoding="utf-8")
    for token in (
        "Restore windows",
        "Resize CLI and Firefox panes",
        "Clipboard privacy and study recording",
        "Skipping saves your work and ends this task.",
    ):
        if token not in js:
            raise RuntimeError("Staged React build missing " + token)
    return match.group(0)


def stage():
    with tempfile.TemporaryDirectory(prefix="nerds-r2d2-polish-") as path:
        root = Path(path)
        (root / "www").mkdir()
        container = run("docker", "create", "--network", "none",
                        "--entrypoint", "/bin/true", IMAGE, capture=True)
        try:
            run("docker", "cp", container + ":/home/user/www/.", str(root / "www"))
            run("docker", "cp", container + ":/home/user/workspace_layout.py",
                str(root / "workspace_layout.py"))
        finally:
            run("docker", "rm", container)
        main = bundle_in(root / "www")
        helper = (root / "workspace_layout.py").read_text(encoding="utf-8")
        if "divider_percent" not in helper or "CLI and Firefox are not adjacent" not in helper:
            raise RuntimeError("Updated X11 layout helper missing")
        run("docker", "cp", str(root / "www"), LIVE + ":" + BASE + "-next-www")
        run("docker", "cp", str(root / "workspace_layout.py"),
            LIVE + ":" + BASE + "-next-layout.py")
        return main


def get_server_bundle():
    script = (
        "import re,urllib.request;"
        "h=urllib.request.urlopen('http://127.0.0.1:8888/',timeout=10)"
        ".read().decode();"
        "m=re.search(r'static/js/main\\.[A-Za-z0-9_-]+\\.js',h);"
        "print(m.group(0) if m else 'NOT_FOUND')"
    )
    return run("docker", "exec", LIVE, "python3", "-c", script, capture=True)


def check_split():
    script = (
        "import json,urllib.request;"
        "d=json.dumps({'mode':'split','cli_percent':50}).encode();"
        "r=urllib.request.Request('http://127.0.0.1:60000/api/workspace/layout',"
        "data=d,headers={'Content-Type':'application/json'},method='POST');"
        "a=json.load(urllib.request.urlopen(r,timeout=12));"
        "assert a['mode']=='split' and 'divider_percent' in a,a;"
        "print('Actual X11 divider:',a['divider_percent'],'percent');"
        "print('Window bounds:',a['windows'])"
    )
    return run("docker", "exec", LIVE, "python3", "-c", script, capture=True)


def set_openbox_buttons():
    # Keep the title and Close for dialogs, remove Iconify and Maximize.
    # The original config or an absence-marker is preserved for rollback.
    script = String_rc_update
    as_user("python3", "-c", script)
    as_user("openbox", "--reconfigure")


String_rc_update = r"""
import pathlib,re,shutil
rc=pathlib.Path('/home/user/.config/openbox/rc.xml')
bak=pathlib.Path(str(rc)+'.r2d2-polish-backup')
new=pathlib.Path(str(rc)+'.r2d2-polish-was-new')
rc.parent.mkdir(parents=True,exist_ok=True)
if bak.exists() or new.exists():
    raise SystemExit('STOP: Openbox polish configuration already staged')
if rc.exists():
    shutil.copy2(rc,bak)
    src=rc.read_text()
else:
    new.touch()
    src=pathlib.Path('/etc/xdg/openbox/rc.xml').read_text()
patched,count=re.subn(r'(<titleLayout>)[^<]*(</titleLayout>)',
                      r'\g<1>NLC\g<2>',src,count=1)
if count!=1:
    raise SystemExit('STOP: Could not locate Openbox title button configuration')
rc.write_text(patched)
"""


def restore_openbox():
    script = r"""
import pathlib,shutil
rc=pathlib.Path('/home/user/.config/openbox/rc.xml')
bak=pathlib.Path(str(rc)+'.r2d2-polish-backup')
new=pathlib.Path(str(rc)+'.r2d2-polish-was-new')
if bak.exists():
    shutil.move(str(bak),str(rc))
elif new.exists():
    rc.unlink(missing_ok=True)
    new.unlink()
"""
    as_user("python3", "-c", script)
    as_user("openbox", "--reconfigure")


def restore_files():
    stamp = str(int(time.time() * 1_000_000))
    sh(f"""
      if [ -d {BASE}-old-www ]; then
        if [ -d {WWW} ]; then mv {WWW} {BASE}-failed-www-{stamp}; fi
        mv {BASE}-old-www {WWW}
      fi
      if [ -f {BASE}-old-layout.py ]; then
        if [ -f {LAYOUT} ]; then mv {LAYOUT} {BASE}-failed-layout-{stamp}.py; fi
        mv {BASE}-old-layout.py {LAYOUT}
      fi
      sv restart /home/user/services/api
      sv restart /home/user/services/novnc
    """)


def apply():
    prepare()
    sh(f"""test ! -e {BASE}-old-www &&
            test ! -e {BASE}-old-layout.py &&
            test ! -e {BASE}-next-www &&
            test ! -e {BASE}-next-layout.py""")
    expected = stage()
    try:
        sh(f"""
          mv {WWW} {BASE}-old-www
          mv {LAYOUT} {BASE}-old-layout.py
          mv {BASE}-next-www {WWW}
          mv {BASE}-next-layout.py {LAYOUT}
          sv restart /home/user/services/api
          sv restart /home/user/services/novnc
        """)
        actual = get_server_bundle()
        if actual != expected:
            raise RuntimeError(f"noVNC serves {actual}, expected {expected}")
        print(check_split(), flush=True)
        set_openbox_buttons()
    except Exception:
        print("Update unverified; restoring previous R2D.2 frontend and layout.", flush=True)
        try:
            restore_openbox()
        finally:
            restore_files()
        raise
    print("PASS: Single aligned splitter and Restore windows control deployed")
    print("PASS: Openbox minimize/maximize buttons disabled")
    print("PASS: Active participant task, CLI, Firefox, clipboard and database preserved")
    print("Refresh Edge with Ctrl+Shift+R")
    print("Rollback: python3 scripts/r2d2_polish_live.py rollback")


def rollback():
    prepare()
    available = sh(f"test -d {BASE}-old-www && test -f {BASE}-old-layout.py "
                   "&& echo yes || echo no", capture=True)
    if available != "yes":
        print("No active R2D.2 polish backup; nothing to roll back.")
        return
    restore_openbox()
    restore_files()
    print("PASS: Previous R2D.2 UI/layout restored, without changing task/data.")


def status():
    prepare()
    print("noVNC:", get_server_bundle())
    print("API:", sh("sv status /home/user/services/api", capture=True))
    print("noVNC service:", sh("sv status /home/user/services/novnc", capture=True))
    print("Polish backup:",
          sh(f"test -d {BASE}-old-www && echo active || echo not-active", capture=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("apply", "rollback", "status"))
    args = parser.parse_args()
    try:
        {"apply": apply, "rollback": rollback, "status": status}[args.action]()
    except (OSError, RuntimeError, subprocess.CalledProcessError, AssertionError) as exc:
        parser.exit(1, f"STOP: {exc}\n")
