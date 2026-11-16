import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import setup
import manage
import cloudflare_connect


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = self.root / '.runtime' / 'pickle-runner'
        self.store = self.root / '.runtime' / 'cloudflare-setup'
        self.patches = [patch.object(manage, 'ROOT', self.root), patch.object(manage, 'RUNTIME', self.runtime), patch.object(setup, 'STORE', self.store)]
        for p in self.patches:p.start()
        with contextlib.redirect_stdout(io.StringIO()):manage.initialize(18796)

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def test_new_install_terminal_and_existing_settings_preserved(self):
        path = self.runtime/'config.json'
        self.assertTrue(json.loads(path.read_text())['terminal_enabled'])
        original = path.read_bytes()
        token = (self.runtime/'agent-token').read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):manage.initialize(28796)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual((self.runtime/'agent-token').read_bytes(), token)

    def test_cloudflare_config_is_local_only_and_uses_installed_port(self):
        result = setup.configure('example.net', 'runner.example.net', ['app.example.net'])
        self.assertFalse(result['cloudflare_changed'])
        config = json.loads((self.store/'settings.json').read_text())
        self.assertEqual(config['port'], 18796)
        self.assertEqual(config['preserve_hostnames'], ['app.example.net'])
        self.assertEqual((self.store/'settings.json').stat().st_mode & 0o077, 0)

    def test_invalid_host_and_retarget_are_rejected(self):
        for host in ['runner.other.net', 'https://runner.example.net', '*.example.net', 'example.net', 'x.example.net/path']:
            with self.subTest(host=host), self.assertRaises(ValueError):setup.configure('example.net',host)
        setup.configure('example.net','runner.example.net')
        (self.store/'resources.json').write_text('{}')
        with self.assertRaises(ValueError):setup.configure('example.net','other.example.net')
        self.assertTrue(setup.configure('example.net','runner.example.net')['configured'])

    def test_status_never_reads_or_returns_credentials(self):
        setup.configure('example.net','runner.example.net')
        (self.store/'api-token').write_text('test-private-placeholder')
        result = setup.status()
        self.assertTrue(result['setup_token_present'])
        self.assertNotIn('test-private-placeholder', json.dumps(result))
        self.assertNotIn((self.runtime/'agent-token').read_text().strip(),json.dumps(result))

    def test_preserved_dns_snapshot_is_compared_without_mutations(self):
        setup.configure('example.net','runner.example.net')
        obj = object.__new__(cloudflare_connect.Setup)
        obj.plan = {'preserve_hostnames':['app.example.net']};obj.zone='/zones/fixture'
        records=[{'id':'fixture-id','name':'app.example.net','content':'192.0.2.1','type':'A'}]
        with patch.object(cloudflare_connect,'STORE',self.store), patch.object(obj,'api',return_value=records) as api:
            self.assertTrue(obj.preserve_app())
            self.assertTrue(obj.preserve_app())
            api.return_value=[dict(records[0], content='192.0.2.2')]
            with self.assertRaises(RuntimeError):obj.preserve_app()
            self.assertTrue(all(len(c.args)==1 for c in api.call_args_list))

    def test_install_refuses_occupied_port_before_writing_service(self):
        import socket
        from types import SimpleNamespace
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            config_path=self.runtime/'config.json'
            config=json.loads(config_path.read_text());config['port']=listener.getsockname()[1]
            config_path.write_text(json.dumps(config))
            plist=self.root/'LaunchAgents'/'fixture.plist'
            with patch.object(manage,'PLIST',plist), patch.object(manage.subprocess,'run',return_value=SimpleNamespace(returncode=1)) as proc:
                with self.assertRaises(SystemExit):manage.service('install')
                self.assertFalse(plist.exists())
                self.assertEqual(proc.call_count,1)

    def test_connect_checks_auth_before_removing_management_token(self):
        import client, check_remote
        self.store.mkdir(parents=True)
        token=self.store/'api-token';token.write_text('fake-management-token')
        (self.runtime/'client-remote.json').write_text('{}')
        with patch.object(setup.sys,'platform','darwin'), patch.object(setup.shutil,'which',return_value='/fake/cloudflared'), patch.object(client,'request',return_value=(200,{'service':'pickle-runner'})), patch.object(cloudflare_connect,'Setup') as cls, patch.object(check_remote,'check',return_value={'passed':True}):
            obj=cls.return_value;obj.account='/accounts/fake';obj.state={'tunnel_id':'fake'}
            obj.api.return_value={'status':'healthy'}
            result=setup.connect()
            self.assertTrue(result['connected'])
            self.assertFalse(token.exists())
            obj.provision.assert_called_once();obj.service.assert_called_once();obj.publish.assert_called_once();obj.credential_metadata.assert_called_once()

    def test_failed_auth_check_retains_management_token_for_repair(self):
        import client, check_remote
        self.store.mkdir(parents=True)
        token=self.store/'api-token';token.write_text('fake-management-token')
        (self.runtime/'client-remote.json').write_text('{}')
        with patch.object(setup.sys,'platform','darwin'), patch.object(setup.shutil,'which',return_value='/fake/cloudflared'), patch.object(client,'request',return_value=(200,{'service':'pickle-runner'})), patch.object(cloudflare_connect,'Setup') as cls, patch.object(check_remote,'check',return_value={'passed':False}), patch.object(setup.time,'sleep'):
            obj=cls.return_value;obj.account='/accounts/fake';obj.state={'tunnel_id':'fake'}
            obj.api.return_value={'status':'healthy'}
            with self.assertRaises(ValueError):setup.connect()
            self.assertTrue(token.exists())
