#!/usr/bin/env python3
"""Pilot 1 host-side automatic task handoff, using the existing guarded lifecycle.

Run on the trusted WSL host, NEVER in the participant container.
The watcher does not take task IDs/outcomes from web parameters and never writes
PostgreSQL itself; pilot1_lifecycle.py validates the participant decision,
archives data, switches workspaces, commits states, and relaunches collectors.

Preview: python3 scripts/pilot1_auto_transition.py
Supervise: python3 -u scripts/pilot1_auto_transition.py --watch --apply

If any transition errors, the watcher halts and does NOT retry automatically:
a partially completed transition requires explicit operator inspection.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime

from pilot1_lifecycle import CONTAINER, SESSION, INSTANCE, assignment, container_identity

MARKER='/home/user/fuzz-study/.finish-request.json'
RUNNER=Path(__file__).resolve().with_name('pilot1_lifecycle.py')
STOP=False


def say(msg):
    print(f'[{datetime.now().astimezone().isoformat(timespec="seconds")}] {msg}',flush=True)


def marker_from_container():
    # Only data, not an executable command, crosses the trust boundary.
    source=r'''
import json,os,stat
p='/home/user/fuzz-study/.finish-request.json'
if not os.path.lexists(p):
 print('null')
else:
 st=os.lstat(p)
 if not stat.S_ISREG(st.st_mode) or not (0<st.st_size<2048):
  raise SystemExit('Invalid participant outcome marker')
 with open(p) as file: data=json.load(file)
 print(json.dumps(data,sort_keys=True))
'''
    result=subprocess.run(['docker','exec','-i','-u','root',CONTAINER,
                           'python3','-c',source],capture_output=True,text=True,timeout=15)
    if result.returncode:
        raise RuntimeError('Unable to read pending request safely: '+result.stderr[-500:])
    try:
        value=json.loads(result.stdout)
    except (ValueError,TypeError) as exc:
        raise RuntimeError('Participant request is not valid JSON') from exc
    return value


def choose_action(rows, marker):
    """Validate a participant intent against authoritative DB task assignment.

    Returns (action, outcome) or None for no request / already completed.
    Does not run lifecycle steps or mutate the filesystem.
    """
    if marker is None:
        return None
    if not isinstance(marker,dict):
        raise RuntimeError('Unexpected outcome request format')
    first,second=rows
    if first[2] in ('ready','active') and second[2]=='locked':
        active=first;action='advance'
    elif first[2] in ('completed','skipped') and second[2] in ('ready','active'):
        active=second;action='complete'
    else:
        raise RuntimeError('A request exists, but session is not at a safe task boundary')
    if (type(marker.get('position')) is not int or
        marker['position']!=int(active[0]) or
        marker.get('task_code')!=active[1] or
        marker.get('outcome','completed') not in ('completed','skipped')):
        raise RuntimeError('Participant request and current DB task mismatch')
    stamp=marker.get('requested_at')
    if not isinstance(stamp,str) or len(stamp)>90:
        raise RuntimeError('Invalid request timestamp')
    try:
        parsed=datetime.fromisoformat(stamp)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('Missing timezone')
    except (ValueError,OverflowError) as exc:
        raise RuntimeError('Invalid request timestamp') from exc
    return action,marker.get('outcome','completed')


def check_once(apply):
    # Validates against the exact running instance and active session.
    container_identity()
    rows=assignment()
    pending=marker_from_container()
    chosen=choose_action(rows,pending)
    if chosen is None:
        return 'none'
    action,outcome=chosen
    code=rows[0][1] if action=='advance' else rows[1][1]
    say(f'Participant requested {outcome} for {code}; action={action}')
    if not apply:
        say('PREVIEW ONLY — no transition performed')
        return 'pending'
    # Explicit mode comes from the trusted host supervisor, never participant data.
    launcher=os.environ.get('NERDS_COLLECTOR_LAUNCHER','popen')
    if launcher not in ('popen','systemd-user'):
        raise RuntimeError('Invalid collector-launcher environment')
    command=[sys.executable,str(RUNNER),'--action',action,'--outcome',outcome,
             '--collector-launcher',launcher,'--apply']
    say('Executing guarded task transition with archive, DB transaction, and collector switch')
    result=subprocess.run(command,check=False)
    if result.returncode:
        raise RuntimeError('Lifecycle transition failed (exit '+str(result.returncode)+'). '
                           'Automatic watcher halted; inspect workspace, logs, task rows and collector state before retrying.')
    say('Task transition completed; next task will appear in the participant UI')
    return 'advanced' if action=='advance' else 'completed'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Authorize processing stored participant requests')
    parser.add_argument('--watch',action='store_true',help='Keep watching for future participant decisions')
    parser.add_argument('--interval',type=float,default=3.0)
    args=parser.parse_args()
    if not (1 <= args.interval <= 30):
        parser.error('--interval must be between 1 and 30 seconds')
    if args.watch and not args.apply:
        parser.error('--watch requires --apply (the default is a one-time read-only preview)')
    if not RUNNER.is_file():
        raise RuntimeError('Existing lifecycle script is missing')
    root=Path.home()/'nerds-pilot-runtime'/'logs'
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(root,0o700)
    lock=root/('pilot1-auto-transition-'+SESSION+'.lock')
    if lock.is_symlink():
        raise RuntimeError('Unsafe watcher lock path')
    with lock.open('a+') as handle:
        os.chmod(lock,0o600)
        try:
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('A Pilot 1 transition watcher is already active') from exc
        def stop_handler(signum,frame):
            global STOP
            STOP=True
        signal.signal(signal.SIGTERM,stop_handler)
        signal.signal(signal.SIGINT,stop_handler)
        say('Pilot 1 handoff watcher starting; mode='+('APPLY' if args.apply else 'PREVIEW'))
        while True:
            # Stop after finalization rather than treating the now-terminal session as an error.
            if args.watch:
                # assignment() requires active session; detect terminal session before calling it.
                from pilot1_lifecycle import sql as db_sql
                status=db_sql(f"SELECT status FROM fuzz_pilot.study_sessions WHERE session_id='{SESSION}'::uuid;").strip()
                if status=='completed':
                    say('Session already completed; watcher stopping')
                    return 0
                if status!='active':
                    raise RuntimeError('Unexpected study session status: '+status)
            state=check_once(args.apply)
            if not args.watch or state=='completed':
                return 0
            if STOP:
                say('Stop requested; no new task transition will start')
                return 0
            time.sleep(args.interval)


if __name__=='__main__':
    try:
        sys.exit(main())
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        print('PILOT1 AUTO TRANSITION STOPPED:',exc,file=sys.stderr,flush=True)
        sys.exit(1)
