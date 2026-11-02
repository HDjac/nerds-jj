# Release 2C — scoped internal clipboard text capture

Source base: NERDs Pilot 1 `feature/cli-fuzzing-pilot` commit
`8f5d9e6f6d24010f0b4058942f575ebcea599b89`.

## Approved scope to implement and validate

Capture *candidate text associated with a paste request* in three directions:

1. `internal_cli` → `internal_cli`, keyboard method `shift_insert`.
2. `internal_browser` → `internal_cli`, keyboard method `shift_insert`.
3. `internal_cli` → `internal_browser`, keyboard method `ctrl_shortcut` or `meta_shortcut`.

Do not capture task-sidebar or fuzzing-guide content in clipboard-text records,
Firefox → Firefox, unknown sources, or any host OS clipboard content.
Preserve the already-validated host↔NERDs clipboard isolation and metadata
tracking. Other paste mechanisms, such as X11 middle-click, may not trigger
text telemetry; they must not be counted as captured insertions.

## Recording semantics

The current frontend creates a `paste_requested` event with a candidate
clipboard value only if it has a recent, matching noVNC observation. This is
**NOT proof that xterm or Firefox actually inserted the text**. Describe these
values as "text associated with a paste request", never as verified final
editor/terminal content. CLI commands that are actually run are recorded by
other task logging; task-description copying is excluded from this text feature.

## Existing safeguards to keep

- Explicit frontend build flag `REACT_APP_NERDS_CLIPBOARD_TEXT=1` and independent
  runtime flags `PILOT1_CLIPBOARD_TEXT_ENABLED=1` at the participant API and
  canary Submit service; all remain OFF until the test/approval gate.
- Text only for the three directions, with method and kind validation at both
  API and Submit. Reject host/unknown and sidebar/guide content.
- 2,048-character ceiling, current event-time task attribution, deduplication,
  restricted DB access, and no request-content logging.
- Keep the existing best-effort API redaction; do not describe it as complete
  protection or as a substitute for instructions and consent.
- Participant-facing notice in the Copy/Paste Guide, and matching study consent
  / IRB language (as required by the approved protocol) before live collection.

## Activation sequence (not automated by this package)

1. Verify source-level Python and JS synthetic tests.
2. Review notice and consent language with study leadership and confirm that
   collecting clipboard text falls within institutional approvals.
3. Use an isolated participant and canary with synthetic non-sensitive data;
   verify all three allowed directions and all excluded directions, database
   records, event/task attribution, duplicate suppression, and access controls.
4. Only after the above passes, decide whether to activate flags for consented
   Pilot 1 participants. Rebuild frontend with `REACT_APP_NERDS_CLIPBOARD_TEXT=1`
   as a separate stage; enabling a backend flag alone cannot enable the build.
5. Obtain and document a deletion/retention process for the restricted text table.

This package never flips a capture flag, deploys a container, changes the DB,
or updates participant invitations. All tests use synthetic values.
