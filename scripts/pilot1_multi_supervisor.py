#!/usr/bin/env python3
"""Trusted host supervisor for multiple *Pilot 1* sessions.

PREVIEW by default. `--watch --apply` manages collectors and executes the
existing guarded single-session transition, with a durable per-session
inflight marker preventing automatic retries after crashes/failures.

Runs on Docker host (WSL for local pilot, Ubuntu for server); NEVER in
participant containers. This release deliberately only handles pilot1 sessions
and protected nerds-pilot1-* instances. Full-study manager integration needs
separate qualification, rather than broadening trust silently.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
from uuid import UUID

ROOT = Path.home() / 'nerds-pilot-runtime' / 'supervisor'
SCRIPT_DIR = Path(__file__).resolve().parent
NAME_RE = re.compile(r'nerds-pilot1-[a-z0-9][a-z0-9-]{0,60}\Z')
INSTANCE_RE = re.compile(r'[0-9a-f]{12}\Z')
SESSION_RE = re.compile(r'[0-9a-f-]{36}\Z')
STOP = False

# Collector services are opt-in. Existing/manual Pilot 1 sessions retain their
# current processes; new collectors can be placed in distinct user systemd
# transient services without affecting any active participant.
COLLECTOR_LAUNCHERS = ('popen', 'systemd-user')

@dataclass(frozen=True)
class Assignment:
    session: str
    container: str
    instance: str
    first_id: str
    first_code: str
    first_status: str
    second_id: str
    second_code: str
    second_status: str

    @property
    def released(self):
        if self.first_status in ('ready', 'active') and self.second_status == 'locked':
            return self.first_id
        if self.first_status in ('completed', 'skipped') and self.second_status in ('ready', 'active'):
            return self.second_id
        if self.first_status == 'locked' and self.second_status == 'locked':
            return None  # enrollment/provisioning in progress
        raise ValueError('Unexpected task-state combination; manual review required')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def say(value):
    print(f'[{now()}] {value}', flush=True)


def call(args, timeout=30, input=None):
    return subprocess.run(args, input=input, text=True, capture_output=True,
                          timeout=timeout, check=False)


def sql_active():
    query = """
SELECT s.session_id::text,s.instance_name,s.instance_id,
       a.task_run_id::text,a.task_code,a.status,
       b.task_run_id::text,b.task_code,b.status
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs a ON a.session_id=s.session_id AND a.position=1
JOIN fuzz_pilot.task_runs b ON b.session_id=s.session_id AND b.position=2
WHERE s.status='active' AND s.study_phase='pilot1'
  AND s.instance_name IS NOT NULL AND s.instance_id IS NOT NULL
ORDER BY s.session_id;
"""
    result = call(['docker','exec','-u','postgres','devob-db-1','psql',
                   '-X','-qAt','-F','|','-v','ON_ERROR_STOP=1','-d','notebook','-c',query])
    if result.returncode:
        raise RuntimeError('Unable to list study sessions from PostgreSQL: '+result.stderr[-300:])
    return parse_rows(result.stdout)


def parse_rows(output):
    entries=[]
    seen_sessions=set(); seen_containers=set()
    for line in output.splitlines():
        cells=line.split('|')
        if len(cells)!=9:
            raise ValueError('Unexpected PostgreSQL session row structure')
        a=Assignment(*cells)
        if (str(UUID(a.session)) != a.session or
            not NAME_RE.fullmatch(a.container) or not INSTANCE_RE.fullmatch(a.instance) or
            str(UUID(a.first_id)) != a.first_id or str(UUID(a.second_id)) != a.second_id or
            (a.first_code,a.second_code) not in (('dense_v2','lowyield_v1'),('lowyield_v1','dense_v2')) or
            a.session in seen_sessions or a.container in seen_containers):
            raise ValueError('Invalid or duplicate active session assignment')
        _ = a.released  # validate that the task combination is expected
        seen_sessions.add(a.session);seen_containers.add(a.container)
        entries.append(a)
    return entries


def validate_docker(a):
    result=call(['docker','inspect',a.container])
    if result.returncode:
        raise RuntimeError('Assigned container is not available')
    items=json.loads(result.stdout)
    if len(items)!=1:
        raise RuntimeError('Unexpected Docker inspect result')
    item=items[0]
    if (not item['State']['Running'] or item['Id'][:12]!=a.instance or
        item['Name']!='/'+a.container or
        item['Config'].get('Labels',{}).get('nerds.study')!='pilot1' or
        'devob_instances' not in item['NetworkSettings']['Networks']):
        raise RuntimeError('Assigned Docker identity/label/network mismatch')


def pending_marker(a):
    # Never emit the marker or receipt token to the log. A participant cannot
    # request arbitrary shell actions; the guarded worker validates this JSON.
    source='''import os,json,stat\np='/home/user/fuzz-study/.finish-request.json'\nif not os.path.lexists(p):\n print('no')\nelse:\n s=os.lstat(p)\n if not stat.S_ISREG(s.st_mode) or not 0<s.st_size<2048: raise SystemExit(5)\n with open(p) as f: m=json.load(f)\n if not isinstance(m,dict): raise SystemExit(6)\n print('yes')\n'''
    result=call(['docker','exec','-u','root',a.container,'python3','-c',source],timeout=20)
    if result.returncode or result.stdout.strip() not in ('yes','no'):
        raise RuntimeError('Unsafe/unreadable participant decision marker')
    return result.stdout.strip()=='yes'


def state_dir(root,session):
    path=root/'sessions'/session
    path.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.chmod(0o700)
    return path


def write_once(path, details):
    if path.is_symlink():
        raise RuntimeError('Unsafe state marker')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(details,f,sort_keys=True)
        f.write('\n')
        f.flush();os.fsync(f.fileno())


def blocked(path):
    return (path/'transition-inflight.json').exists() or (path/'needs-review.json').exists()


def environment(a, collector_launcher='popen'):
    if collector_launcher not in COLLECTOR_LAUNCHERS:
        raise ValueError('Invalid collector launcher for transition')
    env=os.environ.copy()
    env.update(NERDS_SESSION_ID=a.session, NERDS_CONTAINER=a.container,
               NERDS_INSTANCE_ID=a.instance,
               NERDS_COLLECTOR_LAUNCHER=collector_launcher)
    return env


def recorded_processes(a):
    result=call(['ps','-eo','pid=,args='])
    if result.returncode:raise RuntimeError('Unable to inspect collector processes')
    out={'pilot1_auto_ingest.py':[],'pilot1_track_sources.py':[]}
    for line in result.stdout.splitlines():
        parts=line.strip().split(None,1)
        if len(parts)!=2 or not parts[0].isdigit(): continue
        try: tokens=shlex.split(parts[1])
        except ValueError: continue
        filenames=[filename for filename in out if any(
            t.endswith('/scripts/'+filename) for t in tokens)]
        if not filenames: continue
        def option(name):
            return tokens[tokens.index(name)+1] if name in tokens and tokens.index(name)+1<len(tokens) else None
        if option('--container')==a.container and option('--session-id')==a.session:
            for f in filenames:out[f].append((int(parts[0]),option('--task-run-id')))
    return out


def collector_unit_name(a, filename, task):
    """Deterministic per-session, per-task unit; no participant input in names."""
    if str(UUID(a.session)) != a.session or str(UUID(task)) != task:
        raise ValueError('Invalid session/task ID for collector unit')
    kind={'pilot1_auto_ingest.py':'cli', 'pilot1_track_sources.py':'src'}[filename]
    return f'nerds-p1-{kind}-{a.session}-{task}.service'


def start_systemd_collector(a, filename, task, command, log):
    """One persistent transient service, with no automatic collector retries.

    `systemd-run` returns after exec for Type=exec. Confirm that *our* task's
    process is the unit's MainPID, not merely a same-named detached program.
    """
    unit=collector_unit_name(a,filename,task)
    # An already loaded (including FAILED) unit is never overwritten/reset.
    status=call(['systemctl','--user','show',unit,'-p','LoadState','--value'],timeout=15)
    if status.returncode or status.stdout.strip()!='not-found':
        raise RuntimeError('Collector unit already exists or cannot be inspected: '+unit+
                           ' '+status.stdout.strip()+' '+status.stderr[-150:])
    systemd_command=[
        'systemd-run','--user','--unit='+unit,
        '--property=Type=exec','--property=Restart=no',
        '--property=KillMode=control-group','--property=UMask=0077',
        '--property=StandardOutput=append:'+str(log),
        '--property=StandardError=inherit',
        *command,
    ]
    launched=call(systemd_command,timeout=25)
    if launched.returncode:
        raise RuntimeError('systemd-run failed for '+unit+': '+launched.stderr[-250:])
    # A short verification window also catches prompt exits and exec failures.
    time.sleep(1)
    pid_result=call(['systemctl','--user','show',unit,'-p','MainPID','--value'],timeout=15)
    if pid_result.returncode or not pid_result.stdout.strip().isdigit():
        raise RuntimeError('Cannot verify collector unit MainPID: '+unit)
    pid=int(pid_result.stdout.strip())
    matches=recorded_processes(a)[filename]
    if pid<=0 or matches != [(pid,task)]:
        raise RuntimeError('Collector systemd unit did not own the expected live task process: '+unit)
    return pid


def manage_collectors(a, root, dry_run, launcher='popen'):
    if launcher not in COLLECTOR_LAUNCHERS:
        raise ValueError('Unsupported collector launcher')
    task=a.released
    if task is None:
        return 'awaiting provisioning'
    d=(root/'sessions'/a.session) if dry_run else state_dir(root,a.session)
    found=recorded_processes(a)
    kinds={'pilot1_auto_ingest.py':'cli','pilot1_track_sources.py':'sources'}
    for filename,matches in found.items():
        if len(matches)>1 or any(item[1]!=task for item in matches):
            raise RuntimeError('Mismatched or duplicate task-specific collector: '+filename)
    missing=[name for name,matches in found.items() if not matches]
    if not missing:
        if not dry_run:
            marker=d/('collectors-observed-'+task)
            if not marker.exists():write_once(marker,{'task_run_id':task,'observed_at':now()})
        return '2 collectors active'
    if dry_run:return 'collector(s) missing: '+', '.join(missing)
    if (d/('collectors-observed-'+task)).exists():
        raise RuntimeError('Previously active collector disappeared; refusing silent restart')
    if launcher == 'systemd-user':
        # Fail closed if a previous attempt may have launched a service, even if
        # systemd later unloaded it. Operators must reconcile attempt markers.
        for filename in missing:
            attempt=d/('collector-launch-attempt-'+kinds[filename]+'-'+task+'.json')
            if attempt.exists() or attempt.is_symlink():
                raise RuntimeError('Collector previously launched or attempted; manual review: '+str(attempt))
    for filename in missing:
        log_dir=Path.home()/'nerds-pilot-backups'/'supervisor-logs'/a.session
        log_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        log=log_dir/(kinds[filename]+'-'+task+'.log')
        command=[sys.executable,'-u',str(SCRIPT_DIR/filename),
                 '--container',a.container,'--session-id',a.session,
                 '--task-run-id',task,'--apply']
        if launcher == 'systemd-user':
            # Write before spawn: a crash between spawn and bookkeeping must
            # NOT allow an automatic second collector for this task.
            attempt=d/('collector-launch-attempt-'+kinds[filename]+'-'+task+'.json')
            write_once(attempt,{'task_run_id':task,'kind':kinds[filename],
                                'attempted_at':now(),'launcher':'systemd-user'})
            pid=start_systemd_collector(a,filename,task,command,log)
        else:
            with log.open('ab') as out:
                proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,
                                      stdout=out,stderr=subprocess.STDOUT,
                                      start_new_session=True)
            time.sleep(0.8)
            if proc.poll() is not None:
                raise RuntimeError('Collector failed to start: '+filename+'; inspect '+str(log))
            pid=proc.pid
        say(f'Collector started for session {a.session}: {filename}, PID {pid} ({launcher})')
    return 'collectors started'


def start_transition(a, d, dry_run, collector_launcher='popen'):
    if dry_run:return 'pending participant decision (preview only)'
    inflight=d/'transition-inflight.json'
    write_once(inflight,{'session':a.session,'container':a.container,
                         'instance':a.instance,'collector_launcher':collector_launcher,
                         'started_at':now()})
    log=d/'transition.log'
    cmd=[sys.executable,'-u',str(SCRIPT_DIR/'pilot1_auto_transition.py'),'--apply']
    try:
        with log.open('ab') as out:
            proc=subprocess.Popen(cmd,env=environment(a, collector_launcher),stdin=subprocess.DEVNULL,
                                  stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
    except BaseException:
        # The marker is intentionally retained if spawning fails, for review.
        raise
    say(f'Transition started for session {a.session}; PID {proc.pid}; log {log}')
    return proc


def finish_workers(workers, root):
    for session,proc in list(workers.items()):
        rc=proc.poll()
        if rc is None:continue
        d=state_dir(root,session)
        if rc==0:
            (d/'transition-inflight.json').unlink()
            say(f'Transition completed for session {session}')
        else:
            marker=d/'needs-review.json'
            if not marker.exists():
                write_once(marker,{'session':session,'exit_code':rc,'failed_at':now(),
                                   'message':'Manual inspection required before further actions'})
            say(f'TRANSITION FAILED for session {session}; auto-retry disabled, inspect {d}/transition.log')
        workers.pop(session)


def signal_stop(*_):
    global STOP
    STOP=True


def supervisor_once(root, apply, workers, collector_launcher='popen'):
    sessions=sql_active()
    for a in sessions:
        if a.session in workers:continue
        d=state_dir(root,a.session) if apply else root/'sessions'/a.session
        if blocked(d):
            say(f'SESSION BLOCKED (manual review required): {a.session}')
            continue
        try:
            validate_docker(a)
            if a.released is None:
                say(f'Awaiting provisioned first task: {a.session}')
                continue
            if pending_marker(a):
                result=start_transition(a,d,not apply,collector_launcher)
                if apply:workers[a.session]=result
                else:say(f'PREVIEW: {a.session}: {result}')
            else:
                result=manage_collectors(a,root,not apply,launcher=collector_launcher)
                if not apply:say(f'PREVIEW: {a.session}: {result}')
        except Exception as exc:
            say(f'SESSION PROBLEM {a.session}: {exc}')
            if apply:
                marker=d/'needs-review.json'
                if not marker.exists():
                    write_once(marker,{'session':a.session,'failed_at':now(),
                                       'message':'Supervisor preflight failed; manual review required'})
    return len(sessions)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--watch',action='store_true')
    p.add_argument('--apply',action='store_true')
    p.add_argument('--interval',type=float,default=5.0)
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--collector-launcher',choices=COLLECTOR_LAUNCHERS,
                   default='popen',help='Opt-in systemd-user services for NEW collectors only')
    args=p.parse_args(argv)
    if args.watch and not args.apply:
        p.error('--watch requires --apply')
    if not 3<=args.interval<=60:
        p.error('--interval must be 3–60 seconds')
    for filename in ('pilot1_auto_transition.py','pilot1_lifecycle.py',
                     'pilot1_auto_ingest.py','pilot1_track_sources.py'):
        if not (SCRIPT_DIR/filename).is_file():
            raise RuntimeError('Missing required host script: '+filename)
    root=args.root.expanduser().resolve()
    if not args.apply:
        say('Pilot supervisor preview; no mutations')
        supervisor_once(root,False,{},collector_launcher=args.collector_launcher)
        return 0
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    root.chmod(0o700)
    lock=root/'supervisor.lock'
    if lock.is_symlink():raise RuntimeError('Unsafe supervisor lock path')
    with lock.open('a+') as f:
        fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        os.chmod(lock,0o600)
        signal.signal(signal.SIGTERM,signal_stop)
        signal.signal(signal.SIGINT,signal_stop)
        workers={}
        say('Pilot supervisor running; watch='+str(args.watch))
        while True:
            finish_workers(workers,root)
            try:supervisor_once(root,True,workers,collector_launcher=args.collector_launcher)
            except Exception as exc:say('Supervisor database/discovery error: '+str(exc))
            if not args.watch or STOP:
                if workers:
                    say('Supervisor stopping with in-flight transitions; durable markers prevent automatic replay')
                break
            time.sleep(args.interval)
    return 0


if __name__=='__main__':
    try:sys.exit(main())
    except (RuntimeError,ValueError,OSError,subprocess.TimeoutExpired) as exc:
        print('PILOT SUPERVISOR STOPPED: '+str(exc),file=sys.stderr,flush=True)
        sys.exit(1)
