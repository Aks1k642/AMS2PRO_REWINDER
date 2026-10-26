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
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from mqtt_client import MQTTClient, MQTTError
from lan_discovery import discover_printers

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
        self.discovered = {}
        self.discovery_at = 0
        self.discovery_busy = False

    def discover(self):
        """Discover printers read-only; don't store their LAN codes."""
        with self.lock:
            if self.discovery_busy:
                raise ValueError("Поиск принтеров уже выполняется")
            self.discovery_busy = True
        try:
            devices = discover_printers(timeout=6)
            with self.lock:
                self.discovered = {d["serial"]: d for d in devices}
                self.discovery_at = time.monotonic()
            self.event("Поиск завершён: найдено " + str(len(devices)) + " устройств")
            return {"devices": [
                {k: d[k] for k in ("serial", "host", "model", "model_code", "name", "connect_mode", "firmware")}
                for d in devices],
                "note": "Если устройств нет: убедись, что принтер и ПК в одной LAN, проверь UDP 2021 и Bambu Studio."}
        except RuntimeError as exc:
            raise ValueError(str(exc)) from None
        finally:
            with self.lock:
                self.discovery_busy = False

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
        device_id = str(cfg.get("device_id", "")).strip()
        if device_id:
            with self.lock:
                entry = self.discovered.get(device_id)
                if not entry or time.monotonic() - self.discovery_at > 180:
                    raise ValueError("Принтер не найден в недавнем поиске. Нажми «Найти принтеры» снова.")
                host, serial = entry["host"], entry["serial"]
                detected_model = entry.get("model")
            requested_model = cfg.get("model")
            if detected_model and requested_model != detected_model:
                raise ValueError("Модель не совпадает с обнаруженной (" + detected_model + ")")
        else:
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
        if api == "/api/discover":
            try:
                return self._reply(service.discover())
            except ValueError as exc:
                return self._reply({"error": str(exc)}, 400)
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


DEFAULT_WEB_PORT = 8765


def validate_web_port(value):
    """HTTP port (not the printer MQTT port 8883)."""
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("Порт должен быть целым числом от 1024 до 65535") from None
    if not 1024 <= port <= 65535:
        raise ValueError("Выбери порт от 1024 до 65535")
    return port


def _preferences_file():
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
    root = Path(base) if base else Path.home() / ".config"
    return root / "AMS2ProRewinder" / "settings.json"


def load_web_port():
    """Keep the last selected port, without saving access codes or secrets."""
    try:
        return validate_web_port(json.loads(_preferences_file().read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, TypeError, KeyError):
        return DEFAULT_WEB_PORT


def save_web_port(port):
    try:
        path = _preferences_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"port": validate_web_port(port)}), encoding="utf-8")
    except OSError as exc:
        print("Не удалось сохранить выбранный порт:", exc)


def open_web_server(host, explicit_port=None, *, interactive=False, automatic=False):
    """Select the port before binding; retry locally if the chosen port is busy."""
    candidate = load_web_port() if explicit_port is None else validate_web_port(explicit_port)
    while True:
        if interactive and explicit_port is None and not automatic:
            try:
                selected = input(
                    f"Выбери порт веб-интерфейса [{candidate}] (Enter = оставить): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                selected = ""
            try:
                candidate = validate_web_port(selected or candidate)
            except ValueError as exc:
                print(exc)
                continue
        try:
            server = ThreadingHTTPServer((host, 0 if automatic else candidate), Handler)
            return server, server.server_port
        except OSError as exc:
            if automatic:
                raise RuntimeError("Не удалось выбрать свободный порт: " + str(exc)) from exc
            if not interactive or explicit_port is not None:
                raise RuntimeError(
                    f"Порт {candidate} недоступен ({exc}). Выбери другой через --port 8899 "
                    "или используй --auto-port."
                ) from exc
            print(f"Порт {candidate} занят или недоступен: {exc}")
            candidate = 8766 if candidate >= 65535 else candidate + 1


def main():
    ap = argparse.ArgumentParser(description="AMS 2 Pro Rewinder — LAN bridge and planner")
    ap.add_argument("--host", default="127.0.0.1", help="127.0.0.1 (только ПК) или 0.0.0.0 (домашняя сеть)")
    ap.add_argument("--port", type=int, default=None, help="Фиксированный порт веб-интерфейса, например 8899")
    ap.add_argument("--auto-port", action="store_true", help="Автоматически выбрать свободный порт")
    ap.add_argument("--no-port-prompt", action="store_true", help="Без запроса использовать последний выбранный порт")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "0.0.0.0"):
        ap.error("Bind only on 127.0.0.1 or 0.0.0.0")
    if args.port is not None and args.auto_port:
        ap.error("--port и --auto-port нельзя использовать вместе")
    if args.port is not None:
        try:
            validate_web_port(args.port)
        except ValueError as exc:
            ap.error(str(exc))

    interactive = not args.no_port_prompt and not args.auto_port and sys.stdin is not None and sys.stdin.isatty()
    try:
        server, selected_port = open_web_server(
            args.host, explicit_port=args.port, interactive=interactive, automatic=args.auto_port
        )
    except RuntimeError as exc:
        raise SystemExit("Ошибка запуска: " + str(exc)) from None

    if not args.auto_port:
        save_web_port(selected_port)
    server.auth_token = secrets.token_urlsafe(24)
    endpoint_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    url = f"http://{endpoint_host}:{selected_port}/#token={server.auth_token}"
    print("\nAMS 2 Pro Rewinder — локальное приложение\n")
    print("Порт приложения:", selected_port)
    print("Открыть на ПК:", url)
    if args.host == "0.0.0.0":
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("192.0.2.1", 1))  # local route lookup; no network data sent
                lan_ip = s.getsockname()[0]
        except OSError:
            lan_ip = "<IP_ПК>"
        print("Доступ с Android: http://%s:%s/#token=%s" % (lan_ip, selected_port, server.auth_token))
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
