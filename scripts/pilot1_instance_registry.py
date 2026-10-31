#!/usr/bin/env python3
"""Discover trusted Pilot 1 participant containers."""

import ipaddress
import json
import os
import re
import subprocess

NETWORK = os.environ.get(
    "NERDS_PARTICIPANT_NETWORK", "devob_instances"
)
IMAGE = os.environ.get(
    "NERDS_PILOT_IMAGE", "devob_instance:cli-pilot-protected"
)


def command(args):
    result = subprocess.run(
        args, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def database_assignments():
    query = """
    SELECT COALESCE(json_agg(
        json_build_object(
            'instance_id', s.instance_id,
            'instance_name', s.instance_name
        )
    ), '[]'::json)
    FROM fuzz_pilot.study_sessions s
    JOIN fuzz_pilot.participants p
      ON p.participant_id = s.participant_id
    JOIN fuzz_pilot.task_runs t
      ON t.session_id = s.session_id
    WHERE s.study_phase = 'pilot1'
      AND s.status = 'active'
      AND p.withdrawn_at IS NULL
      AND t.status IN ('ready', 'active')
      AND s.instance_id IS NOT NULL
      AND s.instance_name IS NOT NULL;
    """

    raw = command([
        "docker", "exec", "-u", "postgres",
        "devob-db-1", "psql",
        "-X", "-A", "-t", "-d", "notebook",
        "-c", query
    ])
    return json.loads(raw)


def running_containers():
    ids = command([
        "docker", "ps", "-q",
        "--filter", "label=nerds.study=pilot1"
    ]).splitlines()

    if not ids:
        return {}

    containers = json.loads(
        command(["docker", "inspect"] + ids)
    )

    return {
        item["Name"].lstrip("/"): item
        for item in containers
    }


def discover():
    assignments = database_assignments()
    containers = running_containers()
    registry = {}

    for assignment in assignments:
        name = assignment["instance_name"]
        expected_id = assignment["instance_id"]

        if not isinstance(name, str):
            continue

        if not isinstance(expected_id, str) or not re.fullmatch(
            r"[a-f0-9]{12}", expected_id
        ):
            continue

        container = containers.get(name)

        if container is None:
            continue

        config = container["Config"]
        networks = container["NetworkSettings"]["Networks"]

        if not container["State"]["Running"]:
            continue

        if container["Id"][:12] != expected_id:
            continue

        if config["Image"] != IMAGE:
            continue

        if config["User"] != "user":
            continue

        if config.get("Labels", {}).get("nerds.study") != "pilot1":
            continue

        if NETWORK not in networks:
            continue

        if container["HostConfig"].get("Privileged", False):
            continue

        ip = networks[NETWORK].get("IPAddress")

        try:
            ip = str(ipaddress.ip_address(ip))
        except ValueError:
            continue

        if ip in registry:
            raise RuntimeError("Duplicate participant IP")

        registry[ip] = expected_id

    return registry


if __name__ == "__main__":
    print(json.dumps(discover(), indent=2, sort_keys=True))
