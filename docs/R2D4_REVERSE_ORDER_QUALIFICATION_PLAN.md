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

**Immediate next action:** Phase 1 offline tests and Phase 2 **read-only** inventory. No participant/session creation or container changes yet.
