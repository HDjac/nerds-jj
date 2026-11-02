-- Release 2D.4: prospective per-task timing instrumentation.
--
-- Task 1 begins when the participant submits the mandatory HowTo
-- "Start Study" action (howto_acknowledged_at changes from NULL).
-- Task 2's operational clock starts at the trusted locked->ready transition;
-- this is a release boundary, NOT evidence of first participant interaction.
--
-- IMPORTANT: This migration never backfills historical rows or updates
-- currently ready/active task runs. Validate on an isolated Pilot 1 session
-- before deploying to a live participant database.
BEGIN;

CREATE OR REPLACE FUNCTION fuzz_pilot.pilot1_task1_on_howto()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $body$
DECLARE
    v_task uuid;
BEGIN
    IF NEW.study_phase <> 'pilot1' OR NEW.status <> 'active'
       OR OLD.howto_acknowledged_at IS NOT NULL
       OR NEW.howto_acknowledged_at IS NULL THEN
        RETURN NEW;
    END IF;

    -- Only an available first task, never a locked or finished task.
    UPDATE fuzz_pilot.task_runs AS t
       SET started_at = NEW.howto_acknowledged_at
     WHERE t.session_id = NEW.session_id AND t.position = 1
       AND t.status IN ('ready', 'active') AND t.started_at IS NULL
    RETURNING t.task_run_id INTO v_task;

    IF v_task IS NOT NULL THEN
        INSERT INTO fuzz_pilot.events
            (session_id, task_run_id, event_type, event_source,
             event_key, occurred_at, payload)
        VALUES
            (NEW.session_id, v_task, 'task_started', 'landing',
             'task-start:1:howto', NEW.howto_acknowledged_at,
             jsonb_build_object('capture_method', 'howto_start_study',
                                'position', 1))
        ON CONFLICT (session_id, event_key) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$body$;

DROP TRIGGER IF EXISTS pilot1_task1_on_howto ON fuzz_pilot.study_sessions;
CREATE TRIGGER pilot1_task1_on_howto
AFTER UPDATE OF howto_acknowledged_at ON fuzz_pilot.study_sessions
FOR EACH ROW
WHEN (OLD.howto_acknowledged_at IS NULL
      AND NEW.howto_acknowledged_at IS NOT NULL)
EXECUTE FUNCTION fuzz_pilot.pilot1_task1_on_howto();

CREATE OR REPLACE FUNCTION fuzz_pilot.pilot1_task2_on_release()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $body$
BEGIN
    -- The release timestamp is a trustworthy operational boundary,
    -- not a claim that the participant interacted immediately.
    IF OLD.status = 'locked' AND NEW.status = 'ready'
       AND NEW.position = 2 AND NEW.started_at IS NULL THEN
        NEW.started_at := transaction_timestamp();
    END IF;
    RETURN NEW;
END;
$body$;

DROP TRIGGER IF EXISTS pilot1_task2_on_release ON fuzz_pilot.task_runs;
CREATE TRIGGER pilot1_task2_on_release
BEFORE UPDATE OF status ON fuzz_pilot.task_runs
FOR EACH ROW
WHEN (OLD.status = 'locked' AND NEW.status = 'ready'
      AND NEW.position = 2)
EXECUTE FUNCTION fuzz_pilot.pilot1_task2_on_release();

-- Keep the task start instrumentation tied to actual transition events,
-- not session invitations, reauthentication, unrelated task reads or
-- asynchronously imported CLI/browser observations.
COMMIT;
