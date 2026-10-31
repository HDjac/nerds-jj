"""Host-only unit tests. No Docker or PostgreSQL required."""
from pathlib import Path
import importlib.util
import unittest
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
import sys
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('pilot1_auto_transition',SCRIPTS/'pilot1_auto_transition.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ROWS=[
    ['1','dense_v2','ready','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','active','bfa6705c456c','nerds-pilot1-runtime'],
    ['2','lowyield_v1','locked','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','active','bfa6705c456c','nerds-pilot1-runtime'],
]
MARKER={'position':1,'task_code':'dense_v2','outcome':'completed','requested_at':'2026-10-26T19:00:00-06:00'}

class AutoHandoffTests(unittest.TestCase):
    def test_finish_task_one_releases_second(self):
        self.assertEqual(m.choose_action(ROWS,MARKER),('advance','completed'))
    def test_skip_task_one_remains_distinct(self):
        self.assertEqual(m.choose_action(ROWS,dict(MARKER,outcome='skipped')),('advance','skipped'))
    def test_skip_second_finalizes_session(self):
        rows=[list(ROWS[0]),list(ROWS[1])]
        rows[0][2]='completed';rows[1][2]='ready'
        self.assertEqual(m.choose_action(rows,dict(MARKER,position=2,task_code='lowyield_v1',outcome='skipped')),('complete','skipped'))
    def test_missing_marker_never_processes(self):
        self.assertIsNone(m.choose_action(ROWS,None))
    def test_stale_or_malformed_request_is_rejected(self):
        for updates in ({'position':2},{'task_code':'lowyield_v1'},{'outcome':'aborted'},
                        {'requested_at':'yesterday'}, {'position':'1'}):
            with self.subTest(updates=updates), self.assertRaises(RuntimeError):
                m.choose_action(ROWS,dict(MARKER,**updates))
    @patch.object(m,'container_identity')
    @patch.object(m,'assignment',return_value=ROWS)
    @patch.object(m,'marker_from_container',return_value=MARKER)
    @patch.object(m.subprocess,'run')
    def test_preview_never_launches_privileged_transition(self, run, marker, rows, identity):
        self.assertEqual(m.check_once(False),'pending')
        run.assert_not_called()
    @patch.object(m,'container_identity')
    @patch.object(m,'assignment',return_value=ROWS)
    @patch.object(m,'marker_from_container',return_value=MARKER)
    @patch.object(m.subprocess,'run')
    def test_apply_uses_existing_guarded_transition(self, run, marker, rows, identity):
        run.return_value.returncode=0
        self.assertEqual(m.check_once(True),'advanced')
        args=run.call_args.args[0]
        self.assertIn('pilot1_lifecycle.py',' '.join(args))
        self.assertEqual(args[-5:],['--action','advance','--outcome','completed','--apply'])
    @patch.object(m,'container_identity')
    @patch.object(m,'assignment',return_value=ROWS)
    @patch.object(m,'marker_from_container',return_value=MARKER)
    @patch.object(m.subprocess,'run')
    def test_failed_transition_halts_without_retry(self, run, marker, rows, identity):
        run.return_value.returncode=1
        with self.assertRaisesRegex(RuntimeError,'Automatic watcher halted'):
            m.check_once(True)
        self.assertEqual(run.call_count,1)

if __name__=='__main__': unittest.main()
