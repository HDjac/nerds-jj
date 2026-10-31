#!/usr/bin/env python3
"""Trusted HOST-only publication of a non-identifying Pilot 1 completion receipt.

Nginx serves a high-entropy receipt status from a read-only bind mount. The
status file is published ONLY after a PostgreSQL session-completed commit. The
bearer value must come from the acknowledged final-task request (or an explicit
operator recovery action on an already completed session). Never run this in a
participant container. Pilot 1 is single-session; generalize identifiers and
DB authorizations before the multi-participant study.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from uuid import UUID

RECEIPT_PATTERN = re.compile(r'[a-f0-9]{64}\Z')
ROOT = Path.home() / 'nerds-pilot-runtime' / 'completion-receipts'
PILOT_SESSION = '9c6fdb2b-3cdd-4ef6-bc61-d4040bd74155'


def db_completed(session_id):
    ident = str(UUID(str(session_id)))
    query = f"""
SELECT s.status, t1.status, t2.status
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t1 ON t1.session_id=s.session_id AND t1.position=1
JOIN fuzz_pilot.task_runs t2 ON t2.session_id=s.session_id AND t2.position=2
WHERE s.session_id='{ident}'::uuid
  AND s.ended_at IS NOT NULL
  AND t2.ended_at IS NOT NULL;
"""
    result = subprocess.run([
        'docker', 'exec', '-u', 'postgres', 'devob-db-1',
        'psql', '-X', '-qAt', '-F', '|', '-v', 'ON_ERROR_STOP=1',
        '-d', 'notebook', '-c', query,
    ], text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Unable to verify PostgreSQL finalization: ' +
                           result.stderr[-400:])
    rows = result.stdout.strip().splitlines()
    if len(rows) != 1:
        raise RuntimeError('Expected exactly one finalized study session')
    parts = rows[0].split('|')
    if len(parts) != 3 or parts[0] != 'completed' or parts[1] not in ('completed', 'skipped') or parts[2] not in ('completed', 'skipped'):
        raise RuntimeError('PostgreSQL does not confirm completed session and resolved tasks')
    return parts[2]


def publish_verified_receipt(token, session_id=PILOT_SESSION, *, root=ROOT, verifier=db_completed):
    """Publish one opaque status document; raise instead of faking success."""
    if not isinstance(token, str) or RECEIPT_PATTERN.fullmatch(token) is None:
        raise ValueError('Invalid bearer receipt format')
    outcome = verifier(session_id)  # must succeed BEFORE any public status exists
    root = Path(root)
    if root.is_symlink():
        raise RuntimeError('Receipt directory must not be a symlink')
    root.mkdir(parents=True, exist_ok=True, mode=0o711)
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise RuntimeError('Unsafe receipt directory')
    # Nginx's unprivileged worker needs traversal but not directory listing.
    root.chmod(0o711)
    dest = root / (token + '.json')
    if dest.exists() or dest.is_symlink():
        raise RuntimeError('Receipt file already exists; refusing overwrite')
    now = datetime.now(timezone.utc)
    record = {
        'status': 'completed',
        'final_outcome': outcome,
        'verified_at': now.isoformat(timespec='seconds'),
        'expires_at': (now + timedelta(hours=24)).isoformat(timespec='seconds'),
    }
    tmp = root / ('.pending-' + secrets.token_hex(16))
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(record, handle, sort_keys=True)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        tmp.chmod(0o644)
        # Hard-link creation is atomic and refuses to replace a preexisting file.
        os.link(tmp, dest, follow_symlinks=False)
        dfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        tmp.unlink(missing_ok=True)
    print('PASS: PostgreSQL-verified completion receipt published (bearer not logged)')
    return dest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepare-directory', action='store_true',
                   help='Create the read-only-Nginx receipt bind mount directory')
    p.add_argument('--recover-completed-pilot', action='store_true',
                   help='For operator testing only: generate a new receipt for completed Pilot 1')
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    if args.prepare_directory:
        if args.apply:
            if ROOT.is_symlink(): raise RuntimeError('Unsafe receipt bind directory')
            ROOT.mkdir(parents=True, exist_ok=True, mode=0o711)
            ROOT.chmod(0o711)
            print('Prepared receipt bind mount:', ROOT)
        else:
            print('DRY RUN: would prepare', ROOT)
    elif args.recover_completed_pilot:
        result = db_completed(PILOT_SESSION)
        print('Verified completed Pilot 1; final task outcome:', result)
        if args.apply:
            token = secrets.token_hex(32)
            publish_verified_receipt(token, PILOT_SESSION)
            print('OPERATOR-ONLY preview path: /study-complete#receipt=' + token)
            print('Keep this bearer URL private. It expires in 24 hours.')
        else:
            print('DRY RUN: no receipt issued')
    else:
        p.error('Choose --prepare-directory or --recover-completed-pilot')


if __name__ == '__main__':
    main()
