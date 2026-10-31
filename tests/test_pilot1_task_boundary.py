"""Offline tests for NERDs Pilot 1 task-boundary CLI evidence segregation."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


def load_source():
    modules = ("pilot1_collect_cli", "pilot1_ingest_cli_events",
               "pilot1_import_campaign_multi", "pilot1_import_crash_campaign")
    originals = {k: sys.modules.get(k) for k in modules}
    try:
        for name in modules:
            sys.modules[name] = types.ModuleType(name)
        spec = importlib.util.spec_from_file_location(
            "pilot1_auto_ingest_task_boundary_tests", Path(__file__).resolve().parents[1] / "scripts" / "pilot1_auto_ingest.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for name in modules:
            if originals[name] is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = originals[name]
    return mod


class TaskBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_source()

    def test_only_new_task_recordings_are_read(self):
        old, new = '20261023T221241Z-2726', '20261027T020236Z-9901'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for tag in (old, new):
                for ext in ('.out', '.timing', '.commands.jsonl'):
                    (root / (tag + ext)).write_text(tag)
            with self.m.task_recording_view(root, '20261027T020235Z') as view:
                self.assertEqual([t for t in self.m.archived_tag_files(view)], [new])
                self.assertFalse((view / (old + '.out')).exists())
                self.assertEqual((view / (new + '.commands.jsonl')).read_text(), new)
            self.assertEqual(len(list(root.glob('*.out'))), 2)  # Raw evidence preserved

    def test_same_second_of_release_is_eligible(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '20261027T020235Z-9901.commands.jsonl').write_text('{}\n')
            with self.m.task_recording_view(root, '20261027T020235Z') as view:
                self.assertEqual(len(list(view.iterdir())), 1)

    def test_task_one_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.m.task_recording_view(root, None) as view:
                self.assertEqual(root, view)

    def test_missing_release_event_fails_closed(self):
        for response in ('2|', '9|20261027T020235Z', '', '2|not-a-date'):
            with self.subTest(response=response):
                with patch.object(self.m.subprocess, 'run', return_value=types.SimpleNamespace(
                        returncode=0, stdout=response, stderr='')):
                    with self.assertRaises(RuntimeError):
                        self.m.authoritative_task_recording_floor('a'*36, 'b'*36)

    def test_db_task2_boundary_and_first_task(self):
        for response, expected in [('1|', None), ('2|20261027T020235Z', '20261027T020235Z')]:
            with patch.object(self.m.subprocess, 'run', return_value=types.SimpleNamespace(
                    returncode=0, stdout=response + '\n', stderr='')):
                actual = self.m.authoritative_task_recording_floor('a'*36, 'b'*36)
                self.assertEqual(actual, expected)

    def test_old_crash_not_imported_under_second_task(self):
        old, new = '20261023T221241Z-2726', '20261027T020236Z-9901'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for tag in (old, new):
                for ext in ('.out', '.timing', '.commands.jsonl'):
                    (root / (tag + ext)).write_text(tag)
            processed=[]
            m=self.m
            m.collector.check_assignment = lambda *_: 'bfa6705c456c'
            m.collector.sync_once = lambda *args: (6,0,0)
            m.ingest_events = lambda view, *args: (processed.append(('events',tuple(m.archived_tag_files(view)))) or 1,0)
            m.read_campaigns = lambda view,tag,task: ([{'harness_id':'c','status':'crashed'}],[])
            m.import_campaign = lambda item,*args: processed.append(('crash_import', item['harness_id'])) or 'imported'
            args=types.SimpleNamespace(container='nerds-pilot1-runtime', session_id='session',task_run_id='lowyield',max_chunk_mib=4,apply=True,archive_root=root,once=True)
            with patch.object(m,'read_campaigns',side_effect=lambda view,tag,task: processed.append(('campaign',tag)) or ([], [])):
                result=m.run_cycle(args,root,{'tag_floor':'20261027T020235Z'})
            self.assertIn(('events',(new,)),processed)
            self.assertIn(('campaign',new),processed)
            self.assertNotIn(('campaign',old),processed)
            self.assertNotIn(('events',(old,)),processed)

if __name__=='__main__': unittest.main()
