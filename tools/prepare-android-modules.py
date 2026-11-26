#!/usr/bin/env python3
"""Prepare a new vendor_dlkm partition with modules matching the custom kernel.

Only generated regular files are written; the Android disk is not touched.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / 'prepared/android/arm64'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cdc', action='store_true', help='prepare modules for the separate Clang12 ACM+ECM kernel')
parser.add_argument('--usbnet', action='store_true', help='prepare modules for the separate Ethernet-only kernel')
parser.add_argument('--wifi-uwe5622', action='store_true', help='include matching optional UWE5622 Wi-Fi modules')
args = parser.parse_args()
if args.cdc and args.usbnet:
    parser.error('choose one kernel profile')
profile = 'usbnet' if args.usbnet else 'cdc' if args.cdc else None
if args.wifi_uwe5622 and profile != 'usbnet':
    parser.error('--wifi-uwe5622 requires --usbnet')
module_root = TARGET / ('kernel-' + profile + '-root' if profile else 'kernel-root') / 'lib/modules/5.4.125'
modules = {p.name: p for p in module_root.rglob('*.ko')}
modules['mali_kbase.ko'] = TARGET / ('mali-kbase-' + profile + '.ko' if profile else 'mali-kbase-usb.ko')
if args.wifi_uwe5622:
    wifi = TARGET / 'wifi-uwe5622'
    receipt = json.loads((wifi / 'build-receipt.json').read_text())
    if receipt['kernel_sha256'] != hashlib.sha256((TARGET / 'Image.usbnet').read_bytes()).hexdigest():
        raise ValueError('Wi-Fi modules were built against a different kernel')
    for name, expected in receipt['modules'].items():
        path = wifi / name
        if path.name != name or path.suffix != '.ko' or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Invalid Wi-Fi module receipt')
        modules[name] = path
versions = {}
out_dir = ROOT / 'build' / ('android-kernel-' + profile + '-out' if profile else 'android-kernel-out')
for line in (out_dir / 'Module.symvers').read_text().splitlines():
    fields = line.split()
    if len(fields) >= 2:
        versions[fields[1]] = int(fields[0], 16)
for path in modules.values():
    exports = subprocess.run(['modprobe', '--show-exports', str(path)], text=True, capture_output=True)
    if exports.returncode and 'No data available' not in exports.stderr:
        raise RuntimeError(exports.stderr)
    for row in exports.stdout.splitlines():
        crc, symbol = row.split()
        value = int(crc, 16)
        if symbol in versions and versions[symbol] != value:
            raise ValueError('Conflicting module export version: ' + symbol)
        versions[symbol] = value
for name, path in modules.items():
    info = subprocess.check_output(['modprobe', '--dump-modversions', str(path)], text=True)
    for row in info.splitlines():
        crc, symbol = row.split()
        if versions.get(symbol) != int(crc, 16):
            raise ValueError('Kernel symbol version mismatch: ' + name + ': ' + symbol)
print('Checked symbol-version CRCs for', len(modules), 'matching modules')
stage = ROOT / 'build' / ('android-' + profile + '-module-stage' if profile else 'android-module-stage')
stage_modules = stage / 'lib/modules/5.4.125'
stage_modules.mkdir(parents=True, exist_ok=True)
for path in stage_modules.glob('*.ko'):
    path.unlink()
for name, path in modules.items():
    shutil.copyfile(path, stage_modules / name)
(stage_modules / 'modules.order').write_text('\n'.join(modules) + '\n')
for name in ['modules.builtin', 'modules.builtin.modinfo']:
    shutil.copyfile(module_root / name, stage_modules / name)
subprocess.run(['depmod', '-b', str(stage), '5.4.125'], check=True)
load = ['sunxi-hci.ko', 'ehci-sunxi.ko', 'ohci-sunxi.ko', 'sunxi_usbc.ko',
        'init-input.ko', 'mali_kbase.ko']
if profile:
    load = ['init-input.ko', 'mali_kbase.ko']
if any(name not in modules for name in load):
    raise ValueError('Required load module is missing')
(stage_modules / 'modules.load').write_text('\n'.join(load) + '\n')
source = TARGET / 'partitions/vendor_dlkm_a.img'
output = TARGET / ('modified/vendor_dlkm_' + profile + '_a.img' if profile else 'modified/vendor_dlkm_a.img')
shutil.copyfile(source, output)
# The original image is pinned. Enumerate only its module directory, then
# replace old drivers rather than leaving incompatible stock copies present.
listing = subprocess.check_output(['debugfs', '-R', 'ls -p /lib/modules', str(source)],
                                  text=True, stderr=subprocess.DEVNULL)
old_names = []
for row in listing.splitlines():
    parts = row.split('/')
    if len(parts) > 5:
        name = parts[5]
        if name.endswith('.ko') or name.startswith('modules.'):
            if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in name):
                raise ValueError('Unsafe module filename')
            old_names.append(name)
if not old_names:
    raise ValueError('Could not enumerate the original module directory')
commands = ['rm /lib/modules/' + name for name in old_names]
files = list(stage_modules.glob('*.ko')) + list(stage_modules.glob('modules.*'))
for path in files:
    remote = '/lib/modules/' + path.name
    commands += [f'write {path} {remote}', f'sif {remote} mode 0100644',
                 f'ea_set {remote} security.selinux u:object_r:vendor_file:s0']
command_file = stage / 'image.commands'
command_file.write_text('\n'.join(commands) + '\n')
log_prefix = 'android-' + profile + '-vendor-dlkm' if profile else 'android-vendor-dlkm'
with (ROOT / 'logs' / (log_prefix + '-write.log')).open('w') as log:
    subprocess.run(['debugfs', '-w', '-f', str(command_file), str(output)],
                   check=True, stdout=log, stderr=subprocess.STDOUT)
# debugfs may report individual command errors while exiting zero: independently
# read each installed module back and compare bytes.
readback = stage / 'readback.ko'
for name, source_path in modules.items():
    if readback.exists():
        readback.unlink()
    subprocess.run(['debugfs', '-R', f'dump /lib/modules/{name} {readback}', str(output)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if readback.read_bytes() != source_path.read_bytes():
        raise ValueError('Module image readback mismatch: ' + name)
with (ROOT / 'logs' / (log_prefix + '-check.log')).open('w') as log:
    subprocess.run(['e2fsck', '-fn', str(output)], check=True, stdout=log, stderr=subprocess.STDOUT)
manifest = {'partition_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'kernel_sha256': hashlib.sha256((TARGET / ('Image.' + profile if profile else 'Image.debug')).read_bytes()).hexdigest(),
            'modules': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in modules.items()},
            'modules_load': load, 'symbol_versions_checked': True,
            'status': 'prepared and filesystem-checked; not deployed to Android disk or loaded by Android'}
manifest_name = 'vendor-dlkm-' + profile + '-manifest.json' if profile else 'vendor-dlkm-manifest.json'
(TARGET / 'modified' / manifest_name).write_text(json.dumps(manifest, indent=2) + '\n')
print('Prepared', output.relative_to(ROOT), 'with verified module readbacks and filesystem check')
