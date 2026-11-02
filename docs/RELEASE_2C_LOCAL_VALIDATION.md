# Release 2C — Local Deployment and Validation

## Deployment

Source preparation commit: 56e0cfd

Environment: Local NERDs Pilot 1 testing
Participant container: nerds-pilot1-browser-r1-test
Submit container: nerds-pilot1-submit-r2b2-canary
Active task: dense_v2

Frontend: main.bddf8ef9.js

Enabled configuration:
- Frontend clipboard ingestion: 1
- Frontend clipboard text: 1
- Participant API clipboard ingestion: 1
- Participant API clipboard text: 1
- Submit clipboard ingestion: 1
- Submit clipboard text: 1

## End-to-end validation

Exact-text matches:
- Event 3171: internal_cli -> internal_cli
- Event 3275: internal_cli -> internal_browser
- Event 3337: internal_browser -> internal_cli

Database regression:
- Total clipboard-text records: 5
- Excluded-source text records: 0

All three successful transfers were attributed to dense_v2.

## Interpretation

Events represent clipboard text associated with a
paste request, not independently confirmed insertion.

Earlier tests recorded mismatched clipboard selections.
These observations are retained and should be considered
when interpreting participant activity.

## Deployment observations

After replacing the React build, the running noVNC service
continued serving an older frontend bundle.

Restarting only the noVNC service corrected the issue.
The updated Copy/Paste Guide was then verified.

## Rollback

Use the original scripts and activation state under
~/nerds-r2c-activation.

Rollback participant first:

python3 ~/nerds-r2c-activation/nerds_r2c_participant_activate.py rollback

Then rollback Submit if necessary:

python3 ~/nerds-r2c-activation/nerds_r2c_submit_canary.py rollback

The deployment scripts are snapshots of this particular
local environment. They contain pinned image IDs, container
names, and source assumptions and should not be reused
blindly for future deployments.

Do not commit runtime secrets, PostgreSQL dumps,
participant recordings, or local activation backups.

## Status

Release 2C local text-capture integration validated.
