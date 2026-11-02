#!/usr/bin/env python3
"""Read-only acceptance check: Google Web search and navigation task attribution.

In the INTERNAL Firefox of the existing local NERDs pilot participant:
  1. Search for nerds-r2d3-address using the Firefox address bar.
  2. Search for nerds-r2d3-form using Google's homepage search field.
  3. Visit https://example.com/ directly and wait for it to load.
Then run this script in WSL.

This script only SELECTs the database, has no migration, and shows no
unrelated searches, visited websites, prompt content or clipboard text.
"""
import subprocess
import sys

PARTICIPANT = "nerds-pilot1-browser-r1-test"
POSTGRES = "devob-db-1"
DB_NAME = "notebook"

def execute(argv, data=None):
    return subprocess.run(argv, input=data, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=True).stdout

def main():
    cid = execute(["docker", "inspect", "-f", "{{.Id}}", PARTICIPANT]).strip()
    if len(cid) != 64 or any(c not in "0123456789abcdef" for c in cid):
        raise RuntimeError("Cannot identify the existing pilot participant instance")
    iid = cid[:12]

    sql = f"""
BEGIN READ ONLY;
SELECT 'INSTANCE' AS check_type, s.status AS session_status,
       t.position::text AS task_position, t.task_code,
       t.status AS task_status
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t ON t.session_id = s.session_id
WHERE s.instance_id = '{iid}' AND s.status = 'active'
  AND t.status IN ('ready','active');

SELECT 'TEST_EVENT' AS check_type,
       CASE
         WHEN e.event_type='browser_search'
          AND e.payload->>'search_query' = 'nerds-r2d3-address'
             THEN 'address-bar-search'
         WHEN e.event_type='browser_search'
          AND e.payload->>'search_query' = 'nerds-r2d3-form'
             THEN 'google-form-search'
         WHEN e.event_type='browser_navigation'
          AND e.payload->>'page_host' IN ('example.com','www.example.com')
             THEN 'example-navigation'
         ELSE 'unmatched'
       END AS test,
       e.event_id,
       t.position AS task_position,
       t.task_code,
       e.event_type,
       e.payload->>'page_host' AS page_host,
       e.payload->>'search_engine' AS search_engine,
       e.received_at
FROM fuzz_pilot.events e
JOIN fuzz_pilot.task_runs t ON t.task_run_id=e.task_run_id
JOIN fuzz_pilot.study_sessions s ON s.session_id=e.session_id
WHERE s.instance_id='{iid}' AND s.status='active'
  AND e.event_source='browser'
  AND e.received_at >= now() - interval '2 hours'
  AND (
       (e.event_type='browser_search'
          AND e.payload->>'search_query'
              IN ('nerds-r2d3-address','nerds-r2d3-form'))
       OR
       (e.event_type='browser_navigation'
          AND e.payload->>'page_host' IN ('example.com','www.example.com'))
  )
ORDER BY e.event_id DESC
LIMIT 25;

SELECT 'TEST_COUNTS' AS check_type,
       COUNT(*) FILTER (
          WHERE e.event_type='browser_search'
          AND e.payload->>'search_query'='nerds-r2d3-address'
       ) AS address_search_events,
       COUNT(*) FILTER (
          WHERE e.event_type='browser_search'
          AND e.payload->>'search_query'='nerds-r2d3-form'
       ) AS form_search_events,
       COUNT(*) FILTER (
          WHERE e.event_type='browser_navigation'
          AND e.payload->>'page_host'='example.com'
       ) AS example_navigation_events,
       COUNT(*) FILTER (
          WHERE e.task_run_id <> t.task_run_id
       ) AS wrong_task_events
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t
 ON t.session_id=s.session_id AND t.status IN ('ready','active')
LEFT JOIN fuzz_pilot.events e
 ON e.session_id=s.session_id
  AND e.event_source='browser'
  AND e.received_at >= now() - interval '2 hours'
  AND (
    (e.event_type='browser_search'
       AND e.payload->>'search_query' IN ('nerds-r2d3-address','nerds-r2d3-form'))
    OR (e.event_type='browser_navigation'
       AND e.payload->>'page_host'='example.com')
  )
WHERE s.instance_id='{iid}' AND s.status='active'
GROUP BY s.session_id;

-- Aggregate-only health check; do not reveal any unrelated domains or queries.
SELECT 'BROWSER_HEALTH' AS check_type,
       COUNT(*) FILTER (WHERE e.event_type='browser_navigation') AS all_navigation_events,
       COUNT(*) FILTER (WHERE e.event_type='browser_search') AS all_search_events,
       MAX(e.received_at) FILTER (WHERE e.event_type='browser_navigation') AS latest_navigation_at
FROM fuzz_pilot.study_sessions s
JOIN fuzz_pilot.task_runs t
  ON t.session_id=s.session_id AND t.status IN ('ready','active')
LEFT JOIN fuzz_pilot.events e
  ON e.session_id=s.session_id AND e.task_run_id=t.task_run_id
 AND e.event_source='browser'
 AND e.received_at >= now() - interval '2 hours'
WHERE s.instance_id='{iid}' AND s.status='active'
GROUP BY s.session_id;
COMMIT;
"""
    # Using PostgreSQL's local superuser exclusively for read-only SELECTs.
    output = execute(
        ["docker", "exec", "-i", "-u", "postgres", POSTGRES,
         "psql", "-X", "-v", "ON_ERROR_STOP=1", "-P", "pager=off",
         "-d", DB_NAME], data=sql
    )
    print(output)
    print("Acceptance: both named searches and example-navigation should be")
    print("present on the active task; wrong_task_events should equal zero.")
    print("BROWSER_HEALTH counts unrelated navigations without printing their URLs.")
    print("If both searches are present but example-navigation is absent:")
    print("- all_navigation_events > 0: navigation collection works elsewhere;")
    print("  this example.com visit may not have committed or may have been redirected.")
    print("- all_navigation_events = 0: investigate why non-search page loads")
    print("  are not producing browser_navigation observations.")

if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError, OSError) as exc:
        print("STOP:", getattr(exc, "stderr", None) or str(exc),
              file=sys.stderr)
        raise SystemExit(1)
