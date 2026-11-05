"""Offline-only guard tests for deterministic Low-Yield-first Pilot 1 qualification.

No live Docker, PostgreSQL, or study containers are contacted.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pilot1_image_trust as trust
import pilot1_enroll_reverse_qualification as qualify

PID = "a" * 24
SESSION = "11111111-1111-4111-8111-111111111111"


def image(tag, image_id):
    return {"Config": {"Image": tag}, "Image": image_id}


class ReverseQualificationTests(unittest.TestCase):
    def test_only_two_named_rc2_containers_approved(self):
        sample = image(trust.RC2_TAG, trust.RC2_ID)
        self.assertTrue(trust.image_is_approved(sample, trust.RC2_NAME))
        self.assertTrue(trust.image_is_approved(
            sample, trust.REVERSE_QUALIFICATION_NAME
        ))
        for wrong in ("nerds-pilot1-unexpected", "", trust.RC2_NAME + "-copy"):
            self.assertFalse(trust.image_is_approved(sample, wrong))

    def test_rc2_must_match_pinned_id_and_tag(self):
        name = trust.REVERSE_QUALIFICATION_NAME
        self.assertFalse(trust.image_is_approved(
            image(trust.RC2_TAG, "sha256:" + "f" * 64), name
        ))
        self.assertFalse(trust.image_is_approved(
            image(trust.LEGACY_TAG, trust.RC2_ID), name
        ))
        self.assertFalse(trust.image_is_approved({}, name))

    def test_legacy_images_remain_authorized_without_broad_rc2_exception(self):
        for image_id in trust.LEGACY_IDS:
            self.assertTrue(trust.image_is_approved(
                image(trust.LEGACY_TAG, image_id), "nerds-pilot1-existing"
            ))

    def test_preview_never_uses_docker_or_filesystem(self):
        out = io.StringIO()
        with patch.object(qualify, "private_directory") as directory, \
             patch.object(qualify, "enroll") as enroll, \
             contextlib.redirect_stdout(out):
            self.assertEqual(qualify.main([]), 0)
        directory.assert_not_called()
        enroll.assert_not_called()
        self.assertIn("PREVIEW ONLY", out.getvalue())
        self.assertIn("lowyield_first", out.getvalue())

    def test_creation_requires_explicit_acknowledgement(self):
        with patch.object(qualify, "enroll") as enroll, \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                qualify.main(["--create"])
        enroll.assert_not_called()

    def test_acknowledgement_without_creation_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                qualify.main(["--confirm-nonrandom-qualification"])

    def test_response_must_contain_expected_order_and_assigned_status(self):
        row = f"{SESSION}|{PID}|lowyield_first|pilot1|assigned"
        self.assertEqual(qualify.interpret_result(row + "\n", PID), SESSION)
        for bad in (
            f"{SESSION}|{PID}|dense_first|pilot1|assigned",
            f"{SESSION}|{PID}|lowyield_first|pilot1|completed",
            f"{SESSION}|{'b' * 24}|lowyield_first|pilot1|assigned",
            row + "\n" + row,
        ):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                qualify.interpret_result(bad, PID)

    def test_database_call_is_explicitly_lowyield_first(self):
        row = f"{SESSION}|{PID}|lowyield_first|pilot1|assigned\n"
        with patch.object(
            qualify.subprocess, "run",
            return_value=SimpleNamespace(stdout=row)
        ) as run:
            self.assertEqual(qualify.enroll(PID), SESSION)
        args = run.call_args
        self.assertEqual(args.kwargs["input"], qualify.SQL)
        self.assertIn("order_code=lowyield_first", args.args[0])
        self.assertIn("ON_ERROR_STOP=1", args.args[0])

    def test_private_marker_can_only_be_created_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = qualify.record_qualification(root, SESSION, PID)
            data = json.loads(target.read_text())
            self.assertTrue(data["exclude_from_research_analysis"])
            self.assertEqual(data["qualification_kind"], qualify.KIND)
            self.assertEqual(data["order_code"], "lowyield_first")
            self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                qualify.record_qualification(root, SESSION, PID)

    def test_apply_creates_one_private_qualification_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(qualify, "private_directory", return_value=Path(tmp)), \
                 patch.object(qualify, "enroll", return_value=SESSION) as enroll, \
                 patch.object(qualify.secrets, "token_hex", return_value=PID), \
                 contextlib.redirect_stdout(io.StringIO()):
                outcome = qualify.main([
                    "--create", "--confirm-nonrandom-qualification"
                ])
            self.assertEqual(outcome, 0)
            enroll.assert_called_once_with(PID)
            self.assertTrue((Path(tmp) / (SESSION + ".json")).is_file())

    def test_marker_failure_after_enrollment_does_not_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(qualify, "private_directory", return_value=Path(tmp)), \
                 patch.object(qualify, "enroll", return_value=SESSION) as enroll, \
                 patch.object(qualify, "record_qualification",
                              side_effect=OSError("synthetic failure")), \
                 patch.object(qualify.secrets, "token_hex", return_value=PID), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(qualify.main([
                    "--create", "--confirm-nonrandom-qualification"
                ]), 2)
            enroll.assert_called_once()


if __name__ == "__main__":
    unittest.main()
