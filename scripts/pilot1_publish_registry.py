#!/usr/bin/env python3
"""Publish trusted Pilot 1 container assignments."""

import argparse
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pilot1_instance_registry import command, discover


def gateway_ip(container_name, network):
    data = json.loads(command([
        "docker", "inspect", container_name
    ]))

    if len(data) != 1:
        raise RuntimeError("Gateway container not found")

    item = data[0]

    if not item["State"]["Running"]:
        raise RuntimeError("Gateway is not running")

    if item["Config"].get("Labels", {}).get(
        "com.docker.compose.service"
    ) != "nginx":
        raise RuntimeError("Unexpected gateway service")

    return item["NetworkSettings"]["Networks"][
        network
    ]["IPAddress"]


def publish(output, gateway, network, ttl):
    assignments = discover()
    peer_ip = gateway_ip(gateway, network)

    now = datetime.now(timezone.utc)

    registry = {
        "version": 1,
        "generated_at": now.isoformat(),
        "expires_at": (
            now + timedelta(seconds=ttl)
        ).isoformat(),
        "gateway_ips": [peer_ip],
        "instances": assignments,
    }

    output.parent.mkdir(
        parents=True, exist_ok=True, mode=0o700
    )
    os.chmod(output.parent, 0o700)

    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=".registry-",
            delete=False
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            json.dump(registry, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, output)

    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return registry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home()
        / "nerds-pilot-runtime/registry/participants.json"
    )
    parser.add_argument(
        "--gateway",
        default="nerds-pilot1-nginx-private"
    )
    parser.add_argument(
        "--gateway-network",
        default="devob_main"
    )
    parser.add_argument(
        "--ttl", type=int, default=30
    )

    args = parser.parse_args()

    if not 5 <= args.ttl <= 300:
        parser.error("TTL must be between 5 and 300 seconds")

    registry = publish(
        args.output,
        args.gateway,
        args.gateway_network,
        args.ttl
    )

    print("Registry published:", args.output)
    print("Gateway:", registry["gateway_ips"])
    print("Participants:", len(registry["instances"]))


if __name__ == "__main__":
    main()
