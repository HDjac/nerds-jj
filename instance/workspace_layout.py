"""Single-display, bounded window layout for the Pilot 1 CLI/Firefox workspace.

No new VNC session or clipboard channel is created. The existing X11 windows
are arranged using wmctrl; no shell=True and no arbitrary window IDs supplied
by the browser are accepted.
"""
import re
import subprocess

XENV = {"DISPLAY": ":1", "XAUTHORITY": "/home/user/.Xauthority"}
VALID_MODES = ("split", "cli", "browser")


class WorkspaceLayoutError(Exception):
    pass


def _command(*argv):
    import os
    env = os.environ.copy()
    env.update(XENV)
    try:
        return subprocess.run(argv, env=env, check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=5).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceLayoutError("Remote desktop window operation unavailable") from exc


def _windows():
    windows = {}
    for line in _command("wmctrl", "-lx").splitlines():
        cols = line.split(None, 4)
        if len(cols) < 3:
            continue
        cls = cols[2].lower()
        if cls == "xterm.xterm":
            windows["cli"] = cols[0]
        elif cls.endswith(".firefox-esr"):
            windows["browser"] = cols[0]
    return windows


def _focused_window_chain():
    """Fallback focus IDs from libX11, even if xprop is not installed."""
    import ctypes
    import ctypes.util
    found = ctypes.util.find_library("X11")
    if not found:
        return []
    try:
        lib = ctypes.CDLL(found)
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XGetInputFocus.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int)
        ]
        lib.XQueryTree.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.XQueryTree.restype = ctypes.c_int
        lib.XFree.argtypes = [ctypes.c_void_p]
        display = lib.XOpenDisplay(b":1")
        if not display:
            return []
        try:
            window = ctypes.c_ulong()
            revert = ctypes.c_int()
            lib.XGetInputFocus(display, ctypes.byref(window), ctypes.byref(revert))
            seen = []
            current = int(window.value)
            for _ in range(20):
                if current in (0, 1) or current in seen:
                    break
                seen.append(current)
                root = ctypes.c_ulong()
                parent = ctypes.c_ulong()
                children = ctypes.POINTER(ctypes.c_ulong)()
                count = ctypes.c_uint()
                ok = lib.XQueryTree(
                    display, current, ctypes.byref(root), ctypes.byref(parent),
                    ctypes.byref(children), ctypes.byref(count)
                )
                if children:
                    lib.XFree(ctypes.cast(children, ctypes.c_void_p))
                if not ok or not parent.value:
                    break
                current = int(parent.value)
            return seen
        finally:
            lib.XCloseDisplay(display)
    except (OSError, ValueError, TypeError):
        return []


def focus():
    """Return focused X11 application or 'unknown'; never guess by UI tab."""
    windows = _windows()
    by_id = {int(xid, 16): kind for kind, xid in windows.items()}
    try:
        active = _command("xprop", "-root", "_NET_ACTIVE_WINDOW")
        match = re.search(r"window id # (0x[0-9a-fA-F]+)", active)
        if match:
            result = by_id.get(int(match.group(1), 16))
            if result:
                return result
    except (ValueError, WorkspaceLayoutError):
        pass
    for xid in _focused_window_chain():
        if xid in by_id:
            return by_id[xid]
    return "unknown"

def screen_size():
    desktop = _command("wmctrl", "-d")
    match = re.search(r"\bDG:\s*(\d+)x(\d+)", desktop)
    if not match:
        raise WorkspaceLayoutError("Cannot read desktop dimensions")
    width, height = int(match.group(1)), int(match.group(2))
    if width < 750 or height < 400 or width > 3840 or height > 2160:
        raise WorkspaceLayoutError("Unsupported remote desktop dimensions")
    return width, height


def current_geometry():
    """Return bounded window extents to detect window-manager failures."""
    result = {}
    for line in _command("wmctrl", "-lGx").splitlines():
        parts = line.split(None, 8)
        if len(parts) < 8:
            continue
        cls = parts[6].lower()
        kind = ("cli" if cls == "xterm.xterm" else
                "browser" if cls.endswith(".firefox-esr") else None)
        if not kind:
            continue
        try:
            result[kind] = tuple(int(parts[n]) for n in (2, 3, 4, 5))
        except ValueError:
            continue
    return result


def set_layout(mode, cli_percent=50):
    if mode not in VALID_MODES:
        raise ValueError("Invalid workspace mode")
    if type(cli_percent) is not int or not 30 <= cli_percent <= 70:
        raise ValueError("Invalid CLI pane width")

    windows = _windows()
    if "cli" not in windows or "browser" not in windows:
        raise WorkspaceLayoutError("Both CLI and Firefox must be running")
    width, height = screen_size()
    # The divider is a drawn HTML overlay; leave an 8px native gap under it.
    edge = max(300, round(width * cli_percent / 100))
    gap = 8
    if mode == "split":
        bounds = {
            "cli": (0, 0, edge - gap // 2, height),
            "browser": (edge + gap // 2, 0, width - edge - gap // 2, height),
        }
    else:
        bounds = {
            mode: (0, 0, width, height),
            ("browser" if mode == "cli" else "cli"): (0, 0, width, height),
        }

    # Remove maximized flags before requesting geometry, otherwise some WMs
    # silently ignore -e. No processes are killed or restarted.
    for kind, xid in windows.items():
        _command("wmctrl", "-ir", xid, "-b", "remove,maximized_vert,maximized_horz")
        x, y, w, h = bounds[kind]
        _command("wmctrl", "-ir", xid, "-e",
                 f"0,{x},{y},{max(200, w)},{max(250, h)}")

    if mode != "split":
        _command("wmctrl", "-ia", windows[mode])
    else:
        _command("wmctrl", "-ia", windows["cli"])

    return {"mode": mode, "cli_percent": cli_percent,
            "width": width, "height": height,
            "windows": current_geometry(),
            "focus": focus()}
