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

    def test_partial_provisioning_status_resumes_connect(self):
        setup.configure('example.net', 'runner.example.net')
        (self.store/'api-token').write_text('fake-management-token')
        (self.runtime/'client-remote.json').write_text('{}')
        self.assertIn('setup.py connect', setup.status()['next'])
        (self.store/'api-token').unlink()
        self.assertIn('check_remote.py', setup.status()['next'])

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

    def test_connect_failure_reports_stage_without_exception_secret(self):
        import client
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup.shutil, 'which', return_value='/fake/cloudflared'), patch.object(client, 'request', side_effect=OSError('private-test-value')):
            with self.assertRaises(setup.ConnectionFailure) as caught:
                setup.connect()
        self.assertEqual(caught.exception.stage, 'local_health')
        self.assertNotIn('private-test-value', str(caught.exception))
        output = io.StringIO()
        with patch.object(setup.sys, 'argv', ['setup.py', 'connect']), patch.object(setup, 'connect', side_effect=caught.exception), contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            setup.main()
        self.assertEqual(json.loads(output.getvalue())['stage'], 'local_health')
        self.assertNotIn('private-test-value', output.getvalue())

    def test_tunnel_service_restarts_owned_loaded_label_without_bootout(self):
        from types import SimpleNamespace
        obj = object.__new__(cloudflare_connect.Setup)
        self.store.mkdir(parents=True)
        (self.store/'tunnel-token').write_text('fake')
        binary = self.root/'cloudflared';binary.write_text('fake')
        plist = self.root/'tunnel.plist'
        with patch.object(cloudflare_connect,'STORE',self.store), patch.object(cloudflare_connect,'PLIST',plist), patch.object(cloudflare_connect,'ROOT',self.root), patch.object(cloudflare_connect.shutil,'which',return_value=str(binary)), patch.object(obj,'verify_policy'), patch.object(cloudflare_connect.subprocess,'run') as proc:
            proc.return_value=SimpleNamespace(returncode=1)
            obj.service()
            self.assertEqual(proc.call_args.args[0][1], 'bootstrap')
            proc.reset_mock();proc.return_value=SimpleNamespace(returncode=0)
            obj.service()
            self.assertEqual(proc.call_args.args[0][1], 'kickstart')
            self.assertFalse(any('bootout' in call.args[0] for call in proc.call_args_list))
            plist.unlink();proc.reset_mock()
            with self.assertRaises(RuntimeError):obj.service()
            self.assertEqual(proc.call_count, 1)

    def test_publish_refuses_unowned_dns_without_mutation(self):
        obj = object.__new__(cloudflare_connect.Setup)
        obj.account='/accounts/fake';obj.zone='/zones/fake';obj.state={'tunnel_id':'owned'}
        with patch.object(obj,'verify_policy'), patch.object(obj,'preserve_app'), patch.object(obj,'api',side_effect=[{'status':'healthy'}, [{'id':'other','content':'owned.cfargotunnel.com'}]]) as api:
            with self.assertRaises(RuntimeError):obj.publish()
            self.assertTrue(all(len(call.args)==1 for call in api.call_args_list))
