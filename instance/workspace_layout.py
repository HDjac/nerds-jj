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


# Pin the participant's Firefox X11 window for this API lifetime. wmctrl's
# ordering can change with stacking: choosing the last match on every call
# silently flips between independently-open Firefox windows.
_PRIMARY_FIREFOX_ID = None


def _entries():
    entries = []
    for line in _command("wmctrl", "-lGx").splitlines():
        cols = line.split(None, 8)
        if len(cols) < 7:
            continue
        cls = cols[6].lower()
        if cls == "xterm.xterm":
            kind = "cli"
        elif cls.endswith(".firefox-esr"):
            kind = "browser"
        else:
            continue
        entries.append({"kind": kind, "id": cols[0],
                        "title": cols[8] if len(cols) > 8 else ""})
    return entries


def _windows():
    global _PRIMARY_FIREFOX_ID
    entries = _entries()
    cli = [e for e in entries if e["kind"] == "cli"]
    browsers = [e for e in entries if e["kind"] == "browser"]
    if not cli or not browsers:
        return {}
    by_id = {e["id"] for e in browsers}
    if _PRIMARY_FIREFOX_ID not in by_id:
        # Prefer the currently used Firefox window, then an existing tab
        # with a page title over a blank/new-tab window. Never close another
        # Firefox window or erase its profile/history.
        focused = _focused_window_chain()
        active = next((e for e in browsers
                       if int(e["id"], 16) in focused), None)
        meaningful = [e for e in browsers
                      if e["title"].strip() and
                      not e["title"].lower().startswith(("new tab", "mozilla firefox"))]
        selected = active or (meaningful[0] if meaningful else browsers[0])
        _PRIMARY_FIREFOX_ID = selected["id"]
    return {"cli": cli[0]["id"], "browser": _PRIMARY_FIREFOX_ID}


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
    """Actual focused X11 application, including other Firefox windows.

    Clipboard provenance must never infer the focused app from the selected
    primary Firefox window alone. Preserve 'unknown' on ambiguous focus.
    """
    entries = _entries()
    try:
        active = _command("xprop", "-root", "_NET_ACTIVE_WINDOW")
        m = re.search(r"(0x[0-9a-fA-F]+)", active)
        if m:
            xid = int(m.group(1), 16)
            for e in entries:
                if int(e["id"], 16) == xid:
                    return e["kind"]
    except (ValueError, WorkspaceLayoutError):
        pass
    focused = _focused_window_chain()
    for xid in focused:
        for e in entries:
            if xid == int(e["id"], 16):
                return e["kind"]
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

    # Terminal widths are rounded to character columns by XTerm. Measure the
    # actual right edge before positioning Firefox to prevent a black gap.
    for xid in windows.values():
        _command("wmctrl", "-ir", xid, "-b", "remove,maximized_vert,maximized_horz")
    if mode == "split":
        x, y, w, h = bounds["cli"]
        _command("wmctrl", "-ir", windows["cli"], "-e",
                 f"0,{x},{y},{max(300, w)},{max(250, h)}")
        actual = current_geometry().get("cli")
        if actual is None:
            raise WorkspaceLayoutError("CLI geometry unavailable")
        browser_x = max(300, actual[0] + actual[2] + 2)
        _command("wmctrl", "-ir", windows["browser"], "-e",
                 f"0,{browser_x},0,{max(300, width - browser_x)},{height}")
    else:
        for kind, xid in windows.items():
            x, y, w, h = bounds[kind]
            _command("wmctrl", "-ir", xid, "-e",
                     f"0,{x},{y},{max(200, w)},{max(250, h)}")

    if mode != "split":
        _command("wmctrl", "-ia", windows[mode])
    else:
        # Restoring ONLY the CLI leaves an iconified Firefox invisible until
        # a participant changes modes. Raise both windows, then focus CLI.
        # Bringing up a window through -ia also de-iconifies it in Openbox.
        _command("wmctrl", "-ia", windows["browser"])
        _command("wmctrl", "-ia", windows["cli"])

    geometry = current_geometry()
    if mode == "split":
        cli = geometry.get("cli")
        browser = geometry.get("browser")
        if cli is None or browser is None:
            raise WorkspaceLayoutError("Window geometry unavailable")
        right = cli[0] + cli[2]
        if abs(browser[0] - right) > 35:
            raise WorkspaceLayoutError("CLI and Firefox are not adjacent")
        if cli[2] < 280 or browser[2] < 300:
            raise WorkspaceLayoutError("A pane became too narrow")
        divider_percent = round(100 * right / width, 2)
    else:
        divider_percent = cli_percent

    return {"mode": mode, "cli_percent": cli_percent,
            "divider_percent": divider_percent,
            "width": width, "height": height,
            "windows": geometry,
            "focus": focus()}
