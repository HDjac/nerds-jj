#!/usr/bin/env python3
"""Release 2C local-test Submit canary switch with guarded rollback.

Only mutates nerds-pilot1-submit-r2b2-canary and reloads the PRIVATE Nginx gateway.
Never changes the participant, browser assets, PostgreSQL, or primary Submit.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

CANARY='nerds-pilot1-submit-r2b2-canary'
PRIVATE='nerds-pilot1-nginx-private'
PARTICIPANT='nerds-pilot1-browser-r1-test'
REQUIRED_NETWORKS={'devob_main','nerds-r2b2-canary-net'}
NEEDED_MOUNTS={'/run/nerds/registry','/run/secrets/pilot1_ai_gateway_token','/run/secrets/pilot1_ai_db_password'}
CHECKSUM='d176df9a9d1c2ee678f79cc6e18b52209cee6af54ceb73dc650f424d6ee9136a'
BASE=Path.home()/'nerds-pilot-backups'
STATE=BASE/'r2c-local-submit-state.json'

class Stop(RuntimeError): pass

def cmd(*args,ok=True):
    p=subprocess.run([str(x) for x in args],capture_output=True,text=True)
    if ok and p.returncode:
        raise Stop('Command failed ('+str(args[0])+' '+str(args[1] if len(args)>1 else '')+'):\n'+(p.stderr or p.stdout)[-1300:])
    return p

def d(*args,ok=True): return cmd('docker',*args,ok=ok)

def inspect(name):
    p=d('container','inspect',name,ok=False)
    return json.loads(p.stdout)[0] if p.returncode==0 else None

def env_map(entry):
    return dict(s.split('=',1) for s in entry['Config']['Env'] if '=' in s)

def save(data):
    BASE.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,indent=2)+'\n')
    os.chmod(tmp,0o600)
    os.replace(tmp,STATE)

def smoke():
    code='''import urllib.request, urllib.error, time, sys
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for n in range(24):
 try:
  req=urllib.request.Request('http://127.0.0.1:8000/pilot1/clipboard-event',data=b'{}',headers={'Content-Type':'application/json'},method='POST')
  try: opener.open(req,timeout=2); status=200
  except urllib.error.HTTPError as exc: status=exc.code
  if status==403: sys.exit(0)
 except Exception: pass
 time.sleep(.5)
sys.exit(1)'''
    p=d('exec',CANARY,'python3','-c',code,ok=False)
    if p.returncode: raise Stop('New canary HTTP/authentication smoke test failed (no research data submitted)')
    print('PASS: New canary HTTP running; invalid gateway credential rejected (403)')

def gateways():
    names=[PRIVATE]
    optional='nerds-pilot1-nginx-r2b2-canary'
    o=inspect(optional)
    if o and o['State']['Running']: names.append(optional)
    return names

def gateway_reload():
    for n in gateways():
        d('exec',n,'nginx','-t')
        d('exec',n,'nginx','-s','reload')
        print('PASS: Reloaded',n,'after Submit address change')

def preflight():
    if STATE.exists(): raise Stop('Existing activation state at '+str(STATE)+'; inspect status/rollback first')
    s=inspect(CANARY)
    if not s or not s['State']['Running']: raise Stop('Existing canary not running')
    e=env_map(s)
    if (e.get('PILOT1_CLIPBOARD_TEXT_ENABLED')!='0' or
        e.get('PILOT1_CLIPBOARD_INGEST_ENABLED')!='1'):
        raise Stop('Expected existing metadata-only canary flags (1/0)')
    if s['Config'].get('Cmd')!=['python3','/home/user/app/main.py'] or s['Config'].get('User')!='user':
        raise Stop('Unexpected canary startup command or user; do not clone blindly')
    if s['HostConfig']['RestartPolicy'].get('Name')!='no':
        raise Stop('Unexpected canary restart policy')
    if s['HostConfig'].get('PortBindings'):
        raise Stop('Canary has published ports; unsupported by guarded clone')
    net=s['NetworkSettings']['Networks']
    if set(net)!=REQUIRED_NETWORKS or 'submit' not in (net['nerds-r2b2-canary-net'].get('Aliases') or []):
        raise Stop('Unexpected network or alias; preserve routing before proceeding')
    mounts=s['Mounts']
    if {m['Destination'] for m in mounts}!=NEEDED_MOUNTS or any(m['Type']!='bind' or m['RW'] for m in mounts):
        raise Stop('Unexpected canary mounts; requires exactly three read-only binds')
    # Docker bind sources belong to the Docker daemon's filesystem.  WSL's
    # Python process may not see Docker Desktop's mount paths even while
    # Docker can remount them.  Verify through the same daemon rather than
    # using Path(source).exists() in the client namespace.  --mount refuses
    # a missing source (unlike -v, which can create a directory accidentally).
    for m in mounts:
        src=m.get('Source')
        if not isinstance(src,str) or not src.startswith('/'):
            raise Stop('Invalid bind source for '+m['Destination'])
        probe=d('run','--rm','--network','none',
                '--mount','type=bind,source='+src+',target=/r2c-bind-check,readonly',
                '--entrypoint','sh','nginx:alpine','-c',
                'test -e /r2c-bind-check',ok=False)
        if probe.returncode:
            raise Stop('Docker daemon cannot remount source for '+m['Destination']+
                       '; original canary unchanged. '+(probe.stderr or probe.stdout)[-650:])
        print('PASS: Docker daemon can remount',m['Destination'],'read-only')
    if not inspect(PRIVATE)['State']['Running']: raise Stop('Private gateway not running')
    if not inspect(PARTICIPANT)['State']['Running']: raise Stop('Local participant not running')
    run=d('exec',PARTICIPANT,'cat','/home/user/services/api/run').stdout
    if 'PILOT1_CLIPBOARD_TEXT_ENABLED=0' not in run:raise Stop('Participant text flag was changed; stop')
    sha=d('exec',CANARY,'sha256sum','/home/user/app/pilot1_clipboard_payload.py').stdout.split()[0]
    if sha!=CHECKSUM:raise Stop('Canary validator differs from verified R2B.3 hotfix')
    if d('exec',PRIVATE,'sh','-c','grep -Fq "nerds-pilot1-submit-r2b2-canary:8000" /etc/nginx/nginx.conf',ok=False).returncode:
        raise Stop('Private Nginx route to canary is not the expected one')
    for n in gateways(): d('exec',n,'nginx','-t')
    print('PASS: Canary hotfix checksum, all mounts, networks, alias, gateway route and flags')
    print('PASS: Participant remains text-disabled; no resources changed')
    return s

def status():
    if STATE.exists():
        v=json.loads(STATE.read_text())
        print('Switch state:',v['phase'],'Backup:',v['backup_name'])
    else:print('No managed Release 2C Submit switch state')
    for n in [CANARY,PRIVATE,PARTICIPANT]:
        s=inspect(n)
        print(n, ('running' if s['State']['Running'] else 'stopped') if s else 'MISSING')
        if s and n==CANARY:
            x=env_map(s)
            print('Clipboard flags: ingest=',x.get('PILOT1_CLIPBOARD_INGEST_ENABLED'), 'text=',x.get('PILOT1_CLIPBOARD_TEXT_ENABLED'))

def rollback():
    if not STATE.exists():raise Stop('No activation state; not changing anything')
    st=json.loads(STATE.read_text())
    if st['canary']!=CANARY:raise Stop('Unexpected rollback state')
    backup=st['backup_name']
    old=inspect(backup)
    if not old:raise Stop('Backup canary missing; do not remove anything')
    new=inspect(CANARY)
    if new:
        # A different user-supplied replacement should never be deleted.
        if st.get('new_container_id') and new['Id']!=st['new_container_id']:
            raise Stop('New canary identity differs from activation state')
        d('stop','-t','15',CANARY,ok=False)
        d('rm',CANARY)
    d('rename',backup,CANARY)
    if not inspect(CANARY)['State']['Running']:d('start',CANARY)
    gateway_reload()
    e=env_map(inspect(CANARY))
    if e.get('PILOT1_CLIPBOARD_TEXT_ENABLED')!='0':raise Stop('Rollback flag unexpected')
    done=BASE/('r2c-local-submit-rolled-back-'+st['stamp']+'.json')
    STATE.rename(done)
    print('PASS: Original patched canary restored, text flag OFF')
    print('NOTE: Prepared image retained:',st['image'])

def apply():
    original=preflight()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=CANARY+'-pre-r2c-'+stamp
    image='nerds-pilot1-submit:r2c-local-preserved-'+stamp.lower()
    if inspect(backup):raise Stop('Backup container name already exists')
    print('===== SNAPSHOT CURRENT RUNNING CANARY (INCLUDING RUNTIME HOTFIX) =====')
    d('commit','--pause=true',CANARY,image)
    print('PASS: Preserved canary filesystem as image:',image)
    state={'canary':CANARY,'backup_name':backup,'image':image,'stamp':stamp,
           'phase':'snapshot_complete','new_container_id':None}
    save(state)
    try:
        d('stop','-t','20',CANARY)
        d('rename',CANARY,backup)
        state['phase']='old_canary_renamed';save(state)
        env=env_map(original)
        env['PILOT1_CLIPBOARD_TEXT_ENABLED']='1'
        args=['create','--name',CANARY,'--restart','no','--network','nerds-r2b2-canary-net',
              '--network-alias','submit','--user','user']
        if original['Config'].get('WorkingDir'):
            args+=['--workdir',original['Config']['WorkingDir']]
        for k,v in sorted(env.items()):args+=['--env',k+'='+v]
        for m in original['Mounts']:
            args+=['--volume',m['Source']+':'+m['Destination']+':ro']
        args += [image, 'python3','/home/user/app/main.py']
        created=d(*args).stdout.strip()
        state['new_container_id']=created;state['phase']='new_canary_created';save(state)
        d('network','connect','devob_main',CANARY)
        d('start',CANARY)
        state['phase']='new_canary_running';save(state)
        smoke()
        gateway_reload()
        check=inspect(CANARY)
        if (set(check['NetworkSettings']['Networks'])!=REQUIRED_NETWORKS or
                'submit' not in (check['NetworkSettings']['Networks']['nerds-r2b2-canary-net'].get('Aliases') or [])):
            raise Stop('Replacement routing networks or aliases mismatch')
        sha=d('exec',CANARY,'sha256sum','/home/user/app/pilot1_clipboard_payload.py').stdout.split()[0]
        if sha!=CHECKSUM:raise Stop('Replacement lost the host-paste validator patch')
        e=env_map(check)
        if e.get('PILOT1_CLIPBOARD_TEXT_ENABLED')!='1':raise Stop('Replacement text flag not enabled')
        state['phase']='active';save(state)
        print('PASS: Text-enabled Submit canary active with original name and aliases')
        print('PASS: Old canary retained stopped as',backup)
        print('PASS: Live participant/frontend unchanged (text capture remains OFF)')
        print('ROLLBACK: python3 nerds_r2c_submit_canary.py rollback')
    except BaseException:
        print('ERROR: Submit switch incomplete; attempting original-canary rollback',file=sys.stderr)
        try: rollback()
        except Exception as exc:print('ROLLBACK NEEDS MANUAL REVIEW:',exc,file=sys.stderr)
        raise

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['preflight','apply','status','rollback'])
    args=ap.parse_args()
    try:
        {'preflight':preflight,'apply':apply,'status':status,'rollback':rollback}[args.action]()
    except Stop as exc:
        print('STOP:',exc,file=sys.stderr)
        sys.exit(1)

if __name__=='__main__': main()
