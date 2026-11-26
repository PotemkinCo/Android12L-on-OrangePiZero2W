#!/usr/bin/env python3
"""Configure Android Wi-Fi privately through the USB console after boot."""
import getpass
from pathlib import Path
import secrets
import shlex
import socket

ssid=input('Wi-Fi SSID: ')
password=getpass.getpass('Wi-Fi password (WPA2): ')
if not ssid or not password or '\n' in ssid or '\n' in password:
    raise SystemExit('SSID/password must be nonempty single lines')
token=secrets.token_hex(12)
script=('set -e\n[ "$(getprop sys.boot_completed)" = 1 ]\n'
        'svc wifi enable >/dev/null\n'
        'cmd wifi connect-network '+shlex.quote(ssid)+' wpa2 '+shlex.quote(password)+
        ' >/dev/null 2>&1\nprintf "'+token+'\\n"\n').encode()
response=bytearray()
with socket.create_connection(('192.168.246.2',2323),timeout=20,
                              source_address=('192.168.246.1',0)) as conn:
    conn.sendall(script);conn.shutdown(socket.SHUT_WR)
    while data:=conn.recv(4096):
        response.extend(data)
        if len(response)>65536:raise RuntimeError('Unexpected console response')
if token.encode() not in response:
    raise SystemExit('Wi-Fi command did not complete; credentials were not printed or saved on this host')
print('Wi-Fi connection requested. Check Android status after association.')
