-- NERDs CLI fuzzing study: mark pilot vs final sessions at the source.
-- Apply to the empty fuzz_pilot.study_sessions table before Pilot 1 enrollment.
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM fuzz_pilot.study_sessions) THEN
        RAISE EXCEPTION 'study_sessions must be empty before applying migration 002; review existing records first';
    END IF;
END
$$;

ALTER TABLE fuzz_pilot.study_sessions
    ADD COLUMN study_phase text NOT NULL,
    ADD COLUMN enrollment_method text NOT NULL;

ALTER TABLE fuzz_pilot.study_sessions
    ADD CONSTRAINT study_sessions_study_phase_check
    CHECK (study_phase IN ('pilot1', 'pilot2', 'main_study'));

ALTER TABLE fuzz_pilot.study_sessions
    ADD CONSTRAINT study_sessions_enrollment_method_check
    CHECK (enrollment_method IN ('manual', 'questionpro'));

COMMENT ON COLUMN fuzz_pilot.study_sessions.study_phase IS
    'Distinguishes local pilot, server pilot, and final study for analysis.';
COMMENT ON COLUMN fuzz_pilot.study_sessions.enrollment_method IS
    'How participant access was authorized; no survey responses stored here.';

COMMIT;
