#!/usr/bin/env python3
"""Read-only investigation of Pilot 1 task/session start timestamp gaps.

Reports authoritative database lifecycle timestamps and earliest *received*
events by task/source. First received event is an observation, NOT proof of
task start. Does not modify records or print CLI commands/URLs/prompts.
"""
import subprocess
import sys

PARTICIPANT = "nerds-pilot1-browser-r1-test"


def call(*argv, data=None):
    r = subprocess.run(argv, input=data, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=45)
    if r.returncode:
        raise RuntimeError("Command failed: " + " ".join(argv[:5])
                           + "\n" + (r.stderr or r.stdout)[-700:])
    return r.stdout.strip()


def main():
    cid = call("docker", "inspect", "-f", "{{.Id}}", PARTICIPANT)
    if len(cid) != 64 or any(c not in "0123456789abcdef" for c in cid):
        raise RuntimeError("Could not identify existing participant container")
    iid = cid[:12]
    sql = f"""
BEGIN TRANSACTION READ ONLY;
SELECT 'SESSION' AS check_type, s.status, s.order_code,
       s.assigned_at AS assigned_at_utc,
       s.started_at AS stored_started_at_utc,
       s.intro_acknowledged_at AS intro_acknowledged_utc,
       s.howto_acknowledged_at AS howto_start_study_utc,
       s.ended_at AS stored_ended_at_utc
FROM fuzz_pilot.study_sessions s
WHERE s.instance_id='{iid}';

SELECT t.position,t.task_code,t.status,
       t.started_at AS stored_started_at_utc,
       t.ended_at AS stored_ended_at_utc,
       MIN(e.received_at) AS first_received_event_utc,
       MIN(e.received_at) FILTER (WHERE e.event_source='cli')
         AS first_received_cli_utc,
       MIN(e.received_at) FILTER (WHERE e.event_source='browser')
         AS first_received_browser_utc,
       MIN(e.received_at) FILTER (WHERE e.event_type='task_released')
         AS task_release_event_utc,
       MIN(e.received_at) FILTER (WHERE e.event_type='task_completed')
         AS task_completed_event_utc,
       COUNT(e.event_id) AS total_events
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t ON t.session_id=s.session_id
LEFT JOIN fuzz_pilot.events e
  ON e.task_run_id=t.task_run_id AND e.session_id=s.session_id
WHERE s.instance_id='{iid}'
GROUP BY t.position,t.task_code,t.status,t.started_at,t.ended_at
ORDER BY t.position;
COMMIT;
"""
    print(call("docker", "exec", "-i", "-u", "postgres", "devob-db-1",
               "psql", "-X", "-P", "pager=off", "-v", "ON_ERROR_STOP=1",
               "-d", "notebook", data=sql))
    print()
    print("Read-only timeline check complete.")
    print("Important: first_received_* timestamps are ingestion observations,")
    print("NOT guaranteed participant task start times. Do not backfill automatically.")
    print("Task 1 HowTo acknowledgment is the explicit Start Study action when used.")
    print("Task 2 release is an operational boundary, not first interaction.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print("STOP:", exc, file=sys.stderr)
        sys.exit(1)
