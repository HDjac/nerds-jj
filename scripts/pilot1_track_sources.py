#!/usr/bin/env python3
"""NERDs Pilot 1 host-side polling source tracker.

Capture only source-like files under the assigned participant's /home/user/fuzz-study/work.
Keep content-addressed ZIP snapshots, line diffs, an append-only observation journal,
and optionally idempotent PostgreSQL events + source_snapshot/source_diff artifacts.

OBSERVATIONAL LIMITATIONS: Poll timestamps are observations, NOT exact edit times.
Intermediate quick changes and unsaved editor buffers may be missed. Task-specific
initial baseline is the state when this watcher starts, NOT necessarily the released
original if the watcher is started late. The workspace is participant writable, so
this is best-effort evidence, not tamper proof.

This program is for the trusted WSL/Docker host only. Never deploy it into the
participant's container or expose Docker/PostgreSQL credentials in that container.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import difflib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import UUID
import zipfile

import pilot1_collect_cli as collector

MAX_FILES = 200
MAX_SINGLE = 256 * 1024
MAX_TOTAL = 4 * 1024 * 1024
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
REL_RE = re.compile(r"^[a-zA-Z0-9._+@ /-]{1,256}$")

REMOTE_READER = r'''
import base64, json, os, pathlib, stat, sys
root = '/home/user/fuzz-study/work'
allowed = {'.c','.h','.cc','.cpp','.hpp','.py','.sh','.mk'}
fixed = {'Makefile','GNUmakefile','CMakeLists.txt'}
skip = {'runs','corpus','corpora','build','out','node_modules','.git','.cache',
        '.venv','venv','__pycache__','reference','tmp','temp','artifacts','logs'}
limit_files = 200
limit_one = 256 * 1024
limit_total = 4 * 1024 * 1024
files = {}
total = 0
dirs_visited = 0
if not os.path.isdir(root) or os.path.islink(root):
    sys.exit('Workspace root missing or linked')
for parent, dirs, names in os.walk(root, topdown=True, followlinks=False):
    depth = pathlib.Path(os.path.relpath(parent,root)).parts
    if len(depth) > 6:
        sys.exit('Workspace exceeds source scanning depth limit')
    dirs_visited += 1
    if dirs_visited > 800:
        sys.exit('Workspace exceeds directory traversal limit')
    dirs[:] = sorted(d for d in dirs if d not in skip and not d.startswith('.')
                     and not os.path.islink(os.path.join(parent,d)))
    for name in sorted(names):
        if name not in fixed and pathlib.Path(name).suffix.lower() not in allowed:
            continue
        path = os.path.join(parent, name)
        relative = os.path.relpath(path,root).replace(os.sep,'/')
        if os.path.islink(path):
            sys.exit('Source entry is symlink: ' + relative)
        pre = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(pre.st_mode):
            sys.exit('Source entry not regular file: ' + relative)
        if pre.st_size > limit_one:
            sys.exit('Source file exceeds 256 KiB limit: ' + relative)
        if len(files) >= limit_files or total + pre.st_size > limit_total:
            sys.exit('Source capture exceeds file count or 4 MiB limit')
        fd = os.open(path, os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_ino != pre.st_ino:
                sys.exit('File changed before capture: ' + relative)
            with os.fdopen(fd, 'rb', closefd=False) as f:
                data = f.read(limit_one + 1)
            post = os.fstat(fd)
        finally:
            os.close(fd)
        if (len(data)>limit_one or pre.st_size!=len(data) or
            pre.st_size != post.st_size or pre.st_mtime_ns != post.st_mtime_ns):
            sys.exit('File changed during capture: '+relative)
        total += len(data)
        files[relative] = base64.b64encode(data).decode('ascii')
print(json.dumps({'files':files, 'total_bytes':total}, separators=(',',':')))
'''


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f'Unsafe archive folder: {path}')
    os.chmod(path, 0o700)


def safe_regular(path: Path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(f'Unsafe archive file: {path}')


def capture(container: str) -> dict[str, bytes]:
    proc = subprocess.run(['docker', 'exec', '-u', 'user', container,
                           'python3', '-c', REMOTE_READER], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=False, timeout=40)
    if proc.returncode:
        raise RuntimeError('Source capture failed: '+proc.stderr.decode(errors='replace')[-450:])
    if len(proc.stdout) > 2 * MAX_TOTAL:
        raise RuntimeError('Source capture output unexpectedly large')
    result = json.loads(proc.stdout)
    enc = result.get('files')
    if not isinstance(enc, dict) or len(enc) > MAX_FILES:
        raise ValueError('Bad source manifest')
    files = {}
    total = 0
    for name, data in enc.items():
        if (not isinstance(name, str) or not REL_RE.fullmatch(name) or
            name.startswith('/') or name.startswith('.') or '..' in Path(name).parts or
            '\\' in name or not isinstance(data, str)):
            raise ValueError('Unsafe source file entry')
        content = base64.b64decode(data, validate=True)
        if len(content) > MAX_SINGLE:
            raise ValueError('Overlarge captured source file')
        files[name] = content
        total += len(content)
    if total > MAX_TOTAL or total != result.get('total_bytes'):
        raise ValueError('Source capture size mismatch')
    return files


def manifest(files):
    return {name: {'sha256': hashlib.sha256(data).hexdigest(), 'size':len(data)}
            for name, data in sorted(files.items())}


def tree_digest(files):
    serial = json.dumps(manifest(files), sort_keys=True, separators=(',',':'))
    return hashlib.sha256(serial.encode('utf-8')).hexdigest()


def encode_zip(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED,
                         allowZip64=False) as z:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (0o600 << 16)
            z.writestr(info, content)
    return stream.getvalue()


def decode_zip(data):
    files = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = info.filename
            if not REL_RE.fullmatch(name) or name.startswith(('/', '.')) or '..' in Path(name).parts:
                raise ValueError('Unsafe path in source snapshot')
            files[name] = z.read(info)
        if len(files) != len(z.infolist()):
            raise ValueError('Duplicate source snapshot entries')
    return files


def changes(before, after):
    a, b = manifest(before), manifest(after)
    found=[]
    for path in sorted(set(a)|set(b)):
        if a.get(path)==b.get(path):
            continue
        kind='modified' if path in a and path in b else ('added' if path in b else 'deleted')
        found.append({'path':path, 'kind':kind,
                      'before_sha256':a[path]['sha256'] if path in a else None,
                      'after_sha256':b[path]['sha256'] if path in b else None})
    return found


def diff_bytes(before, after, changed):
    parts=[]
    for item in changed:
        path = item['path']
        orig = before.get(path, b'')
        new = after.get(path, b'')
        if b'\x00' in orig or b'\x00' in new:
            parts.append(f'Binary source difference (see snapshots): {path}\n')
            continue
        try:
            a=orig.decode('utf-8').splitlines(keepends=True)
            b=new.decode('utf-8').splitlines(keepends=True)
        except UnicodeDecodeError:
            parts.append(f'Non-UTF8 source difference (see snapshots): {path}\n')
            continue
        diff=''.join(difflib.unified_diff(a,b, fromfile=f'a/{path}' if path in before else '/dev/null',
                                         tofile=f'b/{path}' if path in after else '/dev/null'))
        parts.append(diff if diff.endswith('\n') else diff+'\n')
    return ''.join(parts).encode('utf-8')


def save_immutable(path: Path, contents: bytes):
    ensure_dir(path.parent)
    safe_regular(path)
    digest=hashlib.sha256(contents).hexdigest()
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Existing archive differs from new snapshot: '+str(path))
        return {'sha256':digest,'size_bytes':len(contents)}
    tmp=path.parent / ('.'+path.name+'.'+str(os.getpid())+'.tmp')
    safe_regular(tmp)
    with tmp.open('xb') as f:
        os.chmod(tmp,0o600)
        f.write(contents)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return {'sha256':digest,'size_bytes':len(contents)}


def records_in(journal):
    safe_regular(journal)
    if not journal.exists():
        return []
    result=[]
    with journal.open('rb') as f:
        for n, raw in enumerate(f,1):
            if not raw.endswith(b'\n'):
                raise ValueError(f'Incomplete source journal line {n}; review required')
            entry=json.loads(raw)
            if (entry.get('seq')!=n or not re.fullmatch(r'[a-f0-9]{64}',entry.get('tree',''))):
                raise ValueError(f'Invalid source journal sequence {n}')
            result.append(entry)
    return result


def append_journal(journal,entry):
    line=(json.dumps(entry, sort_keys=True,ensure_ascii=True,separators=(',',':'))+'\n').encode()
    safe_regular(journal)
    fd=os.open(journal, os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        os.write(fd,line)
        os.fsync(fd)
    finally:
        os.close(fd)


def archive_snapshot(root, session, task, files):
    tree=tree_digest(files)
    relative=Path('sources') / session / task / 'snapshots' / (tree+'.zip')
    result=save_immutable(root/relative,encode_zip(files))
    return tree, {'storage_key':relative.as_posix(),**result}


def persist_observation(root, session, task, journal, previous_files, current_files, prior):
    now=utc()
    tree, snap=archive_snapshot(root,session,task,current_files)
    changed=changes(previous_files,current_files) if prior is not None else []
    seq=(prior['seq']+1) if prior else 1
    diff=None
    if changed:
        rel=Path('sources')/session/task/'diffs'/(f'{seq:06d}.patch')
        diff={'storage_key':rel.as_posix(),**save_immutable(root/rel,
                                                   diff_bytes(previous_files,current_files,changed))}
    entry={'seq':seq,'event_type':'source_baseline_captured' if prior is None else 'source_change_detected',
           'observed_at':now,'previous_tree':prior['tree'] if prior else None,
           'tree':tree,'changed':changed,'snapshot':snap,'diff':diff,
           'capture_method':'trusted_host_source_polling',
           'observation_previous_at':prior['observed_at'] if prior else None}
    append_journal(journal,entry)
    return entry


def db_sql(entry,session,task,instance):
    encoded=base64.b64encode(json.dumps(entry,ensure_ascii=True,separators=(',',':')).encode()).decode()
    return f"""BEGIN;
DO $guard$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM fuzz_pilot.study_sessions s
    JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
    WHERE s.session_id='{session}'::uuid AND t.task_run_id='{task}'::uuid
      AND s.instance_id='{instance}' AND s.status='active'
      AND t.status IN ('ready','active')
    FOR SHARE OF s,t
  ) THEN
    RAISE EXCEPTION 'Source observer task assignment is no longer valid';
  END IF;
END $guard$;
WITH j AS (SELECT convert_from(decode('{encoded}','base64'),'UTF8')::jsonb AS data)
INSERT INTO fuzz_pilot.events(session_id,task_run_id,event_type,event_source,occurred_at,event_key,payload)
SELECT '{session}'::uuid,'{task}'::uuid,data->>'event_type','manager',
       (data->>'observed_at')::timestamptz,CASE WHEN (SELECT position FROM fuzz_pilot.task_runs WHERE task_run_id='{task}'::uuid)=1
            THEN 'source:'||(data->>'seq')
            ELSE 'source:2:'||(data->>'seq') END,
       jsonb_build_object('capture_method',data->>'capture_method',
         'previous_tree_sha256',data->'previous_tree', 'tree_sha256',data->'tree',
         'changes',data->'changed', 'snapshot_storage_key',data->'snapshot'->>'storage_key',
         'diff_storage_key',data->'diff'->>'storage_key',
         'observed_at',data->'observed_at',
         'previous_observed_at',data->'observation_previous_at')
FROM j ON CONFLICT(session_id,event_key) DO NOTHING;
WITH j AS (SELECT convert_from(decode('{encoded}','base64'),'UTF8')::jsonb AS data)
INSERT INTO fuzz_pilot.artifacts(task_run_id,artifact_kind,storage_key,sha256,size_bytes)
SELECT '{task}'::uuid,'source_snapshot',data->'snapshot'->>'storage_key',
       data->'snapshot'->>'sha256',(data->'snapshot'->>'size_bytes')::bigint
FROM j ON CONFLICT(storage_key) DO NOTHING;
WITH j AS (SELECT convert_from(decode('{encoded}','base64'),'UTF8')::jsonb AS data)
INSERT INTO fuzz_pilot.artifacts(task_run_id,artifact_kind,storage_key,sha256,size_bytes)
SELECT '{task}'::uuid,'source_diff',data->'diff'->>'storage_key',
       data->'diff'->>'sha256',(data->'diff'->>'size_bytes')::bigint
FROM j WHERE data->'diff' IS NOT NULL AND data->'diff' <> 'null'::jsonb
ON CONFLICT(storage_key) DO NOTHING;
COMMIT;
"""


def upload_event(entry,session,task,instance):
    sql=db_sql(entry,session,task,instance).encode()
    p=subprocess.run(['docker','exec','-i','-u','postgres','devob-db-1','psql',
                      '-X','-v','ON_ERROR_STOP=1','-d','notebook','-f','-'],
                     input=sql, stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
    if p.returncode:
        raise RuntimeError('PostgreSQL source-event import failed: '
                           +p.stderr.decode(errors='replace')[-800:])


def prior_files(root,entry):
    path=root/entry['snapshot']['storage_key']
    safe_regular(path)
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=entry['snapshot']['sha256']:
        raise RuntimeError('Source snapshot checksum mismatch: '+str(path))
    files=decode_zip(data)
    if tree_digest(files)!=entry['tree']:
        raise RuntimeError('Source snapshot tree mismatch')
    return files


def describe(entry, action):
    if entry['event_type']=='source_baseline_captured':
        return f"{action}: baseline snapshot {entry['tree'][:12]} (no historical edit times inferred)"
    counts={k:sum(1 for x in entry['changed'] if x['kind']==k)
            for k in ('added','modified','deleted')}
    names=', '.join(x['path'] for x in entry['changed'][:8])
    return (f"{action}: {len(entry['changed'])} changed source file(s) "
            f"(added={counts['added']}, modified={counts['modified']}, "
            f"deleted={counts['deleted']}): {names}")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--container',required=True)
    p.add_argument('--session-id',required=True)
    p.add_argument('--task-run-id',required=True)
    p.add_argument('--archive-root',type=Path,default=Path.home()/'nerds-pilot-backups')
    p.add_argument('--interval',type=float,default=5.0)
    p.add_argument('--once',action='store_true',help='Poll once and exit')
    p.add_argument('--apply',action='store_true',help='Archive observations and link PostgreSQL records')
    args=p.parse_args()
    try:
        session,task=str(UUID(args.session_id)),str(UUID(args.task_run_id))
        if not collector.CONTAINER_RE.fullmatch(args.container):
            p.error('Invalid container name')
        if not 1 <= args.interval <= 300:
            p.error('Interval must be 1..300 seconds')
        os.umask(0o077)
        root=args.archive_root.expanduser()
        destination=root/'sources'/session/task
        if args.apply:
            ensure_dir(destination)
        instance=collector.check_assignment(args.container,session,task)
        lock_path=destination/'.source-watch.lock'
        if args.apply:
            safe_regular(lock_path)
            lock_path.touch(exist_ok=True)
            with lock_path.open('r+') as lock:
                os.chmod(lock_path,0o600)
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB)
                return watch(args,root,destination,session,task,instance)
        else:
            # Dry run makes no archive or DB changes. Read existing baseline when present.
            return watch(args,root,destination,session,task,instance)
    except KeyboardInterrupt:
        print('Source watcher stopped; archived data preserved.',flush=True)
        return 0
    except (RuntimeError,ValueError,OSError,json.JSONDecodeError,zipfile.BadZipFile) as exc:
        print('SOURCE WATCH STOPPED: '+str(exc),file=sys.stderr,flush=True)
        return 1


def watch(args,root,destination,session,task,instance):
    journal=destination/'source_observations.jsonl'
    records=records_in(journal)
    if records and not args.apply:
        print(f'Found {len(records)} previously archived observation(s).')
    if args.apply:
        # Replay after interrupted DB transactions; event keys and storage paths are stable.
        for entry in records:
            upload_event(entry,session,task,instance)
        print(f'Previously archived source observations synchronized: {len(records)}')
    prior=records[-1] if records else None
    previous_files=prior_files(root,prior) if prior else {}
    print('Source observer mode: '+('ARCHIVE + DB' if args.apply else 'DRY RUN'),flush=True)
    print('Observation baseline: '+('existing snapshot' if prior else 'current workspace on first capture'),flush=True)
    counter=0
    while True:
        # This guards against a task transition while observer runs.
        instance=collector.check_assignment(args.container,session,task)
        current=capture(args.container)
        tree=tree_digest(current)
        if not prior or tree!=prior['tree']:
            if not args.apply:
                if prior:
                    found=changes(previous_files,current)
                    print(f'DRY RUN: {len(found)} changed file(s): '
                          +', '.join(x['path'] for x in found[:12]),flush=True)
                else:
                    print(f'DRY RUN: would capture initial baseline ({len(current)} source files, '
                          f'{sum(map(len,current.values()))} bytes, tree {tree[:12]})',flush=True)
            else:
                entry=persist_observation(root,session,task,journal,previous_files,current,prior)
                # Archive journal before database write so failed DB imports can be retried.
                upload_event(entry,session,task,instance)
                print(f'[{utc()}] '+describe(entry,'RECORDED'),flush=True)
                prior=entry
                previous_files=current
        elif counter==0 and args.once:
            print(f'No source changes ({len(current)} files; tree {tree[:12]})',flush=True)
        counter+=1
        if args.once:
            break
        time.sleep(args.interval)
    return 0

if __name__=='__main__':
    sys.exit(main())
