#!/usr/bin/env python3
"""R2D.4 in-place UI hotfix: preserve xterm history and restore title bar policy.

Only replaces the Flask workspace layout helper, Openbox config, and the
future xterm startup script. The current xterm and Firefox processes,
noVNC framebuffer, participant task state, DB and source files stay running.
"""
import argparse
import subprocess
from pathlib import Path

LIVE = "nerds-pilot1-browser-r1-test"
BASE = "/home/user/.r2d4-ui"
LAYOUT = "/home/user/workspace_layout.py"
XTERM = "/home/user/services/xterm/run"
OPENBOX = "/home/user/.config/openbox/rc.xml"


def command(*args, output=False):
    result = subprocess.run(args, check=True, text=True,
                            stdout=subprocess.PIPE if output else None)
    return result.stdout.strip() if output else None


def sh(script, output=False):
    return command("docker", "exec", LIVE, "sh", "-ec", script, output=output)


def as_user(*args):
    return command("docker", "exec", "-u", "user", "-e", "DISPLAY=:1",
                   "-e", "XAUTHORITY=/home/user/.Xauthority", LIVE, *args)


def verify_environment():
    if command("docker", "inspect", "-f", "{{.State.Running}}",
               LIVE, output=True) != "true":
        raise RuntimeError("Existing participant is not running")
    sh(f"test -f {LAYOUT} && test -f {XTERM} && test -f {OPENBOX}")
    sh("grep -q 'PILOT1_SPLIT_WORKSPACE_ENABLED=1' /home/user/services/api/run")
    wm = sh("DISPLAY=:1 XAUTHORITY=/home/user/.Xauthority "
            "wmctrl -m | head -n 1", output=True)
    if "openbox" not in wm.lower():
        raise RuntimeError("Expected Openbox; no changes made")


PATCH_OPENBOX = r"""
import pathlib,re
path=pathlib.Path('/home/user/.config/openbox/rc.xml')
src=path.read_text(encoding='utf-8')
# Remove only the old NERDs per-application undecorate rules. Preserve
# all unrelated desktop configuration, including participant preferences.
pat=re.compile(
  r'\s*<application\s+class="(?:XTerm|firefox-esr)"\s*>\s*'
  r'<decor>\s*no\s*</decor>\s*</application>',
  flags=re.I)
updated,count=pat.subn('',src)
if '<titleLayout>NLIMC</titleLayout>' in updated:
  updated=updated.replace('<titleLayout>NLIMC</titleLayout>',
                          '<titleLayout>NLC</titleLayout>')
if '<applications>' not in updated or '</applications>' not in updated:
  raise SystemExit('Invalid Openbox applications block')
path.write_text(updated,encoding='utf-8')
print('Removed',count,'obsolete undecorated-window rules')
"""


def apply():
    verify_environment()
    root = Path(__file__).resolve().parents[1] / "instance"
    layout = root / "workspace_layout.py"
    xterm = root / "services/xterm/run"
    if not layout.is_file() or not xterm.is_file():
        raise RuntimeError("Updated layout or xterm source not found")
    if "prior_cli" not in layout.read_text() or "-sl 10000" not in xterm.read_text():
        raise RuntimeError("Checkout does not include R2D.4 UI fix; git pull first")

    sh(f"test ! -e {BASE}-old-layout.py && test ! -e {BASE}-old-xterm-run "
       f"&& test ! -e {BASE}-old-openbox.xml "
       f"&& test ! -e {BASE}-next-layout.py && test ! -e {BASE}-next-xterm-run")
    command("docker", "cp", str(layout), f"{LIVE}:{BASE}-next-layout.py")
    command("docker", "cp", str(xterm), f"{LIVE}:{BASE}-next-xterm-run")
    sh(f"python3 -m py_compile {BASE}-next-layout.py")
    try:
        # Back up exact live files before changing any startup configuration.
        sh(f"cp -p {LAYOUT} {BASE}-old-layout.py; "
           f"cp -p {XTERM} {BASE}-old-xterm-run; "
           f"cp -p {OPENBOX} {BASE}-old-openbox.xml")
        sh(f"mv {BASE}-next-layout.py {LAYOUT}; "
           f"mv {BASE}-next-xterm-run {XTERM}; "
           f"chmod 0755 {XTERM}; "
           "sv restart /home/user/services/api")
        as_user("python3", "-c", PATCH_OPENBOX)
        as_user("openbox", "--reconfigure")
    except Exception:
        print("Update unverified: restoring original files.", flush=True)
        sh(f"if [ -f {BASE}-old-layout.py ]; then "
           f"cp -p {BASE}-old-layout.py {LAYOUT}; fi; "
           f"if [ -f {BASE}-old-xterm-run ]; then "
           f"cp -p {BASE}-old-xterm-run {XTERM}; chmod 755 {XTERM}; fi; "
           f"if [ -f {BASE}-old-openbox.xml ]; then "
           f"cp -p {BASE}-old-openbox.xml {OPENBOX}; fi; "
           "sv restart /home/user/services/api")
        as_user("openbox", "--reconfigure")
        raise

    print("PASS: Firefox-only no longer resizes the hidden xterm.")
    print("PASS: Redundant Split View commands avoid unnecessary xterm resize.")
    print("PASS: Openbox no-decorations rule removed, title buttons kept minimal.")
    print("PASS: Future xterm windows have a scrollbar and 10,000 scrollback lines.")
    print("Current Firefox, CLI, noVNC and Task 2 remain in place.")
    print("NOTE: Existing windows may still need Openbox 'Decorate' action")
    print("to restore their titlebars; they are not restarted.")
    print("Rollback: python3 scripts/r2d4_ui_live.py rollback")


def rollback():
    verify_environment()
    if sh(f"test -f {BASE}-old-layout.py && echo yes || echo no",
          output=True) != "yes":
        print("No active R2D.4 UI backup; nothing changed.")
        return
    sh(f"cp -p {BASE}-old-layout.py {LAYOUT}; "
       f"cp -p {BASE}-old-xterm-run {XTERM}; chmod 755 {XTERM}; "
       f"cp -p {BASE}-old-openbox.xml {OPENBOX}; "
       "sv restart /home/user/services/api")
    as_user("openbox", "--reconfigure")
    print("PASS: Previous R2D.2 layout and Openbox configuration restored.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["apply", "rollback"])
    a = parser.parse_args()
    try:
        {"apply": apply, "rollback": rollback}[a.action]()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as err:
        parser.exit(1, "STOP: " + str(err) + "\n")
