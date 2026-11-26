#!/usr/bin/env python3
"""Request normal Android reboot, verify live FEL, then release our disk server.

Never stop a disk server while Android might still have its image mounted.
No laptop power setting, USB-port path, or Linux-only device API is used.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from f2fs_checkpoint import inspect_clean_userdata

ROOT = Path(__file__).resolve().parent.parent


def verify_fel():
    result = subprocess.run(['bash', str(ROOT / 'tools/host-sunxi-fel.sh'), 'version'],
                            cwd=ROOT, capture_output=True, text=True, timeout=5)
    return result.returncode == 0 and 'soc=00001823' in result.stdout


def reboot_android(output):
    with tempfile.TemporaryDirectory(prefix='opi-usb-stop-') as directory:
        script = Path(directory) / 'reboot.sh'
        script.write_text('set -e\n[ "$(getprop ro.build.version.sdk)" = 32 ]\n'
                          'printf "__ANDROID_NORMAL_REBOOT_REQUEST__\\n"\n'
                          'sync\nsvc power reboot bootloader\n')
        try:
            subprocess.run([sys.executable, str(ROOT / 'tools/usb-net-command.py'),
                            str(script), '--timeout', '15'], cwd=ROOT, stdout=output,
                           stderr=subprocess.STDOUT, timeout=25)
        except subprocess.TimeoutExpired:
            # Android can close this connection during normal shutdown.
            output.write('Host control ended while waiting for Android shutdown.\n')
            output.flush()
        output.flush()
        if '__ANDROID_NORMAL_REBOOT_REQUEST__' not in Path(output.name).read_text():
            raise RuntimeError('No actual Android SDK32 shutdown acknowledgement; disk server left running')


def release_owned_server(state):
    pid, token = state.get('pid'), state.get('instance_token')
    if (not isinstance(pid, int) or pid <= 1 or not isinstance(token, str) or len(token) != 32
            or any(c not in '0123456789abcdef' for c in token)):
        raise RuntimeError('No valid disk-server ownership record; process left untouched')
    process = subprocess.run(['ps', '-ww', '-p', str(pid), '-o', 'command='],
                             capture_output=True, text=True, timeout=5)
    if process.returncode != 0:
        return
    command = process.stdout
    if str(ROOT / 'tools/serve-usb-disk.py') not in command or '--instance-token ' + token not in command:
        raise RuntimeError('Disk-server PID no longer matches this launch; process left untouched')
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        pass  # The proven old Android connection may have just closed itself.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--already-in-fel', action='store_true', help='verify live ROM and clean up after automatic recovery')
    parser.add_argument('--reboot-only', action='store_true', help='diagnostic mode: verify reboot, leave external server cleanup to its owner')
    args = parser.parse_args()
    logs = ROOT / 'logs'; logs.mkdir(exist_ok=True)
    receipt = {'status': 'requested', 'normal_android_shutdown': not args.already_in_fel}
    if not args.already_in_fel:
        print('Requesting normal Android shutdown/reboot. Disk remains served.', flush=True)
        with (logs / 'portable-android-stop-control.log').open('w') as output:
            reboot_android(output)
    deadline = time.monotonic() + 120
    while True:
        try:
            ready = verify_fel()
        except subprocess.TimeoutExpired:
            ready = False
        if ready:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('No live Boot ROM confirmation; disk server left running')
        time.sleep(1)
    receipt['live_boot_rom_verified'] = True
    if args.reboot_only:
        receipt['status'] = 'Boot ROM verified; external disk-server owner retains cleanup'
    else:
        runtime = logs / 'portable-android-runtime.json'
        state = json.loads(runtime.read_text())
        release_owned_server(state)
        image = ROOT / 'data/android-arm64.img'
        deadline = time.monotonic() + 10
        while True:
            try:
                with image.open('rb') as disk:
                    fcntl.flock(disk, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    layout = json.loads((ROOT / 'prepared/android/arm64/disk-layout.json').read_text())
                    receipt['userdata_checkpoint'] = inspect_clean_userdata(disk, layout)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('ROM verified but backing image remains locked; do not copy it')
                time.sleep(.1)
        state['status'] = 'stopped; Boot ROM verified and disk image unlocked'
        runtime.write_text(json.dumps(state, indent=2) + '\n')
        receipt['status'] = state['status']
    (logs / 'portable-android-stop-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(receipt['status'], flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
