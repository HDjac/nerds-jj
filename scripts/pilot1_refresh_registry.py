#!/usr/bin/env python3
"""Continuously refresh trusted Pilot 1 participant assignments."""

import argparse
import time
from pathlib import Path

from pilot1_publish_registry import publish


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

    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--ttl", type=int, default=30)

    args = parser.parse_args()

    if not 5 <= args.ttl <= 300:
        parser.error("TTL must be between 5 and 300 seconds")

    if not 1 <= args.interval < args.ttl:
        parser.error("Refresh interval must be positive and shorter than TTL")

    print("NERDs Pilot 1 registry refresh started", flush=True)

    while True:
        registry = publish(
            args.output,
            args.gateway,
            args.gateway_network,
            args.ttl
        )

        print(
            f"[{registry['generated_at']}] "
            f"Registry refreshed: "
            f"{len(registry['instances'])} participant(s), "
            f"gateway={registry['gateway_ips']}",
            flush=True
        )

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
