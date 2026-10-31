"""Offline mock-filesystem checks; does not touch real Docker/PostgreSQL."""
import contextlib
import getpass
import io
import importlib.util
import json
import os
import stat
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec=importlib.util.spec_from_file_location('pilot1_lifecycle',SCRIPTS/'pilot1_lifecycle.py')
lc=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.base=self.root/'fuzz-study'
        self.ref=self.root/'released-reference'
        self.protected=self.root/'task-bundles'
        for d in (self.base,self.ref,self.protected): d.mkdir()
        for code in ('dense_v2','lowyield_v1'):
            folder=self.protected/code
            folder.mkdir()
            (folder/'Makefile').write_text(f'# {code}\n')
            (folder/'main.c').write_text(code)
        (self.ref/'current').mkdir()
        (self.ref/'current'/'Makefile').write_text('# dense reference')
        (self.base/'work').mkdir()
        (self.base/'work'/'Makefile').write_text('# modified dense')
        (self.base/'runs').mkdir()
        (self.base/'reference').symlink_to(self.ref/'current')
        (self.ref/'active-task.json').write_text(json.dumps({'task_code':'dense_v2','position':1}))

    def code(self,src):
        # Replace full paths without colliding with the shorter protected base.
        return (src.replace('/home/user/fuzz-study',str(self.base))
                   .replace('/opt/nerds/released-reference',str(self.ref))
                   .replace('/opt/nerds/task-bundles',str(self.protected)))

    def remote(self,code,params=None):
        # The remote snippets run as root in Docker. Simulate ONLY chown;
        # keep chmod, moves, archive visibility, and file I/O real, confined
        # to this test's temporary directory. Executing in-process avoids
        # Python subprocess startup overhead on slower WSL hosts.
        # Root can move a read-only directory between parent directories.
        # An ordinary Linux user cannot change the source's internal '..'
        # entry. Simulate only that privilege for temporary test paths;
        # retain actual filesystem renames and preserve directory modes.
        actual_rename = os.rename
        def rename_as_root(src, dst, *args, **kwargs):
            path = Path(src)
            if (path.is_dir() and not path.is_symlink()
                    and path.parent != Path(dst).parent):
                mode = stat.S_IMODE(path.stat().st_mode)
                if not mode & stat.S_IWUSR:
                    path.chmod(mode | stat.S_IWUSR)
                    try:
                        actual_rename(src, dst, *args, **kwargs)
                    except BaseException:
                        path.chmod(mode)
                        raise
                    Path(dst).chmod(mode)
                    return
            return actual_rename(src, dst, *args, **kwargs)

        output=io.StringIO()
        with (patch('os.chown', lambda *args, **kwargs: None),
              patch('os.rename', rename_as_root),
              patch('sys.stdin', io.StringIO(json.dumps(params or {}))),
              contextlib.redirect_stdout(output)):
            exec(self.code(code), {'__name__':'__main__'})
        return output.getvalue()

    def test_stage_swap_prevents_early_access_and_preserves_first_task(self):
        self.remote(lc.REMOTE_PREFLIGHT,{'code':'dense_v2','position':1})
        self.remote(lc.REMOTE_STAGE,{'next_code':'lowyield_v1','next_task_run_id':'abc'})
        self.assertFalse((self.ref/'current'/'main.c').exists())
        self.assertEqual((self.base/'work'/'Makefile').read_text(),'# modified dense')
        self.assertTrue((self.protected/'.lifecycle-stage-reference'/'main.c').exists())
        self.remote(lc.REMOTE_SWAP,{'uid':os.getuid(),'gid':os.getgid()})
        self.assertEqual(json.loads((self.ref/'active-task.json').read_text())['task_code'],'lowyield_v1')
        self.assertEqual((self.base/'work'/'main.c').read_text(),'lowyield_v1')
        self.assertTrue((self.base/'.previous-work'/'Makefile').exists())
        self.assertTrue((self.protected/'.lifecycle-previous-reference'/'Makefile').exists())
        self.remote(lc.REMOTE_PREFLIGHT,{'code':'lowyield_v1','position':2})
        self.remote(lc.REMOTE_FINISH,{'code':'lowyield_v1','outcome':'completed'})
        self.assertEqual(json.loads((self.ref/'active-task.json').read_text())['status'],'completed')

    def test_released_source_files_and_nested_directories_are_writable(self):
        import stat
        src=self.protected/'lowyield_v1'
        (src/'nested').mkdir()
        (src/'nested'/'editable.c').write_text('int main(void) { return 0; }\n')
        (src/'Makefile').chmod(0o444)
        (src/'nested'/'editable.c').chmod(0o444)
        (src/'nested').chmod(0o555)
        self.addCleanup(lambda: (src/'nested').chmod(0o755))
        self.remote(lc.REMOTE_STAGE,{'next_code':'lowyield_v1','next_task_run_id':'abc'})
        self.remote(lc.REMOTE_SWAP,{'uid':os.getuid(),'gid':os.getgid()})
        self.assertTrue((self.base/'work'/'Makefile').stat().st_mode & stat.S_IWUSR)
        self.assertTrue((self.base/'work'/'nested').stat().st_mode & stat.S_IWUSR)
        self.assertTrue((self.base/'work'/'nested'/'editable.c').stat().st_mode & stat.S_IWUSR)
        self.assertFalse((self.ref/'current'/'Makefile').stat().st_mode & stat.S_IWUSR)

    def test_rollback_restores_previous_task_files(self):
        self.remote(lc.REMOTE_STAGE,{'next_code':'lowyield_v1','next_task_run_id':'abc'})
        self.remote(lc.REMOTE_SWAP,{'uid':os.getuid(),'gid':os.getgid()})
        local_user=getpass.getuser()
        self.remote(lc.REMOTE_ROLLBACK.replace("getpwnam('user')",f"getpwnam('{local_user}')"))
        self.assertEqual((self.base/'work'/'Makefile').read_text(),'# modified dense')
        self.assertEqual(json.loads((self.ref/'active-task.json').read_text())['task_code'],'dense_v2')

    def test_source_event_keys_do_not_collide_between_tasks(self):
        watcher=(SCRIPTS/'pilot1_track_sources.py').read_text()
        self.assertIn("'source:2:'||(data->>'seq')",watcher)
        self.assertIn("THEN 'source:'||(data->>'seq')",watcher)

    def test_skip_request_marker_is_distinct_and_matching(self):
        marker=self.base/'.finish-request.json'
        marker.write_text(json.dumps({
            'task_code':'dense_v2', 'position':1,
            'outcome':'skipped', 'requested_at':'2026-10-26T18:00:00-06:00'
        }))
        text=self.remote(lc.REMOTE_MARKER, {
            'code':'dense_v2','position':1,'outcome':'skipped'
        })
        self.assertEqual(json.loads(text)['outcome'],'skipped')
        with self.assertRaises(AssertionError):
            self.remote(lc.REMOTE_MARKER, {
                'code':'dense_v2','position':1,'outcome':'completed'
            })
        self.assertTrue(marker.is_file())

    def test_skip_first_task_still_releases_second(self):
        first=['1','dense_v2','ready','00000000-0000-4000-8000-000000000001']
        second=['2','lowyield_v1','locked','00000000-0000-4000-8000-000000000002']
        script=lc.transition_sql(first,second,'advance','skipped',
                                 '2026-10-26T18:00:00-06:00')
        self.assertIn("SET status='skipped',ended_at=now()",script)
        self.assertIn("'task_skipped'",script)
        self.assertIn("'task_outcome_requested'",script)
        self.assertIn('2026-10-27T00:00:00.000000+00:00',script)
        self.assertIn("SET status='ready'",script)
        self.assertNotIn("'task_completed'",script)

    def test_skip_second_task_finishes_session_without_task_completion(self):
        first=['1','dense_v2','skipped','00000000-0000-4000-8000-000000000001']
        second=['2','lowyield_v1','ready','00000000-0000-4000-8000-000000000002']
        script=lc.transition_sql(first,second,'complete','skipped',
                                 '2026-10-27T00:00:00+00:00')
        self.assertIn("t1.status IN ('completed','skipped')",script)
        self.assertIn("SET status='skipped',ended_at=now()",script)
        self.assertIn("'task_skipped'",script)
        self.assertIn("'session_completed'",script)
        self.assertIn('"final_task_outcome":"skipped"',script)
        self.assertNotIn("'task_completed'",script)
        self.remote(lc.REMOTE_STAGE,{'next_code':'lowyield_v1','next_task_run_id':'abc'})
        self.remote(lc.REMOTE_SWAP,{'uid':os.getuid(),'gid':os.getgid()})
        self.remote(lc.REMOTE_FINISH,{'code':'lowyield_v1','outcome':'skipped'})
        self.assertEqual(json.loads((self.ref/'active-task.json').read_text())['status'],'skipped')

    def test_reject_unknown_task_outcome_and_naive_timestamp(self):
        first=['1','dense_v2','ready','00000000-0000-4000-8000-000000000001']
        second=['2','lowyield_v1','locked','00000000-0000-4000-8000-000000000002']
        with self.assertRaises(ValueError):
            lc.transition_sql(first,second,'advance','aborted')
        with self.assertRaises(ValueError):
            lc.transition_sql(first,second,'advance','skipped','2026-10-27T00:00:00')

    def test_transaction_contains_guards_and_events(self):
        first=['1','dense_v2','ready','00000000-0000-4000-8000-000000000001']
        second=['2','lowyield_v1','locked','00000000-0000-4000-8000-000000000002']
        advance=lc.transition_sql(first,second,'advance')
        complete=lc.transition_sql(first,second,'complete')
        self.assertIn('FOR UPDATE OF s,t1,t2',advance)
        self.assertIn("'task_completed'",advance)
        self.assertIn("'task_released'",advance)
        self.assertLess(advance.index("SET status='completed'"),advance.index("SET status='ready'"))
        self.assertIn("status='completed',ended_at=now()",complete)
        self.assertIn("'session_completed'",complete)
        self.assertNotIn('DELETE FROM',advance+complete)


if __name__=='__main__': unittest.main()
