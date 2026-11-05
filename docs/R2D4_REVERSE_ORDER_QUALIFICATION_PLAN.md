# NERDs Pilot 1 — Reverse-Order Qualification Plan

Prepared: 2026-11-04  
Branch: test/r2d4-reverse-order-qualification  
Base: RC2 source plus merged release documentation (0217080ef4738e44e508a95f6c9fbbefd3cd3028)

## Goal and safety scope

Qualify the full **Low-Yield v1 (position 1) → Dense v2 (position 2) → Study Complete** path using a fresh, isolated test session, separate from the completed RC2 and the two existing active participants. The previously blocked session stays blocked.

The frozen acceptance tag r2d4-rc2-pilot1-accepted and pinned Docker image ID sha256:825246d5460d56c0df37444bf113e7c9a03e8867d724b86401a8c24a098a5abf remain unchanged.

**No participant, Docker container, registry service or study database has been changed during preparation of this branch.** The branch only adds a narrowly named trust entry, separate qualification-only enrollment script, mock tests and this plan.

LLM response collection remains deferred. Existing prompt capture and clipboard privacy settings remain unchanged.

## Test-only changes

1. The image trust allowlist now admits a second **designated name only**, nerds-pilot1-r2d4-reverse-qualification, when its configured image tag and immutable ID exactly match the accepted RC2 image. Unknown names and image IDs remain rejected.
2. Normal random enrollment in scripts/pilot1_enroll.py is **unchanged**.
3. New trusted-host script scripts/pilot1_enroll_reverse_qualification.py explicitly forces lowyield_first and requires **both** --create and --confirm-nonrandom-qualification to write a test participant. Its preview is read-only.
4. A successful special enrollment writes a private mode-0600 JSON marker at ~/nerds-pilot-runtime/qualification-sessions/<session UUID>.json. This flags the session as **nonrandom test data excluded from research analysis**. Never share or commit the marker or generated identifiers.
5. If DB commit/response or marker publication fails, the operator must STOP and reconcile without replaying enrollment. There is no automatic retry.

## Phase 1 — isolated checkout and offline tests (safe now)

Run from WSL; this creates only a second host Git worktree and executes local mock tests:

    cd ~/nerds-r2d
    git fetch origin test/r2d4-reverse-order-qualification
    git worktree add ~/nerds-r2d-reverse -b test/r2d4-reverse-order-local origin/test/r2d4-reverse-order-qualification
    cd ~/nerds-r2d-reverse
    git status --short
    git diff --check
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" python3 -m unittest discover -s tests -p 'test_r2d4_reverse_qualification.py' -v
    python3 scripts/pilot1_enroll_reverse_qualification.py

Expected: **11 offline tests pass**; enrollment preview says lowyield_first and makes no DB/credential changes. If the worktree/branch exists already, STOP and inspect rather than force-reset.

## Phase 2 — read-only Docker/service inventory (safe now)

Use the following summary-only command; it intentionally excludes sensitive environment, tokens, participant data and mount paths:

    cd ~/nerds-r2d-reverse
    python3 - <<'PY'
    import json, subprocess
    names = ["nerds-pilot1-r2d4-rc2-acceptance",
             "nerds-pilot1-crash-r2d4",
             "nerds-pilot1-browser-r1-test"]
    objs = json.loads(subprocess.check_output(["docker", "inspect", *names]))
    for obj in objs:
        c, host = obj["Config"], obj["HostConfig"]
        print("NAME:", obj["Name"].lstrip("/"))
        print("  IMAGE:", c.get("Image"), obj.get("Image"))
        print("  USER:", c.get("User"))
        print("  LABEL:", (c.get("Labels") or {}).get("nerds.study"))
        print("  NETWORKS:", sorted(obj["NetworkSettings"]["Networks"]))
        print("  PRIVILEGED:", host.get("Privileged"))
        print("  NETWORK_MODE:", host.get("NetworkMode"))
        print("  RESTART_POLICY:", (host.get("RestartPolicy") or {}).get("Name"))
        print("  MOUNT_COUNT:", len(obj.get("Mounts") or []))
        print("  PORT_BINDINGS_PRESENT:", bool(host.get("PortBindings")))
        print("  MEMORY:", host.get("Memory"))
        print("  PIDS_LIMIT:", host.get("PidsLimit"))
    PY

    if docker container inspect nerds-pilot1-r2d4-reverse-qualification >/dev/null 2>&1; then
      echo "STOP: Reverse-qualification container name already exists"
    else
      echo "PASS: Proposed container name is unused"
    fi

    systemctl --user is-active nerds-p1-registry-r2d4.service
    python3 scripts/pilot1_multi_supervisor.py

**Do not paste raw Docker inspect JSON, Config.Env, tokens, participant URLs or personal data.**

The registry publisher may still be running code from the **frozen checkout** and therefore may not admit the new name until a safe, scoped deployment is approved. **Do not restart the active registry service while the two other participants remain active.**

Before creating anything, confirm that the new container will use the same immutable image ID, unprivileged user, study label, approved network, appropriate runtime restrictions and internal routing, without conflicting ports/resources. Do not blindly clone a running participant container or start a broad supervisor --apply.

## Phase 2 observation record (operator output, 2026-11-04)

Read-only Docker/service inventory completed for all three existing containers:

| Container | Image ID | User/label/network | Privileged | Mounts | Ports | Memory | Restart |
| --- | --- | --- | --- | ---: | --- | --- | --- |
| RC2 completed acceptance | `sha256:825246d5460d56c0df37444bf113e7c9a03e8867d724b86401a8c24a098a5abf` | `user` / `pilot1` / `devob_instances` | false | 0 | none | unlimited | no |
| Active crash R2D4 legacy | `sha256:787f850c610ec095eaf3b7e62172ada9ffb6d0b2f2ff1dee590434b5a7ed0033` | same | false | 0 | none | unlimited | no |
| Active browser R1 legacy | `sha256:d39c6a42b3692246a0ffc086f04ea2f83d261d67cf820fcf96a7e34d78f66581` | same | false | 0 | none | 1 GiB | no |

New test name `nerds-pilot1-r2d4-reverse-qualification` **available**. Registry service **active**. Supervisor preview remains two separate active sessions with exactly **2 collectors each**; unrelated manually blocked session remains blocked. Completed RC2 did not reappear among active sessions.

**Readiness finding:** container identity/network configuration is consistent with the accepted Pilot 1 topology and new name is unused. This is **not** authorization to create the new container. No test-specific Docker memory/PID limits have been chosen, and registration from the live registry service remains unverified. The 11 new offline tests were **not included in the supplied Phase 2 output**; request their full PASS/fail summary separately.

### Next read-only registry provenance check

Use a sanitized active-unit inspection that **does not print ExecStart arguments, environment variables or credentials**:

```bash
cd ~/nerds-r2d-reverse
python3 - <<'PY'
import subprocess
service = 'nerds-p1-registry-r2d4.service'
props = ('ActiveState','SubState','MainPID','FragmentPath','WorkingDirectory','ExecStart')
cmd = ['systemctl','--user','show',service] + [f'--property={p}' for p in props]
r = subprocess.run(cmd,capture_output=True,text=True,check=True)
values = dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
for name in ('ActiveState','SubState'):
    print(name+':', values.get(name,'unknown'))
print('MAINPID_PRESENT:', values.get('MainPID','0') not in ('','0'))
raw = '\\n'.join((values.get('ExecStart',''),values.get('WorkingDirectory','')))
for label, path in [('RC2_SOURCE','/nerds-r2d/'),('REVERSE_WORKTREE','/nerds-r2d-reverse/')]:
    print(label+'_REFERENCED:', path in raw)
print('REGISTRY_SCRIPT_MENTIONED:', 'pilot1_instance_registry.py' in raw)
print('SERVICE_ARGUMENTS_AND_ENV: intentionally suppressed')
PY
```

If source ownership is unknown, **stop** before creating a new participant. Never restart the live registry merely to load this feature branch.

## Phase 2 additional results: offline tests and registry provenance (operator, 2026-11-04)

- **PASS:** all **11/11** isolated `test_r2d4_reverse_qualification.py` assertions, no errors/failures; no live Docker or PostgreSQL touched by those mocked tests.
- **PASS:** `pilot1_enroll_reverse_qualification.py` preview explicitly displayed `lowyield_first` (position 1 Low-Yield v1, position 2 Dense v2), with no database/filesystem changes.
- **Registry unit:** `nerds-p1-registry-r2d4.service` reported `ActiveState=active`, `SubState=running`, `MainPID` present. Its sanitized ExecStart/WorkingDirectory string **references `/nerds-r2d/`** (frozen RC2 checkout), **does not reference `/nerds-r2d-reverse/`**, and did **not directly mention `pilot1_instance_registry.py`**. The actual executed entrypoint and loaded trust module are therefore **not yet proven** by these checks. The branch's new allowlist should **not** be assumed to be in effect in the live registry.
- **New:** An extra **offline registry-discovery test module** `tests/test_r2d4_reverse_registry.py` was added (8 test methods) to test synthetic DB/container bindings, exact image and name trust, existing legacy compatibility, network/label/user checks, duplicate IP rejection, and ignored unknown names. **These eight tests are not yet operator-executed.**

**Hold live enrollment and provisioning** until source process and registry publication path are known, offline registry checks pass, and a no-interference strategy is reviewed. Do not restart the registry or rewrite its registry artifact with live participants active.

### Additional read-only active-registry provenance inspection

Run from WSL; the script reports only process executable/file basenames and checkout-origin booleans, **not service arguments, environment variables, credentials or raw process command lines**:

```bash
cd ~/nerds-r2d-reverse
python3 - <<'PY'
from pathlib import Path
import os, subprocess
service = 'nerds-p1-registry-r2d4.service'
props = ('MainPID','FragmentPath','WorkingDirectory','ExecStart')
cmd = ['systemctl','--user','show',service] + [f'--property={key}' for key in props]
raw = subprocess.check_output(cmd, text=True)
data = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
pid = data.get('MainPID', '0')
print('MAINPID_PRESENT:', pid.isdecimal() and int(pid)>0)
print('UNIT_PATH_EXISTS:', Path(data.get('FragmentPath','/nonexistent')).is_file())
if pid.isdecimal() and int(pid)>0:
    proc = Path('/proc')/pid
    args = (proc/'cmdline').read_bytes().decode('utf-8','replace').split(chr(0))
    print('PROCESS_EXE_BASENAME:', Path(os.readlink(proc/'exe')).name)
    print('PROCESS_CWD_RC2:', '/nerds-r2d' in os.readlink(proc/'cwd'))
    print('PROCESS_CWD_REVERSE:', '/nerds-r2d-reverse' in os.readlink(proc/'cwd'))
    print('PROCESS_CMDLINE_RC2:', any('/nerds-r2d/' in a for a in args))
    print('PROCESS_CMDLINE_REVERSE:', any('/nerds-r2d-reverse/' in a for a in args))
    print('PROCESS_SCRIPT_BASENAMES:', sorted(set(Path(a).name for a in args if a.endswith(('.py','.sh')))))
unit = Path(data.get('FragmentPath','/nonexistent'))
if unit.is_file():
    txt = unit.read_text(errors='replace')
    print('UNIT_REGISTRY_IMPORT_MENTIONED:', 'pilot1_instance_registry' in txt)
    print('UNIT_SCRIPT_BASENAMES:', sorted(set(Path(word).name for word in txt.split() if word.endswith(('.py','.sh')))))
print('RAW_ARGUMENTS_AND_ENVIRONMENT: suppressed')
PY

# Only matching filename paths are displayed, not potentially sensitive source lines.
git grep -l -E 'nerds-p1-registry-r2d4|pilot1_instance_registry|registry/pilot' HEAD -- scripts containers || true
```

If the process is a shell wrapper or the actual registry importer is unclear, inspect only the matching non-secret **source files** and unit launcher's basename next. Keep the existing registry process and current two active participants untouched.

## Phase 3 — live study qualification (NOT YET AUTHORIZED)

Only after the above outputs and registry-isolation strategy have been reviewed:

1. Enroll **one** nonrandom Low-Yield-first test participant using the qualification-only create flags; store IDs and private marker locally. Never use this for real randomized study enrollment.
2. Provision a **new** dedicated approved container with isolated identity and bind it to the new session. Read-only preview first; authorized apply once.
3. Confirm first released task is lowyield_v1, second task dense_v2 locked, and internal browser/CLI, task guide and collector ownership are correct.
4. Exercise CLI commands, LibFuzzer campaigns, sources, AI prompt and clipboard metadata inside the participant workspace; check DB/journal/archive attribution.
5. Participant finishes Low-Yield → guarded transition/archives → Dense release; verify Task 1 evidence is not copied into Task 2 DB and collectors swap correctly.
6. Participant finishes Dense → final archives, DB states, completion receipt, visible Study Complete and collector cleanup.
7. Verify unrelated participants unchanged and blocked session remains blocked. Save sanitized acceptance results and exclude qualification marker from research analysis.

**Success:** correct reversed tasks, identical pinned accepted image, exactly-once completion, clean task boundaries, preserved evidence, participant-visible receipt, zero cross-session interference and no LLM response capture.

**Immediate next action:** Execute the additional eight offline registry tests; perform sanitized active-process provenance inspection above. No participant/session creation, registry restart or container changes yet.
