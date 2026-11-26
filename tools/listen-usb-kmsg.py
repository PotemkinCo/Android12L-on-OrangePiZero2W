#!/usr/bin/env python3
"""Receive diagnostic kernel messages on the USB address only."""
import argparse
import errno
import json
import socket
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--duration', type=float, default=600)
args = parser.parse_args()
if not 1 <= args.duration <= 3600:
    parser.error('duration must be 1..3600 seconds')
deadline = time.monotonic() + args.duration
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
    while True:
        try:
            receiver.bind(('192.168.246.1', 6666))
            break
        except OSError as error:
            if error.errno != errno.EADDRNOTAVAIL or time.monotonic() >= deadline:
                raise
            time.sleep(.2)
    receiver.settimeout(1)
    print(json.dumps({'status': 'listening', 'address': '192.168.246.1:6666'}), flush=True)
    while time.monotonic() < deadline:
        try:
            data, source = receiver.recvfrom(65535)
        except socket.timeout:
            continue
        if source[0] == '192.168.246.2':
            print(json.dumps({'kmsg': data.decode('utf-8', errors='replace')}), flush=True)
