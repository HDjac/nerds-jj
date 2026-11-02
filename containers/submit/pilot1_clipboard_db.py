"""Dedicated restricted DB call for clipboard observations."""
import json
import os
from pathlib import Path
import psycopg2

def store_clipboard_event(trusted_instance_id, normalized):
    secret=Path(os.environ.get('PILOT1_AI_DB_PASSWORD_FILE','/run/secrets/pilot1_ai_db_password'))
    password=secret.read_text(encoding='ascii').strip()
    if len(password)<32: raise RuntimeError('Ingestion credentials unavailable')
    db=psycopg2.connect(host=os.environ.get('PILOT1_AI_DB_HOST','db'),
        dbname=os.environ.get('PILOT1_AI_DB_NAME','notebook'),user='pilot1_ai_login',
        password=password,connect_timeout=5,application_name='nerds_pilot_clipboard_ingest')
    try:
        with db:
            with db.cursor() as cursor:
                cursor.execute('SET ROLE pilot1_ai_ingest')
                cursor.execute('SELECT stored_event_id, was_inserted FROM fuzz_pilot.ingest_clipboard_event(%s,%s::jsonb)',
                               (trusted_instance_id,json.dumps(normalized)))
                row=cursor.fetchone()
                if row is None: raise RuntimeError('No clipboard DB acknowledgement')
                return {'event_id':row[0], 'inserted':row[1]}
    finally: db.close()
