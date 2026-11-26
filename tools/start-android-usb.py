#!/usr/bin/env python3
"""Portable macOS/Linux launcher for the prepared laptop-backed Android image.

Uses native sunxi-fel and the USB adapter's DHCP configuration. No host UUID,
USB bus number, network-interface name, or local account name is stored here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
BOARD = '192.168.246.2'
HOST = '192.168.246.1'


def verify_payload():
    manifest = json.loads((ROOT / 'prepared/android/arm64/userspace-manifest.json').read_text())
    for name, expected in manifest['files'].items():
        path = (ROOT / name).resolve()
        if ROOT not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Payload path/checksum mismatch: ' + name)
    image = ROOT / 'data/android-arm64.img'
    if not image.is_file() or image.stat().st_size != 8 * 1024**3:
        raise ValueError('Expected the project regular 8 GiB Android backing image')
    for name in ('confirm-android-control.sh', 'confirm-android-ready.sh'):
        if not (ROOT / 'prepared/android/arm64' / name).is_file():
            raise ValueError('Missing Android verification script: ' + name)
    print('Prepared Android payload checks passed.', flush=True)
    return manifest


def host_usb_address_ready():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((HOST, 0))
        return True
    except OSError:
        return False


def sync_device_clock(output):
    # This board has no battery-backed clock. Use this host's current time at
    # each boot, rather than persisting one laptop's old startup timestamp.
    with tempfile.TemporaryDirectory(prefix='opi-usb-clock-') as directory:
        script = Path(directory) / 'set-device-clock.sh'
        script.write_text('set -e\n/system/bin/date -u @' + str(int(time.time())) +
                          '\n/system/bin/date -u\n')
        subprocess.run([sys.executable, str(ROOT / 'tools/usb-net-command.py'),
                        str(script), '--timeout', '8'], cwd=ROOT, stdout=output,
                       stderr=subprocess.STDOUT, timeout=12, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='validate local files without USB/network access')
    parser.add_argument('--wait-fel', type=float, default=120)
    parser.add_argument('--control-timeout', type=float, default=420)
    args = parser.parse_args()
    if not 1 <= args.wait_fel <= 3600 or not 30 <= args.control_timeout <= 1800:
        parser.error('invalid wait timeout')
    manifest = verify_payload()
    if args.check:
        return
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    runtime = logs / 'portable-android-runtime.json'
    server = None
    live_logger = None
    try:
        if manifest.get('live_kernel_logging'):
            with (logs / 'portable-android-live-kmsg.jsonl').open('w') as output:
                live_logger = subprocess.Popen([sys.executable, '-u',
                                                 str(ROOT / 'tools/listen-usb-kmsg.py'),
                                                 '--duration', '1200'], cwd=ROOT,
                                                stdout=output, stderr=subprocess.STDOUT,
                                                start_new_session=True)
        print('Waiting for Orange Pi USB0 in Boot ROM FEL.', flush=True)
        deadline = time.monotonic() + args.wait_fel
        while True:
            try:
                probe = subprocess.run(['bash', str(ROOT / 'tools/host-sunxi-fel.sh'), 'version'],
                                       cwd=ROOT, capture_output=True, text=True, timeout=5)
            except subprocess.TimeoutExpired:
                probe = None
            if probe and probe.returncode == 0 and 'soc=00001823' in probe.stdout:
                break
            if time.monotonic() >= deadline:
                detail = (probe.stderr if probe else 'FEL query timed out').strip()
                raise RuntimeError('No matching live H616/H618 FEL response. ' + detail)
            time.sleep(1)
        with (logs / 'portable-android-upload.log').open('w') as output:
            subprocess.run(['bash', str(ROOT / 'tools/boot-usb-android-diagnostic.sh'),
                            '--userspace', '--fix-thermal-syscfg'], cwd=ROOT,
                           stdout=output, stderr=subprocess.STDOUT, timeout=420, check=True)
        with (logs / 'portable-android-disk.log').open('a') as output:
            instance_token = secrets.token_hex(16)
            server = subprocess.Popen([sys.executable, '-u', str(ROOT / 'tools/serve-usb-disk.py'),
                                       str(ROOT / 'data/android-arm64.img'), '--wait', '600',
                                       '--port', '5555',
                                       '--instance-token', instance_token,
                                       '--progress-seconds', '10', '--trace-requests', '12'],
                                      cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                                      start_new_session=True)
        state = {'runtime_only': True, 'pid': server.pid, 'board': BOARD,
                 'instance_token': instance_token,
                 'image': 'data/android-arm64.img', 'status': 'waiting for Android control'}
        runtime.write_text(json.dumps(state, indent=2) + '\n')
        print('Disk server started. Waiting for Android control; USB DHCP must assign ' + HOST + '.', flush=True)
        deadline = time.monotonic() + args.control_timeout
        control_verified = False
        with (logs / 'portable-android-control.log').open('a') as output:
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError('Disk server exited; inspect portable-android-disk.log')
                if host_usb_address_ready():
                    script = 'confirm-android-ready.sh' if control_verified else 'confirm-android-control.sh'
                    result = subprocess.run([sys.executable, str(ROOT / 'tools/usb-net-command.py'),
                                             str(ROOT / 'prepared/android/arm64' / script),
                                             '--timeout', '5'], cwd=ROOT, stdout=output,
                                            stderr=subprocess.STDOUT, timeout=12)
                    if result.returncode == 0:
                        if not control_verified:
                            sync_device_clock(output)
                            control_verified = True
                            print('Android userspace verified; waiting for framework boot completion.', flush=True)
                        else:
                            state['status'] = 'Android boot completed; disk server stays running'
                            runtime.write_text(json.dumps(state, indent=2) + '\n')
                            print('Android boot completed. Disk server PID ' + str(server.pid) +
                                  ' remains running. ADB target: ' + BOARD + ':5555', flush=True)
                            return
                time.sleep(2)
        raise RuntimeError('Android control did not verify within the configured wait')
    finally:
        if live_logger is not None and live_logger.poll() is None:
            live_logger.terminate()
            live_logger.wait(timeout=5)
        if server is not None and server.poll() is None:
            # The image may be mounted even when control cannot be reached.
            # Leave the server alive until Android has shut down cleanly.
            print('Backing disk remains served; runtime record: ' + str(runtime), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as failure:
        print(str(failure), file=sys.stderr)
        raise SystemExit(1)
