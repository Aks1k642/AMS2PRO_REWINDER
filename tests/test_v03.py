"""v0.3.0 diagnostics, safety, credential binding. No real-printer I/O."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, PropertyMock
from app import Service
from credentials import CredentialVault
from readiness import evaluate


class DummyMQTT:
    def __init__(self, host, access_code, serial, on_message, on_disconnect):
        self.host, self.password, self.serial = host, access_code, serial
        self.connected = False
        self.sent = []
    def connect(self): self.connected = True
    def publish(self, value): self.sent.append(value)
    def close(self): self.connected = False


class ReadyTests(unittest.TestCase):
    def setUp(self):
        self.telemetry = {'gcode_state': 'IDLE', 'ams_status': 0, 'ams': {'tray_now': 1}, 'fun': '0'}
        self.last_seen = time.monotonic()
    def eval(self, **overrides):
        self.telemetry.update(overrides)
        return evaluate(True, self.telemetry, self.last_seen, selected_tray=1)
    def test_ready_for_single_unload(self):
        self.assertTrue(self.eval()['ready'])
    def test_no_telemetry_explained(self):
        diag = evaluate(True, {}, 0, 1)
        self.assertEqual(diag['stage'], 'waiting_status')
        self.assertEqual(diag['blockers'][0]['code'], 'telemetry')
    def test_developer_mode_off_explained(self):
        self.assertEqual(self.eval(fun='20000000')['blockers'][0]['code'], 'developer_mode')
    def test_unknown_control_not_silently_mapped_to_off(self):
        self.assertEqual(self.eval(fun=None)['warnings'][0]['code'], 'control_unknown')
    def test_wrong_tray_explained(self):
        self.assertFalse(self.eval(ams={'tray_now': 0})['ready'])
        self.assertIn('tray_mismatch', [i['code'] for i in self.eval(ams={'tray_now': 0})['blockers']])
    def test_unloaded_tray_explained(self):
        self.assertIn('tray_unloaded', [i['code'] for i in self.eval(ams={'tray_now': 255})['blockers']])
    def test_busy_ams(self):
        self.assertIn('ams_busy', [i['code'] for i in self.eval(ams_status=256)['blockers']])
    def test_cooldown_prevents_double_action(self):
        diag = evaluate(True, self.telemetry, self.last_seen, selected_tray=1, last_sent=time.monotonic())
        self.assertIn('cooldown', [i['code'] for i in diag['blockers']])


class VaultTests(unittest.TestCase):
    def test_unsupported_platform_not_plaintext(self):
        vault = CredentialVault(Path(tempfile.gettempdir()) / 'never-write-secrets.json')
        if not vault.available:
            with self.assertRaises(RuntimeError):
                vault.put('093AB12345678', 'supersecret')
    def test_saved_per_serial_and_retrieval(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = CredentialVault(Path(tmp) / 'vault.json')
            def crypt(data, decrypt=False):
                return data[4:] if decrypt else b'DPAP' + data
            with patch.object(CredentialVault,'available',new_callable=PropertyMock,return_value=True), patch('credentials._protect',side_effect=crypt):
                vault.put('093AB12345678','secret7777')
                vault.put('22EAB12345678','different7777')
                raw = vault.path.read_text()
                self.assertNotIn('secret7777', raw)
                self.assertEqual(vault.get('093AB12345678'),'secret7777')
                self.assertEqual(vault.get('22EAB12345678'),'different7777')
                vault.delete('093AB12345678')
                self.assertIsNone(vault.get('093AB12345678'))
                self.assertEqual(vault.get('22EAB12345678'),'different7777')


class ServiceTests(unittest.TestCase):
    def test_unload_command_never_sets_temperatures(self):
        svc = Service()
        svc.client = DummyMQTT('192.168.1.5','secret123','093AB12345678',None,None)
        svc.client.connected = True
        svc.connected = True
        svc.on_message({'print': {'gcode_state': 'IDLE','ams_status':0,'fun':'0','ams':{'tray_now':'0'}}})
        q={'confirm':'Я НАХОЖУСЬ У ПРИНТЕРА','joined_spools':False,'unit':0,'slot':0,'method':'unload_filament'}
        svc.unload_one_shot(q)
        self.assertEqual(len(svc.client.sent), 1)
        self.assertEqual(set(svc.client.sent[0]['print']), {'sequence_id','command'})
        with self.assertRaisesRegex(ValueError, 'пауза безопасности'):
            svc.unload_one_shot(q)
    def test_discovered_connect_uses_stored_code(self):
        svc=Service()
        serial='093AB12345678'
        svc.discovered[serial]={'serial':serial,'host':'192.168.1.5','model':'H2S'}
        svc.discovery_at=time.monotonic()
        with patch.object(svc.vault,'get',return_value='stored999'), patch('app.MQTTClient',DummyMQTT):
            status=svc.connect({'device_id':serial,'model':'H2S','access_code':'','use_saved_code':True})
            self.assertTrue(status['connected'])
            self.assertEqual(svc.client.password, 'stored999')
            self.assertNotIn('stored999', json.dumps(status))
    def test_without_saved_code_asks_user(self):
        svc=Service()
        with self.assertRaisesRegex(ValueError,'LAN Access Code'):
            svc.connect({'host':'192.168.1.5','serial':'093AB12345678','model':'H2S','access_code':''})


if __name__=='__main__':
    unittest.main()
