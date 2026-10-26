"""Small dependency-free MQTT 3.1.1 client for Bambu LAN MQTTs.

Only a controlled, bounded subset of protocol is implemented. No auto-reconnect while
an operation is running. The connection is local; printers use self-signed TLS certs.
"""
import json
import socket
import ssl
import struct
import threading
import time
from typing import Callable


def varint(value: int) -> bytes:
    if not 0 <= value <= 268435455:
        raise ValueError("MQTT remaining length out of bounds")
    out = bytearray()
    while True:
        digit = value % 128
        value //= 128
        if value:
            digit |= 128
        out.append(digit)
        if not value:
            return bytes(out)


def utf8(value: str) -> bytes:
    data = value.encode("utf-8")
    return struct.pack(">H", len(data)) + data


def packet(kind: int, data: bytes) -> bytes:
    return bytes([kind]) + varint(len(data)) + data


class MQTTError(Exception):
    pass


class MQTTClient:
    def __init__(self, host: str, access_code: str, serial: str, on_message: Callable, on_disconnect: Callable):
        self.host = host
        self.access_code = access_code
        self.serial = serial
        self.on_message = on_message
        self.on_disconnect = on_disconnect
        self.socket = None
        self.lock = threading.Lock()
        self.exit = threading.Event()
        self.thread = None
        self.packet_id = 0
        self.connected = False
        self.last_message = None

    def _read_exact(self, count):
        output = bytearray()
        while len(output) < count:
            b = self.socket.recv(count - len(output))
            if not b:
                raise MQTTError("Соединение закрыто принтером")
            output.extend(b)
        return bytes(output)

    def _recv_packet(self):
        head = self._read_exact(1)[0]
        multiplier = 1
        length = 0
        for _ in range(4):
            digit = self._read_exact(1)[0]
            length += (digit & 127) * multiplier
            if not digit & 128:
                break
            multiplier *= 128
        else:
            raise MQTTError("Недопустимая длина MQTT")
        if length > 2_000_000:
            raise MQTTError("Слишком большой MQTT-пакет")
        return head, self._read_exact(length)

    def _write(self, payload):
        with self.lock:
            if self.socket is None:
                raise MQTTError("Нет подключения")
            self.socket.sendall(payload)

    def connect(self):
        self.close()
        self.exit.clear()
        raw = socket.create_connection((self.host, 8883), timeout=5)
        # The Bambu printer is identified by LAN address and access code; its local
        # TLS certificate is self-signed. Do not use this transport outside LAN.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            self.socket = ctx.wrap_socket(raw, server_hostname=self.host)
            self.socket.settimeout(10)
            keepalive = struct.pack(">H", 30)
            vh = utf8("MQTT") + b"\x04\xc2" + keepalive
            import secrets
            identifier = "ams-rewinder-" + secrets.token_hex(5)
            body = vh + utf8(identifier) + utf8("bblp") + utf8(self.access_code)
            self._write(packet(0x10, body))
            header, connack = self._recv_packet()
            if (header >> 4) != 2 or len(connack) != 2 or connack[1] != 0:
                raise MQTTError("Отказ MQTT (проверь LAN access code и Developer Mode)")
            self.connected = True
            self.packet_id += 1
            topic = "device/" + self.serial + "/report"
            self._write(packet(0x82, struct.pack(">H", self.packet_id) + utf8(topic) + b"\x00"))
            header, data = self._recv_packet()
            if header >> 4 != 9 or len(data) < 3 or data[2] == 0x80:
                raise MQTTError("Принтер не разрешил подписку на телеметрию")
            self.socket.settimeout(2)
            self.thread = threading.Thread(target=self._listen, daemon=True)
            self.thread.start()
            self.publish({"pushing": {"sequence_id": "0", "command": "pushall"}})
        except Exception:
            self.close()
            raise

    def publish(self, payload: dict):
        if not self.connected:
            raise MQTTError("Нет подтвержденного MQTT-подключения")
        topic = "device/" + self.serial + "/request"
        data = utf8(topic) + json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self._write(packet(0x30, data))

    def _listen(self):
        last_ping = time.monotonic()
        try:
            while not self.exit.is_set():
                # MQTT keepalive measures messages sent by this client, not status received.
                if time.monotonic() - last_ping >= 10:
                    self._write(packet(0xc0, b""))
                    last_ping = time.monotonic()
                try:
                    head, body = self._recv_packet()
                except socket.timeout:
                    continue
                kind = head >> 4
                if kind == 3 and len(body) >= 2:
                    length = struct.unpack(">H", body[:2])[0]
                    offset = 2 + length + (2 if (head & 0x06) else 0)
                    try:
                        msg = json.loads(body[offset:].decode("utf-8"))
                        self.last_message = time.monotonic()
                        self.on_message(msg)
                    except (ValueError, UnicodeError):
                        pass
                elif kind == 13:
                    last_ping = time.monotonic()
        except Exception as error:
            if not self.exit.is_set():
                self.on_disconnect(str(error))
        finally:
            self.connected = False
            self._close_socket()

    def _close_socket(self):
        with self.lock:
            sock, self.socket = self.socket, None
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass

    def close(self):
        self.exit.set()
        self.connected = False
        self._close_socket()
