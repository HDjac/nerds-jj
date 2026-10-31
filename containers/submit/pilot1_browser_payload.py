"""Strictly validate Pilot 1 browser observations received through trusted gateway.

The instance ID is NEVER accepted from the request JSON; the Submit route
obtains it from authenticated gateway + host-managed instance registry.
"""
import datetime
import ipaddress
import re
from urllib.parse import urlsplit
from uuid import UUID

HOST_PATTERN = re.compile(r'^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$')
SEARCH_HOSTS = {
    'google': re.compile(r'^(?:www\.)?google\.[a-z.]+$'),
    'bing': re.compile(r'^(?:www\.)?bing\.com$'),
    'duckduckgo': re.compile(r'^(?:www\.)?duckduckgo\.com$'),
}


def normalize_browser_observation(data):
    """Return a whitelisted normalized dict or raise ValueError."""
    if not isinstance(data, dict):
        raise ValueError('Expected browser observation object')
    try:
        event = UUID(str(data.get('event_key', ''))[3:] if str(data.get('event_key', '')).startswith('br:') else '')
        task = UUID(str(data.get('expected_task_run_id', '')))
    except (TypeError, AttributeError, ValueError) as exc:
        raise ValueError('Invalid browser event ID or task ID') from exc
    if event.version != 4 or str(data.get('event_key')) != f'br:{event}':
        raise ValueError('Invalid browser event key')
    if str(task) != data.get('expected_task_run_id'):
        raise ValueError('Task identifier not canonical')

    kind = data.get('event_kind')
    if kind not in ('search', 'navigation'):
        raise ValueError('Invalid browser event kind')
    url = data.get('url')
    if not isinstance(url, str) or not (8 <= len(url) <= 2048):
        raise ValueError('Invalid URL')
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise ValueError('Invalid URL controls')
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
        port = parsed.port
    except ValueError as exc:
        raise ValueError('Invalid parsed URL') from exc
    if (parsed.scheme not in ('http', 'https') or
            not host or not HOST_PATTERN.fullmatch(host) or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            '@' in parsed.netloc or
            data.get('page_host') != host):
        raise ValueError('URL not minimized or host mismatched')
    if host in ('localhost', 'metadata.google.internal') or host.endswith(
            ('.localhost', '.local', '.internal', '.test')):
        raise ValueError('Private or reserved host')
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None and not addr.is_global:
        raise ValueError('Non-public IP address')
    # The client redacts long token-shaped path segments. Refuse raw ones.
    segments = parsed.path.split('/')
    for segment in segments:
        if len(segment) > 120 or (
            segment != '[redacted]' and
            (re.fullmatch(r'[A-Za-z0-9_-]{32,}', segment) or
             re.fullmatch(r'[0-9a-f]{8}-[0-9a-f-]{15,}', segment, re.I))
        ):
            raise ValueError('Unsanitized URL token')

    engine = data.get('search_engine')
    search = data.get('search_query')
    if kind == 'search':
        if engine not in SEARCH_HOSTS or not SEARCH_HOSTS[engine].fullmatch(host):
            raise ValueError('Invalid search engine or host')
        if (engine in ('google', 'bing') and parsed.path != '/search') or (
            engine == 'duckduckgo' and parsed.path not in ('/', '/html/')
        ):
            raise ValueError('Unexpected search page')
        if (not isinstance(search, str) or not (1 <= len(search.strip()) <= 1200)
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in search)):
            raise ValueError('Invalid search query')
    elif engine is not None or search is not None:
        raise ValueError('Unexpected search fields')

    nav_type = data.get('navigation_type')
    if nav_type not in ('committed', 'history_state'):
        raise ValueError('Invalid navigation type')
    transition = data.get('transition_type')
    if not isinstance(transition, str) or not re.fullmatch(r'[\w:-]{1,40}', transition):
        raise ValueError('Invalid transition type')
    tab_id = data.get('browser_tab_id')
    if type(tab_id) is not int or not (-1 <= tab_id <= 2147483647):
        raise ValueError('Invalid browser tab ID')
    timestamp = data.get('client_timestamp')
    if not isinstance(timestamp, str) or not (15 <= len(timestamp) <= 40):
        raise ValueError('Invalid timestamp')
    try:
        dt = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid timestamp') from exc
    if dt.tzinfo is None:
        raise ValueError('Timestamp requires timezone')

    return {
        'event_key': f'br:{event}',
        'expected_task_run_id': str(task),
        'event_kind': kind,
        'url': url,
        'page_host': host,
        'search_engine': engine if kind == 'search' else None,
        'search_query': search.strip() if kind == 'search' else None,
        'navigation_type': nav_type,
        'transition_type': transition,
        'browser_tab_id': tab_id,
        'client_timestamp': timestamp,
    }
