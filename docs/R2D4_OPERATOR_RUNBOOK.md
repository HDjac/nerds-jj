# NERDs Pilot 1 — Release 2D.4 Operator Runbook (RC2)

**Date:** 2026-11-04  
**Audience:** trusted study operator using the local WSL Docker host  
**Scope:** controlled preview, participant enrollment and assignment, task collection, task handoff, completion, auditing and manual-recovery policy for **Pilot 1 only**. This is **not** a production NSF ACCESS procedure.

> **Current RC2 state:** Normal-path acceptance session is **already completed**, archived and receipt-verified. Its collectors are **stopped**. **Do not rerun an apply command for this completed session.** Two unrelated sessions remained active with two collectors each; a separate older session was intentionally blocked for manual review. Do not restart, unblock, modify or reassign any of these during release verification.

## 1. Rules of engagement

- All administration runs **in WSL** on the trusted host, under the configured operator account and repo `~/nerds-r2d`. Participant CLI commands should be typed **inside the participant's NERDs CLI**, not host-side `docker exec`, when acceptance evidence is required.
- No external host clipboard into the NERDs environment; internal Firefox ↔ CLI copy/paste is allowed. Keep telemetry restricted to approved, disclosed fields. Accepted RC2 sets `PILOT1_CLIPBOARD_INGEST_ENABLED=1`, `PILOT1_CLIPBOARD_TEXT_ENABLED=0` and `PILOT1_SPLIT_WORKSPACE_ENABLED=1`.
- **Do not publish** invitations, token fragments, raw prompts, browser history, terminal transcripts, source snapshots, source diffs, participant/session identifiers, registry contents, DB dumps, receipt bearers or secrets to GitHub/ChatGPT/logging channels. Use summarized PASS/FAIL counts instead.
- Do not modify a live participant's filesystem or DB from diagnostics. Use read-only first. All lifecycle actions are **one-time and session-scoped**, never a broad repair script.
- A failed or interrupted transition is **manual review**, not an invitation to retry. Preserve `transition-inflight.json`, `needs-review.json`, logs and archives.
- Avoid `docker compose down`, all-container restarts, broad `systemctl --user restart`, DB schema resets, global source collection, and any `--apply` while reviewing the completed RC2.
- Image trust is intentionally narrow: the consolidated RC2 image is approved only for the named acceptance container; do not assume it can provision newly named participant instances.

## 2. Read-only release and environment checks

On the **host**:

```bash
cd ~/nerds-r2d

git status --short
git branch --show-current
git rev-parse HEAD
git diff --check

docker image inspect devob_instance:r2d4-consolidated-rc2 \
  --format '{{.Id}}'

python3 scripts/pilot1_multi_supervisor.py
systemctl --user is-active nerds-p1-registry-r2d4.service
```

**Expected as of RC2 completion:** source branch `feature/r2d4-consolidated-image` at `513608cd004af5e768512cd292f8b425a8e7e594` and clean tree; image ID `sha256:825246d5460d56c0df37444bf113e7c9a03e8867d724b86401a8c24a098a5abf`; the completed RC2 session is **not** in the active supervisor preview, while two other sessions each show two collectors and one blocked session remains blocked.

**Interpretation:** Preview does not promise that every background service or credential is valid. Investigate unexpected entries without changing participant state. The registry active check demonstrates the host service was active at that time, not readiness of a new remote deployment.

## 3. Participant provisioning, invitation and collections (for a NEW authorized Pilot 1 test only)

These scripts exist on the **host**; their APIs should be previewed before use. This section is descriptive because RC2's exact container-image trust is intentionally fixed and **not** suitable for a new RC2-named participant without separate implementation and approval.

| Stage | Host script or component | Operator gate |
| --- | --- | --- |
| Authorized enrollment/order assignment | Pilot 1 enrollment workflow / DB task-run rows | Verify study phase, single attempt, unique participant, randomized `order_code`; do not reuse earlier study's identifiers |
| Bind and provision Task 1 | `scripts/pilot1_assign.py` | Preview first; requires `--participant-id` and `--container`; checks image allowlist, DB assignment, unreleased task confidentiality |
| Provision collectors | `scripts/pilot1_multi_supervisor.py` | Preview default; the apply/watch mode is **global** and may touch other active sessions. Use scoped guarded operation and operator review instead; new collectors should use `--collector-launcher systemd-user` |
| Issue one-time invitation | `scripts/pilot1_invite.py` | Preview first; token/URL produced by `--apply` is sensitive and must be delivered privately. Invitation TTL default is 15 minutes (allowed 5–30) |
| Participant workspace | Internal CLI and internal Firefox | Verify single released task, locked other task, left sidebar/right CLI/BROWSER; read the guide and host paste restriction |
| Ongoing collection | `scripts/pilot1_auto_ingest.py` and `scripts/pilot1_track_sources.py` | Exactly one collector of each kind for the released task; archive-root is private `~/nerds-pilot-backups` |

**Do not apply enrollment or invitation commands to the completed RC2**. Re-inviting a completed participant is not a valid cleanup or recovery tactic.

### Collector ownership

The user-systemd service name is deterministic per task and session; actual command and unit names are generated by `pilot1_multi_supervisor.py`. Verify the active service's MainPID and `Restart=no` against the recorded task-scoped collector PID. The supervisor also creates a durable `collector-launch-attempt-<kind>-<task>.json` marker **before** launch; this prevents silent duplicate restarts if an operation fails.

New sessions must not start collecting on a task until the DB has released it. For Task 2, the CLI importer uses the **database-authored Task 2 release event** as its recording floor; raw copies of older recordings may remain in the archive but must not be imported under Task 2.

## 4. Normal participant task transition: preview and guarded apply

The participant selects **Finish Task** or **Skip Task** within the authenticated workspace. That records an intent marker; it is **not** itself the final database transaction.

1. **Preflight**: verify DB study session `active`, expected task `ready/active`, next task `locked` for the first transition (or Task 1 terminal and Task 2 `ready/active` for finalization), correct assigned container/image, no active fuzzer/compiler, exactly two collectors for the currently released task, no transition/review block and no previous attempt.
2. **Read-only preview**: `scripts/pilot1_auto_transition.py` is read-only by default. It accepts a fully scoped host environment `NERDS_CONTAINER`, `NERDS_INSTANCE_ID`, `NERDS_SESSION_ID` and `NERDS_COLLECTOR_LAUNCHER=systemd-user`. The preview must display `action=advance` or `action=complete` and the actual participant outcome. Never paste a receipt bearer or invitation into the command line.
3. **Guarded one-time apply**: only after an operator has saved a durable attempt record and `transition-inflight.json`, acquired the supervisor lock, and confirmed no other worker is operating on this session. The lifecycle script revalidates the participant marker against DB assignment and performs stop → flush → archive → (if first handoff, stage/swap workspace) → guarded DB transaction → publish (on final task) → clear intent → restart participant services. It stops only matching old-task collectors; under `systemd-user` mode the next task's collector launch is delegated to the supervisor.
4. **Verify BEFORE clearing safety marker**: task and session states, event uniqueness, archive integrity, task metadata, next-task service availability, stopped old collectors, collector noninterference, and—on final completion—the exact receipt status served via local Nginx. Clear in-flight marker only when all checks pass.
5. **Task 2 collector launch**: only if Task 2 is newly `ready` and active, with no collector-start attempts or prior observed-collectors marker. The full supervisor `--apply` pass can act on multiple participants; avoid it for scoped qualification. Start with the host's identity-checked `manage_collectors(..., launcher='systemd-user')` path and verify both service PIDs.

**Operator policy:** This is a workflow description, **not** a command to run now. Do not launch lifecycle `--apply` from this document against existing or completed sessions. Refer to a session-specific preflight/verification script and retain its private evidence.

## 5. Evidence reconciliation and private data custody

Before concluding a task, compare at least:
- Task-run UUID in DB, approved container and image, released position and recording floor.
- Complete `bash_command_completed` rows against eligible archived JSONL, including keys and SHA256; exclude pre-release recordings from Task 2, but preserve raw archive evidence.
- LibFuzzer campaign count, harness, outcome and final executions against terminal output and timing, with completed campaign event linkage.
- Source journal baseline/change entries against DB `source_baseline_captured` and `source_change_detected`, verified ZIP snapshot/diff file size and SHA256.
- One outcome-request and one `task_completed`/`task_skipped` event per participant decision, exactly one `task_released` for Task 2, and one `session_completed` at the end.
- No clipboard text rows in accepted RC2; verify active API process environment rather than only `docker exec` shell defaults. AI prompt attribution to the correct task when tested; LLM response capture deferred.
- Completion receipt JSON is published only **after** a committed completed session; verify through authenticated study flow/local status endpoint without printing URL token or status filename.

Private data paths: `~/nerds-pilot-backups/`, `~/nerds-pilot-runtime/supervisor/sessions/`, `~/nerds-pilot-runtime/completion-receipts/` and operator logs. Keep `umask 077` for local evidence creation. **Do not commit or upload these directories.**

## 6. Failure handling: stop and preserve

| Condition | Safe response |
| --- | --- |
| No/duplicate collector, MainPID mismatch, missing systemd attempt marker | Stop. Inspect unit state, process list and private supervisor logs. Do not launch another collector until identity is reconciled. |
| Pending Finish marker but no valid next action | Do not fabricate an outcome or edit database to fit the marker. Inspect DB task states and the marker **privately**. |
| Failure before DB commit | Keep in-flight/review marker. Verify which services were restarted, whether workspace rollback occurred, collector state and archives before designing a session-specific recovery. |
| Failure after DB commit or while publishing receipt | **Do not rerun** the lifecycle. Reconcile completed DB rows, archived evidence and receipt publication separately; never create duplicate completion events. |
| Source journal/DB mismatch | Retain archives and content checksums; compare task identity and journal records without overwriting evidence or silently reassigning data. |
| Unexpected blocked session | Maintain manual-review block and investigate separately. Do not remove `needs-review.json` just to make preview green. |
| Failed CI/rebuild reproducibility | Do not replace the accepted image or reassign active participants. Record the failure and use an isolated build/test workspace. |

**The old previously blocked session** was intentionally excluded during RC2 acceptance. It has **not** been repaired, unblocked or requalified by the acceptance run.

## 7. Finalization and release freeze controls

- After final task completion, the study session must have a single authoritative `completed` state, two resolved tasks, end timestamps and a verified receipt. The completed participant no longer appears among active-session collector assignments.
- The receipt is a **bearer capability**. Keep token out of logs/chat/repository, allow its intended expiry, and do not generate recovery receipts casually.
- Preserve both task workspaces and records. Do not delete the completed RC2 container or archive for convenience during the release freeze.
- The source branch at `513608cd004af5e768512cd292f8b425a8e7e594` is backed up. The accepted image digest is separate. No new tag or merge should imply exact image-source reproducibility without a documented evidence check.
- Formal freeze proceeds only after the companion technical acceptance report and freeze checklist are reviewed. Negative-path and Pilot 2 qualifications remain open. **LLM response collection stays deferred**.

## 8. Next safe qualification order

1. Fresh, authorized reverse-order test (Low-Yield first) with isolated identity and release-boundary checks.
2. Skip Task in each position; verify skipped/completed event distinction.
3. Interrupted/stopped/crashing fuzzing and artifact recording; no forced crashes in other participants' containers.
4. Transition/receipt failure handling on an isolated disposable test session; manual recovery validation.
5. Advisor usability/IRB/privacy and retention review; then controlled NSF ACCESS Pilot 2 planning.

This operator runbook is a **maintained qualification guide**. It should be updated after each new test phase; it must not be interpreted as authorization to mutate active participant sessions.
