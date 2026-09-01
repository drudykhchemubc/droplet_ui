import time

import serial

SIMULATE_PORT = 'SIMULATE'  # type this as the Port to fake a connection (debug/dev only, no hardware needed)


class _FakeSerial:
    """Stand-in for serial.Serial so the run loop / cnc_send / pump writes
    have something to call when there's no real hardware plugged in."""

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


def pump_connect(port, baudrate=9600):
    if port.strip().upper() == SIMULATE_PORT:
        return _FakeSerial()

    ser = serial.Serial(port=port, baudrate=baudrate, bytesize=8,
                        timeout=0.5, stopbits=serial.STOPBITS_ONE)
    ser.reset_input_buffer()
    return ser
