"""Passive Bambu Lab LAN discovery (SSDP notifications on UDP/2021).

No proprietary Bambu Network Plugin binaries are bundled or loaded. Printer
identifiers are obtained from the printer's own LAN announcements.
"""
import ipaddress
import re
import socket
import struct
import time
from urllib.parse import urlsplit

MULTICAST_GROUP = "239.255.255.250"
DISCOVERY_PORT = 2021
SERIAL_RE = re.compile(r"[A-Za-z0-9]{6,40}\Z")
MODEL_PREFIXES = {"093": "H2S", "22E": "P2S"}
SUPPORTED_MODELS = {"H2S", "P2S", "X2D"}


def _private_ipv4(value):
    try:
        ip = ipaddress.ip_address(value)
        return str(ip) if ip.version == 4 and ip.is_private else None
    except ValueError:
        return None


def parse_announcement(packet, sender_ip):
    """Return validated device details or None, with no network side effects."""
    if not isinstance(packet, (bytes, bytearray)) or len(packet) > 8192:
        return None
    text = packet.decode("latin-1", errors="replace")
    if not text.startswith(("NOTIFY ", "HTTP/1.")):
        return None
    headers = {}
    for line in text.replace("\r", "").split("\n")[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    # Never accept arbitrary LAN broadcasts as Bambu printers.
    nt = headers.get("nt", "").lower()
    if "bambulab" not in nt and "devmodel.bambu.com" not in headers:
        return None
    serial = headers.get("usn", "")
    if serial.lower().startswith("uuid:"):
        serial = serial[5:]
    if not SERIAL_RE.fullmatch(serial):
        return None
    address = headers.get("location", "")
    if "://" in address:
        address = urlsplit(address).hostname or ""
    source = _private_ipv4(sender_ip)
    host = _private_ipv4(address) or source
    # Mismatched locations are unexpected; do not make network requests to them.
    if not host or not source or host != source:
        return None
    model_code = headers.get("devmodel.bambu.com", "").strip()[:40]
    model = MODEL_PREFIXES.get(serial[:3].upper())
    name = headers.get("devname.bambu.com", "").strip()[:80]
    for candidate in SUPPORTED_MODELS:
        if candidate.lower() in (name + " " + model_code).lower():
            model = candidate
            break
    return {
        "host": host,
        "serial": serial,
        "model": model or "",
        "model_code": model_code,
        "name": name or "Bambu Lab",
        "connect_mode": headers.get("devconnect.bambu.com", "")[:24],
        "firmware": headers.get("devversion.bambu.com", "")[:50],
    }


def discover_printers(timeout=6):
    """Listen briefly for existing printer SSDP announcements.

    Blocking I/O. Call from an authenticated local server request, never
    continuously in the background. A scan will not command a printer.
    """
    timeout = max(1.0, min(float(timeout), 10.0))
    devices = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", DISCOVERY_PORT))
        except OSError as exc:
            raise RuntimeError("UDP 2021 занят или недоступен. Закрой Bambu Studio либо используй ручное подключение.") from exc
        # On some Windows hosts multiple multicast listeners can coexist;
        # on others Bambu Studio may monopolize the port.
        try:
            membership = struct.pack("=4s4s", socket.inet_aton(MULTICAST_GROUP),
                                      socket.inet_aton("0.0.0.0"))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        except OSError as exc:
            raise RuntimeError("Не удалось подписаться на SSDP multicast: " + str(exc)) from exc
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sock.settimeout(min(0.8, max(0.01, deadline - time.monotonic())))
            try:
                packet, remote = sock.recvfrom(8192)
            except socket.timeout:
                continue
            device = parse_announcement(packet, remote[0])
            if device:
                devices[device["serial"]] = device
                if len(devices) >= 32:
                    break
    return sorted(devices.values(), key=lambda x: (x["name"].lower(), x["host"]))
