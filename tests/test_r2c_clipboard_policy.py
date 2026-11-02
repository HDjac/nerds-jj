"""Synthetic, no-network tests against the actual Release 2B.3 validators."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone
from uuid import uuid4

REPO = Path(os.environ.get('NERDS_REPO', Path.home() / 'nerds-r2c-provenance'))


def load_module(name, rel):
    source = REPO / rel
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Cannot load {source}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


instance = load_module('r2c_instance_validator', 'instance/clipboard_observation.py')
submit = load_module('r2c_submit_validator', 'containers/submit/pilot1_clipboard_payload.py')


def observation(source, surface, method, text='NERDS_SYNTHETIC_CLIPBOARD_001'):
    event_id = str(uuid4())
    task_id = str(uuid4())
    payload = {
        'event_id': event_id,
        'expected_task_run_id': task_id,
        'kind': 'paste_requested',
        'source': source,
        'surface': surface,
        'method': method,
        'client_timestamp': datetime.now(timezone.utc).isoformat(),
        'text': text,
    }
    meta = {'task_run_id': task_id, 'status': 'active'}
    return payload, meta


def validate_both(payload, meta, allow_text=True):
    normalized = instance.normalize_event(payload, meta, allow_text=allow_text)
    return submit.normalize_clipboard_observation(normalized, allow_text=allow_text)


class TestClipboardPolicy(unittest.TestCase):
    def test_three_allowed_directions(self):
        for source, target, method in [
            ('internal_cli', 'internal_cli', 'shift_insert'),
            ('internal_browser', 'internal_cli', 'shift_insert'),
            ('internal_cli', 'internal_browser', 'ctrl_shortcut'),
            ('internal_cli', 'internal_browser', 'meta_shortcut'),
        ]:
            with self.subTest(source=source, target=target, method=method):
                data, meta = observation(source, target, method)
                saved = validate_both(data, meta)
                self.assertEqual(saved['text'], data['text'])
                self.assertEqual(saved['source'], source)
                self.assertEqual(saved['surface'], target)

    def test_excluded_directions(self):
        for source, target, method in [
            ('task_sidebar', 'internal_cli', 'shift_insert'),
            ('fuzzing_guide', 'internal_cli', 'shift_insert'),
            ('internal_browser', 'internal_browser', 'ctrl_shortcut'),
            ('unknown', 'internal_cli', 'shift_insert'),
            ('internal_cli', 'task_sidebar', 'other_internal'),
        ]:
            with self.subTest(source=source, target=target):
                data, meta = observation(source, target, method)
                with self.assertRaises(instance.InvalidClipboardObservation):
                    instance.normalize_event(data, meta, allow_text=True)
                forward = {
                    'event_key': 'cb:' + data['event_id'],
                    **{k: v for k, v in data.items() if k not in ('event_id',)},
                }
                with self.assertRaises(ValueError):
                    submit.normalize_clipboard_observation(forward, allow_text=True)

    def test_text_disabled_fails_closed(self):
        data, meta = observation('internal_cli', 'internal_cli', 'shift_insert')
        with self.assertRaises(instance.InvalidClipboardObservation):
            instance.normalize_event(data, meta, allow_text=False)
        normalized = instance.normalize_event(data, meta, allow_text=True)
        with self.assertRaises(ValueError):
            submit.normalize_clipboard_observation(normalized, allow_text=False)

    def test_methods_and_length(self):
        data, meta = observation('internal_browser', 'internal_cli', 'ctrl_shortcut')
        with self.assertRaises(instance.InvalidClipboardObservation):
            instance.normalize_event(data, meta, allow_text=True)
        data, meta = observation('internal_cli', 'internal_browser', 'shift_insert')
        with self.assertRaises(instance.InvalidClipboardObservation):
            instance.normalize_event(data, meta, allow_text=True)
        data, meta = observation('internal_cli', 'internal_cli', 'shift_insert', 'Z' * 2049)
        with self.assertRaises(instance.InvalidClipboardObservation):
            instance.normalize_event(data, meta, allow_text=True)

    def test_stale_task_and_redaction(self):
        data, meta = observation('internal_cli', 'internal_cli', 'shift_insert',
                                 'token=NERDS_SYNTHETIC_VALUE')
        result = instance.normalize_event(data, meta, allow_text=True)
        self.assertEqual(result['text'], 'token=[REDACTED]')
        meta['task_run_id'] = str(uuid4())
        with self.assertRaises(instance.InvalidClipboardObservation):
            instance.normalize_event(data, meta, allow_text=True)

    def test_blocked_host_event_cannot_have_text(self):
        data, meta = observation('unknown', 'internal_cli', 'ctrl_shortcut')
        data['kind'] = 'host_paste_shortcut_blocked'
        with self.assertRaises(instance.InvalidClipboardObservation):
            instance.normalize_event(data, meta, allow_text=True)
        data.pop('text')
        result = instance.normalize_event(data, meta, allow_text=True)
        self.assertNotIn('text', result)
        self.assertNotIn('text', submit.normalize_clipboard_observation(result, allow_text=True))


if __name__ == '__main__':
    unittest.main()
