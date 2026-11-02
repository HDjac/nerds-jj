"""Validate participant clipboard observations against the released task.
Only paste-request event transfers can contain text. No clipboard reads occur.
"""
from datetime import datetime
from uuid import UUID
import re

KINDS = {'copy_committed', 'copy_requested', 'clipboard_observed',
         'paste_requested', 'external_paste_blocked', 'host_paste_shortcut_blocked'}
SURFACES = {'task_sidebar', 'fuzzing_guide', 'internal_cli', 'internal_browser', 'other_internal'}
METHODS = {'copy_button', 'sidebar_keyboard', 'vnc_clipboard', 'ctrl_shortcut',
           'meta_shortcut', 'shift_insert', 'other_internal'}
SOURCES = SURFACES | {'unknown'}
TEXT_TRANSFERS = {('internal_cli', 'internal_cli'), ('internal_cli', 'internal_browser'),
                  ('internal_browser', 'internal_cli')}

class InvalidClipboardObservation(ValueError):
    pass

def normalize_event(data, task_meta, allow_text=False):
    if not isinstance(data, dict) or not isinstance(task_meta, dict):
        raise InvalidClipboardObservation('Invalid observation')
    allowed = {'event_id', 'expected_task_run_id', 'kind', 'surface', 'method',
               'source', 'client_timestamp', 'text'}
    if not set(data).issubset(allowed):
        raise InvalidClipboardObservation('Unknown clipboard fields')
    try:
        eid = UUID(str(data.get('event_id')))
        expected = UUID(str(data.get('expected_task_run_id')))
        active = UUID(str(task_meta.get('task_run_id')))
    except (TypeError, ValueError, AttributeError):
        raise InvalidClipboardObservation('Invalid identifiers') from None
    if eid.version != 4 or str(eid) != data.get('event_id'):
        raise InvalidClipboardObservation('Expected canonical v4 event UUID')
    if str(expected) != str(active) or task_meta.get('status') not in ('ready','active'):
        raise InvalidClipboardObservation('Stale task clipboard observation')
    if str(expected) != data.get('expected_task_run_id'):
        raise InvalidClipboardObservation('Noncanonical task UUID')
    kind, surface, method, source = [data.get(x) for x in ('kind','surface','method','source')]
    if kind not in KINDS or surface not in SURFACES or method not in METHODS or source not in SOURCES:
        raise InvalidClipboardObservation('Invalid clipboard metadata')
    if kind == 'external_paste_blocked' and (source != 'unknown' or method != 'other_internal'):
        raise InvalidClipboardObservation('Blocked event must have unknown source')
    if kind == 'host_paste_shortcut_blocked' and (source != 'unknown' or
            method not in ('ctrl_shortcut', 'meta_shortcut') or
            surface not in ('internal_cli', 'internal_browser')):
        raise InvalidClipboardObservation('Invalid host shortcut block')
    when = data.get('client_timestamp')
    if not isinstance(when,str) or not (15 <= len(when) <= 40):
        raise InvalidClipboardObservation('Invalid timestamp')
    try: stamp=datetime.fromisoformat(when.replace('Z','+00:00'))
    except ValueError: raise InvalidClipboardObservation('Invalid timestamp') from None
    if stamp.tzinfo is None:
        raise InvalidClipboardObservation('Timezone required')
    text = data.get('text')
    if text is not None:
        if (not allow_text or kind != 'paste_requested' or
                (source, surface) not in TEXT_TRANSFERS or
                not isinstance(text,str) or not 1 <= len(text) <= 2048 or
                '\x00' in text or
                (surface == 'internal_cli' and method != 'shift_insert') or
                (surface == 'internal_browser' and method not in ('ctrl_shortcut','meta_shortcut'))):
            raise InvalidClipboardObservation('Clipboard content not permitted')
        # Best-effort redaction; cannot guarantee sensitive text is absent.
        text = re.sub(r'(?i)(password|token|secret|api[_-]?key)(\s*[=:]\s*)[^\s;,]+',
                      r'\1\2[REDACTED]', text)
        text = re.sub(r'\b(?:sk-[a-zA-Z0-9_-]{16,}|gh[pousr]_[a-zA-Z0-9]{16,})\b',
                      '[REDACTED]', text)
    return {'event_key': 'cb:' + str(eid), 'expected_task_run_id': str(active),
            'kind': kind, 'surface':surface, 'method':method, 'source':source,
            'client_timestamp':when, **({'text':text} if text is not None else {})}
