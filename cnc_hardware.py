import time

import serial


def cnc_connect(port, baudrate=115200, timeout=1, log_cb=None):
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
    ser = serial.Serial(port=port, baudrate=baudrate, bytesize=8,
                        timeout=0.5, stopbits=serial.STOPBITS_ONE)
    ser.reset_input_buffer()
    return ser
