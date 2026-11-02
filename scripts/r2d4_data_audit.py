#!/usr/bin/env python3
"""R2D.4 — read-only NERDs Pilot 1 integrated data audit.

Audits the *existing* local participant and both task rows without changing
task status or database contents. Outputs only aggregated counts, identifiers
needed to correlate the two tasks, and consistency warnings. It intentionally
does NOT display terminal commands, source code, prompts, URL history, search
queries or clipboard text.

Usage: cd ~/nerds-r2d && python3 scripts/r2d4_data_audit.py
"""
import subprocess
import sys

PARTICIPANT = "nerds-pilot1-browser-r1-test"
DATABASE_CONTAINER = "devob-db-1"
DATABASE = "notebook"


def call(*args, data=None):
    proc = subprocess.run(
        args, input=data, text=True, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.stdout.strip()


def main():
    container_id = call("docker", "inspect", "-f", "{{.Id}}", PARTICIPANT)
    if len(container_id) != 64 or any(c not in "0123456789abcdef"
                                      for c in container_id):
        raise RuntimeError("Could not identify current Pilot 1 participant")
    instance_id = container_id[:12]

    script = f"""
\\set ON_ERROR_STOP on
BEGIN TRANSACTION READ ONLY;

\\echo ===== SESSION_AND_TASK_STATE =====
SELECT s.status AS session_status, s.order_code, s.study_phase,
       t.position, t.task_code, t.status AS task_status,
       COALESCE(to_char(t.started_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD HH24:MI:SS'), '-') AS started_utc,
       COALESCE(to_char(t.ended_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD HH24:MI:SS'), '-') AS ended_utc
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
WHERE s.instance_id='{instance_id}'
ORDER BY t.position;

\\echo ===== ACTIVITY_BY_TASK_AND_SOURCE =====
SELECT t.position, t.task_code, e.event_source, COUNT(e.event_id) AS events,
       COUNT(DISTINCT e.event_type) AS event_types,
       COUNT(e.event_id) FILTER (WHERE e.event_key IS NULL) AS no_event_key
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
LEFT JOIN fuzz_pilot.events e ON e.task_run_id=t.task_run_id
WHERE s.instance_id='{instance_id}'
GROUP BY t.position,t.task_code,e.event_source
ORDER BY t.position,events DESC,e.event_source;

\\echo ===== SOURCE_AND_CLI_EVENT_TYPES =====
SELECT t.position, e.event_type, COUNT(*) AS total
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
JOIN fuzz_pilot.events e ON e.task_run_id=t.task_run_id
WHERE s.instance_id='{instance_id}'
  AND (e.event_source='cli'
       OR e.event_type LIKE 'source_%'
       OR e.event_type LIKE 'clipboard_%')
GROUP BY t.position,e.event_type
ORDER BY t.position, e.event_type;

\\echo ===== CAMPAIGN_STATUS_AND_HARNESS =====
SELECT t.position, t.task_code, c.harness_id, c.status,
       COUNT(c.campaign_id) AS campaigns,
       COUNT(c.campaign_id) FILTER (WHERE c.ended_at IS NULL) AS open_campaigns
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
LEFT JOIN fuzz_pilot.campaigns c ON c.task_run_id=t.task_run_id
WHERE s.instance_id='{instance_id}'
GROUP BY t.position,t.task_code,c.harness_id,c.status
ORDER BY t.position,c.harness_id,c.status;

\\echo ===== ARTIFACTS_BY_TASK_AND_KIND =====
SELECT t.position, a.artifact_kind, COUNT(a.artifact_id) AS artifacts,
       COUNT(a.artifact_id) FILTER (WHERE a.sha256 IS NULL) AS missing_checksum,
       COUNT(a.artifact_id) FILTER (WHERE a.size_bytes IS NULL) AS missing_size
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
LEFT JOIN fuzz_pilot.artifacts a ON a.task_run_id=t.task_run_id
WHERE s.instance_id='{instance_id}'
GROUP BY t.position,a.artifact_kind
ORDER BY t.position,a.artifact_kind;

\\echo ===== BROWSER_BY_TASK =====
SELECT t.position, t.task_code,
       COUNT(*) FILTER (WHERE e.event_type='browser_search') AS search_notifications,
       COUNT(*) FILTER (WHERE e.event_type='browser_navigation') AS navigation_events,
       COUNT(DISTINCT e.payload->>'page_host') AS unique_hostnames
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
LEFT JOIN fuzz_pilot.events e
  ON e.task_run_id=t.task_run_id AND e.event_source='browser'
WHERE s.instance_id='{instance_id}'
GROUP BY t.position,t.task_code
ORDER BY t.position;

\\echo ===== AI_COUNTS_BY_TASK_AND_SERVICE =====
SELECT t.position, ai.service,
       COUNT(ai.event_id) AS interactions,
       COUNT(*) FILTER (WHERE ai.response_text IS NOT NULL) AS recorded_responses
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
LEFT JOIN fuzz_pilot.events e ON e.task_run_id=t.task_run_id
LEFT JOIN fuzz_pilot.ai_interactions ai ON ai.event_id=e.event_id
WHERE s.instance_id='{instance_id}'
GROUP BY t.position,ai.service
ORDER BY t.position,ai.service;

\\echo ===== CLIPBOARD_COUNTS_AND_PRIVACY =====
SELECT t.position,
       COUNT(*) FILTER (
         WHERE e.event_type LIKE 'clipboard_%') AS clipboard_events,
       COUNT(ct.event_id) AS clipboard_text_records,
       COUNT(ct.event_id) FILTER (
         WHERE e.event_type <> 'clipboard_paste_requested'
            OR (e.payload->>'source',e.payload->>'surface') NOT IN (
              ('internal_cli','internal_cli'),
              ('internal_cli','internal_browser'),
              ('internal_browser','internal_cli'))
            OR e.payload->>'source' IN ('unknown','task_sidebar','fuzzing_guide')
            OR length(ct.text_value) NOT BETWEEN 1 AND 2048
       ) AS excluded_text_records
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
LEFT JOIN fuzz_pilot.events e ON e.task_run_id=t.task_run_id
LEFT JOIN fuzz_pilot.clipboard_text_records ct ON ct.event_id=e.event_id
WHERE s.instance_id='{instance_id}'
GROUP BY t.position
ORDER BY t.position;

\\echo ===== ATTRIBUTION_INTEGRITY =====
SELECT COUNT(*) FILTER (
         WHERE e.task_run_id IS NOT NULL AND
               (t.task_run_id IS NULL OR t.session_id <> e.session_id)
       ) AS wrong_session_or_missing_task,
       COUNT(*) FILTER (
         WHERE e.task_run_id IS NULL
       ) AS session_only_events,
       COUNT(*) FILTER (
         WHERE e.task_run_id IS NOT NULL
       ) AS task_attributed_events,
       COUNT(*) FILTER (
         WHERE e.event_key IS NULL
       ) AS events_without_dedup_key
FROM fuzz_pilot.events e
JOIN fuzz_pilot.study_sessions s ON s.session_id=e.session_id
LEFT JOIN fuzz_pilot.task_runs t ON t.task_run_id=e.task_run_id
WHERE s.instance_id='{instance_id}';

\\echo ===== SOURCE_SNAPSHOT_REFERENCES =====
SELECT t.position,
       COUNT(*) FILTER (WHERE a.artifact_kind='source_snapshot') AS source_snapshots,
       COUNT(*) FILTER (WHERE a.artifact_kind='source_diff') AS source_diffs,
       COUNT(*) FILTER (WHERE a.artifact_kind='source_snapshot'
                      AND a.sha256 IS NOT NULL) AS checksummed_snapshots
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
LEFT JOIN fuzz_pilot.artifacts a ON a.task_run_id=t.task_run_id
WHERE s.instance_id='{instance_id}'
GROUP BY t.position
ORDER BY t.position;
COMMIT;
"""
    output = call(
        "docker", "exec", "-i", "-u", "postgres", DATABASE_CONTAINER,
        "psql", "-X", "-P", "pager=off", "-v", "ON_ERROR_STOP=1",
        "-d", DATABASE, data=script)
    print(output)
    print()
    print("READ-ONLY AUDIT FINISHED: Counts and integrity indicators only.")
    print("Interpret missing data alongside task lifecycle and ingestion status.")
    print("Zero 'wrong_session_or_missing_task' and 'excluded_text_records'")
    print("are expected. This does not prove artifact ZIP files still exist;")
    print("archive hashes and individual campaign transcripts are a later check.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError, OSError) as exc:
        print("STOP:", getattr(exc, "stderr", None) or str(exc),
              file=sys.stderr)
        raise SystemExit(1)
