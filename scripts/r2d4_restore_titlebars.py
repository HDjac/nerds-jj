#!/usr/bin/env python3
"""Restore Openbox title bars to already-running NERDs CLI/Firefox windows.

Unlike openbox --reconfigure alone, Openbox's documented Decorate action
changes the *existing* window. A temporary keyboard binding is installed,
then XTest sends that binding to the selected windows. Does not stop xterm,
Firefox, noVNC, or the participant's collector.

Run on the WSL host:
    python3 scripts/r2d4_restore_titlebars.py apply
    python3 scripts/r2d4_restore_titlebars.py rollback
"""
import subprocess
import sys

LIVE = "nerds-pilot1-browser-r1-test"
RC = "/home/user/.config/openbox/rc.xml"
BACKUP = RC + ".r2d4-titlebar-before"

PATCH = r"""
import pathlib, shutil, xml.etree.ElementTree as ET
p=pathlib.Path('/home/user/.config/openbox/rc.xml')
backup=pathlib.Path(str(p)+'.r2d4-titlebar-before')
if backup.exists(): raise SystemExit('Titlebar rollback backup exists; no overwrite')
src=p.read_text(encoding='utf-8')
if '</keyboard>' not in src: raise SystemExit('Openbox keyboard block missing')
if 'C-A-S-d' in src: raise SystemExit('Keybinding already in config; no overwrite')
# Confirm current config no longer forces xterm/Firefox undecorated.
import re
if re.search(r'<application\s+class="(?:XTerm|firefox-esr)"\s*>\s*'
             r'<decor>\s*no\s*</decor>', src, flags=re.I):
    raise SystemExit('Old <decor>no</decor> rules still active; stop')
binding='  <keybind key="C-A-S-d"><action name="Decorate"/></keybind>\n'
updated=src.replace('</keyboard>',binding+'</keyboard>',1)
ET.fromstring(updated)
shutil.copy2(p,backup)
p.write_text(updated,encoding='utf-8')
print('Installed temporary Openbox Decorate shortcut: Ctrl+Alt+Shift+D')
"""

RESTORE = r"""
import pathlib,shutil
p=pathlib.Path('/home/user/.config/openbox/rc.xml')
backup=pathlib.Path(str(p)+'.r2d4-titlebar-before')
if not backup.exists(): raise SystemExit('No titlebar patch backup; no change')
shutil.copy2(backup,p)
backup.unlink()
"""

# X11's XTest extension injects the same key combination as an operator.
# The Openbox Decorate action (not ToggleDecorations) is idempotent; it won't
# hide a titlebar if a window was already decorated.
XTEST = r"""
import ctypes,ctypes.util,subprocess,time
xlib=ctypes.util.find_library('X11')
testlib=ctypes.util.find_library('Xtst')
if not xlib or not testlib:
    print('XTest extension library unavailable; use manual shortcut')
    raise SystemExit(3)
x=ctypes.CDLL(xlib); xt=ctypes.CDLL(testlib)
x.XOpenDisplay.argtypes=[ctypes.c_char_p]
x.XOpenDisplay.restype=ctypes.c_void_p
x.XCloseDisplay.argtypes=[ctypes.c_void_p]
x.XStringToKeysym.argtypes=[ctypes.c_char_p]
x.XStringToKeysym.restype=ctypes.c_ulong
x.XKeysymToKeycode.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
x.XKeysymToKeycode.restype=ctypes.c_uint
x.XSync.argtypes=[ctypes.c_void_p,ctypes.c_int]
xt.XTestFakeKeyEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
xt.XTestFakeKeyEvent.restype=ctypes.c_int
d=x.XOpenDisplay(b':1')
if not d: raise SystemExit('Cannot open X11 desktop')
try:
    output=subprocess.check_output(['wmctrl','-lx'],text=True)
    ids=[]
    for row in output.splitlines():
        cols=row.split(None,4)
        if len(cols)<3: continue
        cls=cols[2].lower()
        if cls=='xterm.xterm' or cls.endswith('.firefox-esr'):
            if cols[0] not in ids: ids.append(cols[0])
    if not ids: raise SystemExit('No CLI or Firefox windows detected')
    keys=['Control_L','Alt_L','Shift_L','d']
    codes=[int(x.XKeysymToKeycode(d,x.XStringToKeysym(k.encode()))) for k in keys]
    if any(v==0 for v in codes): raise SystemExit('Key mapping unavailable')
    for xid in ids:
        subprocess.run(['wmctrl','-ia',xid],check=True,timeout=6)
        time.sleep(0.15)
        for code in codes:
            if not xt.XTestFakeKeyEvent(d,code,1,0): raise SystemExit('XTest press failed')
        for code in reversed(codes):
            if not xt.XTestFakeKeyEvent(d,code,0,0): raise SystemExit('XTest release failed')
        x.XSync(d,0)
        time.sleep(0.15)
    print('Openbox Decorate action dispatched to',len(ids),'CLI/Firefox windows')
finally:
    x.XCloseDisplay(d)
"""


def run(*args, capture=False, check=True):
    p = subprocess.run(args, capture_output=True, text=True, check=False)
    if check and p.returncode:
        raise RuntimeError("Command failed: " + " ".join(args[:5]) + "\n"
                           + (p.stderr.strip() or p.stdout.strip()))
    if capture:
        return p
    if p.stdout.strip():
        print(p.stdout.strip(), flush=True)
    return p


def user(*args, check=True):
    return run("docker", "exec", "-u", "user", "-e", "DISPLAY=:1",
               "-e", "XAUTHORITY=/home/user/.Xauthority",
               LIVE, *args, check=check)


def apply():
    instance = run("docker", "inspect", "-f", "{{.State.Running}}",
                   LIVE, capture=True)
    if instance.stdout.strip() != "true":
        raise RuntimeError("Live participant unavailable; no changes made")
    mgr = user("sh", "-ec", "wmctrl -m | head -n 1")
    user("python3", "-c", PATCH)
    try:
        user("openbox", "--reconfigure")
        p = user("python3", "-c", XTEST, check=False)
        if p.returncode:
            print("Automatic decoration could not be verified.")
            print("Click inside each NERDs window and press Ctrl+Alt+Shift+D.")
        else:
            print("Decorate requested for current CLI and Firefox windows.")
    except Exception:
        print("Reconfiguration failed; restoring original Openbox config.")
        user("python3", "-c", RESTORE)
        user("openbox", "--reconfigure")
        raise
    print("No participant processes, terminal logs or DB records were restarted.")
    print("Use Split View / Restore windows only if alignment requires it.")
    print("Rollback config: python3 scripts/r2d4_restore_titlebars.py rollback")


def rollback():
    exists = user("sh", "-ec", "test -f " + BACKUP, check=False)
    if exists.returncode:
        print("No temporary titlebar binding backup; nothing to restore.")
        return
    user("python3", "-c", RESTORE)
    user("openbox", "--reconfigure")
    print("Original Openbox keyboard configuration restored.")
    print("Existing title bars remain decorated; no apps restarted.")


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["apply","rollback"])
    args=parser.parse_args()
    try:
        {"apply":apply,"rollback":rollback}[args.action]()
    except (RuntimeError,OSError,subprocess.CalledProcessError) as exc:
        parser.exit(1, "STOP: " + str(exc) + "\n")
