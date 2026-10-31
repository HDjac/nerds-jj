"""Resolve the *active NERDs add-on's* Firefox origin for scoped CORS.

Firefox's moz-extension UUID is per-profile. Do not hardcode it in a Docker
image or trust an Origin supplied by an arbitrary page. This is a narrow
browser CORS allowlist, *not* authentication or a substitute for the
Submit gateway's instance/session/task validation.
"""
import json
from pathlib import Path
import re

ADDON_ID = "chatgpt-prompt-logger@nerds.local"
PROFILE_ROOTS = (
    Path("/home/user/.mozilla"),
    Path("/home/user/.config/mozilla"),
)
_PREF = re.compile(
    r'^\s*user_pref\("extensions\.webextensions\.uuids",\s*'
    r'("(?:\\.|[^"\\])*")\);\s*$',
    re.MULTILINE,
)
_UUID = re.compile(
    r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z', re.I
)


def active_nerds_extension_origin(roots=PROFILE_ROOTS):
    """Return one verified origin, or None (fail closed).

    Match the stable add-on ID in BOTH Firefox's per-profile UUID mapping and
    its active extension registry. Multiple candidate profiles are ambiguous.
    The browser profile must be running/initialized before this can succeed.
    """
    found = set()
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for prefs in root.rglob("prefs.js"):
            index = prefs.with_name("extensions.json")
            if not index.is_file():
                continue
            try:
                match = _PREF.search(prefs.read_text(encoding="utf-8"))
                if not match:
                    continue
                mapping = json.loads(json.loads(match.group(1)))
                uuid = mapping.get(ADDON_ID)
                if not isinstance(uuid, str) or not _UUID.fullmatch(uuid):
                    continue
                addons = json.loads(index.read_text(encoding="utf-8")).get("addons", [])
                if not any(
                    addon.get("id") == ADDON_ID
                    and addon.get("active") is True
                    and addon.get("appDisabled") is False
                    and addon.get("userDisabled") is False
                    for addon in addons
                ):
                    continue
                found.add("moz-extension://" + uuid.lower())
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    return next(iter(found)) if len(found) == 1 else None
