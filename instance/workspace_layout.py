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


def _focused_app_class():
    """Classify the X11 input-focus window (or an ancestor) using WM_CLASS."""
    import ctypes
    import ctypes.util

    class XClassHint(ctypes.Structure):
        _fields_ = [
            ("res_name", ctypes.c_void_p),
            ("res_class", ctypes.c_void_p),
        ]

    library = ctypes.util.find_library("X11")
    if not library:
        return "unknown"
    try:
        x11 = ctypes.CDLL(library)
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XGetClassHint.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XClassHint)
        ]
        x11.XGetClassHint.restype = ctypes.c_int
        x11.XFree.argtypes = [ctypes.c_void_p]
        display = x11.XOpenDisplay(b":1")
        if not display:
            return "unknown"
        try:
            for xid in _focused_window_chain():
                hint = XClassHint()
                if x11.XGetClassHint(display, xid, ctypes.byref(hint)):
                    try:
                        cls = (ctypes.string_at(hint.res_class).decode(
                            "utf-8", errors="replace").lower()
                            if hint.res_class else "")
                        name = (ctypes.string_at(hint.res_name).decode(
                            "utf-8", errors="replace").lower()
                            if hint.res_name else "")
                    finally:
                        if hint.res_class:
                            x11.XFree(hint.res_class)
                        if hint.res_name:
                            x11.XFree(hint.res_name)
                    if cls == "xterm" or name == "xterm":
                        return "cli"
                    if "firefox" in cls or "firefox" in name:
                        return "browser"
        finally:
            x11.XCloseDisplay(display)
    except (OSError, ValueError, TypeError):
        return "unknown"
    return "unknown"


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
    return _focused_app_class()


def screen_size():
    desktop = _command("wmctrl", "-d")
    match = re.search(r"\bDG:\s*(\d+)x(\d+)", desktop)
    if not match:
        raise WorkspaceLayoutError("Cannot read desktop dimensions")
    width, height = int(match.group(1)), int(match.group(2))
    if width < 750 or height < 400 or width > 3840 or height > 2160:
        raise WorkspaceLayoutError("Unsupported remote desktop dimensions")
    return width, height


def current_geometry(window_ids=None):
    """Read geometry for the pinned windows, not arbitrary Firefox windows.

    Several Firefox windows may be open. The last entry from wmctrl is not
    necessarily the participant workspace window selected by _windows().
    """
    window_ids = window_ids if window_ids is not None else _windows()
    by_id = {int(xid, 16): kind for kind, xid in window_ids.items()}
    result = {}
    for line in _command("wmctrl", "-lGx").splitlines():
        parts = line.split(None, 8)
        if len(parts) < 7:
            continue
        try:
            kind = by_id.get(int(parts[0], 16))
            if kind:
                result[kind] = tuple(int(parts[n]) for n in (2, 3, 4, 5))
        except ValueError:
            continue
    return result


def _place_split(windows, width, height, percent):
    """Attempt a split and return measured geometry, or reject that width.

    Window managers enforce minimum Firefox/xterm dimensions independently.
    A requested split may be impossible even if wmctrl accepts the command.
    """
    import time

    edge = max(300, round(width * percent / 100))
    requested_cli_width = edge - 4
    _command("wmctrl", "-ir", windows["cli"], "-e",
             f"0,0,0,{max(300, requested_cli_width)},{height}")
    time.sleep(0.04)
    measured = current_geometry(windows)
    cli = measured.get("cli")
    if cli is None:
        return None

    cli_right = cli[0] + cli[2]
    browser_x = max(300, cli_right + 2)
    browser_requested_width = max(300, width - browser_x)
    _command("wmctrl", "-ir", windows["browser"], "-e",
             f"0,{browser_x},0,{browser_requested_width},{height}")

    # Restore iconified windows before reading their real onscreen geometry.
    _command("wmctrl", "-ia", windows["browser"])
    _command("wmctrl", "-ia", windows["cli"])
    time.sleep(0.05)
    measured = current_geometry(windows)
    cli = measured.get("cli")
    browser = measured.get("browser")
    if cli is None or browser is None:
        return None

    cli_right = cli[0] + cli[2]
    browser_right = browser[0] + browser[2]
    # Reject a split only if it actually places panes incorrectly or clips
    # one past the display. The caller will retry a less extreme percentage.
    if (abs(browser[0] - cli_right) > 35
            or browser_right > width + 45
            or cli[2] < 280
            or browser[2] < 300):
        return None
    return measured


def _split_candidates(requested):
    """Try the requested percentage and progressively retreat to 50/50."""
    if requested < 50:
        options = list(range(requested, 51, 3))
    elif requested > 50:
        options = list(range(requested, 49, -3))
    else:
        options = [50]
    if 50 not in options:
        options.append(50)
    return list(dict.fromkeys(options))


def set_layout(mode, cli_percent=50):
    if mode not in VALID_MODES:
        raise ValueError("Invalid workspace mode")
    if type(cli_percent) is not int or not 30 <= cli_percent <= 70:
        raise ValueError("Invalid CLI pane width")

    windows = _windows()
    if "cli" not in windows or "browser" not in windows:
        raise WorkspaceLayoutError("Both CLI and Firefox must be running")
    width, height = screen_size()

    for xid in windows.values():
        _command("wmctrl", "-ir", xid, "-b",
                 "remove,maximized_vert,maximized_horz")

    if mode == "split":
        geometry = None
        for candidate in _split_candidates(cli_percent):
            geometry = _place_split(windows, width, height, candidate)
            if geometry is not None:
                break
        if geometry is None:
            # No valid split exists on this display. Re-establish both
            # windows at the center and report the unsupported layout.
            raise WorkspaceLayoutError("Neither window can fit in a split layout")
        cli = geometry["cli"]
        divider_percent = round(100 * (cli[0] + cli[2]) / width, 2)
        clamped = candidate != cli_percent
    else:
        # Fullscreen modes preserve the other application. Switching back
        # to Split restores both without restarting Firefox or xterm.
        for xid in windows.values():
            _command("wmctrl", "-ir", xid, "-e",
                     f"0,0,0,{width},{height}")
        _command("wmctrl", "-ia", windows[mode])
        geometry = current_geometry(windows)
        divider_percent = cli_percent
        clamped = False

    return {"mode": mode,
            "cli_percent": cli_percent,
            "divider_percent": divider_percent,
            "clamped": clamped,
            "width": width, "height": height,
            "windows": geometry,
            "focus": focus()}
