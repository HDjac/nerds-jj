"""Offline tests for proposed reverse-order registry admission.

Tests patch both DB discovery and Docker discovery: no Docker socket, database,
systemd or live registry accessed. Qualification image trust must fail closed.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pilot1_instance_registry as registry
from pilot1_image_trust import (
    LEGACY_IDS, LEGACY_TAG, RC2_ID, RC2_NAME, RC2_TAG,
    REVERSE_QUALIFICATION_NAME,
)

IID = "abc123abc123"
OTHER_IID = "def456def456"
IP = "192.168.150.90"


def sample_container(name=REVERSE_QUALIFICATION_NAME, iid=IID,
                     tag=RC2_TAG, image_id=RC2_ID, ip=IP):
    return {
        "Id": iid + "0" * 52,
        "Name": "/" + name,
        "Image": image_id,
        "State": {"Running": True},
        "Config": {
            "Image": tag,
            "User": "user",
            "Labels": {"nerds.study": "pilot1"},
        },
        "NetworkSettings": {
            "Networks": {"devob_instances": {"IPAddress": ip}}
        },
        "HostConfig": {"Privileged": False},
    }


def discover_with(entries, containers):
    with patch.object(registry, "database_assignments", return_value=entries), \
         patch.object(registry, "running_containers", return_value=containers):
        return registry.discover()


class ReverseRegistryTests(unittest.TestCase):
    def test_new_named_qualification_container_is_visible(self):
        assigned = [{"instance_id": IID,
                     "instance_name": REVERSE_QUALIFICATION_NAME}]
        container = sample_container()
        actual = discover_with(assigned, {REVERSE_QUALIFICATION_NAME: container})
        self.assertEqual(actual, {IP: IID})

    def test_existing_legacy_images_remain_admitted(self):
        for n, image_id in enumerate(sorted(LEGACY_IDS)):
            with self.subTest(image_id=image_id):
                name = "nerds-pilot1-legacy-" + str(n)
                assigned = [{"instance_id": IID, "instance_name": name}]
                container = sample_container(name=name, tag=LEGACY_TAG, image_id=image_id)
                self.assertEqual(discover_with(assigned, {name: container}), {IP: IID})

    def test_original_rc2_approval_unchanged(self):
        assigned = [{"instance_id": IID, "instance_name": RC2_NAME}]
        self.assertEqual(
            discover_with(assigned, {RC2_NAME: sample_container(name=RC2_NAME)}),
            {IP: IID},
        )

    def test_unknown_rc2_name_fails_closed(self):
        name = "nerds-pilot1-anything-else"
        assigned = [{"instance_id": IID, "instance_name": name}]
        self.assertEqual(
            discover_with(assigned, {name: sample_container(name=name)}), {},
        )

    def test_tag_or_digest_substitution_fails_closed(self):
        assigned = [{"instance_id": IID,
                     "instance_name": REVERSE_QUALIFICATION_NAME}]
        cases = (
            {"tag": LEGACY_TAG, "image_id": RC2_ID},
            {"tag": RC2_TAG, "image_id": "sha256:" + "0" * 64},
        )
        for kw in cases:
            with self.subTest(kw=kw):
                container = sample_container(**kw)
                self.assertEqual(
                    discover_with(assigned,
                                  {REVERSE_QUALIFICATION_NAME: container}), {},
                )

    def test_mismatched_db_binding_is_not_published(self):
        assigned = [{"instance_id": OTHER_IID,
                     "instance_name": REVERSE_QUALIFICATION_NAME}]
        self.assertEqual(
            discover_with(assigned, {
                REVERSE_QUALIFICATION_NAME: sample_container(),
            }), {},
        )

    def test_privileged_or_wrong_user_or_label_rejected(self):
        assigned = [{"instance_id": IID,
                     "instance_name": REVERSE_QUALIFICATION_NAME}]
        for kind in ("privileged", "user", "label", "network", "stopped"):
            with self.subTest(kind=kind):
                container = sample_container()
                if kind == "privileged":
                    container["HostConfig"]["Privileged"] = True
                elif kind == "user":
                    container["Config"]["User"] = "root"
                elif kind == "label":
                    container["Config"]["Labels"]["nerds.study"] = "other"
                elif kind == "network":
                    container["NetworkSettings"]["Networks"] = {
                        "other_network": {"IPAddress": IP}
                    }
                else:
                    container["State"]["Running"] = False
                self.assertEqual(
                    discover_with(assigned,
                                  {REVERSE_QUALIFICATION_NAME: container}), {},
                )

    def test_duplicate_ip_is_rejected(self):
        name2 = RC2_NAME
        assigned = [
            {"instance_id": IID, "instance_name": REVERSE_QUALIFICATION_NAME},
            {"instance_id": OTHER_IID, "instance_name": name2},
        ]
        containers = {
            REVERSE_QUALIFICATION_NAME: sample_container(),
            name2: sample_container(name=name2, iid=OTHER_IID),
        }
        with self.assertRaisesRegex(RuntimeError, "Duplicate participant IP"):
            discover_with(assigned, containers)


if __name__ == "__main__":
    unittest.main()
