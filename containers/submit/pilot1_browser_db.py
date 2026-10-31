"""Dedicated browser ingestion adapter for existing trusted Submit route.

This is NOT a Flask route. The existing Submit app must register a gateway-
authenticated /pilot1/browser-event handler which authenticates Docker peer
identity exactly like /pilot1/ai-prompt and passes only that trusted instance.
"""
import json
import os
from pathlib import Path

import psycopg2


def store_browser_event(trusted_instance_id, normalized_observation):
    secret = Path(os.environ.get(
        'PILOT1_AI_DB_PASSWORD_FILE', '/run/secrets/pilot1_ai_db_password'))
    password = secret.read_text(encoding='ascii').strip()
    if len(password) < 32:
        raise RuntimeError('Browser ingest database credential unavailable')
    connection = psycopg2.connect(
        host=os.environ.get('PILOT1_AI_DB_HOST', 'db'),
        dbname=os.environ.get('PILOT1_AI_DB_NAME', 'notebook'),
        user='pilot1_ai_login', password=password,
        connect_timeout=5, application_name='nerds_pilot_browser_ingest')
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute('SET ROLE pilot1_ai_ingest')
                cursor.execute(
                    '''SELECT stored_event_id, was_inserted
                       FROM fuzz_pilot.ingest_browser_event(%s,%s::jsonb)''',
                    (trusted_instance_id, json.dumps(normalized_observation)),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError('Browser function did not acknowledge event')
                return {'event_id': row[0], 'inserted': row[1]}
    finally:
        connection.close()
