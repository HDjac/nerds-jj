"""Offline-only regression tests for R2D.4 explicit LibFuzzer interruptions.

Run from a staging checkout after applying source patch:
 python3 -m unittest discover -s tests -p 'test_r2d4_stopped_campaign.py' -v
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pilot1_auto_ingest as auto
import pilot1_import_campaign_multi as multi

TAG = '20261104T180000Z-1234'
TASK = str(uuid4())
CMD = './fuzz_a -runs=100000000 -max_len=1'
STAMP = '2026-11-04T18:00:30+00:00'
METRICS = b'cov: 5 ft: 5 corp: 2/3b exec/s: 100 rss: 32Mb'
INIT = b'#1 INITED ' + METRICS + b'\r\n'
PULSE = b'#80 pulse ' + METRICS + b'\r\n'
DONE = b'#100 DONE ' + METRICS + b'\r\n'
STOP = b'libFuzzer: run interrupted; exiting\r\n'


def commands(rows):
    return b''.join((json.dumps({
        'terminal_session': TAG, 'sequence': seq, 'command': command,
        'exit_status': rc, 'occurred_at': STAMP,
    }) + '\n').encode() for seq, command, rc in rows)


def parse(output, rows):
    with patch.object(auto, 'read_tag', return_value=(output, b'', commands(rows))):
        with patch.object(auto.completed_importer, 'time_at_output_offset',
                          return_value=datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)):
            return auto.read_campaigns(Path('unused'), TAG, TASK)


class InterruptedCampaignTests(unittest.TestCase):
    def test_verified_explicit_interrupt_is_stopped_not_final(self):
        output = CMD.encode() + b'\r\n' + INIT + PULSE + STOP
        outcomes, deferred = parse(output, [(1, CMD, 72)])
        self.assertFalse(deferred)
        self.assertEqual(len(outcomes), 1)
        item = outcomes[0]
        self.assertEqual((item['kind'], item['status'], item['harness_id']), ('stopped', 'stopped', 'a'))
        self.assertEqual(item['config']['command_exit_status'], 72)
        self.assertEqual(item['config']['outcome_evidence'], 'libfuzzer_explicit_interrupt')
        self.assertEqual(item['final_metrics']['executions'], 80)
        self.assertIs(item['final_metrics']['is_final_fuzzer_metric'], False)
        self.assertEqual(item['event_key'], 'campaign:' + TAG + ':1')
        self.assertEqual(item['campaign_id'], str(auto.uuid5(auto.UUID(TASK), 'libfuzzer:' + TAG + ':1')))

    def test_nonzero_exit_alone_is_not_sufficient(self):
        for code in (1, 72, 130, 143):
            with self.subTest(code=code):
                out, de = parse(CMD.encode() + b'\r\n' + INIT + PULSE, [(1, CMD, code)])
                self.assertEqual(out, [])
                self.assertTrue(de)

    def test_marker_without_specific_exit_code_is_deferred(self):
        for code in (0, 1, 130, 143):
            with self.subTest(code=code):
                out, de = parse(CMD.encode() + b'\r\n' + INIT + STOP, [(1, CMD, code)])
                self.assertEqual(out, [])
                self.assertTrue(de)

    def test_mismatched_invocation_is_deferred(self):
        out, de = parse(b'./fuzz_b -runs=100\r\n' + INIT + STOP, [(1, CMD, 72)])
        self.assertEqual(out, [])
        self.assertTrue(de)

    def test_conflicting_outcomes_are_deferred(self):
        extras = [DONE, b'ERROR: AddressSanitizer: heap-buffer-overflow\r\n',
                  b'ERROR: libFuzzer: deadly signal\r\n',
                  b'SUMMARY: AddressSanitizer: heap-buffer-overflow\r\n',
                  STOP]
        for marker in extras:
            with self.subTest(marker=marker[:35]):
                out, de = parse(CMD.encode() + b'\r\n' + INIT + STOP + marker,
                                [(1, CMD, 72)])
                self.assertEqual(out, [])
                self.assertTrue(de)

    def test_normal_completion_remains_completed(self):
        out, de = parse(CMD.encode() + b'\r\n' + INIT + DONE, [(1, CMD, 0)])
        self.assertFalse(de)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['status'], 'completed')

    def test_two_commands_after_interruption_are_independent(self):
        cmd2 = './fuzz_b -runs=100'
        output = CMD.encode() + b'\r\n' + INIT + STOP + cmd2.encode() + b'\r\n' + INIT + DONE
        out, de = parse(output, [(1, CMD, 72), (2, cmd2, 0)])
        self.assertFalse(de)
        self.assertEqual([(x['harness_id'], x['status']) for x in out],
                         [('a', 'stopped'), ('b', 'completed')])

    def test_stopped_import_uses_existing_idempotent_sql_with_separate_event(self):
        out, _ = parse(CMD.encode() + b'\r\n' + INIT + STOP, [(1, CMD, 72)])
        summary = {k: v for k, v in out[0].items() if k not in ('kind', 'artifact')}
        with patch.object(multi, 'run', return_value='mock result') as run:
            multi.apply_campaign(summary, 'a' * 12, str(uuid4()), TASK)
        args, sqlbytes = run.call_args.args
        sql = sqlbytes.decode()
        self.assertIn('libfuzzer_campaign_stopped', sql)
        self.assertIn("'observed_metrics'", sql)
        self.assertIn('ON CONFLICT (campaign_id) DO NOTHING', sql)
        self.assertIn('ON CONFLICT (session_id, event_key) DO NOTHING', sql)

    def test_completed_import_keeps_original_event(self):
        out, _ = parse(CMD.encode() + b'\r\n' + INIT + DONE, [(1, CMD, 0)])
        summary = {k: v for k, v in out[0].items() if k not in ('kind', 'artifact')}
        with patch.object(multi, 'run', return_value='mock result') as run:
            multi.apply_campaign(summary, 'a' * 12, str(uuid4()), TASK)
        sql = run.call_args.args[1].decode()
        self.assertIn('libfuzzer_campaign_finished', sql)
        self.assertIn("'final_metrics'", sql)

    def test_incomplete_stopped_metadata_fails_closed(self):
        out, _ = parse(CMD.encode() + b'\r\n' + INIT + STOP, [(1, CMD, 72)])
        summary = {k: v for k, v in out[0].items() if k not in ('kind', 'artifact')}
        summary['config']['command_exit_status'] = 130
        with patch.object(multi, 'run') as run:
            with self.assertRaises(ValueError):
                multi.apply_campaign(summary, 'a' * 12, str(uuid4()), TASK)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
