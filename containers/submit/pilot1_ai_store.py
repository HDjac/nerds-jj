"""Transactional storage for Pilot 1 AI prompt observations.

The caller must authenticate the originating instance and provide
a SQLAlchemy connection inside an active database transaction.
"""

import json
import re

from sqlalchemy import text


def store_prompt(conn, trusted_instance_id, prompt):
    if not isinstance(trusted_instance_id, str) or not re.fullmatch(
        r"[a-f0-9]{12}", trusted_instance_id
    ):
        raise ValueError("Invalid trusted instance ID")

    study = conn.execute(text("""
        SELECT s.session_id
        FROM fuzz_pilot.study_sessions s
        JOIN fuzz_pilot.participants p
          ON p.participant_id = s.participant_id
        WHERE s.instance_id = :instance
          AND s.status = 'active'
          AND p.withdrawn_at IS NULL
        FOR SHARE OF s, p
    """), {"instance": trusted_instance_id}).mappings().one_or_none()

    if study is None:
        raise ValueError("No eligible active study session")

    session_id = study["session_id"]
    key = prompt["event_key"]

    def find_existing():
        return conn.execute(text("""
            SELECT e.event_id, e.event_type, e.event_source,
                   a.service, a.model, a.prompt_text,
                   a.page_host, a.capture_method
            FROM fuzz_pilot.events e
            LEFT JOIN fuzz_pilot.ai_interactions a
              ON a.event_id = e.event_id
            WHERE e.session_id = :session
              AND e.event_key = :key
        """), {
            "session": session_id, "key": key
        }).mappings().one_or_none()

    def check_existing(row):
        if (row["event_type"] != "ai_interaction"
            or row["event_source"] != "prompt_logger"
            or any(row[field] != prompt[field] for field in (
                "service", "model", "prompt_text",
                "page_host", "capture_method"
            ))):
            raise ValueError("Conflicting interaction UUID")
        return row["event_id"], False

    existing = find_existing()
    if existing is not None:
        return check_existing(existing)

    task = conn.execute(text("""
        SELECT t.task_run_id
        FROM fuzz_pilot.task_runs t
        WHERE t.session_id = :session
          AND t.status IN ('ready', 'active')
        FOR SHARE OF t
    """), {"session": session_id}).mappings().one_or_none()

    if task is None:
        raise ValueError("No currently released task")

    payload = json.dumps({
        "interaction_id": key.removeprefix("ai:"),
        "client_timestamp": prompt["client_timestamp"],
        "capture_method": prompt["capture_method"],
        "provenance": "browser_reported",
    })

    inserted = conn.execute(text("""
        INSERT INTO fuzz_pilot.events
            (session_id, task_run_id, event_type,
             event_source, event_key, payload)
        VALUES
            (:session, :task, 'ai_interaction',
             'prompt_logger', :key, CAST(:payload AS jsonb))
        ON CONFLICT (session_id, event_key) DO NOTHING
        RETURNING event_id
    """), {
        "session": session_id,
        "task": task["task_run_id"],
        "key": key,
        "payload": payload,
    }).scalar_one_or_none()

    if inserted is None:
        existing = find_existing()
        if existing is None:
            raise RuntimeError("Interaction conflict without record")
        return check_existing(existing)

    conn.execute(text("""
        INSERT INTO fuzz_pilot.ai_interactions
            (event_id, service, model, prompt_text,
             page_host, capture_method)
        VALUES
            (:event_id, :service, :model, :prompt_text,
             :page_host, :capture_method)
    """), {
        "event_id": inserted,
        "service": prompt["service"],
        "model": prompt["model"],
        "prompt_text": prompt["prompt_text"],
        "page_host": prompt["page_host"],
        "capture_method": prompt["capture_method"],
    })

    return inserted, True
