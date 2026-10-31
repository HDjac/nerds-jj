"""Validate minimized browser observations before forwarding to trusted gateway.

Attribution is not taken from browser-provided identity: the API reads the
server-provisioned active task metadata, and the DB verifies active session/run.
"""
import datetime
import re
import uuid
from urllib.parse import urlsplit

ALLOWED_TRANSITIONS = {'committed', 'history_state'}
EVENT_KINDS = {'search', 'navigation'}
SEARCH_ENGINES = {'google', 'bing', 'duckduckgo'}


class InvalidObservation(ValueError):
    pass


def normalize_event(data, task_meta):
    if not isinstance(data, dict) or not isinstance(task_meta, dict):
        raise InvalidObservation('Invalid observation input')
    try:
        event_id = str(uuid.UUID(str(data.get('event_id', ''))))
        task_run_id = str(uuid.UUID(str(task_meta.get('task_run_id', ''))))
        expected = str(uuid.UUID(str(data.get('expected_task_run_id', ''))))
    except (ValueError, TypeError, AttributeError):
        raise InvalidObservation('Invalid event or task identifier') from None
    if expected != task_run_id:
        raise InvalidObservation('Stale task context')
    if task_meta.get('status') not in ('ready', 'active'):
        raise InvalidObservation('Task not released')
    if data.get('event_kind') not in EVENT_KINDS:
        raise InvalidObservation('Invalid event kind')
    if data.get('navigation_type') not in ALLOWED_TRANSITIONS:
        raise InvalidObservation('Invalid navigation type')
    raw_url = data.get('url')
    if not isinstance(raw_url, str) or len(raw_url) > 2048:
        raise InvalidObservation('Invalid URL')
    parts = urlsplit(raw_url)
    if (parts.scheme not in ('http', 'https') or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment):
        raise InvalidObservation('URL is not minimized')
    host = parts.hostname.lower()
    if (len(host) > 253 or data.get('page_host') != host
            or host == 'localhost' or host.endswith('.local')
            or host.startswith(('127.', '10.', '192.168.'))):
        raise InvalidObservation('Invalid page host')
    if re.match(r'^172\.(1[6-9]|2\d|3[01])\.', host):
        raise InvalidObservation('Invalid private page host')
    search_engine = data.get('search_engine')
    search_query = data.get('search_query')
    if data['event_kind'] == 'search':
        if (search_engine not in SEARCH_ENGINES or
                not isinstance(search_query, str) or
                not 1 <= len(search_query.strip()) <= 1200):
            raise InvalidObservation('Invalid search query')
        if (search_engine == 'google' and not re.fullmatch(r'(www\.)?google\.[a-z.]+', host)) or \
                (search_engine == 'bing' and host not in ('bing.com', 'www.bing.com')) or \
                (search_engine == 'duckduckgo' and host not in ('duckduckgo.com', 'www.duckduckgo.com')):
            raise InvalidObservation('Search engine host mismatch')
    else:
        if search_engine is not None or search_query is not None:
            raise InvalidObservation('Unexpected search data')
    timestamp = data.get('client_timestamp')
    if not isinstance(timestamp, str) or len(timestamp) > 40:
        raise InvalidObservation('Invalid timestamp')
    try:
        parsed = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError:
        raise InvalidObservation('Invalid timestamp') from None
    if parsed.tzinfo is None:
        raise InvalidObservation('Timestamp must include timezone')
    transition_type = data.get('transition_type')
    if not isinstance(transition_type, str) or len(transition_type) > 40:
        raise InvalidObservation('Invalid transition type')
    tab_id = data.get('browser_tab_id')
    if type(tab_id) is not int or not -1 <= tab_id <= 2_147_483_647:
        raise InvalidObservation('Invalid tab identifier')
    return {
        'event_key': 'br:' + event_id,
        'expected_task_run_id': task_run_id,
        'event_kind': data['event_kind'],
        'url': raw_url,
        'page_host': host,
        'search_engine': search_engine,
        'search_query': search_query.strip() if search_query else None,
        'navigation_type': data['navigation_type'],
        'transition_type': transition_type,
        'browser_tab_id': tab_id,
        'client_timestamp': timestamp,
    }
