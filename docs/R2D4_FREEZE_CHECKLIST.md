# Release 2D.4 RC2 — Freeze and Reproducibility Checklist

**Prepared:** 2026-11-04  
**Review state:** **DRAFT / NOT YET TAGGED**  
**Accepted-source SHA:** `513608cd004af5e768512cd292f8b425a8e7e594`  
**Previously accepted local Docker image ID:** `sha256:825246d5460d56c0df37444bf113e7c9a03e8867d724b86401a8c24a098a5abf`

This checklist distinguishes **normal-path acceptance** (passed), **source backup** (passed), **build provenance/reproducibility** (incomplete) and **unexercised failure/alternate task-order paths** (future qualification). It must not be used to operate the already completed RC2 participant.

## A. Evidence gates

- [x] Pilot 1 RC2 normal path: Dense-first participant, both tasks Finish, PostgreSQL complete, real Study Complete page.
- [x] CLI, LibFuzzer campaign, source changes and artifact integrity reconciled; Task 2 DB-authored release boundary excludes eight pre-release copies.
- [x] Browser, internal clipboard metadata, blocked host paste, one ChatGPT prompt attributed; no RC2 clipboard text.
- [x] Completion receipt published after DB commit, HTTP 200 and visible Study Complete page confirmed; RC2 collectors stopped; existing participant collectors unchanged.
- [x] Seven tracked changes + new 45-line image-trust helper reviewed; targeted positive/negative image trust and syntax checks passed.
- [x] Exactly eight files committed to source SHA `513608c...`, pushed and verified on GitHub, operator observed clean working tree.
- [ ] Record the exact local Docker build invocation, build context and build arguments used for RC2, if available from operator notes. **Do not infer them from tags**.
- [x] Record **read-only available** build toolchain/image metadata (Docker 29.4.0, Compose 5.1.2, linux/amd64, image creation timestamp), no private data. Exact build invocation and all base-image digest metadata remain unknown.
- [x] Inventory relevant test filenames and available GitHub status data; seven offline tests identified for a targeted regression run. **Their results are still pending**, and no CI pass is claimed.
- [ ] Review `R2D4_RC2_ACCEPTANCE_REPORT.md` and `R2D4_OPERATOR_RUNBOOK.md` for confidentiality, accuracy and limitations.
- [ ] Decide whether the release designation means **accepted Pilot 1 RC2** or a broader **ready-for-expanded-testing** release. Do not claim NSF ACCESS/production readiness.
- [ ] Document final owner approval/signoff and freeze tag SHA if a tag is created.

## B. Read-only WSL inventory (operator action)

**Do not execute these commands in the participant CLI or another user's container.**

```bash
cd ~/nerds-r2d

echo "=== SOURCE IDENTITY ==="
git branch --show-current
git rev-parse HEAD
git status --short
git diff --check
git ls-remote --heads origin feature/r2d4-consolidated-image

echo "=== ACCEPTED IMAGE METADATA ==="
docker image inspect devob_instance:r2d4-consolidated-rc2 \
  --format 'ImageID={{.Id}} OS={{.Os}} Architecture={{.Architecture}} Created={{.Created}}'

echo "=== RUNTIME/BUILD TOOL VERSIONS ==="
docker version --format 'Client={{.Client.Version}} Server={{.Server.Version}}'
docker compose version
git --version

echo "=== UNPINNED BUILD INPUTS IN DOCKERFILE ==="
grep -nE '^(FROM |RUN npm |ADD https://|COPY --from=)' instance/Dockerfile

echo "=== KNOWN TEST AND WORKFLOW PATHS ==="
git ls-files '*test*.py' '*Test*.py' '*test*.js' '*test*.jsx' \
  '.github/workflows/*'

echo "=== PACKAGE BUILD COMMANDS (NON-SECRET) ==="
python3 - <<'PY'
import json
from pathlib import Path
p = json.loads(Path('instance/app/package.json').read_text())
for k, v in sorted(p.get('scripts', {}).items()):
    print(k + ': ' + v)
PY

echo "=== VALIDATE CURRENT HOST / REMAINING PARTICIPANTS (PREVIEW ONLY) ==="
python3 scripts/pilot1_multi_supervisor.py
systemctl --user is-active nerds-p1-registry-r2d4.service
```

**Privacy:** Do not paste environment variable values, raw `docker inspect` JSON, build logs with credentials, participant registry content or raw study event rows into public issues. The commands above print limited identity metadata and test-path inventory only.

**Expected:** head/remote at `513608cd004af5e768512cd292f8b425a8e7e594`; image ID as above; working tree clean. Record unexpected differences and stop before tagging. A preview may reveal that unrelated active participants exist; **do not fix or restart them** for this checklist.

## C. Existing test evidence versus missing CI

| Test category | Evidence | Status |
| --- | --- | --- |
| End-to-end real browser + task transitions | RC2 acceptance outputs and private verified markers | **PASS** (single Dense-first normal path) |
| CLI/task boundary reconcile | 8 Task 1, 4 Task 2; source/campaign/artifact reconciliation | **PASS** |
| Source image trust predicate | 2 legacy IDs + exact RC2 accepted; wrong tag/name/ID/malformed rejected; 3 running images approved | **PASS** (operator-run isolated tests) |
| Python syntax | `ast.parse` on six relevant Python files | **PASS** |
| Shell syntax | `sh -n instance/services/api/run` | **PASS** |
| Git diff whitespace and exact 8-file inventory | Operator-run checks | **PASS** |
| React test suite `npm test` | Not established for reviewed commit | **NOT VERIFIED** |
| Fresh image build `docker build` | Not performed during this release checkpoint | **NOT VERIFIED** |
| GitHub CI on exact source commit | No commit status records or PR-triggered runs visible via connector; other workflows unknown | **NOT VERIFIED** |
| Reverse task order, Skip, interrupted campaigns, lifecycle/recovery | Not part of completed RC2 normal-path test | **OUTSTANDING** |

**Do not infer CI absence from the limited commit status query**; inspect repository workflows locally. `instance/app/package.json` exposes `npm run build` and `npm test` through react-scripts. If running tests, use a separate checkout/isolated environment and record exact commands, lockfile and results. Avoid running `npm install`, `docker build`, `docker compose up`, restarts or destructive operations against the accepted live study environment as part of this read-only inventory.

## C1. Verified WSL inventory and offline test discovery (2026-11-04)

Operator ran the checklist's read-only WSL inventory:

- **Source:** `513608cd004af5e768512cd292f8b425a8e7e594`; `git status --short` was empty.
- **Accepted image:** `sha256:825246d5460d56c0df37444bf113e7c9a03e8867d724b86401a8c24a098a5abf`; Docker image created `2026-11-04T19:58:41.144438164Z`; platform `linux/amd64`.
- **Tools:** Docker client/server `29.4.0`, Docker Compose `v5.1.2`.
- **Build inputs (observed):** `FROM node AS build`, `RUN npm install`, `RUN npm run build`, `FROM debian:stable-slim`, and `COPY --from=emscripten/emsdk`; not digest-pinned. No rebuild performed.
- **Supervisor:** Exactly two unrelated active sessions had 2 collectors each; previously blocked manual-review session remained blocked; completed RC2 was not active.
- **Discovered test files:** `instance/test_pilot1_task_descriptions.py`, `tests/test_pilot1_auto_transition.py`, `tests/test_pilot1_lifecycle.py`, `tests/test_pilot1_supervisor.py`, `tests/test_pilot1_task_boundary.py`, `tests/test_r2c_clipboard_policy.py`, `tests/test_r2d4_stopped_campaign.py`, plus the older `scripts/pilot1_issue_test_session.py`, `test/get_suggestions.py` and `test/test-instance.py`. The inventory reported no `.github/workflows/*` tracked paths; connector's commit-status and PR-run summaries were empty, which is not conclusive proof of the absence of every possible CI configuration.

### Suggested offline regression run (pending operator result)

Source inspection confirmed the **seven** tests below are unit/mock/synthetic tests, not live Docker/DB mutation scripts; use the **explicit module names**, not repository-wide discovery, to avoid running older `test/test-instance.py` or enrollment scripts. `test_r2c_clipboard_policy.py` defaults to a different checkout unless `NERDS_REPO` is set. `PYTHONPATH` also ensures sibling module imports in tests resolve from the accepted checkout.

```bash
cd ~/nerds-r2d
PYTHONDONTWRITEBYTECODE=1 \\
PYTHONPATH="$PWD/scripts:$PWD/instance" \\
NERDS_REPO="$PWD" \\
python3 -m unittest -v \\
  tests.test_pilot1_auto_transition \\
  tests.test_pilot1_lifecycle \\
  tests.test_pilot1_supervisor \\
  tests.test_pilot1_task_boundary \\
  tests.test_r2c_clipboard_policy \\
  tests.test_r2d4_stopped_campaign \\
  instance.test_pilot1_task_descriptions
```

**Run only after confirming Python packages/imports are available** and under the trusted WSL operator account; no `--apply` and no service restarts. These tests may create temporary files in system temp and use synthetic subprocess/mocked modules; they are not expected to affect participant data. Record test count, failures and errors before changing freeze status. Do **not** substitute `unittest discover` with a broad pattern without reviewing all discovered tests.

## D. Reproducibility caveats

- The accepted image is pinned by its **Docker image ID**, not just its mutable tag.
- `instance/Dockerfile` currently begins with `FROM node AS build` and `FROM debian:stable-slim`, and imports `emscripten/emsdk` without a digest pin. These sources can resolve differently at later build time.
- The React build uses `npm install` rather than enforcing `npm ci`; verify exact dependency lockfile/Node version if trying to reproduce the image.
- The Dockerfile obtains a websockify archive from a remote tarball and packages a Firefox extension from repository source. External packages, base OS package versions and build timestamps can vary.
- Therefore a successful rebuild from the source commit may **not** have identical image bytes or image ID; functional and source-level reproducibility can be evaluated separately from strict binary identical output.
- The accepted image was validated **before** the reviewed eight-file commit was pushed. Verify build-source provenance or record this limitation; never silently claim that the current release commit produced that exact image.

**Recommended freeze label before fully reproducible build:** `Release 2D.4 RC2 — Pilot 1 E2E accepted; tested Docker image pinned; exact rebuild reproducibility pending`.

## E. Tag/freeze decision gate

**Proposed:** Do not create a formal release tag until the operator reviews section B output and approves the intended scope.

- [ ] Report and runbook linked from release notes or merged as docs-only changes.
- [ ] Confirm the release source commit (currently `513608cd...`) and distinguish any subsequent docs-only commit SHA.
- [ ] Record the build provenance and state known limits in the tag annotation/release notes.
- [ ] No active sessions affected, no acceptance secrets published.
- [ ] Operator chooses **(a)** freeze as *Pilot 1 RC2 normal-path accepted* with documented exclusions, or **(b)** postpone tag until reverse/skip/recovery tests.
- [ ] Verify tag remotely and update the GitHub handoff only after a successful tag push; **never force-push**.
- [ ] Do not merge unrelated changes or broaden the immutable image allowlist as part of release tagging.

## F. Post-freeze validation backlog (not blocking a narrow normal-path tag)

- Reverse-order task flow (Low-Yield first) and task attribution boundaries.
- Skip Task at either position; correct outcome accounting and completion receipt.
- Interrupted/stopped/crashing fuzz campaigns and timed terminal/archive recovery.
- Simulated failures during source/archive/DB transaction/receipt publication, with review markers and safe operator recovery.
- Concurrent sessions, access expiry and task isolation, provisioning a *new* RC2-style participant from an approved image policy.
- Advisor/lab-mate UX feedback and privacy/consent/retention review.
- NSF ACCESS Pilot 2 with separate deployment qualification and QuestionPro consent/invitation/exit integration.
- **LLM response capture deferred** until these higher-priority flows are stable and consent/privacy scope is re-reviewed; prompt logging remains supported.

## G. Continuation record

Start the next chat with:

> Continue NERDs Release 2D.4 freeze from `docs/R2D4_RC2_ACCEPTANCE_REPORT.md`, `docs/R2D4_OPERATOR_RUNBOOK.md` and this checklist on `docs/r2d4-rc2-freeze-20261104`. The accepted source code remains backed up at `513608cd004af5e768512cd292f8b425a8e7e594` and the accepted Docker image ID is `sha256:825246d5460d56c0df37444bf113e7c9a03e8867d724b86401a8c24a098a5abf`. RC2's session is completed; do not rerun transitions. Next gather the read-only WSL build/test inventory, finalize freeze scope and tagging decision; thereafter begin isolated reverse-order and Skip Task tests. LLM responses remain deferred.
