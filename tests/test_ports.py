"""Local HTTP port selection tests; never touch a printer."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class PortSelectionTests(unittest.TestCase):
    def test_valid_port(self):
        self.assertEqual(app.validate_web_port("8899"), 8899)
        self.assertEqual(app.validate_web_port(65535), 65535)

    def test_invalid_port(self):
        for value in ["nope", "", None, 1, 1023, 65536, -5]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.validate_web_port(value)

    def test_saved_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            preferences = Path(tmp) / "settings.json"
            with patch.object(app, "_preferences_file", return_value=preferences):
                self.assertEqual(app.load_web_port(), 8765)
                app.save_web_port(8899)
                self.assertEqual(json.loads(preferences.read_text())["port"], 8899)
                self.assertEqual(app.load_web_port(), 8899)

    def test_auto_port_binds_socket(self):
        server, port = app.open_web_server("127.0.0.1", automatic=True)
        try:
            self.assertGreaterEqual(port, 1024)
            self.assertLessEqual(port, 65535)
        finally:
            server.server_close()

    def test_explicit_port_conflict_explained(self):
        server, port = app.open_web_server("127.0.0.1", automatic=True)
        try:
            with self.assertRaisesRegex(RuntimeError, "Порт"):
                app.open_web_server("127.0.0.1", explicit_port=port, interactive=False)
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
