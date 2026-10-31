-- Mandatory invitation-based Intro -> HowTo -> workspace gate.
-- Additive and safe for existing completed sessions; no historical rows are changed.
-- Apply before PHP/Nginx deploy: psql -v ON_ERROR_STOP=1 -d notebook -f ...
BEGIN;
ALTER TABLE fuzz_pilot.study_sessions
    ADD COLUMN IF NOT EXISTS intro_acknowledged_at timestamptz;
ALTER TABLE fuzz_pilot.study_sessions
    ADD COLUMN IF NOT EXISTS howto_acknowledged_at timestamptz;

CREATE OR REPLACE FUNCTION fuzz_pilot.pilot1_onboarding_state(p_browser_digest text)
RETURNS TABLE (instance_id text, intro_done boolean, howto_done boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $body$
BEGIN
    IF p_browser_digest IS NULL OR p_browser_digest !~ '^[a-f0-9]{64}$' THEN RETURN; END IF;
    RETURN QUERY
    SELECT s.instance_id, s.intro_acknowledged_at IS NOT NULL,
           s.howto_acknowledged_at IS NOT NULL
    FROM fuzz_pilot.auth_sessions a
    JOIN fuzz_pilot.study_sessions s ON s.session_id = a.session_id
    JOIN fuzz_pilot.participants p ON p.participant_id = s.participant_id
    WHERE a.secret_sha256 = p_browser_digest
      AND a.expires_at > now() AND a.revoked_at IS NULL
      AND s.status = 'active' AND s.study_phase = 'pilot1'
      AND p.withdrawn_at IS NULL
      AND s.instance_id ~ '^[a-f0-9]{12}$'
    LIMIT 1;
END;
$body$;

CREATE OR REPLACE FUNCTION fuzz_pilot.advance_pilot1_onboarding(p_browser_digest text, p_step text)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $body$
DECLARE v_session uuid; v_intro timestamptz; v_howto timestamptz;
BEGIN
    IF p_browser_digest IS NULL OR p_browser_digest !~ '^[a-f0-9]{64}$'
       OR p_step IS NULL OR p_step NOT IN ('intro', 'howto') THEN RETURN false; END IF;
    SELECT s.session_id, s.intro_acknowledged_at, s.howto_acknowledged_at
        INTO v_session, v_intro, v_howto
    FROM fuzz_pilot.auth_sessions a
    JOIN fuzz_pilot.study_sessions s ON s.session_id = a.session_id
    JOIN fuzz_pilot.participants p ON p.participant_id = s.participant_id
    WHERE a.secret_sha256 = p_browser_digest
      AND a.expires_at > now() AND a.revoked_at IS NULL
      AND s.status = 'active' AND s.study_phase = 'pilot1'
      AND p.withdrawn_at IS NULL
    FOR UPDATE OF s;
    IF NOT FOUND THEN RETURN false; END IF;
    IF p_step = 'intro' THEN
        UPDATE fuzz_pilot.study_sessions
           SET intro_acknowledged_at = COALESCE(intro_acknowledged_at, now())
         WHERE session_id = v_session;
        RETURN true;
    END IF;
    IF v_intro IS NULL THEN RETURN false; END IF;
    UPDATE fuzz_pilot.study_sessions
       SET howto_acknowledged_at = COALESCE(howto_acknowledged_at, now())
     WHERE session_id = v_session;
    RETURN true;
END;
$body$;

REVOKE ALL ON FUNCTION fuzz_pilot.pilot1_onboarding_state(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION fuzz_pilot.advance_pilot1_onboarding(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fuzz_pilot.pilot1_onboarding_state(text) TO created_instances_user;
GRANT EXECUTE ON FUNCTION fuzz_pilot.advance_pilot1_onboarding(text, text) TO created_instances_user;
COMMIT;
