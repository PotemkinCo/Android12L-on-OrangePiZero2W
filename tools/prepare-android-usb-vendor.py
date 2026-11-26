#!/usr/bin/env python3
"""Add USB test control to a separate generated vendor image."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / 'prepared/android/arm64'
source = TARGET / 'modified/vendor_a.img'
output = TARGET / 'modified/vendor_usbnet_a.img'
shutil.copyfile(source, output)
with (ROOT / 'logs/android-usbnet-vendor-prepare.log').open('w') as log:
    subprocess.run(['e2fsck', '-fy', str(output)], check=True, stdout=log, stderr=subprocess.STDOUT)
    # The LP extent already contains unused bytes after the smaller filesystem.
    # Grow only inside that existing regular image; do not change LP/GPT layout.
    subprocess.run(['resize2fs', str(output)], check=True, stdout=log, stderr=subprocess.STDOUT)
if output.stat().st_size != source.stat().st_size:
    raise ValueError('Vendor filesystem resize changed the partition-image length')
# The stock low-RAM feature filter removes AppWidgetManager, while its bundled
# Quickstep still dereferences it. Enable that service for this test profile.
feature_file = TARGET / 'opi-usb-features.xml'
feature_file.write_text('<?xml version="1.0" encoding="utf-8"?>\n'
                        '<permissions>\n'
                        '    <feature name="android.software.app_widgets" />\n'
                        '</permissions>\n')
wifi_config = ROOT / 'references/orangepi-firmware/wifi_2355b001_1ant.ini'
wifi_receipt = json.loads((wifi_config.parent / 'wifi-ini-receipt.json').read_text())
if hashlib.sha256(wifi_config.read_bytes()).hexdigest() != wifi_receipt['sha256']:
    raise ValueError('Manufacturer Wi-Fi configuration checksum mismatch')
files = [(TARGET / 'busybox', '/bin/busybox-opi', '0100755'),
         (TARGET / 'opi-watchdog', '/bin/opi-watchdog', '0100755'),
         (TARGET / 'opi-usb-control.rc', '/etc/init/init.opi-usb.rc', '0100644'),
         (TARGET / 'opi-usb-network-guard.sh', '/bin/opi-usb-network-guard.sh', '0100755'),
         (feature_file, '/etc/permissions/opi-usb-features.xml', '0100644'),
         (wifi_config, '/etc/firmware/wifi_2355b001_1ant.ini', '0100644')]
commands = []
for local, remote, mode in files:
    commands += [f'write {local} {remote}', f'sif {remote} mode {mode}',
                 f'ea_set {remote} security.selinux u:object_r:vendor_file:s0']
command_file = ROOT / 'build/android-usbnet-vendor.commands'
command_file.write_text('\n'.join(commands) + '\n')
with (ROOT / 'logs/android-usbnet-vendor-write.log').open('w') as log:
    subprocess.run(['debugfs', '-w', '-f', str(command_file), str(output)], check=True,
                   stdout=log, stderr=subprocess.STDOUT)
for number, (local, remote, _) in enumerate(files):
    readback = ROOT / 'build' / f'android-usbnet-vendor-readback-{number}'
    readback.unlink(missing_ok=True)
    subprocess.run(['debugfs', '-R', f'dump {remote} {readback}', str(output)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if readback.read_bytes() != local.read_bytes():
        raise ValueError('Vendor image content mismatch: ' + remote)
with (ROOT / 'logs/android-usbnet-vendor-check.log').open('w') as log:
    subprocess.run(['e2fsck', '-fn', str(output)], check=True, stdout=log, stderr=subprocess.STDOUT)
receipt = {'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
           'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
           'bytes': output.stat().st_size,
           'files': {remote: hashlib.sha256(local.read_bytes()).hexdigest() for local, remote, _ in files},
           'status': 'prepared and filesystem-checked; not deployed or Android-verified'}
(TARGET / 'modified/vendor-usbnet-manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('Prepared separate vendor image with verified USB control files')
