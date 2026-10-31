#!/usr/bin/env python3
"""Render a systemd unit for installation by the operator; does not enable it."""
import argparse
import getpass
from pathlib import Path
import shlex


def render(repo, user):
    if not (repo/'scripts/pilot1_multi_supervisor.py').is_file():
        raise RuntimeError('Supervisor not yet installed in the repository')
    if not user or not all(c.isalnum() or c in ('_', '-') for c in user):
        raise ValueError('Invalid service account name')
    script=repo/'scripts/pilot1_multi_supervisor.py'
    # systemd ExecStart: no shell interpolation, paths must not include whitespace.
    if any(c.isspace() for c in str(script)):
        raise ValueError('Repository path cannot contain spaces')
    return f'''[Unit]
Description=NERDs Pilot task and collector supervisor
Wants=network-online.target
After=network-online.target docker.service
Requires=docker.service

[Service]
Type=simple
User={user}
WorkingDirectory={repo}
ExecStart=/usr/bin/python3 -u {script} --watch --apply --interval 5
Restart=on-failure
RestartSec=15
KillMode=control-group
TimeoutStopSec=20
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
'''

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,required=True)
    p.add_argument('--user',default=getpass.getuser())
    p.add_argument('--output',type=Path,default=Path('nerds-pilot-supervisor.service'))
    args=p.parse_args()
    target=args.output.resolve()
    if target.exists():raise SystemExit('STOP: output already exists: '+str(target))
    target.write_text(render(args.repo.expanduser().resolve(),args.user))
    print('Wrote unit (NOT installed or started):',target)
