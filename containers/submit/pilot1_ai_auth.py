"""Authentication for Pilot 1 AI observations."""

import hmac
import re
from pathlib import Path

from pilot1_ai_registry import resolve_request


def authenticate_ai_request(
    remote_addr,
    headers,
    registry_path,
    secret_path,
    now=None
):
    """Return a trusted instance ID or reject the request."""

    supplied = headers.get("X-NERDS-Gateway-Token", "")

    if not isinstance(supplied, str):
        raise PermissionError("Invalid gateway credential")

    if not re.fullmatch(r"[0-9a-f]{64}", supplied):
        raise PermissionError("Invalid gateway credential")

    try:
        raw = Path(secret_path).read_bytes()

        if len(raw) > 128:
            raise PermissionError("Invalid secret configuration")

        if not re.fullmatch(rb"[0-9a-f]{64}\n?", raw):
            raise PermissionError("Invalid secret configuration")

        expected = raw.rstrip(b"\n")

    except OSError as exc:
        raise PermissionError(
            "Gateway authentication unavailable"
        ) from exc

    if not hmac.compare_digest(
        supplied.encode("ascii"), expected
    ):
        raise PermissionError("Gateway authentication failed")

    source_ip = headers.get("X-NERDS-Source-IP", "")

    return resolve_request(
        registry_path,
        remote_addr,
        source_ip,
        now=now
    )
