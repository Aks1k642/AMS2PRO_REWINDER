"""Deterministic tests; never contact a real printer."""
import os
import sys
import time
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Service
from mqtt_client import varint, utf8

class DummyMQTT:
    connected = True
    def __init__(self): self.sent=[]
    def publish(self, payload): self.sent.append(payload)
    def close(self): self.connected=False

class TestMQTT(unittest.TestCase):
    def test_length_encoding(self):
        self.assertEqual(varint(0), b'\x00')
        self.assertEqual(varint(127), b'\x7f')
        self.assertEqual(varint(128), b'\x80\x01')
        self.assertEqual(varint(16384), b'\x80\x80\x01')
        with self.assertRaises(ValueError): varint(-1)
    def test_string_encoding(self): self.assertEqual(utf8('AMS'),b'\x00\x03AMS')

class TestSafety(unittest.TestCase):
    def setUp(self):
        self.svc=Service()
        self.mock=DummyMQTT()
        self.svc.client=self.mock
        self.svc.connected=True
        self.svc.on_message({'print':{'command':'push_status','gcode_state':'IDLE','ams':{'tray_now':'0'},'ams_status':0}})
        self.request={'confirm':'Я НАХОЖУСЬ У ПРИНТЕРА','joined_spools':False,'slot':0,'unit':0,'method':'ams_change_filament'}
    def test_single_unload_request(self):
        self.svc.unload_one_shot(self.request)
        self.assertEqual(len(self.mock.sent), 1)
        data=self.mock.sent[0]['print']
        self.assertEqual(data['command'], 'ams_change_filament')
        self.assertEqual(data['target'], 255)
        self.assertEqual(data['slot_id'], 255)
    def test_alternate_unload(self):
        self.request['method']='unload_filament'
        self.svc.unload_one_shot(self.request)
        self.assertEqual(self.mock.sent[0]['print']['command'], 'unload_filament')
    def assertBlocked(self):
        with self.assertRaises(ValueError):self.svc.unload_one_shot(self.request)
        self.assertFalse(self.mock.sent)
    def test_block_during_print(self):
        self.svc.on_message({'print':{'gcode_state':'RUNNING'}})
        self.assertBlocked()
    def test_block_during_pause(self):
        self.svc.on_message({'print':{'gcode_state':'PAUSE'}})
        self.assertBlocked()
    def test_block_stale(self):
        self.svc.last_status_time=time.monotonic()-12
        self.assertBlocked()
    def test_block_spliced(self):
        self.request['joined_spools']=True
        self.assertBlocked()
    def test_block_other_slot(self):
        self.request['slot']=1
        self.assertBlocked()
    def test_block_missing_confirmation(self):
        self.request['confirm']=''
        self.assertBlocked()
    def test_block_no_ams_feedback(self):
        self.svc.telemetry['ams']={}
        self.assertBlocked()
    def test_block_disconnected(self):
        self.mock.connected=False
        self.assertBlocked()
    def test_block_busy_ams(self):
        self.svc.telemetry['ams_status'] = 256
        self.assertBlocked()
    def test_accept_assist_ams(self):
        self.svc.telemetry['ams_status'] = 768
        self.svc.unload_one_shot(self.request)
        self.assertEqual(len(self.mock.sent),1)
    def test_empty_password_logs(self):
        self.svc.event('Disconnected')
        self.assertNotIn('secret123',str(self.svc.status()))

if __name__=='__main__': unittest.main()
