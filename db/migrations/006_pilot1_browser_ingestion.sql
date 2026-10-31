-- Pilot 1: task-attributed, minimized browser navigation and search observations.
-- ADDITIVE. Apply with psql -X -v ON_ERROR_STOP=1 -f ... after review.
-- Requires v001 activity schema and the restricted pilot1_ai_ingest role from v004.
-- The trusted gateway resolves the instance from the actual Docker peer IP.
BEGIN;
CREATE OR REPLACE FUNCTION fuzz_pilot.ingest_browser_event(
    p_instance text, p_data jsonb
)
RETURNS TABLE(stored_event_id bigint, was_inserted boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
    v_session uuid;
    v_task uuid;
    v_event bigint;
    v_key text;
    v_old record;
    v_type text;
    v_kind text;
    v_host text;
    v_url text;
BEGIN
    IF p_data IS NULL OR jsonb_typeof(p_data) <> 'object' THEN
        RAISE EXCEPTION 'Invalid browser observation';
    END IF;
    v_key := p_data->>'event_key';
    v_kind := p_data->>'event_kind';
    v_host := p_data->>'page_host';
    v_url := p_data->>'url';
    v_type := CASE v_kind WHEN 'search' THEN 'browser_search'
                          WHEN 'navigation' THEN 'browser_navigation'
                          ELSE NULL END;
    IF p_instance IS NULL OR p_instance !~ '^[0-9a-f]{12}$'
       OR v_key IS NULL OR v_key !~
           '^br:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
       OR v_type IS NULL
       OR COALESCE(length(v_url), 0) NOT BETWEEN 8 AND 2048
       OR v_url !~ '^https?://'
       OR v_url ~ '[?#]'
       OR split_part(v_url, '/', 3) ~ '@'
       OR v_host !~ '^[a-z0-9][a-z0-9.-]{0,251}[a-z0-9]$'
       OR v_host IN ('localhost', 'metadata.google.internal')
       OR v_host ~ '(\.local|\.internal|\.localhost|\.test)$'
       OR split_part(split_part(v_url, '/', 3), ':', 1) <> v_host
       OR v_host ~ '^(127\.|10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)'
       OR COALESCE(length(v_host), 0) NOT BETWEEN 1 AND 253
       OR (p_data->>'expected_task_run_id') IS NULL
       OR (p_data->>'expected_task_run_id') !~
           '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       OR p_data->>'navigation_type' IS NULL
       OR p_data->>'navigation_type' NOT IN ('committed', 'history_state')
       OR COALESCE(length(p_data->>'transition_type'),0) NOT BETWEEN 1 AND 40
       OR COALESCE(length(p_data->>'client_timestamp'),0) NOT BETWEEN 15 AND 40
       OR (p_data->>'browser_tab_id') IS NULL
       OR (p_data->>'browser_tab_id') !~ '^(-1|[0-9]{1,10})$'
       OR (v_kind = 'search' AND (
           p_data->>'search_engine' IS NULL OR
           p_data->>'search_engine' NOT IN ('google','bing','duckduckgo') OR
           COALESCE(length(p_data->>'search_query'),0) NOT BETWEEN 1 AND 1200))
       OR (v_kind = 'navigation' AND (
           p_data->>'search_engine' IS NOT NULL OR
           p_data->>'search_query' IS NOT NULL))
    THEN
        RAISE EXCEPTION 'Invalid browser observation';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(p_instance || ':' || v_key, 0));
    SELECT s.session_id INTO v_session
    FROM fuzz_pilot.study_sessions s
    JOIN fuzz_pilot.participants p ON p.participant_id = s.participant_id
    WHERE s.instance_id = p_instance AND s.status = 'active'
      AND p.withdrawn_at IS NULL
    FOR SHARE OF s, p;
    IF v_session IS NULL THEN
        RAISE EXCEPTION 'No eligible study session';
    END IF;
    -- Do not use a browser-provided task ID for attribution. Accept only if
    -- it matches this instance's currently released task in PostgreSQL.
    SELECT t.task_run_id INTO v_task
    FROM fuzz_pilot.task_runs t
    WHERE t.session_id = v_session AND t.status IN ('ready','active')
    FOR SHARE OF t;
    IF v_task IS NULL OR v_task::text <> p_data->>'expected_task_run_id' THEN
        RAISE EXCEPTION 'Stale task browser observation';
    END IF;
    SELECT e.event_id, e.event_type, e.event_source, e.payload
      INTO v_old
    FROM fuzz_pilot.events e
    WHERE e.session_id = v_session AND e.event_key = v_key;
    IF FOUND THEN
        IF v_old.event_type <> v_type OR v_old.event_source <> 'browser'
           OR v_old.payload IS DISTINCT FROM (p_data - 'expected_task_run_id') THEN
            RAISE EXCEPTION 'Conflicting browser event UUID';
        END IF;
        RETURN QUERY SELECT v_old.event_id, false;
        RETURN;
    END IF;
    INSERT INTO fuzz_pilot.events (
        session_id,task_run_id,event_type,event_source,event_key,payload
    ) VALUES (
        v_session,v_task,v_type,'browser',v_key,
        p_data - 'expected_task_run_id'
    ) RETURNING event_id INTO v_event;
    RETURN QUERY SELECT v_event, true;
END;
$fn$;
REVOKE ALL ON FUNCTION fuzz_pilot.ingest_browser_event(text,jsonb) FROM PUBLIC;
-- Restricted role already exists for pilot study ingestion. This grants
-- execution of one security-definer routine, not direct table write access.
GRANT EXECUTE ON FUNCTION fuzz_pilot.ingest_browser_event(text,jsonb) TO pilot1_ai_ingest;

-- Count *normalized* URLs per task, not raw browser URLs or network requests.
CREATE OR REPLACE VIEW fuzz_pilot.analysis_browser_task_summary AS
SELECT e.session_id, e.task_run_id,
       COUNT(*) FILTER (WHERE e.event_type='browser_navigation') AS navigation_events,
       COUNT(*) FILTER (WHERE e.event_type='browser_search') AS search_events,
       COUNT(DISTINCT e.payload->>'url') AS unique_normalized_urls,
       COUNT(DISTINCT e.payload->>'page_host') AS unique_domains
FROM fuzz_pilot.events e
WHERE e.event_source='browser'
GROUP BY e.session_id,e.task_run_id;
COMMIT;
