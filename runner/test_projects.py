import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from projects import Projects
from agent import Problem

class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'projects'/'demo').mkdir(parents=True)
        self.home = self.root/'projects'/'demo'
        self.projects = Projects(self.root/'projects', self.root/'runtime')
    def tearDown(self):
        self.tmp.cleanup()
    def test_backup_conflict_and_create(self):
        self.projects.write('demo', 'x.py', 'old', None, 'create')
        digest = hashlib.sha256(b'old').hexdigest()
        self.projects.write('demo', 'x.py', 'new', digest, 'update')
        self.assertEqual((self.root/'runtime/project-file-backups/update/before.bin').read_bytes(), b'old')
        with self.assertRaises(Problem):
            self.projects.write('demo', 'x.py', 'lost', digest, 'conflict')
        self.assertEqual((self.home/'x.py').read_text(), 'new')
    def test_credentials_and_escape(self):
        for path in ['../escape', '.env', '.ssh/id_rsa', 'credentials.json']:
            with self.assertRaises(Problem):
                self.projects.read('demo', path)
        (self.home/'secret.txt').write_text('-----BEGIN PRIVATE KEY-----')
        with self.assertRaises(Problem):
            self.projects.read('demo', 'secret.txt')
        (self.home/'link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(Problem):
            self.projects.read('demo', 'link/file.txt')
    def test_project_symlink_and_hardlink(self):
        (self.root/'projects'/'alias').symlink_to(self.home, target_is_directory=True)
        with self.assertRaises(Problem):
            self.projects.read('alias', 'x.py')
        (self.home/'a.py').write_text('a')
        os.link(self.home/'a.py', self.home/'b.py')
        with self.assertRaises(Problem):
            self.projects.read('demo', 'b.py')
        self.assertEqual(self.projects.listing()['count'], 1)

    def test_bridge_duplicate_write_and_restart(self):
        import agent
        import time
        runtime=self.root/'bridge'
        runtime.mkdir()
        (runtime/'agent-token').write_text('test-only-'+'x'*48)
        config={'workspace':str(self.home), 'project_root':str(self.root/'projects'), 'tasks':{}}
        bridge=agent.Bridge(config,runtime)
        body={'request_id':'project-create', 'action':'project.files.write',
              'args':{'project':'demo','path':'bridge.py','content':'saved','expected_sha256':None}}
        try:
            job,reused=bridge.submit(body)
            for _ in range(100):
                result=bridge.get(job['id'])
                if result['state'] in agent.TERMINAL:break
                time.sleep(.02)
            self.assertEqual(result['state'],'succeeded')
            self.assertTrue(bridge.submit(body)[1])
        finally:
            bridge.stopping.set();bridge.worker.join(3);bridge.db.close();os.close(bridge.workspace.fd)
        bridge=agent.Bridge(config,runtime)
        try:
            same,reused=bridge.submit(body)
            self.assertTrue(reused)
            self.assertEqual(same['id'],job['id'])
            self.assertEqual((self.home/'bridge.py').read_text(),'saved')
        finally:
            bridge.stopping.set();bridge.worker.join(3);bridge.db.close();os.close(bridge.workspace.fd)

    def test_restore_refuses_intervening_edit(self):
        from recover_project import restore
        self.projects.write('demo','x.py','before',None,'initial')
        h=hashlib.sha256(b'before').hexdigest()
        self.projects.write('demo','x.py','after',h,'change')
        restore(self.projects,'change')
        self.assertEqual((self.home/'x.py').read_text(),'before')
        with self.assertRaises(Problem):restore(self.projects,'change')

    def test_cli_arguments_do_not_accept_shell_or_arbitrary_tools(self):
        from project_cli import argv_for
        args=argv_for('codex','/bin/echo',self.home,'explore','$(touch /tmp/escape)')
        self.assertIn('default_permissions="runner"',args)
        self.assertTrue(args[-1].endswith('$(touch /tmp/escape)'))
        with self.assertRaises(Problem):argv_for('claude','/bin/echo',self.home,'work','test')

    def test_snapshot_omits_credentials_and_preserves_original(self):
        from project_cli import snapshot
        (self.home/'.env').write_text('fake fixture')
        (self.home/'source.py').write_text('original')
        target=self.root/'copy';target.mkdir()
        result=snapshot(self.projects,'demo',target)
        self.assertNotIn('.env',result['files'])
        (target/'source.py').write_text('changed')
        self.assertEqual((self.home/'source.py').read_text(),'original')
