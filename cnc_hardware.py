import time

import serial

SIMULATE_PORT = 'SIMULATE'  # type this as the Port to fake a connection (debug/dev only, no hardware needed)


class _FakeSerial:
    """Stand-in for serial.Serial so the run loop / cnc_send / pump writes
    have something to call when there's no real hardware plugged in."""

    def __init__(self):
        # GRBL settings answered by cnc_query in simulation ($3 dir mask, $100-$102 steps/mm)
        self.settings = {3: 0, 100: 250.0, 101: 250.0, 102: 250.0}

    def write(self, data):
        pass

    def readline(self):
        return b''

    @property
    def in_waiting(self):
        return 0

    def close(self):
        pass


def cnc_connect(port, baudrate=115200, timeout=1, log_cb=None):
    if port.strip().upper() == SIMULATE_PORT:
        if log_cb:
            log_cb("CNC: [simulated connection, no hardware]")
        return _FakeSerial()

    cnc = serial.Serial(port, baudrate, timeout=timeout)
    resp = cnc.readline().decode('utf-8').strip()
    if log_cb and resp:
        log_cb(f"CNC: {resp}")
    time.sleep(2)
    while cnc.in_waiting:
        resp = cnc.readline().decode('utf-8').strip()
        if log_cb and resp:
            log_cb(f"CNC: {resp}")
    return cnc


def cnc_send(cnc, command, log_cb=None):
    if isinstance(cnc, _FakeSerial):
        if log_cb:
            log_cb(f"CNC: [sim] {command}")
        return
    if not command.endswith('\n'):
        command += '\n'
    cnc.write(command.encode('utf-8'))
    resp = cnc.readline().decode('utf-8').strip()
    if log_cb and resp:
        log_cb(f"CNC: {resp}")
    time.sleep(0.1)
    while cnc.in_waiting:
        resp = cnc.readline().decode('utf-8').strip()
        if log_cb and resp:
            log_cb(f"CNC: {resp}")


def cnc_query(cnc, command, log_cb=None, timeout=3.0):
    """Send a command and return the controller's reply lines up to its 'ok'.
    Raises RuntimeError if GRBL answers with an error or alarm."""
    if isinstance(cnc, _FakeSerial):
        if log_cb:
            log_cb(f"CNC: [sim] {command}")
        cmd = command.strip()
        if cmd == '$$':
            return [f"${k}={v:g}" if isinstance(v, float) else f"${k}={v}"
                    for k, v in cnc.settings.items()]
        if cmd.startswith('$') and '=' in cmd and cmd[1:cmd.index('=')].isdigit():
            key, val = cmd[1:].split('=', 1)
            cnc.settings[int(key)] = float(val) if '.' in val else int(val)
        return []

    if not command.endswith('\n'):
        command += '\n'
    cnc.write(command.encode('utf-8'))
    lines = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = cnc.readline().decode('utf-8', errors='replace').strip()
        if not line:
            continue
        if line == 'ok':
            return lines
        if line.startswith(('error', 'ALARM')):
            if log_cb:
                log_cb(f"CNC: {line}")
            raise RuntimeError(f"Controller replied {line} to {command.strip()!r}")
        lines.append(line)
    raise RuntimeError(f"No reply from controller to {command.strip()!r}")


def pump_connect(port, baudrate=9600):
    if port.strip().upper() == SIMULATE_PORT:
        return _FakeSerial()

    ser = serial.Serial(port=port, baudrate=baudrate, bytesize=8,
                        timeout=0.5, stopbits=serial.STOPBITS_ONE)
    ser.reset_input_buffer()
    return ser
