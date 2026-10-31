#!/usr/bin/env python3
"""NERDs Pilot 1 operator-controlled, evidence-preserving task advancement.

Host ONLY; never install in the participant runtime. Does not use browser-supplied
IDs for database attribution. Supports preview, first->second transition, and
final completion. The existing CLI/source collectors are quiesced and flushed
before any status change or workspace replacement.

Important limitation: This is an operator-mediated PILOT workflow. A durable
host supervisor/transactional transition service is needed for unattended study.
"""
from __future__ import annotations
import argparse
import fcntl
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from uuid import UUID

# Explicit per-session context required by the supervisor. Legacy defaults only
# preserve compatibility with the already completed Pilot 1 operator commands.
_DEFAULTS = ('nerds-pilot1-runtime', 'bfa6705c456c',
             '9c6fdb2b-3cdd-4ef6-bc61-d4040bd74155')
_keys = ('NERDS_CONTAINER', 'NERDS_INSTANCE_ID', 'NERDS_SESSION_ID')
_values = tuple(os.environ.get(key) for key in _keys)
if any(_values) and not all(_values):
    raise RuntimeError('All three NERDS_CONTAINER/INSTANCE_ID/SESSION_ID values are required')
CONTAINER, INSTANCE, SESSION = _values if all(_values) else _DEFAULTS
if not re.fullmatch(r'nerds-pilot1-[a-z0-9][a-z0-9-]{0,60}', CONTAINER):
    raise RuntimeError('Unexpected participant container name')
if not re.fullmatch(r'[0-9a-f]{12}', INSTANCE):
    raise RuntimeError('Invalid assigned instance ID')
if str(UUID(SESSION)) != SESSION:
    raise RuntimeError('Invalid session UUID')
TASK_CODES = {'dense_v2', 'lowyield_v1'}
SERVICES = ('xterm', 'firefox', 'api')
COLLECTORS = ('pilot1_auto_ingest.py', 'pilot1_track_sources.py')
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
BASE = '/home/user/fuzz-study'
REFERENCE = '/opt/nerds/released-reference'


def run(args, *, input=None, timeout=90, check=True):
    result = subprocess.run(args, input=input, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'{args[0]} command failed: ' +
                           (result.stderr or result.stdout).decode(errors='replace')[-1200:])
    return result.stdout.decode(errors='replace').strip()


def docker(*args, input=None, timeout=90):
    return run(['docker', 'exec', '-i', '-u', 'root', CONTAINER, *args], input=input, timeout=timeout)


def sql(query):
    return run(['docker','exec','-i','-u','postgres','devob-db-1',
                'psql','-X','-qAt','-v','ON_ERROR_STOP=1','-d','notebook','-c',query])


def assignment():
    rows = sql(f"""
SELECT t.position, t.task_code, t.status, t.task_run_id::text,
       s.status, s.instance_id, s.instance_name
FROM fuzz_pilot.study_sessions s JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
WHERE s.session_id='{SESSION}'::uuid ORDER BY t.position;
""").splitlines()
    if len(rows)!=2:
        raise RuntimeError('Expected exactly two task rows')
    data = [r.split('|') for r in rows]
    if any(len(r)!=7 for r in data) or [r[0] for r in data]!=['1','2']:
        raise RuntimeError('Unexpected task row data')
    if any(r[4]!='active' or r[5]!=INSTANCE or r[6]!=CONTAINER for r in data):
        raise RuntimeError('Active session or instance assignment mismatch')
    if {r[1] for r in data}!=TASK_CODES:
        raise RuntimeError('Unexpected task definitions')
    return data


def container_identity():
    data=json.loads(run(['docker','inspect',CONTAINER]))[0]
    if (not data['State']['Running'] or data['Id'][:12]!=INSTANCE or
        data['Config'].get('Labels',{}).get('nerds.study')!='pilot1' or
        'devob_instances' not in data['NetworkSettings']['Networks']):
        raise RuntimeError('Unexpected participant container identity')


def remote(code, params=None):
    return docker('python3','-c',code, input=json.dumps(params or {}).encode())


REMOTE_PREFLIGHT = r'''
import json,os,sys
p=json.load(sys.stdin)
base='/home/user/fuzz-study'
ref='/opt/nerds/released-reference'
with open(ref+'/active-task.json') as f: metadata=json.load(f)
assert metadata.get('task_code')==p['code'] and metadata.get('position')==p['position'], 'Active task metadata differs'
assert not os.path.islink(base+'/work') and os.path.isfile(base+'/work/Makefile'), 'Missing work Makefile'
assert not os.path.islink(base+'/runs') and os.path.isdir(base+'/runs'), 'Missing runs directory'
assert os.path.islink(base+'/reference') and os.path.realpath(base+'/reference')==ref+'/current', 'Reference link mismatch'
assert os.path.isfile(ref+'/current/Makefile'), 'Missing reference'
assert os.path.isfile('/opt/nerds/task-bundles/'+p['code']+'/Makefile'), 'Missing protected task bundle'
if p['position']==1:
    for name in ('.next-work','.next-runs','.previous-work','.previous-runs'):
        assert not os.path.lexists(base+'/'+name), 'Incomplete earlier transition: '+name
    for name in ('active-task.next.json','active-task.previous.json'):
        assert not os.path.lexists(ref+'/'+name), 'Incomplete earlier transition: '+name
    protected='/opt/nerds/task-bundles'
    for name in ('.lifecycle-stage-reference','.lifecycle-previous-reference'):
        assert not os.path.lexists(protected+'/'+name), 'Incomplete earlier transition: '+name
print(json.dumps(metadata,sort_keys=True))
'''

REMOTE_MARKER = r'''
import json,os,stat,sys
p=json.load(sys.stdin)
path='/home/user/fuzz-study/.finish-request.json'
st=os.lstat(path)
assert stat.S_ISREG(st.st_mode) and 0 < st.st_size < 2048, 'Unsafe outcome request'
with open(path) as f:m=json.load(f)
assert m.get('task_code')==p['code'] and m.get('position')==p['position'], 'No matching participant outcome request'
# Backward compatibility for Finish requests recorded by the original API.
outcome=m.get('outcome','completed')
assert outcome in ('completed','skipped') and outcome==p['outcome'], 'Participant choice does not match operator outcome'
assert isinstance(m.get('requested_at'),str) and len(m['requested_at'])<90, 'Invalid request timestamp'
print(json.dumps({'task_code':p['code'],'position':p['position'],
                  'outcome':outcome,'requested_at':m['requested_at'],
                  'completion_receipt':m.get('completion_receipt')}))
'''

REMOTE_CLEAR_MARKER = r'''
import os,stat
path='/home/user/fuzz-study/.finish-request.json'
if os.path.lexists(path):
    st=os.lstat(path)
    assert stat.S_ISREG(st.st_mode), 'Unsafe finish request marker'
    os.unlink(path)
print('Finish request cleared')
'''

REMOTE_STAGE = r'''
import json,os,shutil,sys
p=json.load(sys.stdin)
base='/home/user/fuzz-study'; ref='/opt/nerds/released-reference'; protected='/opt/nerds/task-bundles'; src=protected+'/'+p['next_code']
assert p['next_code'] in ('dense_v2','lowyield_v1')
assert os.path.isfile(src+'/Makefile')
for path in (base+'/.next-work',base+'/.next-runs',protected+'/.lifecycle-stage-reference',ref+'/active-task.next.json'):
    assert not os.path.lexists(path), 'Pre-existing staging path: '+path
# The staging directories stay root-inaccessible to participants until cutover.
os.mkdir(base+'/.next-work',0o700)
shutil.copytree(src,base+'/.next-work',dirs_exist_ok=True,symlinks=True)
os.mkdir(base+'/.next-runs',0o700)
shutil.copytree(src,protected+'/.lifecycle-stage-reference',symlinks=True)
for parent,dirs,files in os.walk(protected+'/.lifecycle-stage-reference'):
    for fn in files:
        if not os.path.islink(os.path.join(parent,fn)): os.chmod(os.path.join(parent,fn),0o444)
    for dn in dirs:
        if not os.path.islink(os.path.join(parent,dn)): os.chmod(os.path.join(parent,dn),0o555)
os.chmod(protected+'/.lifecycle-stage-reference',0o555)
# Do not expose staged task until cutover, regardless of copied modes.
os.chmod(base+'/.next-work',0o700)
with open(ref+'/active-task.json') as f: m=json.load(f)
m.update(task_code=p['next_code'],position=2,task_run_id=p['next_task_run_id'],status='ready')
with open(ref+'/active-task.next.json','x') as f: json.dump(m,f,sort_keys=True)
os.chmod(ref+'/active-task.next.json',0o600)
print('Next workspace staged without releasing it')
'''

REMOTE_SWAP = r'''
import json,os,stat,sys
p=json.load(sys.stdin)
b='/home/user/fuzz-study'; r='/opt/nerds/released-reference';protected='/opt/nerds/task-bundles'
assert os.path.isfile(b+'/.next-work/Makefile') and os.path.isdir(b+'/.next-runs')
assert os.path.isfile(protected+'/.lifecycle-stage-reference/Makefile') and os.path.isfile(r+'/active-task.next.json')
for old,new in ((b+'/work',b+'/.previous-work'),(b+'/runs',b+'/.previous-runs'),
                (r+'/current',protected+'/.lifecycle-previous-reference'),(r+'/active-task.json',r+'/active-task.previous.json')):
    os.rename(old,new)
    if os.path.isdir(new): os.chown(new,0,0); os.chmod(new,0o700)
for old,new in ((b+'/.next-work',b+'/work'),(b+'/.next-runs',b+'/runs'),
                (protected+'/.lifecycle-stage-reference',r+'/current'),(r+'/active-task.next.json',r+'/active-task.json')):
    os.rename(old,new)
# Protected task bundles may be read-only. Restore user write access to
# the participant work tree after switching; preserve existing execute bits.
for parent,dirs,files in os.walk(b+'/work'):
    os.chown(parent, p['uid'],p['gid'])
    os.chmod(parent, stat.S_IMODE(os.lstat(parent).st_mode) | stat.S_IRWXU)
    for fn in files:
        path=os.path.join(parent,fn)
        if not os.path.islink(path):
            os.chown(path,p['uid'],p['gid'])
            os.chmod(path,stat.S_IMODE(os.lstat(path).st_mode) | stat.S_IRUSR | stat.S_IWUSR)
for path in (b+'/runs',): os.chown(path,p['uid'],p['gid'])
os.chmod(b+'/work',0o755);os.chmod(b+'/runs',0o700)
os.chmod(r+'/current',0o555);os.chmod(r+'/active-task.json',0o644)
print('Task workspace and reference swapped; prior task root-protected in container')
'''

REMOTE_ROLLBACK = r'''
import os
b='/home/user/fuzz-study';r='/opt/nerds/released-reference';protected='/opt/nerds/task-bundles'
for active,old,failed in ((b+'/work',b+'/.previous-work',b+'/.failed-work'),
                          (b+'/runs',b+'/.previous-runs',b+'/.failed-runs'),
                          (r+'/current',protected+'/.lifecycle-previous-reference',protected+'/.lifecycle-failed-reference'),
                          (r+'/active-task.json',r+'/active-task.previous.json',r+'/active-task.failed.json')):
    if os.path.lexists(old):
        if os.path.lexists(active):os.rename(active,failed)
        os.rename(old,active)
        if active in (b+'/work',b+'/runs'):
            os.chown(active,os.getpwnam('user').pw_uid,os.getpwnam('user').pw_gid)
            os.chmod(active,0o755 if active.endswith('work') else 0o700)
        if active==r+'/current':os.chmod(active,0o555)
        if active==r+'/active-task.json':os.chmod(active,0o644)
print('Filesystem rollback attempted; inspect before retrying')
'''.replace('os.getpwnam','__import__("pwd").getpwnam')

REMOTE_FINISH = r'''
import json,os,sys
p=json.load(sys.stdin); r='/opt/nerds/released-reference'
old=r+'/active-task.json';tmp=r+'/active-task.complete.json'
assert not os.path.lexists(tmp)
with open(old) as f: m=json.load(f)
assert m.get('task_code')==p['code'] and m.get('position')==2
assert p['outcome'] in ('completed','skipped')
m['status']=p['outcome']
with open(tmp,'x') as f:json.dump(m,f,sort_keys=True)
os.chmod(tmp,0o644)
os.replace(tmp,old)
print('Marked participant task metadata completed')
'''


def proc_candidates():
    out=run(['ps','-eo','pid=,args='])
    entries={key:[] for key in COLLECTORS}
    for line in out.splitlines():
        parts=line.strip().split(None,1)
        if len(parts)!=2 or not parts[0].isdigit(): continue
        pid=int(parts[0]); args=parts[1]
        for key in COLLECTORS:
            if (key in args and '--container '+CONTAINER in args and
                '--session-id '+SESSION in args and 'scripts/'+key in args):
                entries[key].append((pid,args))
    return entries


def _unit_details(kind, task_id):
    """Read exact systemd unit identity; do not trust a matching PID alone."""
    UUID(SESSION); UUID(task_id)
    label = 'cli' if kind == 'pilot1_auto_ingest.py' else 'src'
    name = f'nerds-p1-{label}-{SESSION}-{task_id}.service'
    result = subprocess.run(
        ['systemctl','--user','show',name,'-p','LoadState','-p','ActiveState',
         '-p','MainPID','-p','Restart'], capture_output=True,text=True,timeout=20)
    if result.returncode:
        raise RuntimeError('Cannot inspect collector systemd unit: '+name)
    values = dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    if not all(key in values for key in ('LoadState','ActiveState','MainPID','Restart')):
        raise RuntimeError('Incomplete systemd collector unit information: '+name)
    return name, values


def stop_collectors(task_id, launcher='popen'):
    """Stop matched collectors; in systemd mode respect true unit ownership.

    Older sessions may have legitimate manually launched collectors. A
    systemd launch-attempt marker always takes precedence over PID fallback.
    """
    matches=proc_candidates()
    for key,entries in matches.items():
        if len(entries)!=1 or '--task-run-id '+task_id not in entries[0][1]:
            raise RuntimeError(f'Expected one collector for current task: {key}, got {entries}')
    decisions=[]
    for key,entries in matches.items():
        pid=entries[0][0]
        if launcher == 'popen':
            decisions.append(('legacy',key,pid,None))
            continue
        if launcher != 'systemd-user':
            raise RuntimeError('Invalid collector launcher')
        label='cli' if key == 'pilot1_auto_ingest.py' else 'sources'
        attempt=Path.home()/'nerds-pilot-runtime'/'supervisor'/'sessions'/SESSION/(
            f'collector-launch-attempt-{label}-{task_id}.json')
        if attempt.is_symlink():
            raise RuntimeError('Unsafe systemd collector attempt marker')
        name,state=_unit_details(key,task_id)
        if attempt.exists():
            if (state['LoadState']!='loaded' or state['ActiveState']!='active' or
                    state['Restart']!='no' or not state['MainPID'].isdigit() or
                    int(state['MainPID'])!=pid):
                raise RuntimeError('Systemd collector ownership mismatch: '+name)
            decisions.append(('systemd',key,pid,name))
        else:
            if state['LoadState']!='not-found':
                raise RuntimeError('Unrecognized systemd collector unit: '+name)
            decisions.append(('legacy',key,pid,None))
    # All collectors are validated before terminating the first one.
    for mode,key,pid,name in decisions:
        if mode=='systemd':
            run(['systemctl','--user','stop',name],timeout=35)
        else:
            os.kill(pid,signal.SIGTERM)
    deadline=time.monotonic()+20
    for mode,key,pid,name in decisions:
        while Path(f'/proc/{pid}').exists() and time.monotonic()<deadline:
            time.sleep(.15)
        if Path(f'/proc/{pid}').exists():
            raise RuntimeError(f'Collector {key} PID {pid} did not exit')
        if mode=='systemd':
            _,state=_unit_details(key,task_id)
            if state['ActiveState']=='active' or state['MainPID'] not in ('0',''):
                raise RuntimeError('Systemd collector still active: '+name)
    print('Old task collectors stopped')


def collector_args(kind,task_id,once):
    script= 'pilot1_auto_ingest.py' if kind=='cli' else 'pilot1_track_sources.py'
    args=[sys.executable,str(Path(__file__).resolve().with_name(script)),
          '--container',CONTAINER,'--session-id',SESSION,'--task-run-id',task_id,'--apply']
    if once:args.append('--once')
    return args


def flush(task_id):
    for kind in ('cli','sources'):
        print('Final '+kind+' collection...')
        result=run(collector_args(kind,task_id,True),timeout=180)
        print('\n'.join(result.splitlines()[-8:]))


def start_collectors(task_id,archive_root):
    if any(proc_candidates().values()):
        raise RuntimeError('Refusing duplicate collectors')
    log_dir=archive_root/'lifecycle-logs'
    log_dir.mkdir(exist_ok=True,parents=True,mode=0o700)
    os.chmod(log_dir,0o700)
    for kind in ('cli','sources'):
        log=log_dir/f'{kind}-{task_id}.log'
        with open(log,'ab') as file:
            process=subprocess.Popen(collector_args(kind,task_id,False),
                stdin=subprocess.DEVNULL,stdout=file,stderr=subprocess.STDOUT,
                start_new_session=True)
        time.sleep(.3)
        if process.poll() is not None:
            raise RuntimeError(f'{kind} collector failed to start; see {log}')
        print(f'Started {kind} collector PID {process.pid}, log {log}')


def ensure_no_live_campaigns():
    # 'comm' reports actual process executable names, not the contents of a
    # participant-supplied shell command. Do not cut over an active fuzz run.
    out=docker('ps','-eo','comm=')
    active=[name for name in out.splitlines()
            if name.strip() in ('fuzz_a','fuzz_b','fuzz_c','clang','clang-19')]
    if active:
        raise RuntimeError('Active fuzzer/compiler processes found: '+', '.join(active))


def services(action):
    for service in SERVICES:
        print(f'{action} {service}')
        docker('sv',action,f'/home/user/services/{service}',timeout=35)


def archive_workspace(archive_root,task_id):
    directory=archive_root/'lifecycle-workspaces'/SESSION/task_id
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(directory,0o700)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path=directory/f'workspace-{stamp}.tar'
    tmp=directory/f'.{path.name}.partial'
    if tmp.exists():raise RuntimeError('Unexpected partial archive exists')
    cmd=['docker','exec','-i','-u','root',CONTAINER,'tar','-C','/', '-cf','-',
         'home/user/fuzz-study/work','home/user/fuzz-study/runs',
         'opt/nerds/released-reference/current',
         'opt/nerds/released-reference/active-task.json']
    digest=hashlib.sha256(); size=0
    with tmp.open('xb') as stream:
        os.chmod(tmp,0o600)
        process=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            while True:
                chunk=process.stdout.read(1024*1024)
                if not chunk:break
                size+=len(chunk)
                if size>MAX_ARCHIVE_BYTES:
                    process.kill()
                    raise RuntimeError('Workspace archive exceeds 1 GiB; aborting transition')
                stream.write(chunk);digest.update(chunk)
            errors=process.stderr.read().decode(errors='replace')
            if process.wait(timeout=30)!=0:raise RuntimeError('Workspace archival failed: '+errors[-400:])
            stream.flush();os.fsync(stream.fileno())
        except BaseException:
            process.kill(); process.wait()
            tmp.unlink(missing_ok=True)
            raise
    with tarfile.open(tmp,'r:') as tar:
        paths=set(tar.getnames())
        required={'home/user/fuzz-study/work','home/user/fuzz-study/runs',
                  'opt/nerds/released-reference/current',
                  'opt/nerds/released-reference/active-task.json'}
        if not all(any(p==r or p.startswith(r+'/') for p in paths) for r in required):
            tmp.unlink()
            raise RuntimeError('Workspace archive missing required paths')
    os.replace(tmp,path)
    print(f'Preserved workspace: {path} ({size} bytes, sha256 {digest.hexdigest()})')


def transition_sql(old, new, mode, outcome='completed', requested_at=None):
    """Atomic task outcome + participant choice events + next-task release.

    `skipped` is an intentional participant decision, not a completed task.
    The host validates and normalizes the request timestamp; DB received_at
    remains the authoritative server-side ingestion time.
    """
    if mode not in ('advance', 'complete') or outcome not in ('completed', 'skipped'):
        raise ValueError('Invalid lifecycle action or participant outcome')
    if requested_at is not None:
        parsed = datetime.fromisoformat(requested_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('Participant request timestamp must include timezone')
        requested_at = parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')
    position = 1 if mode == 'advance' else 2
    chosen = old if mode == 'advance' else new
    outcome_event = 'task_skipped' if outcome == 'skipped' else 'task_completed'
    choice = 'skip' if outcome == 'skipped' else 'finish'
    # Only normalized/known values go into SQL. Escape JSON as a literal too.
    def json_sql(payload):
        value = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        return "'" + value.replace("'", "''") + "'::jsonb"
    requested = json_sql({
        'capture_method': 'operator_host_transition',
        'requested_by': 'participant',
        'participant_choice': choice,
        'outcome': outcome,
        'requested_at': requested_at,
        'position': position,
    })
    recorded = json_sql({
        'capture_method': 'operator_host_transition',
        'requested_by': 'participant',
        'participant_choice': choice,
        'outcome': outcome,
        'position': position,
    })
    request_event = f"""
INSERT INTO fuzz_pilot.events(session_id,task_run_id,event_type,event_source,event_key,payload)
VALUES ('{SESSION}'::uuid,'{chosen[3]}'::uuid,'task_outcome_requested','manager',
        'lifecycle:{position}:outcome-requested',{requested});
"""
    done_event = f"""
INSERT INTO fuzz_pilot.events(session_id,task_run_id,event_type,event_source,event_key,payload)
VALUES ('{SESSION}'::uuid,'{chosen[3]}'::uuid,'{outcome_event}','manager',
        'lifecycle:{position}:{outcome}',{recorded});
"""
    if mode=='advance':
        return f"""
BEGIN;
DO $guard$
BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM fuzz_pilot.study_sessions s
  JOIN fuzz_pilot.task_runs t1 ON t1.session_id=s.session_id AND t1.position=1
  JOIN fuzz_pilot.task_runs t2 ON t2.session_id=s.session_id AND t2.position=2
  WHERE s.session_id='{SESSION}'::uuid AND s.status='active'
   AND s.instance_id='{INSTANCE}' AND s.instance_name='{CONTAINER}'
   AND t1.task_run_id='{old[3]}'::uuid AND t1.status IN ('ready','active')
   AND t2.task_run_id='{new[3]}'::uuid AND t2.status='locked'
  FOR UPDATE OF s,t1,t2
 ) THEN RAISE EXCEPTION 'Task advancement guard failed'; END IF;
END $guard$;
UPDATE fuzz_pilot.task_runs SET status='{outcome}',ended_at=now()
 WHERE task_run_id='{old[3]}'::uuid AND status IN ('ready','active');
UPDATE fuzz_pilot.task_runs SET status='ready'
 WHERE task_run_id='{new[3]}'::uuid AND status='locked';
{request_event}
{done_event}
INSERT INTO fuzz_pilot.events(session_id,task_run_id,event_type,event_source,event_key,payload)
VALUES ('{SESSION}'::uuid,'{new[3]}'::uuid,'task_released','manager',
        'lifecycle:2:released',
        '{{"capture_method":"operator_host_transition","position":2}}'::jsonb);
COMMIT;"""
    return f"""
BEGIN;
DO $guard$
BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM fuzz_pilot.study_sessions s
  JOIN fuzz_pilot.task_runs t1 ON t1.session_id=s.session_id AND t1.position=1
  JOIN fuzz_pilot.task_runs t2 ON t2.session_id=s.session_id AND t2.position=2
  WHERE s.session_id='{SESSION}'::uuid AND s.status='active'
   AND s.instance_id='{INSTANCE}' AND s.instance_name='{CONTAINER}'
   AND t1.status IN ('completed','skipped') AND t2.task_run_id='{new[3]}'::uuid
   AND t2.status IN ('ready','active')
  FOR UPDATE OF s,t1,t2
 ) THEN RAISE EXCEPTION 'Session finalization guard failed'; END IF;
END $guard$;
UPDATE fuzz_pilot.task_runs SET status='{outcome}',ended_at=now()
 WHERE task_run_id='{new[3]}'::uuid AND status IN ('ready','active');
UPDATE fuzz_pilot.study_sessions SET status='completed',ended_at=now()
 WHERE session_id='{SESSION}'::uuid AND status='active';
{request_event}
{done_event}
INSERT INTO fuzz_pilot.events(session_id,task_run_id,event_type,event_source,event_key,payload)
VALUES ('{SESSION}'::uuid,'{new[3]}'::uuid,'session_completed','manager',
        'lifecycle:session:completed',
        {json_sql({'capture_method':'operator_host_transition','final_task_outcome':outcome,
                   'session_outcome':'all_tasks_resolved'})});
COMMIT;"""


def apply_sql(script):
    run(['docker','exec','-i','-u','postgres','devob-db-1','psql',
         '-X','-v','ON_ERROR_STOP=1','-d','notebook','-f','-'],input=script.encode(),timeout=40)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action',choices=('advance','complete'),required=True)
    parser.add_argument('--outcome',choices=('completed','skipped'),default='completed',
                        help='Participant choice on this task; must match recorded request')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--collector-launcher',choices=('popen','systemd-user'),default='popen')
    parser.add_argument('--archive-root',type=Path,default=Path.home()/'nerds-pilot-backups')
    args=parser.parse_args()
    container_identity()
    a,b=assignment()
    chosen=a if args.action=='advance' else b
    expected_position=1 if args.action=='advance' else 2
    if not (chosen[0]==str(expected_position) and chosen[2] in ('ready','active')):
        raise RuntimeError(f'Current task not releasable: {chosen}')
    if args.action=='advance' and b[2]!='locked':raise RuntimeError('Second task already released')
    if args.action=='complete' and a[2] not in ('completed','skipped'):
        raise RuntimeError('First task has not reached a terminal outcome')
    current=json.loads(remote(REMOTE_PREFLIGHT,{'code':chosen[1], 'position':expected_position}))
    print(f'Current task {chosen[1]} ({chosen[2]}), task_run_id={chosen[3]}')
    print(f'Next task {b[1]} ({b[2]})' if args.action=='advance' else 'Next: session completed')
    print('Current metadata:',current)
    print('Requested outcome to process:', args.outcome)
    matches=proc_candidates()
    for key,items in matches.items():
        print(key,':', [(pid, '--task-run-id '+chosen[3] in cmd) for pid,cmd in items])
    if not args.apply:
        print('DRY RUN — no changes made. After the participant chooses Finish or Skip,')
        print('rerun with --apply and the matching --outcome value.')
        return
    marker = json.loads(remote(REMOTE_MARKER, {
        'code': chosen[1], 'position': expected_position,
        'outcome': args.outcome,
    }))
    # Check the recorded time before making any changes to services or files.
    request_time = datetime.fromisoformat(marker['requested_at'])
    if request_time.tzinfo is None or request_time.utcoffset() is None:
        raise RuntimeError('Invalid timezone on participant request timestamp')
    print('Participant choice verified:',marker['outcome'],marker['requested_at'])
    if args.action == 'complete':
        # The receipt is a bearer capability, not an identifying URL parameter.
        token = marker.get('completion_receipt')
        if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{64}', token):
            raise RuntimeError('Final task request lacks a valid completion receipt')
    for key,items in matches.items():
        if len(items)!=1 or '--task-run-id '+chosen[3] not in items[0][1]:
            raise RuntimeError(f'Collector mismatch: {key}')
    os.umask(0o077)
    root=args.archive_root.expanduser()
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock_path=root/('pilot1-lifecycle-'+SESSION+'.lock')
    if lock_path.is_symlink():raise RuntimeError('Unsafe lifecycle lock')
    lock_fd=open(lock_path,'a+')
    os.chmod(lock_path,0o600)
    try:
        fcntl.flock(lock_fd.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock_fd.close()
        raise RuntimeError('Another Pilot 1 lifecycle operation is running')
    frozen=False; committed=False; swapped=False; collectors_stopped=False
    try:
        frozen=True
        services('stop')
        ensure_no_live_campaigns()
        collectors_stopped=True
        stop_collectors(chosen[3],args.collector_launcher)
        flush(chosen[3])
        archive_workspace(root,chosen[3])
        if args.action=='advance':
            remote(REMOTE_STAGE,{'next_code':b[1],'next_task_run_id':b[3]})
            uid=int(docker('id','-u','user')); gid=int(docker('id','-g','user'))
            swapped=True  # rollback handles partial swap as well
            print(remote(REMOTE_SWAP,{'uid':uid,'gid':gid}))
        apply_sql(transition_sql(a,b,args.action,args.outcome,marker['requested_at']))
        committed=True
        if args.action=='complete':
            print(remote(REMOTE_FINISH,{'code':chosen[1], 'outcome':args.outcome}))
            # Publish only AFTER PostgreSQL commits the final outcome.
            # If publication fails, preserve the marker for an operator to
            # recover without re-running this already-committed transition.
            from pilot1_completion_receipt import publish_verified_receipt
            publish_verified_receipt(marker['completion_receipt'], SESSION)
        print(remote(REMOTE_CLEAR_MARKER))
        services('start'); frozen=False
        if args.action=='advance':
            if args.collector_launcher=='systemd-user':
                # Supervisor observes completed transition and owns new collectors.
                # Never bypass its durable launch-attempt markers.
                print('Next-task collector startup delegated to systemd-aware supervisor')
            else:
                start_collectors(b[3],root)
        print('SUCCESS: '+('Next task released and collectors switched' if args.action=='advance'
                            else 'Study session finalized')+f'; participant outcome={args.outcome}')
    except BaseException:
        if not committed and swapped:
            try: print(remote(REMOTE_ROLLBACK))
            except Exception as exc: print('URGENT: automatic file rollback failed:',exc,file=sys.stderr)
        if frozen:
            try: services('start')
            except Exception as exc: print('URGENT: service resume failed:',exc,file=sys.stderr)
        if collectors_stopped and not committed:
            if args.collector_launcher=='systemd-user':
                # Transition-inflight marker is left in place; explicit review is
                # required before any restart after a failed systemd handoff.
                print('URGENT: systemd collector restart blocked pending manual review',file=sys.stderr)
            else:
                try:start_collectors(chosen[3],root)
                except Exception as exc:print('URGENT: check collector PIDs and restart missing collector manually:',exc,file=sys.stderr)
        raise
    finally:
        lock_fd.close()


if __name__=='__main__':
    try:main()
    except (RuntimeError,ValueError,subprocess.TimeoutExpired,OSError,AssertionError) as exc:
        print('PILOT1 LIFECYCLE STOPPED:',exc,file=sys.stderr)
        sys.exit(1)
