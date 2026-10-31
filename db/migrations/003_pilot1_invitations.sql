-- Pilot 1: short-lived, single-use invitations exchanged for browser sessions.
-- Apply using psql -v ON_ERROR_STOP=1 --single-transaction -d notebook.
-- Keep invitation writes exclusively with the trusted host administrator.

CREATE TABLE IF NOT EXISTS fuzz_pilot.invitation_tokens (
    invitation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES fuzz_pilot.study_sessions(session_id),
    token_sha256 text NOT NULL UNIQUE CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL CHECK (expires_at > created_at),
    redeemed_at timestamptz,
    revoked_at timestamptz
);

CREATE INDEX IF NOT EXISTS invitation_tokens_session_idx
    ON fuzz_pilot.invitation_tokens (session_id, expires_at DESC);

-- PHP's landing role cannot read invitations or write the session tables.
REVOKE ALL ON fuzz_pilot.invitation_tokens FROM PUBLIC;
REVOKE ALL ON fuzz_pilot.invitation_tokens FROM created_instances_user;

-- Atomic redemption: the same invitation cannot be consumed by two requests.
-- The function runs with its owner privileges; it does NOT take an instance ID,
-- participant ID, or study session ID from the untrusted browser.
CREATE OR REPLACE FUNCTION fuzz_pilot.redeem_pilot1_invitation(
    p_invitation_digest text,
    p_browser_digest text,
    p_browser_minutes integer
)
RETURNS TABLE (instance_id text, auth_session_id uuid)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $function$
DECLARE
    v_session_id uuid;
    v_instance_id text;
    v_auth_id uuid;
BEGIN
    IF p_invitation_digest !~ '^[0-9a-f]{64}$'
       OR p_browser_digest !~ '^[0-9a-f]{64}$'
       OR p_browser_minutes IS NULL
       OR p_browser_minutes NOT BETWEEN 5 AND 120 THEN
        RETURN;
    END IF;

    -- This UPDATE obtains a row lock. A concurrent second redemption cannot
    -- pass the redeemed_at IS NULL condition after the first transaction commits.
    UPDATE fuzz_pilot.invitation_tokens AS i
    SET redeemed_at = now()
    WHERE i.token_sha256 = p_invitation_digest
      AND i.redeemed_at IS NULL
      AND i.revoked_at IS NULL
      AND i.expires_at > now()
      AND EXISTS (
          SELECT 1
          FROM fuzz_pilot.study_sessions AS s
          JOIN fuzz_pilot.participants AS p ON p.participant_id = s.participant_id
          WHERE s.session_id = i.session_id
            AND s.study_phase = 'pilot1'
            AND s.enrollment_method = 'manual'
            AND s.status IN ('assigned', 'active')
            AND s.instance_id IS NOT NULL
            AND s.instance_name IS NOT NULL
            AND p.withdrawn_at IS NULL
            AND (
                (EXISTS (
                    SELECT 1 FROM fuzz_pilot.task_runs AS t1
                    WHERE t1.session_id = s.session_id AND t1.position = 1
                      AND t1.status IN ('ready', 'active')
                ) AND EXISTS (
                    SELECT 1 FROM fuzz_pilot.task_runs AS t2
                    WHERE t2.session_id = s.session_id AND t2.position = 2
                      AND t2.status = 'locked'
                )) OR (EXISTS (
                    SELECT 1 FROM fuzz_pilot.task_runs AS t1
                    WHERE t1.session_id = s.session_id AND t1.position = 1
                      AND t1.status IN ('completed', 'skipped')
                ) AND EXISTS (
                    SELECT 1 FROM fuzz_pilot.task_runs AS t2
                    WHERE t2.session_id = s.session_id AND t2.position = 2
                      AND t2.status IN ('ready', 'active')
                ))
            )
      )
    RETURNING i.session_id INTO v_session_id;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    UPDATE fuzz_pilot.study_sessions AS s
    SET status = 'active', started_at = COALESCE(s.started_at, now())
    WHERE s.session_id = v_session_id AND s.status IN ('assigned', 'active')
    RETURNING s.instance_id INTO v_instance_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Eligible study session changed during redemption';
    END IF;

    -- Rotate existing authentication, including any previous curl-only test
    -- credential. This makes a new login the sole current browser session.
    UPDATE fuzz_pilot.auth_sessions AS a
    SET revoked_at = now()
    WHERE a.session_id = v_session_id AND a.revoked_at IS NULL;

    INSERT INTO fuzz_pilot.auth_sessions AS a (session_id, secret_sha256, expires_at)
    VALUES (v_session_id, p_browser_digest,
            now() + make_interval(mins => p_browser_minutes))
    RETURNING a.auth_session_id INTO v_auth_id;

    -- Revoke other unused invitations for this participant session.
    UPDATE fuzz_pilot.invitation_tokens AS i
    SET revoked_at = now()
    WHERE i.session_id = v_session_id
      AND i.redeemed_at IS NULL
      AND i.revoked_at IS NULL;

    instance_id := v_instance_id;
    auth_session_id := v_auth_id;
    RETURN NEXT;
END;
$function$;

REVOKE ALL ON FUNCTION fuzz_pilot.redeem_pilot1_invitation(text, text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fuzz_pilot.redeem_pilot1_invitation(text, text, integer)
    TO created_instances_user;
