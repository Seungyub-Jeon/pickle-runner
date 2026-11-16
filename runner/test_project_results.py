import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from agent import Problem
from projects import Projects
from project_cli import argv_for

class ResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/'projects/demo').mkdir(parents=True)
        (self.root/'projects/other').mkdir()
        self.projects=Projects(self.root/'projects',self.root/'runtime')
        self.job='a'*32
        self.work=self.root/'runtime/project-runs'/self.job/'work'
        self.work.mkdir(parents=True)
        (self.work/'output.md').write_text('actual result')
        self.record={'project':'demo','changed_files':['output.md'],'output_hashes':{'output.md':hashlib.sha256(b'actual result').hexdigest()}}
        self.args={'project':'demo','job_id':self.job,'path':'output.md'}
    def tearDown(self):self.tmp.cleanup()
    def test_reads_actual_content_and_rejects_changed_result(self):
        self.assertEqual(self.projects.result_files(self.args,self.record,True)['content'],'actual result')
        (self.work/'output.md').write_text('tampered')
        with self.assertRaises(Problem) as ctx:self.projects.result_files(self.args,self.record,True)
        self.assertEqual(ctx.exception.code,'result_changed')
        self.assertEqual(self.projects.result_files(self.args,self.record)['files'][0]['status'],'changed_since_completion')
    def test_cross_project_and_unlisted_file(self):
        for change in [{'project':'other'},{'path':'../before.json'},{'path':'.env'},{'path':'unlisted.md'}]:
            with self.assertRaises(Problem):self.projects.result_files({**self.args,**change},self.record,True)
    def test_symlink_directory_and_file(self):
        (self.work/'output.md').unlink();(self.work/'output.md').symlink_to(self.root/'projects/demo')
        with self.assertRaises(Problem):self.projects.result_files(self.args,self.record,True)
        self.work.rename(self.work.with_name('original'))
        self.work.symlink_to(self.work.with_name('original'),target_is_directory=True)
        with self.assertRaises(Problem):self.projects.result_files(self.args,self.record,True)
    def test_legacy_integrity_is_explicit(self):
        self.record.pop('output_hashes')
        result=self.projects.result_files(self.args,self.record,True)
        self.assertEqual(result['integrity'],'legacy_current_only')
    def test_close_does_not_force_extra_sections(self):
        prompt=argv_for('codex','/bin/echo',self.work,'close','한 줄만 추가하세요')[-1]
        self.assertNotIn('현재 상태·검증·다음 작업을 기록',prompt)
        self.assertTrue(prompt.endswith('한 줄만 추가하세요'))

    def test_bridge_result_binding_and_pending(self):
        import time
        from agent import Bridge, canonical, TERMINAL
        runtime=self.root/'runtime'
        (runtime/'agent-token').write_text('test-only-'+'x'*48)
        bridge=Bridge({'workspace':str(self.root/'projects/demo'),'project_root':str(self.root/'projects'),'tasks':{}},runtime)
        try:
            with bridge.lock,bridge.db:
                bridge.db.execute('INSERT INTO jobs (id,request_id,fingerprint,action,args,state,created,updated,result) VALUES (?,?,?,?,?,?,?,?,?)',
                    (self.job,'original','f','project.work',canonical({'project':'demo','tool':'codex','kind':'work'}),'running',time.time(),time.time(),canonical(self.record)))
            job,_=bridge.submit({'request_id':'pending-read','action':'project.result.read','args':self.args})
            for _ in range(100):
                result=bridge.get(job['id'])
                if result['state'] in TERMINAL:break
                time.sleep(.02)
            self.assertEqual(result['error']['code'],'result_pending')
            with bridge.lock,bridge.db:bridge.db.execute("UPDATE jobs SET state='succeeded' WHERE id=?",(self.job,))
            job,_=bridge.submit({'request_id':'finished-read','action':'project.result.read','args':self.args})
            for _ in range(100):
                result=bridge.get(job['id'])
                if result['state'] in TERMINAL:break
                time.sleep(.02)
            self.assertEqual(result['result']['content'],'actual result')
            self.assertEqual(result['result']['integrity'],'verified_at_completion')
            original=next(item for item in bridge.state()['recent'] if item['id']==self.job)
            self.assertIn('demo / codex / work',original['say'])
            self.assertIn('원본 미반영',original['say'])
        finally:
            bridge.stopping.set();bridge.worker.join(3);bridge.db.close();os.close(bridge.workspace.fd)

    def test_output_collection_does_not_follow_links_or_block_on_fifo(self):
        from project_cli import collect_outputs
        os.mkfifo(self.work/'pipe')
        (self.work/'link').symlink_to(self.root/'projects')
        hashes=collect_outputs(self.work)
        self.assertEqual(hashes['pipe'],'unreadable')
        self.assertEqual(hashes['link'],'unreadable')
        self.assertEqual(hashes['output.md'],self.record['output_hashes']['output.md'])

    def test_acceptance_exact_append_rejects_extra_sections_and_files(self):
        from project_acceptance import evaluate, validate
        before={'output.md':hashlib.sha256(b'actual result').hexdigest()}
        spec={'allowed_changed_files':['output.md'],'files':[{'path':'output.md','append_exact':'\none line\n'}]}
        (self.work/'output.md').write_text('actual result\none line\n')
        self.assertEqual(evaluate(spec,self.work,before,['output.md'])['status'],'passed')
        (self.work/'output.md').write_text('actual result\nextra section\none line\n')
        self.assertEqual(evaluate(spec,self.work,before,['output.md'])['status'],'failed')
        (self.work/'output.md').write_text('actual result\none line\n')
        self.assertEqual(evaluate(spec,self.work,before,['output.md','extra.md'])['status'],'failed')
        with self.assertRaises(Problem):validate({'files':[{'path':'../secret'}]})
