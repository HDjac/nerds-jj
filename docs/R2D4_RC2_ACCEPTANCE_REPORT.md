# NERDs CLI Fuzzing — Release 2D.4 RC2 Technical Acceptance Report

**Report date:** 2026-11-04  
**Environment:** Pilot 1, private local WSL/Docker study environment  
**Disposition:** **PASS — normal-path, end-to-end RC2 acceptance**; **formal release freeze/tag pending**  
**Evidence basis:** operator-reported acceptance outputs checked against PostgreSQL, archival checks, local Docker/systemd, browser UI and local HTTPS receipt; GitHub source commit independently verified. This report is **not** a claim that all negative paths, production hosting, IRB/consent, CI or binary-identical reproducibility have been qualified.

## 1. Configuration under test

| Item | Identity |
| --- | --- |
| GitHub repository | `HDjac/nerds-jj` |
| Accepted local branch / now pushed | `feature/r2d4-consolidated-image` |
| Pre-backup tested base commit | `4f685b1188f714cd6b614a1c7a66d2075466fa98` |
| Reviewed and pushed eight-file source checkpoint | `513608cd004af5e768512cd292f8b425a8e7e594` |
| Accepted local Docker image tag | `devob_instance:r2d4-consolidated-rc2` |
| Accepted image ID (`docker image inspect`) | `sha256:825246d5460d56c0df37444bf113e7c9a03e8867d724b86401a8c24a098a5abf` |
| Local project checkout | `~/nerds-r2d` |
| Private evidence directory | `~/nerds-pilot-backups/r2d4-rc2-acceptance/` |
| Trial task order | Dense v2 (position 1) → Low-Yield v1 (position 2) |
| Participant AI policy | Voluntary use of AI tools in internal Firefox; no AI/NON_AI assignment |
| Clipboard policy in accepted build | Internal browser↔CLI permitted; host↔study blocked; metadata ingestion on; text capture off |

**Build/source distinction.** The Docker image was accepted **before** the final source-backup commit. The eight files in that commit were inspected and verified against the accepted runtime behavior, but an independent fresh build from `513608c` and byte-for-byte artifact reproduction **have not been demonstrated**. Do not label the pushed source commit itself as the proven image build origin until provenance is reconciled. Preserve the image ID, commit SHA and this distinction in release notes.

## 2. Acceptance method and observed results

The RC2 session was exercised through real participant-facing UI, including the initial task, task transition and final Finish Task action. Host-side read-only reconciliation compared database task IDs, campaign/event counts, archived command hashes, source journals, artifacts and timestamps. Guarded lifecycle transitions were applied **once** and postflight verified before safety markers were cleared. No broad multi-participant supervisor apply operation was used for RC2 transitions.

| Acceptance surface | Result and supporting observation |
| --- | --- |
| Enrollment, invitation and released task | **PASS**: participant assigned; first task ready, second locked; correct private desktop and APIs |
| Task layout, Fuzzing Guide and readability | **PASS** for tested RC2 workspace; LEFT task/sidebar, RIGHT CLI/BROWSER tabs; internal guide copy worked |
| Dense v2 CLI | **PASS**: 8 completed commands in task-scoped DB records |
| Dense v2 fuzzing | **PASS**: 1 completed LibFuzzer campaign |
| Dense v2 source capture | **PASS**: 2 source observations; workspace and evidence archived |
| Internal Firefox | **PASS**: browser navigation captured; RC2 scoped browser events observed |
| Clipboard metadata and isolation | **PASS**: 8 scoped clipboard events, including two paste requests and two blocked host paste shortcuts; internal CLI↔browser activity observed |
| Clipboard text minimization | **PASS**: zero clipboard text rows associated with the RC2 session; runtime text flag disabled |
| LLM prompt collection | **PASS**: one benign internal-Firefox ChatGPT prompt recorded once, associated with Dense v2; response bodies **not** required |
| First Finish Task | **PASS**: Dense v2 completed exactly once; Low-Yield v1 released; two old collectors stopped; workspace archive validated |
| Task 2 baseline | **PASS**: one source baseline, zero initial commands/campaigns, two new systemd-managed collectors |
| Low-Yield v1 CLI | **PASS**: 4 completed commands under Task 2 |
| Low-Yield v1 fuzzing | **PASS**: 1 completed Harness A campaign, 25 executions |
| Low-Yield v1 source capture | **PASS**: 2 source observations and 3 source artifacts verified against journal, DB, size and SHA256 |
| Task-boundary isolation | **PASS**: 8 pre-release command copies mapped to Task 1; 4 eligible Task 2 commands matched DB; zero mismatched or overlapping keys |
| Final Finish Task | **PASS**: one outcome request, one Task 2 completion and one session completion event; both task end timestamps present |
| Final workspace archival | **PASS**: one nonempty Low-Yield workspace tar, including source observation and matching task metadata |
| Completion receipt | **PASS**: PostgreSQL-verified opaque receipt published and fetched through local HTTPS endpoint (HTTP 200); participant visually confirmed **Study Complete** page |
| Collector cleanup | **PASS**: RC2 collectors stopped after completion; RC2 absent from active-session supervisor preview |
| Concurrent participant noninterference | **PASS** for observed test: two other participant instances retained their original four collector PIDs; separate manually blocked session remained blocked |
| Registry service | **PASS**: active after finalization |

### Quantitative evidence summary

| Measure | Dense v2 | Low-Yield v1 |
| --- | ---: | ---: |
| Complete CLI commands stored in PostgreSQL | 8 | 4 |
| Completed campaigns | 1 | 1 |
| Source observations | 2 | 2 |
| Verified source artifacts | Historical evidence preserved; exact Task 1 artifact count not part of this final scoped report | 3 |
| Final task state | `completed` | `completed` |

**Scope of conclusion:** The evidence confirms one **completed/completed** flow with **Dense-first** ordering, not every possible study assignment or failure mode.

## 3. Source backup and integrity checks

The WSL checkout originally contained **seven modified tracked files and one new untracked file**. The operator reviewed all seven diffs and the 45-line `scripts/pilot1_image_trust.py` implementation. The source backup commit includes exactly these eight files:

```text
instance/Dockerfile
instance/services/api/run
scripts/pilot1_assign.py
scripts/pilot1_image_trust.py
scripts/pilot1_instance_registry.py
scripts/pilot1_invite.py
scripts/pilot1_lifecycle.py
scripts/pilot1_multi_supervisor.py
```

The reviewed commit changed 76 insertions and 8 deletions. Local and remote SHA matched `513608cd004af5e768512cd292f8b425a8e7e594`; local working tree was empty after push. GitHub independently returned the commit and the new helper.

Isolated source tests **passed**: exact legacy image IDs and named RC2 accepted; wrong image/tag/container name and malformed inputs rejected; all three observed running containers approved. Six Python files passed AST parsing, API startup shell passed `sh -n`, `git diff --check` passed, and the expected eight-file inventory matched. **Additionally, 51 restricted offline regressions passed after source backup (section 3a).** These are targeted checks, not full integration CI.

## 3a. Scoped offline regressions: 51/51 PASS (2026-11-04)

On the accepted, pushed source checkout (`513608cd...`) the operator ran four restricted `unittest` groups after reviewing their offline/mock/test-double behavior:

| Test group | Number | Result |
| --- | ---: | --- |
| Pilot 1 handoff, lifecycle, supervisor and release-boundary tests | 32 | PASS |
| Clipboard privacy and direction policies | 6 | PASS |
| LibFuzzer stopped/interrupted campaign classifier | 10 | PASS |
| Task-description neutrality and validity | 3 | PASS |
| **Total** | **51** | **PASS; zero failures or errors** |

No working-tree changes were reported afterward. The unit test console logs show simulated transitions using mocks and do not represent any additional live participant action. Unit-level Skip Task and stopped-campaign behavior have coverage, but **real participant skip, interruption and recovery scenarios remain untested here**.

**Freeze recommendation:** The code plus observed normal-path RC2 session and 51 offline tests support a **narrow Pilot 1 acceptance tag** with explicit scope. Fresh React build, exact image-source provenance and binary reproducibility, CI and negative-path tests are still open; do not label this production-ready or NSF ACCESS-qualified.

## 4. Architecture, scope and privacy decisions

- **Image trust:** a small immutable-ID allowlist accepts two legacy pilot images; RC2 acceptance image requires its exact tag, immutable SHA256 image ID and designated acceptance container name. Callers separately guard container running state, DB instance binding, unprivileged user, non-privileged mode, labels and network. This is **not** a generic production image-approval policy.
- **Data collection:** terminal commands and LibFuzzer output/timing and campaigns are task-scoped; source observations are journaled and archived with integrity metadata. The task-release event provides the authoritative recording floor for Task 2.
- **Browser/AI:** participants may voluntarily use ChatGPT or other AI tools in internal Firefox. Tested ChatGPT prompt capture and task attribution stay in scope. **LLM response body/stream capture is explicitly deferred** until the rest of the study flow is finished and its privacy basis reviewed.
- **Clipboard:** host↔NERDs clipboard isolation retained; internal clipboard allowed. Accepted RC2 enabled clipboard metadata with text disabled in both React build and running API. Future deployment must review data minimization and notices rather than silently inheriting RC2 settings.
- **QuestionPro:** consent and exit surveys remain external; Pilot 1 RC2 did not establish full external handoff or NSF ACCESS deployment.
- **Private evidence:** raw CLI transcripts, AI prompts, browser activity, invitation tokens, receipt bearer, IDs and DB secrets remain local; never commit them to GitHub.

## 5. Known limits, outstanding qualification and release gates

**RC2 normal-path passed; the following are not claimed as completed:**

1. Reverse randomized order, including clean task-attribution boundary and independent task archives.
2. Skip Task at position 1 and position 2, correct skipped/completed distinctions and receipt.
3. Interrupted and crashing LibFuzzer campaigns, incomplete transcript/timing, crash artifact and recovery behavior.
4. Mid-transition power/process failure, pre-/post-transaction interruptions, expired invitation and receipt-publication failures; durable markers and manual recovery without automatic replay.
5. Wider concurrency, session isolation, provisioning from the RC2 image to **new names**, registry failure handling and role-based permissions.
6. Repeatable production build: `node`, `debian:stable-slim`, `emscripten/emsdk` base tags are not pinned in this Dockerfile; remote dependencies and `npm install` can change. No fresh build from the pushed SHA was executed during this handoff, and no binary-identical digest claim is made.
7. Automated regression/CI coverage: isolated trust/syntax checks, **51 targeted offline unit regressions**, and the live E2E trace passed. GitHub returned no commit status records or PR-triggered workflow runs for the reviewed source commit; this does **not** prove no other workflows exist.
8. IRB/privacy consent, retention, study data export and full QuestionPro/NSF ACCESS Pilot 2 deployment are separate gates.

### Release disposition

- **Ready to designate:** `R2D.4 RC2 — normal-path Pilot 1 E2E accepted; source backed up`.
- **Not yet ready to claim:** production-ready, fully reproducible, all failure modes tested, or NSF ACCESS deployment validated.
- **Hold formal freeze/tag** until the operator checks the reproducibility inventory and test evidence, reviews the limitations with the advisor as appropriate, and chooses whether to freeze the tested RC2 scope or expand the qualification matrix. A tag on a documentation commit must not be confused with the already accepted Docker image ID.

## 6. Next milestones

1. Finish evidence/test inventory and document build provenance without changing the accepted running containers; use the companion `R2D4_FREEZE_CHECKLIST.md`.
2. Review this report and the `R2D4_OPERATOR_RUNBOOK.md`; approve a docs-only merge, then decide on a version tag/freeze.
3. Pilot 1 additional qualification: reverse task order → Skip outcomes → interrupted/campaign crashes → lifecycle and receipt recovery → advisor usability.
4. Release 3 priorities: participant orchestration, monitoring, recoverability, privacy governance, UI polish and analysis exports; **not** LLM response collection.
5. Pilot 2 on NSF ACCESS with a separately qualified QuestionPro consent → invitation → onboarding → exit flow; do not reuse assumptions from the previous Mines server.

**Evidence custody:** Local authoritative acceptance checkpoints and archives are under `~/nerds-pilot-backups/r2d4-rc2-acceptance/`. This GitHub report is a sanitized operational summary, not an exported participant dataset.
