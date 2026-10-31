#!/usr/bin/env python3
"""Host-admin-only Pilot 1 enrollment for NERDs CLI fuzzing.

Creates a pseudonymous participant and one study session (without instance or
login credentials). The trusted instance claim/provisioning/login flow is a
separate implementation step. Do not expose this script as a web endpoint.

Usage:
    python3 scripts/pilot1_enroll.py            # preview, no database writes
    python3 scripts/pilot1_enroll.py --create   # enroll one pilot tester
"""

import argparse
import secrets
import subprocess
import sys

DB_CONTAINER = "devob-db-1"
DB_NAME = "notebook"
ORDERS = ("dense_first", "lowyield_first")

SQL = r"""
BEGIN;

INSERT INTO fuzz_pilot.participants (participant_id)
VALUES (:'participant_id');

INSERT INTO fuzz_pilot.study_sessions
    (participant_id, attempt_number, order_code,
     status, study_phase, enrollment_method)
VALUES
    (:'participant_id', 1, :'order_code',
     'assigned', 'pilot1', 'manual')
RETURNING session_id::text, participant_id,
          order_code, study_phase, status;

-- Automatically create both task records
-- in the participant's randomized order.
INSERT INTO fuzz_pilot.task_runs
    (session_id, position, task_code, status)
SELECT
    s.session_id,
    positions.position,
    CASE
        WHEN
            (s.order_code = 'dense_first'
             AND positions.position = 1)
            OR
            (s.order_code = 'lowyield_first'
             AND positions.position = 2)
        THEN 'dense_v2'
        ELSE 'lowyield_v1'
    END,
    'locked'
FROM fuzz_pilot.study_sessions s
CROSS JOIN (
    VALUES (1::smallint), (2::smallint)
) AS positions(position)
WHERE s.participant_id = :'participant_id'
  AND s.attempt_number = 1;

COMMIT;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--create", action="store_true",
        help="Write a new Pilot 1 participant and assigned-order session to PostgreSQL",
    )
    args = parser.parse_args()

    participant_id = secrets.token_hex(12)  # 24 lowercase hexadecimal chars
    order = ORDERS[secrets.randbelow(2)]

    if not args.create:
        print("DRY RUN: database unchanged. Use --create to enroll a tester.")
        print(f"Example participant ID: {participant_id}")
        print(f"Example randomized order: {order}")
        return 0

    cmd = [
        "docker", "exec", "-u", "postgres", "-i", DB_CONTAINER,
        "psql", "-X", "-q", "-t", "-A", "-F", "|",
        "-v", "ON_ERROR_STOP=1",
        "-v", f"participant_id={participant_id}",
        "-v", f"order_code={order}",
        "-d", DB_NAME,
    ]
    try:
        result = subprocess.run(cmd, input=SQL, text=True,
                                capture_output=True, check=True)
    except FileNotFoundError:
        print("ERROR: docker executable not found.", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print("ERROR: enrollment transaction failed. Nothing should be partially inserted.",
              file=sys.stderr)
        print(exc.stderr.strip(), file=sys.stderr)
        return 1

    rows = [line for line in result.stdout.splitlines() if line.count("|") == 4]
    if len(rows) != 1:
        print("ERROR: unexpected database response; inspect enrollment manually.",
              file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        return 1

    session_id, saved_pid, saved_order, phase, status = rows[0].split("|")
    if (saved_pid, saved_order, phase, status) != (
        participant_id, order, "pilot1", "assigned"
    ):
        print("ERROR: database enrollment response did not match request.",
              file=sys.stderr)
        return 1

    print("Pilot 1 participant enrolled:")
    print(f"  Participant ID : {saved_pid}")
    print(f"  Study session  : {session_id}")
    print(f"  Task order     : {saved_order}")
    print(f"  Study phase    : {phase}")
    print(f"  Status         : {status}")
    print("  Container      : not assigned")
    print("  Browser login  : not issued")
    print("\nThis record alone does NOT grant NERDs access.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
