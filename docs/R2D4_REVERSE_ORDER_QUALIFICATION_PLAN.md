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

## Phase 2 registry dependency confirmed from process and source (2026-11-04)

Operator's sanitized live `/proc/<MainPID>` inspection reported `python3.10`, process script basename **`pilot1_refresh_registry.py`**, RC2 checkout path present in process arguments, reverse checkout absent. The runtime CWD is neither checkout; CWD alone does not determine module provenance.

The accepted source import chain was independently verified:
`pilot1_refresh_registry.py` → `pilot1_publish_registry.publish` → `pilot1_instance_registry.discover` → `pilot1_image_trust.image_is_approved`.

The refresh script calls `publish` in a repeated loop (default 10-second interval, 30-second TTL). The publisher writes the default private registry file under `~/nerds-pilot-runtime/registry/participants.json` using atomic replacement. **Actual service command-line overrides, output path and loaded module path were not exposed or independently read**; those are still useful no-secret preflight checks.

**Impact:** the already running process imports modules from its launch checkout; **the additional reverse container allowlist entry on the separate GitHub branch is NOT active merely because the branch exists**. Do not create a new test participant/container relying on this active publisher to admit it until its module provenance and output destination are confirmed.

**No-interference gate:** Never start a second publisher writing to the live registry output. Do not replace, restart or modify the running publisher while existing participants are active unless a specific reviewed no-interference cutover is demonstrated. A separate private output and gateway can be explored but is not implemented or qualified yet. The 8 offline registry tests in `tests/test_r2d4_reverse_registry.py` passed; the live deployment gate remains open.

### Safe test and publication-target audit

```bash
cd ~/nerds-r2d-reverse

git status --short
git pull --ff-only origin test/r2d4-reverse-order-qualification

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest discover -s tests -p 'test_r2d4_reverse_registry.py' -v

python3 - <<'PY'
from pathlib import Path
import os, subprocess
service='nerds-p1-registry-r2d4.service'
raw=subprocess.check_output(['systemctl','--user','show',service,
                              '--property=MainPID,FragmentPath'],text=True)
props=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
pid=props.get('MainPID','0')
if not pid.isdecimal() or int(pid)<1:
    raise SystemExit('STOP: service MainPID invalid')
args=[a.decode('utf-8','replace') for a in (Path('/proc')/pid/'cmdline').read_bytes().split(bytes([0])) if a]
def opt(name):
    exact = [i for i,a in enumerate(args) if a == name]
    attached = [a.split('=',1)[1] for a in args if a.startswith(name+'=')]
    if len(exact)+len(attached)>1:
        raise SystemExit('STOP: duplicate output options')
    if exact:
        i=exact[0]
        return args[i+1] if i+1<len(args) else ''
    return attached[0] if attached else None
output=opt('--output')
source=next((a for a in args if a.endswith('pilot1_refresh_registry.py')), '')
print('REFRESH_ENTRYPOINT_RC2:', '/nerds-r2d/' in source and '/nerds-r2d-reverse/' not in source)
print('OUTPUT_OPTION_PRESENT:', output is not None)
print('OUTPUT_EQUALS_DEFAULT:', output is None or os.path.expanduser(output)==str(Path.home()/'nerds-pilot-runtime/registry/participants.json'))
print('OUTPUT_PATH_AND_ARGUMENTS: suppressed')
print('PROCESS_ALIVE:', (Path('/proc')/pid).is_dir())
PY
```

This audit prints only booleans, not raw service arguments or registry contents. It is not a deployment instruction.

## Phase 2 output-target confirmation (2026-11-04)

Operator's sanitized live-process audit: `OUTPUT_OVERRIDE_PRESENT=True`, `OUTPUT_IS_DEFAULT=True`, `OUTPUT_CONFIGURATION_UNAMBIGUOUS=True`. Thus the active refresher explicitly uses the expected shared registry output with no contradictory output options.

**Architecture:** `pilot1_refresh_registry.py` imports `pilot1_publish_registry.publish` → `pilot1_instance_registry.discover` → `pilot1_image_trust.image_is_approved`; the publisher atomically replaces its registry file. Docker Compose binds the shared registry directory **read-only into the submit service**. A new output file alone is **not** a working independent authorization path; an independent registry needs its own isolated consumer, gateway identity and routing. Multiple writers to the same registry path would race and threaten existing participant access.

**Decision:** Keep the active publisher unchanged. Either plan a controlled single-writer policy update after the two live participant sessions finish, or qualify a fully isolated gateway and registry consumer. No new test session, container, registry replacement/restart, or competing publisher until this is settled. The **eight new offline registry tests passed (8/8)**; the previous 11 qualification unit tests passed.

## Phase 2 qualification regression result (operator, 2026-11-04)

**PASS: 8/8 offline registry-discovery tests**, with zero failures or errors (0.003 seconds). The passing cases specifically cover rejecting duplicate IP addresses, preserving both existing legacy image allowlist entries, ignoring mismatched DB/container binding, recognizing the specially named reverse-qualification container, retaining original RC2 approval, denying unexpected privilege/user/label, rejecting substituted tags/digests, and failing closed on unapproved RC2 names.

Previously **11/11 reverse-order enrollment and image-trust mock tests** also passed. Combined **19/19 new qualification tests** have passed. These were offline/mock tests, **not** confirmation that the active registry has loaded the test-branch allowlist or that a participant has been provisioned.

**Operational gate is still OPEN:** Active `pilot1_refresh_registry.py` from frozen checkout is the only known writer to the shared authorization registry; two active sessions depend on it. Neither restart the service nor start a second writer to the same file. The live acceptance test should wait for a reviewed single-writer cutover after active sessions finish, or a fully isolated gateway/registry consumer. No DB enrollment, Docker container creation, invitation or lifecycle apply has been authorized.

## Operator decision: retire old Pilot 1 test sessions (2026-11-04)

The operator clarified that the two active sessions shown by the supervisor are **old, disposable test participants** and may be stopped. This removes the requirement to wait for them to finish their workflows; it **does not** permit broad container shutdown, skipping archive preservation, or removing the unrelated manual-review-blocked session.

**Planned controlled approach (not yet executed):**

1. On the **frozen** host checkout, obtain a DB-authoritative read-only map for only `nerds-pilot1-crash-r2d4` and `nerds-pilot1-browser-r1-test`. Verify two unique active sessions, matching immutable legacy images, 2 task-scoped collectors per session, correct systemd/MainPID ownership or identified legacy PIDs, no pending Finish/Skip request, no transition inflight, and no supervisor watch/apply process.
2. Preserve the original archived data and record existing collector/session state privately. If there is unflushed telemetry, safely stop exact collector units/processes and perform one-shot final ingest/source reconciliation **before changing DB active status**, using their previously validated task-run bindings. Never delete a workspace just to mark the session stopped.
3. Mark only the two known test session DB rows `aborted` with end timestamps using a fail-closed scoped transaction **after** collector reconciliation. Preserve task-run records/evidence; do **not** issue fake Finish/Skip or completion receipts.
4. Stop only those two old test containers; keep completed RC2 and manually blocked session untouched. Confirm no old collectors or active sessions remain; check shared registry regeneration.
5. Only once the authorization registry has no active dependent participants, perform a reviewed **single-writer** cutover from frozen registry refresh code to the qualification branch's exact image-trust allowlist. Do not create simultaneous publishers or silently replace production files.
6. Verify registry still rejects arbitrary names and non-pinned image IDs, then create one new controlled `lowyield_first` qualification session. Keep the participant test marker private and exclude it from study analysis.

**Operator authorization:** the two legacy test sessions can be retired. **Execution is pending exact collector identity/preflight and a guarded stop plan.** Do not run `docker compose down`, kill all Python processes, restart all user systemd units, or modify the blocked session.

## Retirement preflight — passed (operator output, 2026-11-04)

The operator's guarded host-side preflight selected **exactly the two authorized legacy test containers**: `nerds-pilot1-browser-r1-test` and `nerds-pilot1-crash-r2d4`. For each, the PostgreSQL active session-to-container assignment and immutable image approval passed; released task exists; no `transition-inflight` or `needs-review` marker and no pending Finish/Skip request. Each container has exactly one `pilot1_auto_ingest.py` and one `pilot1_track_sources.py` collector whose task binding matches the released task. All four collector units are **systemd-user** owned, with matching MainPID and `Restart=no`; **zero** global `pilot1_multi_supervisor.py --watch --apply` processes were found.

**Gate result:** targeted evidence-preserving retirement can proceed using exact identities, but retirement has **NOT been executed**. Revalidate identities and unit ownership immediately before mutating. Stop exactly four scoped collector units using `pilot1_lifecycle.stop_collectors(task_id, 'systemd-user')` for each participant and perform final `pilot1_lifecycle.flush(task_id)` while the session/DB task remain active, then `archive_workspace` before changing the session's status. Validate no ongoing fuzzer/compiler process first. Preserve private logs; any partial stop or failed drain is **manual review**, not automatic replay. Mark the two sessions `aborted` only in a later guarded transaction once collection/archival verified, then `docker stop` only those two named containers (do not remove).

The completed RC2 acceptance container and manually blocked session must remain unchanged. Existing registry writer stays running until a controlled single-writer cutover following successful retirement.

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

**Immediate next action:** Plan a no-interference registry cutover after active sessions complete, or an entirely isolated gateway/registry consumer. All 19 new offline qualification tests passed. No participant/session creation, registry restart or container changes yet.
