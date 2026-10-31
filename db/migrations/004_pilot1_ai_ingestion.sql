BEGIN;

CREATE OR REPLACE FUNCTION fuzz_pilot.ingest_ai_prompt(
    p_instance text,
    p_data jsonb
)
RETURNS TABLE(stored_event_id bigint, was_inserted boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    v_session uuid;
    v_task uuid;
    v_event bigint;
    v_key text;
    v_old record;
BEGIN
    v_key := p_data->>'event_key';

    IF p_instance IS NULL
       OR p_instance !~ '^[a-f0-9]{12}$'
       OR v_key IS NULL
       OR v_key !~
          '^ai:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    THEN
        RAISE EXCEPTION 'Invalid AI observation identity';
    END IF;

    IF COALESCE(length(p_data->>'prompt_text'), 0)
          NOT BETWEEN 1 AND 100000
       OR COALESCE(length(p_data->>'model'), 0)
          NOT BETWEEN 1 AND 200
       OR p_data->>'capture_method'
          IS DISTINCT FROM 'firefox_extension_prompt'
    THEN
        RAISE EXCEPTION 'Invalid AI observation content';
    END IF;

    IF NOT (
        (p_data->>'service' = 'chatgpt'
         AND (p_data->>'page_host' = 'chatgpt.com'
              OR p_data->>'page_host' LIKE '%.openai.com'))
        OR
        (p_data->>'service' = 'claude'
         AND p_data->>'page_host' = 'claude.ai')
        OR
        (p_data->>'service' = 'gemini'
         AND p_data->>'page_host' = 'gemini.google.com')
    ) THEN
        RAISE EXCEPTION 'Invalid AI service or host';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(p_instance || ':' || v_key, 0)
    );

    SELECT s.session_id INTO v_session
    FROM fuzz_pilot.study_sessions s
    JOIN fuzz_pilot.participants p
      ON p.participant_id = s.participant_id
    WHERE s.instance_id = p_instance
      AND s.status = 'active'
      AND p.withdrawn_at IS NULL
    FOR SHARE OF s, p;

    IF v_session IS NULL THEN
        RAISE EXCEPTION 'No eligible study session';
    END IF;

    SELECT e.event_id, e.event_type, e.event_source,
           a.service, a.model, a.prompt_text,
           a.page_host, a.capture_method,
           e.payload->>'client_timestamp' AS client_timestamp
      INTO v_old
    FROM fuzz_pilot.events e
    LEFT JOIN fuzz_pilot.ai_interactions a
      ON a.event_id = e.event_id
    WHERE e.session_id = v_session
      AND e.event_key = v_key;

    IF FOUND THEN
        IF ROW(v_old.event_type, v_old.event_source,
               v_old.service, v_old.model, v_old.prompt_text,
               v_old.page_host, v_old.capture_method,
               v_old.client_timestamp)
           IS DISTINCT FROM
           ROW('ai_interaction', 'prompt_logger',
               p_data->>'service', p_data->>'model',
               p_data->>'prompt_text', p_data->>'page_host',
               p_data->>'capture_method',
               p_data->>'client_timestamp')
        THEN
            RAISE EXCEPTION 'Conflicting interaction UUID';
        END IF;

        RETURN QUERY SELECT v_old.event_id, false;
        RETURN;
    END IF;

    SELECT t.task_run_id INTO v_task
    FROM fuzz_pilot.task_runs t
    WHERE t.session_id = v_session
      AND t.status IN ('ready', 'active')
    FOR SHARE OF t;

    IF v_task IS NULL THEN
        RAISE EXCEPTION 'No released task';
    END IF;

    INSERT INTO fuzz_pilot.events (
        session_id, task_run_id, event_type,
        event_source, event_key, payload
    )
    VALUES (
        v_session, v_task, 'ai_interaction',
        'prompt_logger', v_key,
        jsonb_build_object(
            'interaction_id', substring(v_key FROM 4),
            'client_timestamp', p_data->>'client_timestamp',
            'capture_method', 'firefox_extension_prompt',
            'provenance', 'browser_reported'
        )
    )
    ON CONFLICT (session_id, event_key) DO NOTHING
    RETURNING event_id INTO v_event;

    IF v_event IS NULL THEN
        RAISE EXCEPTION 'Concurrent AI observation conflict';
    END IF;

    INSERT INTO fuzz_pilot.ai_interactions (
        event_id, service, model, prompt_text,
        page_host, capture_method
    )
    VALUES (
        v_event,
        p_data->>'service',
        p_data->>'model',
        p_data->>'prompt_text',
        p_data->>'page_host',
        'firefox_extension_prompt'
    );

    RETURN QUERY SELECT v_event, true;
END;
$function$;

REVOKE ALL ON FUNCTION
    fuzz_pilot.ingest_ai_prompt(text, jsonb)
    FROM PUBLIC;

GRANT USAGE ON SCHEMA fuzz_pilot
    TO pilot1_ai_ingest;

GRANT EXECUTE ON FUNCTION
    fuzz_pilot.ingest_ai_prompt(text, jsonb)
    TO pilot1_ai_ingest;

COMMIT;
