"""Trusted gateway and participant instance attribution."""

import ipaddress
import re


def resolve_instance(
    remote_addr,
    source_ip,
    trusted_gateway_ips,
    instance_assignments
):
    """Return the trusted instance ID or reject the request."""

    try:
        peer = str(ipaddress.ip_address(remote_addr))
        source = str(ipaddress.ip_address(source_ip))
    except (ValueError, TypeError):
        raise PermissionError("Invalid network identity")

    if peer not in trusted_gateway_ips:
        raise PermissionError("Untrusted gateway")

    instance_id = instance_assignments.get(source)

    if not instance_id or not re.fullmatch(
        r"[a-f0-9]{12}", instance_id
    ):
        raise PermissionError("Unknown participant instance")

    return instance_id
