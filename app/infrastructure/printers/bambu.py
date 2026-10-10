"""Bambu Lab LAN-only MQTT transport with mandatory TLS certificate pinning.

This community protocol is not a vendor-supported interface. Never use without
explicit operator allowlisting and a certificate fingerprint from a trusted LAN.
"""
import hashlib
import hmac
import time
import json
import math
import os
import re
import secrets
import socket
import ssl
from urllib.parse import urlsplit

from app.core.settings import read_secret

MAX_PACKET = 65536


def _text(value: str) -> bytes:
    encoded = value.encode('utf-8')
    if len(encoded) > 65535:
        raise ValueError('Invalid MQTT string length.')
    return len(encoded).to_bytes(2, 'big') + encoded


def _frame(kind: int, body: bytes) -> bytes:
    length = len(body)
    encoded = bytearray()
    while True:
        byte = length % 128
        length //= 128
        encoded.append(byte | (128 if length else 0))
        if not length:
            break
    return bytes([kind]) + bytes(encoded) + body


def _read_exact(stream, size: int) -> bytes:
    output = bytearray()
    while len(output) < size:
        data = stream.recv(size - len(output))
        if not data:
            raise ValueError('Bambu MQTT connection closed.')
        output.extend(data)
    return bytes(output)


def _read_packet(stream) -> tuple[int, bytes]:
    kind = _read_exact(stream, 1)[0]
    length = 0
    for count in range(4):
        octet = _read_exact(stream, 1)[0]
        length += (octet & 127) * 128 ** count
        if not octet & 128:
            if length > MAX_PACKET:
                raise ValueError('Bambu MQTT response is too large.')
            return kind, _read_exact(stream, length)
    raise ValueError('Malformed MQTT packet length.')


def _identity(printer, validate_url):
    target = validate_url(printer['base_url'])
    parsed = urlsplit(target)
    if parsed.scheme != 'mqtts' or parsed.port != 8883:
        raise ValueError('Bambu requires MQTT over TLS on port 8883.')
    serial = printer['serial']
    token_env = printer['token_env']
    if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9]{8,32}', serial):
        raise ValueError('Invalid Bambu serial.')
    if not isinstance(token_env, str) or not re.fullmatch(r'SPOOLMERA_PRINTER_TOKEN_[A-Z0-9_]{1,50}', token_env):
        raise ValueError('Invalid Bambu credential reference.')
    code = read_secret(token_env)
    fingerprint = os.getenv('SPOOLMERA_BAMBU_CERT_SHA256_' + token_env.removeprefix('SPOOLMERA_PRINTER_TOKEN_'), '')
    if not code or not re.fullmatch('[0-9a-fA-F]{64}', fingerprint):
        raise ValueError('Bambu LAN credentials or pinned TLS fingerprint are missing.')
    return parsed.hostname, serial, code, fingerprint.lower()


def _connect(printer, validate_url):
    host, serial, code, fingerprint = _identity(printer, validate_url)
    # Bambu firmware presents device-generated/self-signed certificates. Pin an
    # exact trusted DER SHA-256 instead of globally disabling TLS identity checks.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        raw = socket.create_connection((host, 8883), timeout=5)
        with raw:
            tls = context.wrap_socket(raw, server_hostname=None)
            tls.settimeout(5)
            certificate = tls.getpeercert(binary_form=True)
            if not certificate or not hmac.compare_digest(hashlib.sha256(certificate).hexdigest(), fingerprint):
                tls.close()
                raise ValueError('Bambu TLS fingerprint mismatch. Stop and verify the printer certificate.')
            client_id = 'sm-' + secrets.token_hex(8)
            payload = (_text('MQTT') + b'\x04\xc2\x00\x1e' + _text(client_id)
                       + _text('bblp') + _text(code))
            tls.sendall(_frame(0x10, payload))
            kind, response = _read_packet(tls)
            if kind != 0x20 or len(response) != 2 or response != b'\x00\x00':
                tls.close()
                raise ValueError('Bambu LAN MQTT authentication failed.')
            return tls, serial
    except (OSError, TimeoutError) as exc:
        raise ValueError('Bambu LAN MQTT connection failed.') from exc


def _publish(stream, topic: str, message: dict, *, qos: int = 0):
    body = _text(topic)
    if qos:
        body += b'\x00\x03'
    body += json.dumps(message, separators=(',', ':')).encode('utf-8')
    stream.sendall(_frame(0x32 if qos else 0x30, body))
    if qos:
        for _ in range(12):
            kind, data = _read_packet(stream)
            if kind == 0x40 and data == b'\x00\x03':
                return
        raise ValueError('Bambu MQTT publish confirmation missing.')


def parse_status(report: dict) -> dict:
    """Only normalized telemetry, never assume Bambu estimates are measured grams."""
    print_data = report.get('print')
    if not isinstance(print_data, dict) or not isinstance(print_data.get('gcode_state'), str):
        raise ValueError('Bambu MQTT report did not include print status.')
    raw = print_data['gcode_state'].upper()
    states = {'RUNNING':'printing', 'PAUSE':'paused', 'PAUSED':'paused',
              'PREPARE':'preparing', 'IDLE':'standby', 'FINISH':'complete', 'FAILED':'failed'}
    filename = print_data.get('subtask_name', '')
    if not isinstance(filename, str):
        filename = ''
    def number(key):
        value = print_data.get(key)
        return value if type(value) in (int, float) and math.isfinite(value) and -100 <= value <= 10000 else None
    def layer(key):
        value = print_data.get(key)
        return value if type(value) is int and 0 <= value <= 200000 else None
    task = print_data.get('task_id')
    # Local jobs on some firmware expose no usable task ID. Never infer one
    # from a filename, timestamp, plate or AMS slot for automatic accounting.
    if type(task) not in (int, str):
        task = None
    else:
        task = str(task)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', task) or not task.strip('0'):
            task = None
    progress = number('mc_percent')
    if progress is not None and not 0 <= progress <= 100:
        progress = None
    ams = []
    devices = print_data.get('ams', {})
    if isinstance(devices, dict):
        for unit in devices.get('ams', []) if isinstance(devices.get('ams', []), list) else []:
            if not isinstance(unit, dict):
                continue
            trays = unit.get('tray', [])
            if not isinstance(trays, list):
                continue
            for tray in trays[:4]:
                if not isinstance(tray, dict):
                    continue
                ams.append({'unit': str(unit.get('id',''))[:8],
                            'tray': str(tray.get('id',''))[:8],
                            'material': str(tray.get('tray_type',''))[:40],
                            'color': str(tray.get('tray_color',''))[:8],
                            'remaining_percent': tray.get('remain') if type(tray.get('remain')) is int and 0 <= tray['remain'] <= 100 else None})
    return {'state': states.get(raw, 'unknown'), 'filename': filename[:180],
            'task_id': task, 'progress_percent': progress,
            'layer_num': layer('layer_num'), 'total_layer_num': layer('total_layer_num'),
            'remaining_minutes': number('mc_remaining_time'),
            'nozzle_c': number('nozzle_temper'), 'bed_c': number('bed_temper'),
            'ams': ams[:16]}


def read_bambu_status(printer, validate_url):
    stream, serial = _connect(printer, validate_url)
    with stream:
        topic = f'device/{serial}/report'
        stream.sendall(_frame(0x82, b'\x00\x01' + _text(topic) + b'\x00'))
        kind, response = _read_packet(stream)
        if kind != 0x90 or len(response) != 3 or response[:2] != b'\x00\x01' or response[2] == 0x80:
            raise ValueError('Bambu LAN MQTT subscription failed.')
        _publish(stream, f'device/{serial}/request',
                 {'pushing': {'command': 'pushall', 'sequence_id': '0'}})
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            stream.settimeout(max(0.1, deadline - time.monotonic()))
            kind, body = _read_packet(stream)
            if kind >> 4 != 3:
                continue
            if len(body) < 2:
                continue
            length = int.from_bytes(body[:2], 'big')
            if len(body) < length + 2 or body[2:2 + length] != topic.encode():
                continue
            offset = 2 + length + (2 if kind & 0x06 else 0)
            try:
                report = json.loads(body[offset:])
            except (ValueError, UnicodeError):
                continue
            if isinstance(report, dict) and isinstance(report.get('print'), dict) and 'gcode_state' in report['print']:
                return parse_status(report)
        raise ValueError('Bambu did not send a full print status snapshot.')


def send_bambu_control(printer, validate_url, action: str) -> int:
    commands = {'pause':'pause', 'resume':'resume', 'cancel':'stop'}
    if action not in commands:
        raise ValueError('Unsupported Bambu printer action.')
    stream, serial = _connect(printer, validate_url)
    with stream:
        _publish(stream, f'device/{serial}/request',
                 {'print': {'command': commands[action], 'sequence_id': '0'}}, qos=1)
    # PUBACK confirms MQTT delivery, not execution by the physical printer.
    return 202
