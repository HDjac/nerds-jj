"""Read and validate the trusted Pilot 1 instance registry."""

import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pilot1_ai_gateway import resolve_instance


def load_registry(path, now=None):
    now = now or datetime.now(timezone.utc)
    path = Path(path)

    if not path.is_file():
        raise PermissionError("Registry unavailable")

    if path.stat().st_size > 1048576:
        raise PermissionError("Registry too large")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Invalid registry version")

        generated = datetime.fromisoformat(
            data["generated_at"].replace("Z", "+00:00")
        )
        expires = datetime.fromisoformat(
            data["expires_at"].replace("Z", "+00:00")
        )

        if generated.tzinfo is None or expires.tzinfo is None:
            raise ValueError("Timezone required")

        if generated > now + timedelta(seconds=5):
            raise ValueError("Registry timestamp is in the future")

        if expires <= generated:
            raise ValueError("Invalid registry lifetime")

        if expires - generated > timedelta(seconds=300):
            raise ValueError("Registry lifetime too long")

        if now >= expires:
            raise ValueError("Registry expired")

        gateways = data["gateway_ips"]
        instances = data["instances"]

        if not isinstance(gateways, list) or not gateways:
            raise ValueError("Missing gateways")

        if not isinstance(instances, dict):
            raise ValueError("Invalid participant mapping")

        if len(instances) > 10000:
            raise ValueError("Too many participant mappings")

        for ip in gateways:
            if not isinstance(ip, str):
                raise ValueError("Invalid gateway IP")
            if str(ipaddress.IPv4Address(ip)) != ip:
                raise ValueError("Invalid gateway address")

        if len(set(gateways)) != len(gateways):
            raise ValueError("Duplicate gateway")

        for ip, instance_id in instances.items():
            if str(ipaddress.IPv4Address(ip)) != ip:
                raise ValueError("Invalid participant IP")

            if not isinstance(instance_id, str) or not re.fullmatch(
                r"[a-f0-9]{12}", instance_id
            ):
                raise ValueError("Invalid instance ID")

        if len(set(instances.values())) != len(instances):
            raise ValueError("Duplicate instance assignment")

        return data

    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise PermissionError("Registry validation failed") from exc


def resolve_request(path, remote_addr, source_ip, now=None):
    registry = load_registry(path, now=now)

    return resolve_instance(
        remote_addr,
        source_ip,
        set(registry["gateway_ips"]),
        registry["instances"]
    )
