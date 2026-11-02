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
| ADV-05 | Explain all three harnesses, corpus, and target program purpose without revealing vulnerabilities | PARTIAL | 2D.1 | Neutral, complete task-specific instructions approved by advisor |
| ADV-06 | Anonymous Task 1 / Task 2 in participant interface | OPEN | 2D.1 | No Dense/Low-Yield labels shown; true task codes preserved server-side |
| ADV-07 | Browser search terms and visited URL observations | PARTIAL | 2D.3 / 2D.4 | Normal searches, navigation, task transitions, recovery and DB attribution verified |
| ADV-08 | Avoid Google Search AI summaries/AI Mode as a default or uncollected chat surface | OPEN | 2D.3 | Web-only results by default; AI Mode entry routes blocked or safely handled and tested |
| ADV-09 | Capture AI responses in addition to supported prompts | DEFERRED | Release 3 | Captured responses correctly associated with prompts/tasks; failures detectable |
| UX-01 | Show CLI and Firefox simultaneously in resizable right workspace; sidebar left | OPEN | 2D.2 | Draggable split, focus, sizing, persistent tasks, maximize options and accessibility tested |
| DATA-01 | Joint audit of commands, fuzzing campaigns, source versions, AI/browser and clipboard activity | OPEN | 2D.4 | Reconstruct both tasks with unambiguous IDs, timestamps, outputs, artifacts, and outcome |

## 2D.1 — Participant experience

- Replace participant-facing `dense_v2` / `lowyield_v1` with **Task 1** / **Task 2**, including task headings and instructions. Keep internal stable `task_code` and task-run IDs unchanged.
- Explain what the assigned target program does at a high level, without describing vulnerability locations or directing participants to solutions.
- Explain `fuzz_a`, `fuzz_b`, `fuzz_c`, the purpose and reuse of seed corpora, compilation, basic run/stop/continue workflow, and how to read typical fuzzer output.
- Check sidebar, guide, CLI command font sizes at the actual 1280x720 participant resolution and larger sizes.
- Do not alter randomized order, archived work, or task decision semantics.

**Gate:** A new tester can start the appropriate task without outside coaching; neither hidden condition is disclosed.

## 2D.2 — Resizable split workspace

- Preserve left task sidebar; replace exclusive CLI/BROWSER switching with **simultaneously visible xterm and Firefox** in the right workspace.
- Prefer a **single existing X11 desktop/noVNC connection** with side-by-side X11 windows and a React-controlled splitter. Do not create independent sessions that silently separate clipboard or activity contexts.
- Support draggable resizing, reasonable min sizes, and CLI-only/Browser-only focus modes without terminating either app.
- Ensure task transition creates/displays the new task's CLI without a stale window, and retains a valid split arrangement.
- Replace tab-based clipboard destination inference with the **actual focused remote X11 application/window** and correctly handle focus changes, copy/cut/paste shortcuts, and ambiguous interactions.
- Verify noVNC resize behavior, terminal selection, internal Firefox, clipboard restrictions, and collection while both panes are visible.

**Gate:** Continuous CLI + Firefox usability, reproducible task transitions, correct source/destination metadata, host clipboard isolation.

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

**Gate:** At minimum: address-bar search, Google home/search-box search, Google results navigation, direct AI Mode route, AI Mode controls, history/reload, and extension-disabled failure/recovery paths tested. No ordinary search unexpectedly drops the user's query or silently bypasses the collector.

### Other 2D.3 checks

- Verify browser search/URL events, queued retries and duplicate prevention, task binding, and service differences.
- Retest the three approved clipboard-text directions and exclusions after focus-aware split-view changes.
- Maintain wording: clipboard text associated with a **paste request**, not proof the destination inserted it.

## 2D.4 — Integrated data audit

- Cross-check participant/session/task-run IDs and actual timestamps through both task orders.
- CLI commands + transcripts, harness selection, campaign start/end/interruption, error/crash artifacts and outcome classification.
- Baseline/source-change snapshots, patches, completeness, archive integrity and references.
- Browser navigation/query observations, supported AI prompts, clipboard events and scoped text with exclusion audits.
- Reconcile collector restart, transient failure, late/duplicate events and task transition boundaries.
- Document known blind spots and classification confidence; do not conflate inferred data with observed behavior.

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
