"""Offline tests for Bambu SSDP discovery; never contact physical printers."""
import time
import unittest
from unittest.mock import patch

from lan_discovery import parse_announcement
from app import Service


def packet(serial="093AB12345678", location="192.168.1.50", device_name="H2S Workshop"):
    return (
        "NOTIFY * HTTP/1.1\r\n"
        "NT: urn:bambulab-com:device:3dprinter:1\r\n"
        "USN: " + serial + "\r\n"
        "LOCATION: " + location + "\r\n"
        "DevModel.bambu.com: 093\r\n"
        "DevName.bambu.com: " + device_name + "\r\n"
        "DevConnect.bambu.com: lan\r\n\r\n"
    ).encode("ascii")


class FakeMQTT:
    def __init__(self, host, access_code, serial, on_message, on_disconnect):
        self.host, self.serial = host, serial
        self.connected = False
    def connect(self):
        self.connected = True
    def close(self):
        self.connected = False


class TestDiscovery(unittest.TestCase):
    def test_reads_model_ip_serial(self):
        item = parse_announcement(packet(), "192.168.1.50")
        self.assertEqual(item["host"], "192.168.1.50")
        self.assertEqual(item["serial"], "093AB12345678")
        self.assertEqual(item["model"], "H2S")
        self.assertEqual(item["connect_mode"], "lan")

    def test_p2s_prefix(self):
        item = parse_announcement(packet(serial="22E123456789", device_name="P2S"), "192.168.1.50")
        self.assertEqual(item["model"], "P2S")

    def test_unrelated_udp_ignored(self):
        self.assertIsNone(parse_announcement(b"hello", "192.168.1.50"))

    def test_other_host_location_rejected(self):
        self.assertIsNone(parse_announcement(packet(location="192.168.1.55"), "192.168.1.50"))

    def test_public_address_ignored(self):
        self.assertIsNone(parse_announcement(packet(location="8.8.8.8"), "8.8.8.8"))

    def test_no_ssdp_serial(self):
        self.assertIsNone(parse_announcement(packet(serial="wrong/serial"), "192.168.1.50"))

    def test_connect_discovered_without_manual_serial(self):
        svc = Service()
        item = parse_announcement(packet(), "192.168.1.50")
        with patch("app.discover_printers", return_value=[item]):
            result = svc.discover()
        self.assertEqual(len(result["devices"]), 1)
        with patch("app.MQTTClient", FakeMQTT):
            result = svc.connect({"device_id": item["serial"], "model": "H2S", "access_code": "abcd1234"})
        self.assertTrue(result["connected"])
        self.assertEqual(svc.client.host, "192.168.1.50")
        self.assertEqual(svc.client.serial, "093AB12345678")
        self.assertNotIn("abcd1234", str(result))

    def test_stale_discovery_rejected(self):
        svc = Service()
        item = parse_announcement(packet(), "192.168.1.50")
        svc.discovered[item["serial"]] = item
        svc.discovery_at = time.monotonic() - 181
        with self.assertRaisesRegex(ValueError, "недавнем поиске"):
            svc.connect({"device_id": item["serial"], "model": "H2S", "access_code": "abcd1234"})

    def test_mismatch_model_rejected(self):
        svc = Service()
        item = parse_announcement(packet(), "192.168.1.50")
        svc.discovered[item["serial"]] = item
        svc.discovery_at = time.monotonic()
        with self.assertRaisesRegex(ValueError, "Модель не совпадает"):
            svc.connect({"device_id": item["serial"], "model": "X2D", "access_code": "abcd1234"})

    def test_empty_result(self):
        svc = Service()
        with patch("app.discover_printers", return_value=[]):
            self.assertEqual(svc.discover()["devices"], [])


if __name__ == "__main__":
    unittest.main()
