-- Release 2B.2: clipboard event metadata plus restricted optional pasted text.
-- Requires migrations 001-007, `pilot1_ai_ingest` role. Does not enable ingestion.
BEGIN;
CREATE TABLE IF NOT EXISTS fuzz_pilot.clipboard_text_records (
    event_id bigint PRIMARY KEY REFERENCES fuzz_pilot.events(event_id) ON DELETE CASCADE,
    text_value text NOT NULL CHECK(length(text_value) BETWEEN 1 AND 2048),
    inserted_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON fuzz_pilot.clipboard_text_records FROM PUBLIC;
REVOKE ALL ON fuzz_pilot.clipboard_text_records FROM pilot1_ai_ingest;

CREATE OR REPLACE FUNCTION fuzz_pilot.ingest_clipboard_event(p_instance text, p_data jsonb)
RETURNS TABLE(stored_event_id bigint, was_inserted boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
  v_session uuid;
  v_task uuid;
  v_event bigint;
  v_existing record;
  v_key text := p_data->>'event_key';
  v_kind text := p_data->>'kind';
  v_source text := p_data->>'source';
  v_surface text := p_data->>'surface';
  v_method text := p_data->>'method';
  v_text text := p_data->>'text';
  v_metadata jsonb;
BEGIN
  IF p_instance IS NULL OR p_instance !~ '^[0-9a-f]{12}$'
     OR p_data IS NULL OR jsonb_typeof(p_data) <> 'object'
     OR v_key IS NULL OR v_key !~ '^cb:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
     OR v_kind IS NULL OR v_kind NOT IN ('copy_committed','copy_requested','clipboard_observed','paste_requested','external_paste_blocked')
     OR v_surface IS NULL OR v_surface NOT IN ('task_sidebar','fuzzing_guide','internal_cli','internal_browser','other_internal')
     OR v_source IS NULL OR v_source NOT IN ('task_sidebar','fuzzing_guide','internal_cli','internal_browser','other_internal','unknown')
     OR v_method IS NULL OR v_method NOT IN ('copy_button','sidebar_keyboard','vnc_clipboard','ctrl_shortcut','meta_shortcut','shift_insert','other_internal')
     OR (v_kind='external_paste_blocked' AND v_source<>'unknown')
     OR p_data->>'expected_task_run_id' IS NULL
     OR p_data->>'expected_task_run_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
     OR COALESCE(length(p_data->>'client_timestamp'),0) NOT BETWEEN 15 AND 40
     OR EXISTS (SELECT 1 FROM jsonb_object_keys(p_data) AS k(key)
                WHERE k.key NOT IN ('event_key','expected_task_run_id','kind','surface','method','source','client_timestamp','text'))
     OR (v_text IS NOT NULL AND (v_kind<>'paste_requested'
             OR (v_source,v_surface) NOT IN (
                 ('internal_cli','internal_cli'),('internal_cli','internal_browser'),
                 ('internal_browser','internal_cli'))
             OR length(v_text) NOT BETWEEN 1 AND 2048))
  THEN RAISE EXCEPTION 'Invalid clipboard event'; END IF;
  -- Reject JSON null text distinctly from omitted text.
  IF p_data ? 'text' AND jsonb_typeof(p_data->'text') <> 'string' THEN
      RAISE EXCEPTION 'Invalid clipboard text type';
  END IF;
  -- Enforce idempotent insertion of event and optional content.
  PERFORM pg_advisory_xact_lock(hashtextextended(p_instance || ':' || v_key,0));
  SELECT s.session_id INTO v_session
    FROM fuzz_pilot.study_sessions s
    JOIN fuzz_pilot.participants p ON p.participant_id=s.participant_id
    WHERE s.instance_id=p_instance AND s.status='active' AND p.withdrawn_at IS NULL
    FOR SHARE OF s,p;
  IF v_session IS NULL THEN RAISE EXCEPTION 'No eligible study session'; END IF;
  SELECT t.task_run_id INTO v_task FROM fuzz_pilot.task_runs t
    WHERE t.session_id=v_session AND t.status IN ('ready','active') FOR SHARE OF t;
  IF v_task IS NULL OR v_task::text <> p_data->>'expected_task_run_id' THEN
    RAISE EXCEPTION 'Stale task clipboard observation';
  END IF;
  v_metadata=(p_data-'expected_task_run_id'-'text');
  SELECT e.event_id,e.event_type,e.event_source,e.task_run_id,e.payload,
         (SELECT text_value FROM fuzz_pilot.clipboard_text_records c WHERE c.event_id=e.event_id) AS old_text
    INTO v_existing FROM fuzz_pilot.events e
    WHERE e.session_id=v_session AND e.event_key=v_key;
  IF FOUND THEN
    IF v_existing.event_type<>'clipboard_'||v_kind OR v_existing.event_source<>'api'
       OR v_existing.task_run_id<>v_task OR v_existing.payload<>v_metadata
       OR v_existing.old_text IS DISTINCT FROM v_text THEN
       RAISE EXCEPTION 'Conflicting clipboard event UUID';
    END IF;
    RETURN QUERY SELECT v_existing.event_id,false;
    RETURN;
  END IF;
  INSERT INTO fuzz_pilot.events(session_id,task_run_id,event_type,event_source,event_key,payload)
  VALUES(v_session,v_task,'clipboard_'||v_kind,'api',v_key,v_metadata)
  RETURNING event_id INTO v_event;
  IF v_text IS NOT NULL THEN
    INSERT INTO fuzz_pilot.clipboard_text_records(event_id,text_value) VALUES(v_event,v_text);
  END IF;
  RETURN QUERY SELECT v_event,true;
END;
$fn$;
REVOKE ALL ON FUNCTION fuzz_pilot.ingest_clipboard_event(text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fuzz_pilot.ingest_clipboard_event(text,jsonb) TO pilot1_ai_ingest;
COMMIT;
