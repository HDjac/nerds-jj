# NERDs CLI Fuzzing Study — Roadmap and Acceptance Checklist

Status: **proposed implementation baseline**, agreed for the local pilot.
Source checkpoint: Release 2C commit `8d25dfb`.
Development branch: `feature/cli-fuzzing-r2d`.
Scope: Pilot 1 local WSL implementation, followed by Pilot 2 on NSF ACCESS, then an approved final study.

## Implementation order and release gates

1. **2D.1 — Participant-facing instructions and anonymous task labels.**
2. **2D.2 — Side-by-side, resizable CLI / Firefox workspace.**
3. **2D.3 — Browser observation, Google standard-search enforcement, and clipboard provenance after split view.**
4. **2D.4 — End-to-end research-data audit and task attribution.**
5. **Release 3 — LLM response capture for explicitly supported services, with documented limitations.**
6. **Pilot 1 closeout — Full local sessions, fault/recovery tests, advisor and lab-mate acceptance, frozen build.**
7. **Pilot 2 — NSF ACCESS deployment and full external QuestionPro/onboarding dry run.**
8. **Final study — Approved recruitment, operation, monitoring, exports, analysis.**

No additional feature releases are assumed. Record new requirements and known limitations here before expanding scope.

## Advisor feedback and requests: master tracker

Legend: **DONE** = implemented and locally demonstrated in its specified scope;
**PARTIAL** = implemented in part or awaiting integrated acceptance;
**OPEN** = planned; **DEFERRED** = assigned to later release.

| ID | Request | Status | Target | Acceptance evidence |
|---|---|---|---|---|
| ADV-01 | Internal, revisitable fuzzing guide with usable commands | DONE | 2A | Quick Start/full guide and internal command copy tested |
| ADV-02 | Explain copy/paste for sidebar, CLI, Firefox while blocking host clipboard | DONE (local) | 2A / 2C | Guide, host isolation, all permitted directions tested; recheck in split view |
| ADV-03 | Collect permitted clipboard actions and scoped pasted text with safeguards | DONE (local) | 2B / 2C | Event IDs 3171/3275/3337 exact; five text records; zero excluded-source text records in local audit |
| ADV-04 | Increase command/example readability | PARTIAL | 2D.1 | Inspect sidebar, guide and xterm at actual participant resolutions |
| ADV-05 | Explain all three harnesses, corpus, and target program purpose without revealing vulnerabilities | IMPLEMENTED; awaiting UI/advisor review | 2D.1 | Neutral, task-specific descriptions and three-harness guide implemented; review in live UI |
| ADV-06 | Anonymous Task 1 / Task 2 in participant interface | IMPLEMENTED; awaiting UI check | 2D.1 | API/React labels changed; internal task codes retained; verify both orders |
| ADV-07 | Browser search terms and visited URL observations | CORE LOCAL VERIFIED; cross-task/recovery pending | 2D.3 / 2D.4 | Two Google search paths and ordinary navigation all persisted under Task 2; wider history/task transitions and queue recovery pending |
| ADV-08 | Avoid Google Search AI summaries/AI Mode as a default or uncollected chat surface | LOCAL UI ACCEPTED; DB verification pending | 2D.3 | User confirmed updated Firefox Web-only search and AI Mode behavior after v0.9.0 policy/extension activation; audit search/navigation task attribution next |
| ADV-09 | Capture AI responses in addition to supported prompts | DEFERRED | Release 3 | Captured responses correctly associated with prompts/tasks; failures detectable |
| UX-01 | Show CLI and Firefox simultaneously in resizable right workspace; sidebar left | LOCAL ACCEPTED; task-transition audit pending | 2D.2 / 2D.4 | User confirmed stable dual-window split, bounded resize at 1920x1080, CLI/Firefox focus and both clipboard directions; task-transition regression remains |
| DATA-01 | Joint audit of commands, fuzzing campaigns, source versions, AI/browser and clipboard activity | OPEN | 2D.4 | Reconstruct both tasks with unambiguous IDs, timestamps, outputs, artifacts, and outcome |

## 2D.1 — Participant experience

- Replace participant-facing `dense_v2` / `lowyield_v1` with **Task 1** / **Task 2**, including task headings and instructions. Keep internal stable `task_code` and task-run IDs unchanged.
- Explain what the assigned target program does at a high level, without describing vulnerability locations or directing participants to solutions.
- Explain `fuzz_a`, `fuzz_b`, `fuzz_c`, the purpose and reuse of seed corpora, compilation, basic run/stop/continue workflow, and how to read typical fuzzer output.
- Check sidebar, guide, CLI command font sizes at the actual 1280x720 participant resolution and larger sizes.
- Do not alter randomized order, archived work, or task decision semantics.

**Gate:** A new tester can start the appropriate task without outside coaching; neither hidden condition is disclosed.

### Release 2D.1 implementation checkpoint (source only)

- `instance/pilot1_task_descriptions.py` builds participant-facing Task 1/2 descriptions from neutral program overviews and shared harness/corpus instructions.
- `instance/instance-api.py` now returns anonymous `title`/`desc` while preserving the `task_code` for collection and task-transition logic; `instance/Dockerfile` installs the helper.
- `PilotTaskController.jsx` displays only Task 1/2; `fuzzingGuideData.json` has a dedicated three-harness explanation.
- Source-level tests: `instance/test_pilot1_task_descriptions.py`; repeatable validation: `bash scripts/r2d1_verify.sh`.
- **Live local check:** Release 2D.1 was activated in the existing local participant; Task 2 anonymous heading and harness/corpus guidance were verified. User reported instructions looked good, but identified duplicate assignment/directory text and requested persistent task controls.
- **Follow-up implemented, live acceptance pending:** Redundant assignment/directory block removed; Finish Task / Skip Task moved to a bottom footer outside the scrolling instruction pane. Reversible frontend-only deployment helper: `scripts/r2d1_sidebar_live.py`.
- **Remaining acceptance:** Test footer and scroll behavior in live UI, review both randomized task orders and CLI font readability, and obtain advisor review before freezing 2D.1. Do not mark pending work complete from the code change alone.

## 2D.2 — Resizable split workspace

- Preserve left task sidebar; replace exclusive CLI/BROWSER switching with **simultaneously visible xterm and Firefox** in the right workspace.
- Prefer a **single existing X11 desktop/noVNC connection** with side-by-side X11 windows and a React-controlled splitter. Do not create independent sessions that silently separate clipboard or activity contexts.
- Support draggable resizing, reasonable min sizes, and CLI-only/Browser-only focus modes without terminating either app.
- Ensure task transition creates/displays the new task's CLI without a stale window, and retains a valid split arrangement.
- Replace tab-based clipboard destination inference with the **actual focused remote X11 application/window** and correctly handle focus changes, copy/cut/paste shortcuts, and ambiguous interactions.
- Verify noVNC resize behavior, terminal selection, internal Firefox, clipboard restrictions, and collection while both panes are visible.

**Live attempt and compatibility finding:** The first R2D.2 deployment automatically rolled back after an HTTP 503 from the window-tiling endpoint. In the original participant display, Matchbox reported both xterm and Firefox as full-screen windows (1923 × 750). This is a window-manager constraint rather than a failed frontend build. API and noVNC services remained running, and the prior R2D.1 frontend/API were restored.

**Revised implementation:** Use Openbox for the VNC session (`instance/services/vnc/run` and Docker image) and perform a reversible local WM migration with `scripts/r2d2_openbox_live.py`. Changing WM requires a **VNC display restart**, which can close GUI programs / interrupt an active fuzzing command; never perform while a campaign is running. The participant's database, task assignment and Docker container persist. The frontend/API update remains a separate reversible `scripts/r2d2_live.py apply` action. Verify real CLI and Firefox windows, divider, focus and clipboard, then accept.

**Local UI feedback (2026-11-02):** After switching to Openbox, the existing Task 2 participant successfully displayed CLI and Firefox simultaneously. The user identified a misleading double-boundary/gap beside Firefox, slightly misaligned graphics, and a minimized window that required switching layouts to restore. **UI-polish follow-up implemented, not yet accepted:** force noVNC canvas and HTML splitter to the full workspace width; position Firefox next to the **measured** XTerm edge; return the actual divider percentage; restore both windows in split mode and add a **Restore windows** control; suppress native minimize/maximize titlebar buttons via Openbox configuration. Reversible frontend/layout-only activation is `scripts/r2d2_polish_live.py`; run on the existing instance without resetting Task 2. Verify one divider, no black gap, usable resizing, keyboard focus/clipboard, and recovery after layout changes before marking UX-01 complete.

**Further local feedback (2026-11-02):** Follow-up screenshots show two separate Firefox windows: Firefox-only restores a previously used tab, but Split View exposes a different Firefox tab/window, producing a large black gap. Focus is shown for Firefox-only but often `unknown` in Split View. Root cause in `workspace_layout.py`: selecting the last Firefox X11 window on every call was dependent on window stacking; focus matched only that one selected Firefox window. Follow-up source fix pins one Firefox XID during the API lifetime, classifies input focus across *all* Firefox windows and X11 window classes, and adds non-decorated Openbox application rules for future windows. The dedicated in-place rollback script is `scripts/r2d2_unify_live.py`. **Live acceptance pending:** same Firefox tabs across all layouts, one correctly aligned resize divider, reliable CLI/Firefox focus label, and no clipboard misclassification. The script does not delete other Firefox windows or their tabs; currently open windows may retain existing native frames until remapped.

**Additional 2D.2 acceptance feedback:** The user confirmed the single Firefox workflow and split view are working, but dragging either application below its supported width produced a 503. The layout helper now measures the **pinned** Firefox window and steps extreme divider requests toward a supported 50/50 layout instead of treating normal window minimum sizes as an API failure. The response contains the actual `divider_percent` for the existing React drag handle and a `clamped` indicator. A backend-only live deployment/rollback helper is `scripts/r2d2_clamp_live.py`; test both ends of the divider directly in the current participant before marking this item accepted.

**Resolution and Firefox scaling preference (2026-11-02):** The user validated a live 1920x1080 VNC resolution. New participant displays now default to `1920x1080` in `instance/services/vnc/run`. Firefox interface scaling should remain **automatic** (`layout.css.devPixelsPerPx=-1.0`, its normal default), not forced to 0.85 across users. An earlier manual 0.85 local profile change can be restored to automatic in Firefox's `about:config`; changing the default source does not alter running Firefox preferences or restart VNC. Continue testing resizable split workspace and actual X11 focus/clipboard attribution in the existing local participant before marking 2D.2 accepted.

**Gate:** Continuous CLI + Firefox usability, reproducible task transitions, correct source/destination metadata, host clipboard isolation.

### Release 2D.2 local acceptance (2026-11-02)

The user confirmed that, in the existing local NERDs participant, Split View shows the intended CLI and Firefox, extreme divider movements clamp to usable widths, both application's focus labels behave correctly, and copying CLI→Firefox and Firefox→CLI works. Firefox scaling stays automatic; the accepted VNC desktop is 1920×1080. This closes the **local interactive split-workspace checkpoint**, but full task-transition, database attribution, and advisor acceptance remain part of later integration/closeout.

## 2D.3 — Conventional Google Search and browser reliability

### New approved study-browser policy

Participants may voluntarily use supported AI chat services through internal Firefox. However, **Google Search should present conventional web links, not AI Overviews or conversational AI Mode**. We will *not* add Google Search AI Overview/AI Mode response capture solely to support this surface.

Google documents AI Overviews as a core Search feature that cannot simply be turned off. The Google **Web** filter instead omits AI Overviews. Disabling Search Labs experiments alone does not disable all AI Mode experiences.

Implementation strategy (to be built and tested):
1. Use the controlled Firefox profile/extension to make Google search submissions land in **Web** results (e.g. `udm=14`), including searches from Firefox's address bar and Google's own search form. Keep the original `q` searchable and recorded by the existing browser search observation mechanism.
2. Restrict entry into Google **AI Mode** via known buttons/direct routes, with fail-closed behavior or a user-facing explanation. Avoid relying only on CSS hiding; test direct links, reloads, history and navigations.
3. Preserve access to traditional search, web documentation, and separately supported chat services (e.g. `gemini.google.com`, ChatGPT, Claude) under their own existing prompt/response capture policies.
4. Do not claim absolute elimination of all Google AI exposure: Google can change routes/markup and unrecognized surfaces may remain. Record technical coverage and limitations; repeat tests before Pilot 2.
5. Keep privacy, participant disclosure and source-specific AI capture policies accurate. Google search queries/navigation continue to be logged under existing constraints.

**2D.3 implementation checkpoint (source committed; live validation pending):**
- Firefox policy `instance/firefox-policies/policies.json` adds a managed `NERDs Google Web` search engine using `https://www.google.com/search?udm=14&q={searchTerms}`.
- Extension v0.9.0 adds top-level Google navigation redirects (including known `/ai`, `/aimode`, `udm=50` cases) and cosmetic hiding of known AI Mode links. It does not alter `browser-events.js` or AI prompt logging, and it leaves `gemini.google.com` unaffected.
- The Docker image packages the XPI from its source rather than the previously committed stale binary. The in-place local installer is `scripts/r2d3_google_web_live.py`, which backs up and stages XPI/policy **without restarting Firefox or resetting any study work**. A graceful Firefox restart is required to activate the changes.
- Restriction is explicitly best-effort for known Google Search routes, not a guarantee about future Google markup, country domains, or all possible AI endpoints. Re-test before Pilot 2 and document all observed bypasses.

**Local R2D.3 browser acceptance (2026-11-02):** User reports Google Web-only search routing/AI Mode handling worked after installing and activating the updated Firefox policy and extension. This accepts the observed browser UI behavior for Pilot 1; it is **not yet evidence that search/navigation observations arrived in the PostgreSQL database**, and does not mean all possible AI Mode routes are blocked. `scripts/r2d3_browser_db_check.py` performs SELECT-only verification of two harmless search markers plus an `example.com` navigation, checking event type and association with the currently active task run. Keep this check separate from the later integrated data audit.

**2D.3 PostgreSQL verification (2026-11-02):** In the live Pilot 1 active session, Task 2 (`dense_v2`, task status `ready`), two distinct Google search queries produced three `browser_search` notifications each (event IDs 6154–6156, 6161–6163), all on Task 2; `wrong_task_events=0`. The test `example.com` navigation yielded **zero matching navigation events**, so this part of the acceptance is unresolved. Repeated search notifications should not be interpreted as repeated participant searches. The read-only diagnostic `scripts/r2d3_browser_db_check.py` now accepts both `example.com` and `www.example.com` and reports aggregate navigation counts without revealing unrelated URLs. Do not declare full 2D.3 database acceptance until a non-search navigation is verified.

**Gate:** At minimum: address-bar search, Google home/search-box search, Google results navigation, direct AI Mode route, AI Mode controls, history/reload, and extension-disabled failure/recovery paths tested. No ordinary search unexpectedly drops the user's query or silently bypasses the collector.

### Other 2D.3 checks

- Verify browser search/URL events, queued retries and duplicate prevention, task binding, and service differences.
- Retest the three approved clipboard-text directions and exclusions after focus-aware split-view changes.
- Maintain wording: clipboard text associated with a **paste request**, not proof the destination inserted it.

**2D.3 browser data checkpoint complete (2026-11-02):** The follow-up database query found the previously missed `www.example.com` ordinary navigation at event `6164` under Task 2 (`dense_v2`), plus Google address-bar search events `6154–6156` and Google search-form events `6161–6163`. All seven identified events have Task 2 attribution; `wrong_task_events=0`. Over the diagnostic window there were 19 navigation events and 33 raw search notifications, **not** 33 confirmed distinct participant searches. The `TEST_COUNTS` result of zero for `example_navigation_events` was a defect in the diagnostic SQL filter (`example.com` vs `www.example.com`), now fixed. This verifies the core local browser ingestion path and establishes the starting baseline for integrated auditing. Wider route/recovery checks and advisor acceptance remain open.

## 2D.4 — Integrated data audit

- Cross-check participant/session/task-run IDs and actual timestamps through both task orders.
- CLI commands + transcripts, harness selection, campaign start/end/interruption, error/crash artifacts and outcome classification.
- Baseline/source-change snapshots, patches, completeness, archive integrity and references.
- Browser navigation/query observations, supported AI prompts, clipboard events and scoped text with exclusion audits.
- Reconcile collector restart, transient failure, late/duplicate events and task transition boundaries.
- Document known blind spots and classification confidence; do not conflate inferred data with observed behavior.

**Audit kickoff (2026-11-02):** `scripts/r2d4_data_audit.py` performs a READ ONLY transaction scoped to the existing active participant and reports per-task counts for event source/type, campaigns/harnesses, artifact pointers/checksums, browser searches/navigation, AI interactions, restricted clipboard-text policy, source snapshots, and task/session consistency. It does not print command transcripts, search queries, prompt text, clipboard text, or source code. Data findings are pending live execution. Follow with artifact integrity verification and task-transition tests only after understanding this baseline.

**First live read-only audit (2026-11-02):** The existing participant session is `lowyield_first`, Task 1 `lowyield_v1` completed and Task 2 `dense_v2` ready. The audit reports **278 task-attributed events**, zero events assigned to a different session/task, and zero events without dedup keys. Task 2 has 122 clipboard events and 7 restricted text records, zero excluded-source text records. Browser: Task 1 four search notifications/five navigations; Task 2 forty-five search notifications/thirty navigations. Three ChatGPT prompt interactions total (1+2); no response data, as expected before Release 3. Source tracking references: 5 snapshots and 4 diffs across both tasks, with no reported missing size/checksum values. **Gaps to investigate:** no rows in `fuzz_pilot.campaigns` (the user has just demonstrated building fuzz_a/b/c, which is *not* itself a campaign); neither task row has `started_at` set, including completed Task 1; the existence and integrity of archived bytes remain unverified. The first audit reported `open_campaigns=1` per task despite `campaigns=0` due to null-side rows in a LEFT JOIN; the query now counts non-null `campaign_id`, and the artifact null-counts were corrected similarly. No database changes made.

**UI regression and mitigation (2026-11-02):** User screenshot shows CLI/Firefox titlebars missing and terminal output appearing to disappear when changing views. The earlier Openbox `<decor>no</decor>` rules unintentionally removed native titlebars. Source now restores Openbox titlebars while keeping the participant-controlled layout and limited title buttons; new xterm windows use `-sl 10000 -sb` for navigable scrollback. `workspace_layout.py` now avoids resizing the **hidden** xterm when selecting Firefox-only and avoids redundant resizing on repeated Split View. `scripts/r2d4_ui_live.py` provides reversible live activation **without restarting current Firefox, terminal, VNC, or participant**; the existing windows may require Openbox's Decorate action or an Openbox-only restart to regain their titlebars. Live acceptance pending. Recorded CLI terminal transcripts persist independently of xterm display scrollback.

**Live UI hotfix failure and safe retry (2026-11-02):** First `scripts/r2d4_ui_live.py apply` attempt failed while moving/chmod-ing staged layout and xterm startup files or restarting API. The command reported exit code 1 without captured stderr, so the exact failing operation is not proven. Suspected cause: `docker cp` creates staged files owned by root and the original script attempted `chmod` without ensuring ownership. The script's exception handler attempted restoration. Revised `r2d4_ui_live.py` explicitly assigns staged file ownership and performs file backup/installation using root, separates API restart from moves, captures original stderr, and uses a distinct `.r2d4-ui-retry` backup namespace to preserve artifacts from the failed attempt. **Live retry/acceptance still pending**; do not mark the UI regression fixed before checking actual behavior.

**Live UI retry result (2026-11-02):** The user reported a successful `scripts/r2d4_ui_live.py apply` run. Installation, API restart, and Openbox configuration completed; the script confirmed the hidden-xterm resize fix, reduced redundant layout changes, restoration of titlebar rules, and larger scrollback configuration for *future* xterm processes. The existing CLI/Firefox/VNC and Task 2 were preserved. **Visual acceptance remains pending:** existing windows may still be undecorated until remapped; check history retained across Split/Firefox-only toggles and note that current xterm did not inherit new scrollback flags. The zero-campaign and missing task start-time findings remain open.

**User regression follow-up (2026-11-02):** The previous successful `r2d4_ui_live.py` deployment did **not** restore the title bars on existing CLI/Firefox windows, and resizing the yellow splitter still made some previous xterm output disappear from the visible viewport. The cause is not an undone deployment: Openbox reconfigure affects the rules but does not itself invoke the `Decorate` action on already-open windows. `scripts/r2d4_restore_titlebars.py` installs a temporary `Ctrl+Alt+Shift+D → Decorate` keybinding and uses XTest to send it to the currently open CLI/Firefox windows when available, without restarting apps or VNC; manual shortcut fallback and rollback included. The source Dockerfile carries the same manual shortcut for future deployments. **Live acceptance pending.**

**Remaining xterm limitation:** The running xterm launched before the new `-sl 10000 -sb` startup options were installed, and width changes can rewrap or drop its *visible screen* content according to xterm's resize behavior; the upgraded options only apply to a future xterm process. A non-disruptive workaround is to enable the existing terminal's scrollbar via the xterm VT options menu and review previous lines if they remain in its scrollback; the independent `script` output/timing archive remains authoritative for recorded terminal output. Do not claim the source changes have solved history loss. Before deploying the next fresh Pilot 1 instance, evaluate a terminal emulator with tested reflow/scrollback support **while preserving command logger, clipboard provenance and source snapshots**; replacing the terminal mid-session would risk interactive continuity.

**Live title-bar validation (2026-11-02):** The user confirmed the CLI and Firefox title bars returned after the targeted Openbox Decorate restoration. Mark title-bar restoration **locally accepted**. The separate xterm visible-history/reflow issue when dragging the splitter remains **open**; no claim that it was resolved by restoring decorations. Next 2D.4 evidence needed is `FUZZER_INVOCATION_COUNTS` to distinguish no recorded fuzz runs from absent campaign imports.

**Live fuzzer invocation audit (2026-11-02):** User's updated read-only audit reports Task 1 `lowyield_v1` completed and Task 2 `dense_v2` ready, 288 task-attributed events and zero cross-task attribution/clipboard privacy violations. Task 1 has 22 `bash_command_completed` events; Task 2 has 43. The SQL classifier found **zero direct `./fuzz_[abc]` invocations** in both tasks and the `fuzz_pilot.campaigns` table has **zero campaigns** (and zero open campaigns, correcting the earlier LEFT JOIN count). This is not yet evidence that the importer is broken: the automatic host-side importer only recognizes direct harness invocations with clear LibFuzzer outcomes, while building fuzz binaries alone isn't a campaign. Next: in existing Task 2 internal CLI, `cd /home/user/fuzz-study/work`, `make fuzz_a` if needed, and `./fuzz_a -runs=100`. Confirm Bash event + LibFuzzer INITED/DONE or ASan crash, then rerun SELECT-only audit. If invocation persists but campaign does not, inspect whether `pilot1_auto_ingest.py --apply` supervisor is running and import output/deferrals; do not silently backfill. Missing task `started_at` timestamps remain a separate data integrity issue, requiring review rather than guessed backfill.

**Controlled fuzzing campaign accepted (2026-11-02):** After manually running `make fuzz_a` and `./fuzz_a -runs=100` in the existing Task 2 `dense_v2` CLI, the read-only audit found one direct bounded fuzzer invocation, one `libfuzzer_campaign_finished` event, and one completed `fuzz_pilot.campaigns` row for **Harness A** with `open_campaigns=0`. There are 291 task-attributed events across the current participant, no wrong-session/task attribution, zero events without dedup keys, and zero excluded clipboard-text records. This validates automatic ingestion of one completed bounded campaign; it does **not** cover crashes, interrupted campaigns, non-direct invocation syntax, other harnesses, or the still-missing task `started_at` values. No backfill performed.

**Next source archive integrity gate:** `scripts/r2d4_verify_source_archives.py` is a read-only audit against the actual `~/nerds-pilot-backups/sources/<session>/<task>/...` storage keys. For each PostgreSQL source snapshot or diff, it checks archive path safety, file existence, expected byte length, SHA256, snapshot ZIP CRC/safe member names, and association with a matching source event. It reports only status and counts, never file contents. Live verification pending.

**Source archive verification accepted (2026-11-02):** The user ran `python3 scripts/r2d4_verify_source_archives.py` on WSL against `/home/hoekj/nerds-pilot-backups` and obtained **9/9 PASS**: Task 1 has 3 source diffs and 3 source snapshots, Task 2 has 1 diff and 2 snapshots. All stored files matched PostgreSQL recorded byte counts and SHA-256 hashes, snapshot ZIPs passed checks, and each artifact had matching source-event reference(s). One Task 1 snapshot had 2 source-event references (consistent with content-addressed reuse). This verifies *stored evidence integrity*, not that every intermediate edit was observed. **Remaining 2D.4 checkpoints:** investigate Task 1/2 missing `started_at` fields without inventing timestamps; reconcile structured CLI records with terminal transcripts; test incomplete/crashing fuzzing campaigns and collector restarts; confirm task-boundary isolation in another fresh participant flow. Existing UI title bars restored; xterm resize scrollback issue still open.

**Task start timestamp investigation (2026-11-02):** The user's SELECT-only diagnostic found the session's stored `started_at=2026-10-30 22:03:54 UTC`, but `task_runs.started_at=NULL` for both tasks. Task 1 was completed at `23:15:40 UTC`. Task 2 became `ready` with a trusted `task_released` event at exactly that transition (`23:15:40 UTC`), and its first received CLI event is `23:18:51 UTC`. Task 1's first received browser activity was `22:14:32 UTC`, CLI activity `23:08:58 UTC`. Received event times are **not** proof of first participant engagement and must not be used as retroactive task starts. The existing `redeem_pilot1_invitation` and host test-session issuance set **session** start during authentication; the required HowTo `Start Study` POST is a more meaningful start boundary for Task 1. Lifecycle code released Task 2 but did not populate task `started_at`.

**Prospective fix staged, not deployed:** `db/migrations/011_pilot1_task_start_timestamps.sql` adds event-driven triggers for future Pilot 1 sessions only: Task 1 gets `started_at` when the authenticated participant submits the mandatory HowTo `Start Study` acknowledgment, with a `task_started` event; Task 2 gets `started_at` on the trusted `locked → ready` release transition. In both cases this denotes opening of the participant-accessible task window, **not** the first CLI command or precisely measured active work time. No existing rows are backfilled. `scripts/r2d4_task_timeline_check.py` now also reports the existing Intro and HowTo acknowledgment timestamps to assess current-session evidence. Validate the migration in a disposable session before applying to a live database; the currently active Task 2 and all historical evidence must remain unchanged.

**Explicit study-start timing confirmed (2026-11-02):** The live read-only timeline check shows `study_sessions.assigned_at=2026-10-30 22:01:03.130836+00`, `study_sessions.started_at=22:03:54.042247+00`, `intro_acknowledged_at=22:06:59.302820+00`, and **`howto_acknowledged_at=22:07:09.343551+00`**. This last event is the explicit HowTo **Start Study** acknowledgment and is the defensible Task 1 available-work-window start. Task 1 was completed at `23:15:40.099071+00`, so the elapsed Task 1 window was **68m30.755520s**; this includes any inactivity, breaks, or pilot troubleshooting, and is not an observed active-work duration. Task 2's server-authored `task_released` event occurred at `23:15:40.099071+00` (same instant as Task 1 completion) and its first CLI ingestion is `23:18:51.985175+00`. Both `task_runs.started_at` columns remain NULL as originally recorded. **Do not backfill or rewrite the live task rows.** The prospective migration 011 maps these two distinct, trusted triggers to task-level timestamps for newly progressing sessions only and still requires isolated test acceptance. Current session is longer than the intended ≤1h participant experience, but this exploratory extended pilot is not a representative duration sample.

**Next check staged (2026-11-02):** `scripts/r2d4_cli_archive_audit.py` compares the existing participant's PostgreSQL `bash_command_completed` events against archived complete `.commands.jsonl` rows using the deterministic `cli:<tag>:<line>` event keys, per-line SHA256 hashes, sequence and exit metadata. It counts absent/pending DB rows, lost archived rows, missing `.out` and `.timing` transcript files, and incomplete trailing JSONL lines across both tasks. The script is read-only and intentionally does **not** print command text, terminal output, user identifiers, or file hashes. File presence and matching structured records **do not** demonstrate capture of all shell subprocesses or a content-level transcript echo correspondence. Await live operator output; keep source artifacts and active Task 2 unchanged.

**CLI command/archive first audit (2026-11-02):** The user's read-only comparison reported Task 1 **22 DB commands / 22 archived / all 22 matching**, one terminal session and no missing output, timing, incomplete JSONL, or mismatched metadata. Task 2 reported **45 DB commands / 67 archived / 45 matching**, six terminal sessions, and **22 archive-only rows**, again with no missing output/timing, hash mismatch, or incomplete rows. The 22 excess rows equal the Task 1 count. The original diagnostic scanned all archived files regardless of the host importer's authoritative Task 2 `task_released` start-tag floor. This is **likely deliberate preservation of Task 1 terminal archives in Task 2's raw shared-recording copy**, not confirmed data loss. Updated `scripts/r2d4_cli_archive_audit.py` now applies the exact same task-release tag boundary as `pilot1_auto_ingest.py`, counts pre-release copies separately, and verifies each against Task 1's stored event key and source-line SHA256. **Await user rerun before accepting the gate**. Do not import, delete, or backfill the 22 rows into Task 2 or restart collectors based solely on the initial audit.

**CLI command archive and task-boundary reconciliation accepted (2026-11-02):** User reran `scripts/r2d4_cli_archive_audit.py`. Task 1: 22/22 structured completed Bash commands matched their archive source-key and SHA256/metadata. Task 2: 45/45 eligible commands matched. Its raw archive contains 67 complete records, including 22 pre-release copies of Task 1 commands; all 22 matched Task 1's DB event keys/source-line SHA256 and were correctly excluded by the trusted Task 2 release-tag floor. **Zero** eligible commands were missing from DB, zero DB commands were absent from eligible archives, zero excluded commands were imported into Task 2, zero metadata/hash mismatches, zero missing `.out` or `.timing` files across seven task-specific terminal sessions (one in Task 1, six in Task 2), and zero incomplete trailing JSONL lines. Script reported `PASS`. This confirms archive-to-DB *structured completed command* completeness and task separation at audit time, but is not a proof of complete capture of shell subprocesses, abandoned commands, or every keystroke. No records or terminal processes were changed. Remaining Release 2D.4: live xterm display scrollback/reflow regression during splitter resizing, interrupted/crashing campaign validation, collector failure/restart and session transition testing, prospective timing migration isolated-session acceptance. Do not conflate read-only archive PASS with closure of these items.

**Gate:** Reconstruct a two-task session from exported records, verify no cross-task contamination and preserve raw and derived evidence.

## Release 3 — Supported LLM responses

- Add bounded response capture to supported internal AI services only where stable and within study consent.
- Match prompts ↔ responses and task run; handle streaming/edits, missing data, dedupe, truncation and failures explicitly.
- Test internal Firefox extension packaging/policy, recording/ingestion and retention/access controls.
- Do not treat Google Search AI Overviews/AI Mode as a required new response-capture target; Google Search is controlled separately in 2D.3.

**Gate:** End-to-end demonstrated support for selected AI tools, with documented unsupported states.

## Pilot 1 closeout — local only

Test both randomized task orders and each finish/skip outcome, complete task transitions, interrupted campaigns, source edits, resumed sessions, service restarts, clipboard isolation, browser/AI observations, and full finalization/archiving. Validate one-hour participant experience. Conduct advisor/lab-mate tests through protected local access if needed. Freeze the accepted build and record defects/waivers.

**Gate:** A fresh local tester completes the full study without operator intervention under normal conditions; accepted data can be reconstructed; rollback and backup are documented.

## Pilot 2 — NSF ACCESS

Provision resources only after Pilot 1; verify container runtime/site policy/network restrictions independently from the previous NERDs server. Integrate QuestionPro consent and exit survey; verified handoff/invitation; mandatory Intro then revisitable `howTo.php` guide; randomized task order; participant/session identity, completion routing, cleanup, capacity, persistence and secure data retention. QuestionPro stores consent/survey responses; NERDs stores task and behavior telemetry.

**Gate:** External dry run passes the entire consent → onboarding → two tasks → completion → exit survey flow without operator repair.

## Final study

Proceed only with required institutional approval, approved data/retention disclosures, deployment monitoring, recruitment/payment procedures, tested backups, export pipeline and analysis plan.

## Working practices

- Keep prior Release 2C baseline `8d25dfb` and its known-good local test environment available for rollback. New implementation work belongs on this Release 2D branch or focused branches.
- For each checkpoint: scope → source tests → isolated deployment → real local UI/data acceptance → evidence/limitations → commit/push. Do not apply to a running participant instance as a substitute for isolated staging.
- Do not commit runtime secrets, participant recordings, credential-bearing logs, database dumps, or local activation backups.
- Update this tracker at each checkpoint with actual status, commit, tests, and unresolved blockers. Do not mark gates complete from code presence alone.
