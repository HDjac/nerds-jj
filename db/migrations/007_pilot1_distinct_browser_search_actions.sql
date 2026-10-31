-- Release 1 hardening: analysis-only search action grouping.
-- Keeps raw browser_search events unchanged and available for audit.
-- Groups repeat notifications with matching session, task, tab, search
-- engine and exact query when consecutive browser timestamps differ by <=2s.
-- A deliberate repeat of the same query within 2s may be merged; analysts
-- should use raw counts for instrumentation quality and grouped counts for
-- approximate distinct user search actions. Client timestamps are not trusted
-- server timestamps; this is an explicitly derived analytical metric.
BEGIN;

CREATE OR REPLACE VIEW fuzz_pilot.analysis_browser_search_actions AS
WITH ordered AS (
    SELECT e.session_id,
           e.task_run_id,
           e.event_id,
           e.payload->>'search_engine' AS search_engine,
           e.payload->>'search_query' AS query_text,
           e.payload->>'browser_tab_id' AS browser_tab_id,
           (e.payload->>'client_timestamp')::timestamptz AS observed_at,
           e.payload->>'navigation_type' AS navigation_type,
           LAG((e.payload->>'client_timestamp')::timestamptz)
             OVER (
               PARTITION BY e.session_id, e.task_run_id,
                            e.payload->>'search_engine',
                            e.payload->>'search_query',
                            e.payload->>'browser_tab_id'
               ORDER BY (e.payload->>'client_timestamp')::timestamptz,
                        e.event_id
             ) AS preceding_at
    FROM fuzz_pilot.events e
    WHERE e.event_source = 'browser'
      AND e.event_type = 'browser_search'
      AND e.payload->>'client_timestamp' IS NOT NULL
      AND e.payload->>'search_query' IS NOT NULL
), flagged AS (
    SELECT *,
           CASE WHEN preceding_at IS NULL
                     OR observed_at - preceding_at > interval '2 seconds'
                THEN 1 ELSE 0 END AS starts_action
    FROM ordered
), numbered AS (
    SELECT *,
           SUM(starts_action) OVER (
             PARTITION BY session_id, task_run_id, search_engine,
                          query_text, browser_tab_id
             ORDER BY observed_at, event_id
             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS action_number
    FROM flagged
)
SELECT session_id,
       task_run_id,
       search_engine,
       browser_tab_id,
       MIN(observed_at) AS first_observed_at,
       MAX(observed_at) AS last_observed_at,
       COUNT(*)::bigint AS raw_notifications,
       COUNT(*) FILTER (WHERE navigation_type = 'committed')::bigint
         AS committed_notifications,
       COUNT(*) FILTER (WHERE navigation_type = 'history_state')::bigint
         AS history_state_notifications
FROM numbered
GROUP BY session_id, task_run_id, search_engine,
         browser_tab_id, query_text, action_number;

-- An additive v2 summary: the existing v1 summary remains unchanged.
CREATE OR REPLACE VIEW fuzz_pilot.analysis_browser_task_summary_v2 AS
SELECT r.session_id, r.task_run_id,
       r.navigation_events, r.search_events,
       COALESCE(a.distinct_search_actions, 0)::bigint AS distinct_search_actions,
       r.unique_normalized_urls, r.unique_domains
FROM fuzz_pilot.analysis_browser_task_summary r
LEFT JOIN (
    SELECT session_id, task_run_id, COUNT(*)::bigint AS distinct_search_actions
    FROM fuzz_pilot.analysis_browser_search_actions
    GROUP BY session_id, task_run_id
) a ON r.session_id = a.session_id AND r.task_run_id = a.task_run_id;

COMMIT;
