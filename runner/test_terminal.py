import os
from pathlib import Path
import tempfile
import threading
import unittest
from terminal import run,validate
from agent import Problem

class TerminalTests(unittest.TestCase):
    def test_original_write_pipe_and_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=run({'cwd':tmp,'command':"printf 'direct original' | /usr/bin/tee result.txt"},None,threading.Event(),None)
            self.assertEqual(r['exit_code'],0)
            self.assertEqual((Path(tmp)/'result.txt').read_text(),'direct original')
            self.assertFalse(r['sandboxed'])
            r=run({'cwd':tmp,'command':'exit 7'},None,threading.Event(),None)
            self.assertEqual(r['exit_code'],7)
    def test_timeout_terminates_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=run({'cwd':tmp,'command':'exec /bin/sleep 20','timeout_sec':1},None,threading.Event(),None)
            self.assertTrue(r['timed_out'])
    def test_invalid_cwd(self):
        with self.assertRaises(Problem):validate({'cwd':'relative','command':'pwd'})

    def test_output_preserves_utf8_head_tail(self):
        import sys
        from agent import run_task, MAX_OUTPUT
        r = run_task({'argv':[sys.executable, '-c', "print('START' + '한글'*30000 + 'FINAL_ERROR_MARKER')"], 'cwd':'/tmp'})
        self.assertTrue(r['truncated'])
        self.assertTrue(r['stdout'].startswith('START'))
        self.assertTrue(r['stdout'].endswith('FINAL_ERROR_MARKER\n'))
        self.assertNotIn('\ufffd', r['stdout'])
        self.assertLessEqual(len(r['stdout'].encode()), MAX_OUTPUT)
        self.assertGreater(r['output']['stdout']['omitted_bytes'], 0)
        self.assertEqual(r['output']['stdout']['layout'], 'head_tail')

    def test_cancel_before_start_does_not_execute(self):
        from agent import run_task
        with tempfile.TemporaryDirectory() as tmp:
            stop = threading.Event()
            stop.set()
            r = run_task({'argv':['/usr/bin/touch', 'never.txt'], 'cwd':tmp}, stopping=stop)
            self.assertTrue(r['interrupted'])
            self.assertEqual(r['cleanup_scope'], 'not_started')
            self.assertFalse((Path(tmp)/'never.txt').exists())

    def test_group_permission_error_preserves_result_and_reaps_child(self):
        import sys
        from unittest.mock import patch
        from agent import run_task
        with tempfile.TemporaryDirectory() as tmp:
            with patch('agent.os.killpg', side_effect=PermissionError('test-only')):
                r = run_task({'argv':[sys.executable, '-c', "import time; print('ready', flush=True); time.sleep(20)"], 'cwd':tmp, 'timeout_sec':1}, Path(tmp))
            self.assertTrue(r['timed_out'])
            self.assertIsNotNone(r['exit_code'])
            self.assertEqual(r['stdout'], 'ready\n')
            self.assertEqual(r['cleanup_warning'], 'group_signal_denied')
            self.assertFalse((Path(tmp)/'active-process.json').exists())
