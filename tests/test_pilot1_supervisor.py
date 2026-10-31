import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'scripts'/'pilot1_multi_supervisor.py'
if not SRC.exists(): SRC=ROOT/'patch'/'pilot1_multi_supervisor.py'
spec=importlib.util.spec_from_file_location('pilot1_supervisor_test',SRC)
supervisor=importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name]=supervisor
spec.loader.exec_module(supervisor)


def row(i):
    session=str(uuid4()); first=str(uuid4()); second=str(uuid4())
    return '|'.join((session,f'nerds-pilot1-person-{i}',f'{i:012x}',first,
                     'dense_v2','ready',second,'lowyield_v1','locked'))


class SupervisorTests(unittest.TestCase):
    def test_distinct_sessions_are_discovered(self):
        got=supervisor.parse_rows(row(1)+'\n'+row(2)+'\n')
        self.assertEqual(len(got),2)
        self.assertEqual(got[0].released,got[0].first_id)
        self.assertEqual(got[1].released,got[1].first_id)

    def test_duplicate_container_fails_closed(self):
        r1=row(1).split('|');r2=row(1).split('|')
        with self.assertRaises(ValueError):
            supervisor.parse_rows('|'.join(r1)+'\n'+'|'.join(r2))

    def test_unexpected_task_status_fails_closed(self):
        bad=row(3).split('|');bad[5]='skipped'
        with self.assertRaises(ValueError):supervisor.parse_rows('|'.join(bad))

    def test_released_task_two_is_identified(self):
        r=row(3).split('|');r[5]='completed';r[8]='active'
        result=supervisor.parse_rows('|'.join(r))[0]
        self.assertEqual(result.released,result.second_id)

    def test_marker_is_exclusive_and_persistent(self):
        with tempfile.TemporaryDirectory() as t:
            directory=supervisor.state_dir(Path(t),str(uuid4()))
            path=directory/'transition-inflight.json'
            supervisor.write_once(path,{'status':'inflight'})
            self.assertTrue(supervisor.blocked(directory))
            with self.assertRaises(FileExistsError):
                supervisor.write_once(path,{'status':'duplicate'})

    def test_per_session_environment_overrides_old_pilot(self):
        a=supervisor.parse_rows(row(5))[0]
        env=supervisor.environment(a)
        self.assertEqual(env['NERDS_SESSION_ID'],a.session)
        self.assertEqual(env['NERDS_CONTAINER'],a.container)
        self.assertEqual(env['NERDS_INSTANCE_ID'],a.instance)

    def test_dry_run_never_starts_transition(self):
        a=supervisor.parse_rows(row(7))[0]
        with patch.object(supervisor.subprocess,'Popen') as popen:
            result=supervisor.start_transition(a,Path('/unused'),True)
            self.assertIn('preview',result)
            popen.assert_not_called()

    def test_completed_and_failed_worker_states(self):
        with tempfile.TemporaryDirectory() as t:
            s1=str(uuid4());s2=str(uuid4())
            class Proc:
                def __init__(self,rc):self.rc=rc
                def poll(self):return self.rc
            workers={s1:Proc(0),s2:Proc(1)}
            d=supervisor.state_dir(Path(t),s1)
            supervisor.write_once(d/'transition-inflight.json',{'session':s1})
            d2=supervisor.state_dir(Path(t),s2)
            supervisor.write_once(d2/'transition-inflight.json',{'session':s2})
            supervisor.finish_workers(workers,Path(t))
            self.assertFalse((d/'transition-inflight.json').exists())
            self.assertTrue((d2/'needs-review.json').exists())
            self.assertTrue((d2/'transition-inflight.json').exists())
            self.assertEqual(workers,{})

    def test_installer_matches_source_signatures(self):
        inst_path=ROOT/'install_supervisor.py'
        if not inst_path.exists():
            deployed=(ROOT/'scripts/pilot1_lifecycle.py').read_text()
            self.assertIn('NERDS_SESSION_ID',deployed)
            self.assertIn('pilot1-lifecycle-',deployed)
            return
        spec2=importlib.util.spec_from_file_location('supervisor_installer_test',inst_path)
        inst=importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(inst)
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)
            (repo/'instance').mkdir()
            (repo/'instance/instance-api.py').write_text('app=1\n')
            (repo/'scripts').mkdir()
            (repo/'scripts/pilot1_lifecycle.py').write_text(
                inst.LIFECYCLE_OLD+"lock_path=root/'pilot1-lifecycle.lock'\n")
            (repo/'scripts/pilot1_auto_transition.py').write_text(
                "lock=root/'pilot1-auto-transition.lock'\n")
            updates=inst.construct(repo)
            self.assertIn('NERDS_SESSION_ID',updates['scripts/pilot1_lifecycle.py'])
            self.assertIn("+'",updates['scripts/pilot1_lifecycle.py'])
            self.assertIn('scripts/pilot1_multi_supervisor.py',updates)


if __name__=='__main__':unittest.main()
