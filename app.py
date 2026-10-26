"""Local LAN bridge + web UI for the AMS 2 Pro Rewinder research prototype.

No continuous winding functionality is claimed. This program can issue a *single*
experimental standard unload action, after explicit acknowledgement, only while
idle and with positive, recent printer telemetry. It does not measure filament travel.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from mqtt_client import MQTTClient, MQTTError

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
STATE_IDLE = {"IDLE", "FINISH"}
STATE_ACTIVE = {"RUNNING", "PREPARE", "PAUSE", "SLICING", "PRINTING"}


class Service:
    def __init__(self):
        self.lock = threading.RLock()
        self.client = None
        self.profile = None
        self.telemetry = {}
        self.last_status_time = 0
        self.last_command = None
        self.events = []
        self.connected = False

    def event(self, line):
        self.events.append({"at": time.strftime("%H:%M:%S"), "text": line})
        del self.events[:-80]

    def on_message(self, data):
        with self.lock:
            doc = data.get("print", {})
            if not isinstance(doc, dict):
                return
            # These fields are a stable subset of Bambu status; all are untrusted.
            for field in ("gcode_state", "ams_status", "mc_percent", "print_error", "fun"):
                if field in doc:
                    self.telemetry[field] = doc[field]
            ams = doc.get("ams")
            if isinstance(ams, dict):
                existing = self.telemetry.setdefault("ams", {})
                for field in ("tray_now", "tray_pre", "ams", "ams_exist_bits", "tray_exist_bits"):
                    if field in ams:
                        existing[field] = ams[field]
            if any(k in doc for k in ("gcode_state", "ams_status", "ams")):
                self.last_status_time = time.monotonic()
            command = doc.get("command")
            if command in ("unload_filament", "ams_change_filament", "ams_control"):
                self.last_command = {k: doc[k] for k in ("command", "result", "err_code", "reason", "sequence_id") if k in doc}
                self.event("Ответ принтера: " + command + " / " + str(doc.get("result", "состояние не указано")))

    def on_disconnect(self, reason):
        with self.lock:
            self.connected = False
            self.event("MQTT: соединение прервано")

    def disconnect(self):
        with self.lock:
            if self.client:
                self.client.close()
                self.client = None
            self.connected = False
            self.telemetry = {}
            self.last_status_time = 0
            self.event("Отключено")

    def connect(self, cfg):
        host = str(cfg.get("host", "")).strip()
        serial = str(cfg.get("serial", "")).strip()
        password = str(cfg.get("access_code", "")).strip()
        model = cfg.get("model")
        if model not in ("H2S", "P2S", "X2D"):
            raise ValueError("Выбери H2S, P2S или X2D")
        try:
            ip = ipaddress.ip_address(host)
            if ip.version != 4 or not ip.is_private:
                raise ValueError("not LAN")
        except ValueError:
            raise ValueError("Используй IPv4-адрес принтера в локальной сети")
        if len(serial) < 6 or len(serial) > 40 or not re.fullmatch(r"[A-Za-z0-9]+", serial):
            raise ValueError("Некорректный серийный номер")
        if not (4 <= len(password) <= 64):
            raise ValueError("Введи LAN Access Code принтера")
        self.disconnect()
        client = MQTTClient(host, password, serial, self.on_message, self.on_disconnect)
        try:
            client.connect()
        except Exception as exc:
            raise ValueError("MQTT не подключён: " + str(exc)) from None
        with self.lock:
            self.client = client
            self.connected = True
            self.profile = {"host": host, "serial_masked": serial[:3] + "…" + serial[-3:], "model": model}
            self.event("Подключён " + model + ". Ожидание телеметрии.")
        return self.status()

    def status(self):
        with self.lock:
            age = None if self.last_status_time == 0 else round(time.monotonic() - self.last_status_time, 1)
            return {"connected": bool(self.client and self.client.connected and self.connected),
                    "printer": self.profile, "status": self.telemetry.copy(),
                    "telemetry_age_s": age, "last_command": self.last_command,
                    "events": list(self.events[-30:]),
                    "capabilities": {"one_shot_unload": True, "continuous_rewind": False, "mass_feedback": False}}

    def unload_one_shot(self, request):
        """Only one user-initiated unload, never automatic repetition.

        This is still experimental: firmware differences may reject the command and
        there is no reliable automatic abort of the motor. The user must stand by.
        """
        with self.lock:
            if request.get("confirm") != "Я НАХОЖУСЬ У ПРИНТЕРА":
                raise ValueError("Требуется явное подтверждение присутствия у принтера")
            if request.get("joined_spools") is not False:
                raise ValueError("Первый эксперимент выполняется только БЕЗ соединения двух катушек")
            if not self.client or not self.client.connected or not self.connected:
                raise ValueError("Нет подключения")
            if self.last_status_time == 0 or time.monotonic() - self.last_status_time > 10:
                raise ValueError("Нет свежей телеметрии — команда заблокирована")
            state = str(self.telemetry.get("gcode_state", "")).upper()
            if state not in STATE_IDLE:
                raise ValueError("Принтер не в безопасном состоянии ожидания (" + (state or "неизвестно") + ")")
            ams_value = self.telemetry.get("ams_status")
            try:
                ams_mode = (int(str(ams_value), 0) if isinstance(ams_value, str) else int(ams_value)) >> 8
            except (TypeError, ValueError):
                raise ValueError("Состояние механизма AMS неизвестно — команда заблокирована")
            if ams_mode not in (0, 3):
                raise ValueError("AMS занят операцией (код " + str(ams_mode) + ")")
            ams = self.telemetry.get("ams")
            if not isinstance(ams, dict) or "tray_now" not in ams:
                raise ValueError("Нет данных об активном AMS-слоте")
            try:
                tray_now = int(ams["tray_now"])
                intended = int(request.get("slot"))
                unit = int(request.get("unit", 0))
            except (TypeError, ValueError):
                raise ValueError("Проверь AMS и слот")
            if not (0 <= unit <= 3 and 0 <= intended <= 3):
                raise ValueError("Поддерживаются AMS 0–3 и слоты 1–4")
            global_tray = unit * 4 + intended
            if tray_now != global_tray:
                raise ValueError("Текущий пруток не из выбранного слота AMS (tray_now=" + str(tray_now) + ")")
            method = request.get("method", "ams_change_filament")
            sequence = str(int(time.time() * 1000) % 100000000)
            if method == "ams_change_filament":
                msg = {"print": {"sequence_id": sequence, "command": "ams_change_filament", "ams_id": unit,
                        "slot_id": 255, "target": 255, "soft_temp": 0, "tar_temp": 210, "curr_temp": 210}}
            elif method == "unload_filament":
                msg = {"print": {"sequence_id": sequence, "command": "unload_filament"}}
            else:
                raise ValueError("Неподдерживаемый тип штатной выгрузки")
            self.client.publish(msg)
            self.last_command = {"command": msg["print"]["command"], "sequence_id": sequence,
                                 "result": "sent_not_confirmed"}
            self.event("Отправлен один запрос выгрузки: " + method + ". Результат ожидается.")
            return {"sent": True, "sequence_id": sequence,
                    "warning": "Команда отправлена, но выполнение и намотанная длина не подтверждены."}


service = Service()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def log_message(self, format, *args):
        # Never log URL/token or credentials.
        return

    def _auth(self):
        return secrets.compare_digest(self.headers.get("X-Session-Token", ""), self.server.auth_token)

    def _reply(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _api(self):
        path = urlsplit(self.path).path
        if not path.startswith("/api/"):
            return None
        if not self._auth():
            self._reply({"error": "Нет токена доступа к локальному мосту"}, 403)
            return "done"
        return path

    def do_GET(self):
        api = self._api()
        if api == "done":
            return
        if api == "/api/status":
            return self._reply(service.status())
        if api is not None:
            return self._reply({"error": "Неизвестный API"}, 404)
        return super().do_GET()

    def do_POST(self):
        api = self._api()
        if api == "done":
            return
        if api not in ("/api/connect", "/api/disconnect", "/api/unload"):
            return self._reply({"error": "Неизвестный API"}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4096 or length < 0:
                raise ValueError("Слишком большой запрос")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Неверный формат")
            if api == "/api/connect":
                result = service.connect(data)
            elif api == "/api/disconnect":
                service.disconnect()
                result = service.status()
            else:
                result = service.unload_one_shot(data)
            self._reply(result)
        except (ValueError, MQTTError) as exc:
            self._reply({"error": str(exc)}, 400)
        except Exception:
            self._reply({"error": "Внутренняя ошибка; проверь журнал приложения"}, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="Binding address, default localhost")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    if args.host != "127.0.0.1" and args.host != "localhost" and args.host != "0.0.0.0":
        ap.error("Bind only on 127.0.0.1 or 0.0.0.0")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.auth_token = secrets.token_urlsafe(24)
    endpoint_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    url = f"http://{endpoint_host}:{args.port}/#token={server.auth_token}"
    print("\nAMS 2 Pro Rewinder — локальное приложение\n")
    print("Открыть на ПК:", url)
    if args.host == "0.0.0.0":
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("192.0.2.1", 1))  # local route lookup; no network data sent
                lan_ip = s.getsockname()[0]
        except OSError:
            lan_ip = "<IP_ПК>"
        print("Доступ с Android: http://%s:%s/#token=%s" % (lan_ip, args.port, server.auth_token))
        print("ВНИМАНИЕ: доступ по HTTP для доверенной домашней LAN; не открывать в интернет.")
    if not args.no_browser:
        threading.Timer(.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.disconnect()
        server.server_close()


if __name__ == "__main__":
    main()
