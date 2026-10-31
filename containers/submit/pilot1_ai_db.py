"""Pilot 1 AI ingestion via a dedicated role and the restricted DB function.

No participant identifiers are taken from the prompt data. Caller supplies
an instance ID authenticated from the gateway and the trusted registry.
"""
import json
import os
from pathlib import Path

import psycopg2


def store_ai_prompt(trusted_instance_id, normalized_prompt):
    secret_path = Path(os.environ.get(
        "PILOT1_AI_DB_PASSWORD_FILE", "/run/secrets/pilot1_ai_db_password"
    ))
    password = secret_path.read_text(encoding="ascii").strip()
    if len(password) < 32:
        raise RuntimeError("AI database credential unavailable or invalid")

    connection = psycopg2.connect(
        host=os.environ.get("PILOT1_AI_DB_HOST", "db"),
        dbname=os.environ.get("PILOT1_AI_DB_NAME", "notebook"),
        user="pilot1_ai_login",
        password=password,
        connect_timeout=5,
        application_name="nerds_pilot1_ai_ingest",
    )
    try:
        with connection:
            with connection.cursor() as cursor:
                # Role membership is granted by the host-side setup script.
                # The login role has NOINHERIT and no direct table grants.
                cursor.execute("SET ROLE pilot1_ai_ingest")
                cursor.execute(
                    """SELECT stored_event_id, was_inserted
                       FROM fuzz_pilot.ingest_ai_prompt(%s, %s::jsonb)""",
                    (trusted_instance_id, json.dumps(normalized_prompt)),
                )
                result = cursor.fetchone()
                if result is None:
                    raise RuntimeError("AI ingest function returned no result")
                return {"event_id": result[0], "inserted": result[1]}
    finally:
        connection.close()
