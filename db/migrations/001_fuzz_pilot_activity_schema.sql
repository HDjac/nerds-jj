-- NERDs CLI fuzzing pilot -- activity-only research schema, version 001
-- PostgreSQL 13+ (uses core gen_random_uuid()).
-- Non-destructive: legacy public.conditions and public."createdInstances" are retained
-- until the legacy landing, manager, and submit workflows have been migrated.
-- Review database privileges before deployment. Execute with psql -v ON_ERROR_STOP=1 -1
-- for all-or-nothing migration. Apply only to a database without an earlier v001.

CREATE SCHEMA IF NOT EXISTS fuzz_pilot;

-- A stable pseudonymous identifier also passed to QuestionPro as ext_ref.
-- Survey content and response IDs remain exclusively in QuestionPro.
-- Suggested PHP generator: bin2hex(random_bytes(12)); not an auth credential.
CREATE TABLE fuzz_pilot.participants (
    participant_id text PRIMARY KEY
        CHECK (participant_id ~ '^[0-9a-f]{24}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    withdrawn_at timestamptz
);

-- One attempt is the default; more attempts are explicitly distinguishable.
-- order_code is assigned once after externally verified enrollment.
-- Actual per-task state resides in task_runs, which is authoritative for progression.
CREATE TABLE fuzz_pilot.study_sessions (
    session_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    participant_id text NOT NULL REFERENCES fuzz_pilot.participants(participant_id),
    attempt_number integer NOT NULL DEFAULT 1 CHECK (attempt_number > 0),
    order_code text NOT NULL CHECK (order_code IN ('dense_first', 'lowyield_first')),
    status text NOT NULL DEFAULT 'assigned'
        CHECK (status IN ('assigned', 'active', 'completed', 'aborted', 'withdrawn')),
    instance_id text UNIQUE CHECK (instance_id ~ '^[0-9a-f]{12}$'),
    instance_name text,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    ended_at timestamptz,
    UNIQUE (participant_id, attempt_number)
);
CREATE INDEX study_sessions_participant_idx
    ON fuzz_pilot.study_sessions (participant_id, assigned_at DESC);

-- Both task rows are created in a single transaction when order is assigned.
-- The second task stays 'locked' until the trusted provisioner activates it.
CREATE TABLE fuzz_pilot.task_runs (
    task_run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES fuzz_pilot.study_sessions(session_id),
    position smallint NOT NULL CHECK (position IN (1, 2)),
    task_code text NOT NULL CHECK (task_code IN ('dense_v2', 'lowyield_v1')),
    status text NOT NULL DEFAULT 'locked'
        CHECK (status IN ('locked', 'ready', 'active', 'completed', 'skipped', 'aborted')),
    bundle_version text,
    bundle_sha256 text CHECK (bundle_sha256 ~ '^[0-9a-f]{64}$'),
    started_at timestamptz,
    ended_at timestamptz,
    UNIQUE (session_id, position),
    UNIQUE (session_id, task_code),
    UNIQUE (task_run_id, session_id)
);
CREATE INDEX task_runs_session_idx
    ON fuzz_pilot.task_runs (session_id, position);
-- Do not release two tasks to the same participant at once.
CREATE UNIQUE INDEX task_runs_one_released_per_session_idx
    ON fuzz_pilot.task_runs (session_id)
    WHERE status IN ('ready', 'active');

-- Every fuzzing invocation is a separate campaign; many campaigns per task.
CREATE TABLE fuzz_pilot.campaigns (
    campaign_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_run_id uuid NOT NULL REFERENCES fuzz_pilot.task_runs(task_run_id),
    harness_id text NOT NULL CHECK (harness_id IN ('a', 'b', 'c', 'custom')),
    status text NOT NULL DEFAULT 'started'
        CHECK (status IN ('started', 'completed', 'stopped', 'crashed', 'error')),
    command_summary text,
    config jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(config) = 'object'),
    final_metrics jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(final_metrics) = 'object'),
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    UNIQUE (campaign_id, task_run_id)
);
CREATE INDEX campaigns_task_started_idx
    ON fuzz_pilot.campaigns (task_run_id, started_at);

-- Chronological event stream: terminal, browser, AI prompts, build, fuzzing,
-- task progression, etc. Received time is set by the trusted ingest backend.
-- Client-reported occurred_at is useful but NOT authoritative evidence of order.
-- The backend MUST derive session/task from authenticated server state, not a
-- participant-supplied JSON field. Server-side transitions must be written
-- transactionally with study_sessions/task_runs updates.
CREATE TABLE fuzz_pilot.events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES fuzz_pilot.study_sessions(session_id),
    task_run_id uuid,
    campaign_id uuid,
    event_type text NOT NULL,
    event_source text NOT NULL CHECK (event_source IN
        ('landing', 'manager', 'api', 'cli', 'browser', 'prompt_logger', 'submit')),
    occurred_at timestamptz,
    received_at timestamptz NOT NULL DEFAULT now(),
    event_key text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(payload) = 'object'),
    CHECK (campaign_id IS NULL OR task_run_id IS NOT NULL),
    FOREIGN KEY (task_run_id, session_id)
        REFERENCES fuzz_pilot.task_runs(task_run_id, session_id),
    FOREIGN KEY (campaign_id, task_run_id)
        REFERENCES fuzz_pilot.campaigns(campaign_id, task_run_id),
    UNIQUE (session_id, event_key)
);
CREATE INDEX events_session_time_idx
    ON fuzz_pilot.events (session_id, received_at, event_id);
CREATE INDEX events_task_time_idx
    ON fuzz_pilot.events (task_run_id, received_at, event_id);
CREATE INDEX events_type_time_idx
    ON fuzz_pilot.events (event_type, received_at);

-- Optional structured AI record for easier qualitative and quantitative analysis.
-- Create its matching events row with event_type='ai_interaction'; event_id
-- associates the captured prompt/response with the unified event timeline.
-- Only populate response_text if the study logger ACTUALLY captures that content;
-- do not infer model outputs from prompts or subsequent participant behavior.
-- AI text is potentially sensitive: restrict database access and retention.
CREATE TABLE fuzz_pilot.ai_interactions (
    event_id bigint PRIMARY KEY REFERENCES fuzz_pilot.events(event_id),
    service text,
    model text,
    prompt_text text,
    response_text text,
    page_host text,
    capture_method text NOT NULL,
    CHECK (prompt_text IS NOT NULL OR response_text IS NOT NULL)
);
CREATE INDEX ai_interactions_service_idx
    ON fuzz_pilot.ai_interactions (service);

-- Large binary artifacts, corpora, terminal logs and prompt transcripts reside
-- in a separate access-controlled store. The DB keeps pointers/checksums only.
CREATE TABLE fuzz_pilot.artifacts (
    artifact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_run_id uuid NOT NULL REFERENCES fuzz_pilot.task_runs(task_run_id),
    campaign_id uuid,
    artifact_kind text NOT NULL CHECK (artifact_kind IN
        ('terminal_log', 'corpus', 'crash', 'reproducer', 'source_snapshot',
         'source_diff', 'fuzzer_log', 'ai_transcript', 'other')),
    storage_key text NOT NULL UNIQUE,
    sha256 text CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes bigint CHECK (size_bytes >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (campaign_id, task_run_id)
        REFERENCES fuzz_pilot.campaigns(campaign_id, task_run_id)
);
CREATE INDEX artifacts_task_kind_idx
    ON fuzz_pilot.artifacts (task_run_id, artifact_kind);

-- Browser session authentication, unrelated to QuestionPro response IDs: independently generated 256-bit secret;
-- store only SHA-256 of the random secret, never the cookie value itself.
-- Require expires_at > now(), revoked_at IS NULL and matching instance on
-- every proxy authorization check. Creation/refresh must be server-controlled.
CREATE TABLE fuzz_pilot.auth_sessions (
    auth_session_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES fuzz_pilot.study_sessions(session_id),
    secret_sha256 text NOT NULL UNIQUE
        CHECK (secret_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    last_seen_at timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX auth_sessions_study_idx
    ON fuzz_pilot.auth_sessions (session_id, expires_at);

-- Convenience view for activity analysis; authoritative order is recorded at assignment
-- and validated by application transactional logic against task_runs.
CREATE VIEW fuzz_pilot.analysis_session_summary AS
SELECT s.session_id, s.participant_id, s.attempt_number, s.order_code,
       s.status AS session_status, s.assigned_at, s.started_at, s.ended_at,
       max(t.task_code) FILTER (WHERE t.position = 1) AS first_task,
       max(t.task_code) FILTER (WHERE t.position = 2) AS second_task,
       max(t.status) FILTER (WHERE t.position = 1) AS first_task_status,
       max(t.status) FILTER (WHERE t.position = 2) AS second_task_status
FROM fuzz_pilot.study_sessions s
LEFT JOIN fuzz_pilot.task_runs t ON t.session_id = s.session_id
GROUP BY s.session_id;
