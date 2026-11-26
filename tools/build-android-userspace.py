#!/usr/bin/env python3
"""Prepare a separate experimental Android userspace RAM boot; do not launch it."""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zlib

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / 'prepared/android/arm64'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--trace-nbd', action='store_true', help='include the instrumented storage attachment client')
parser.add_argument('--live-kmsg', action='store_true', help='forward new kernel messages to the USB host on UDP6666')
args = parser.parse_args()
client = ROOT / 'prepared/storage' / ('nbd-reverse-client-trace' if args.trace_nbd else 'nbd-reverse-client')
spec = importlib.util.spec_from_file_location('storage_builder', ROOT / 'tools/build-storage-boot.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
entries = [(n, 0o040755, b'') for n in ['opi', 'run', 'tmp', 'first_stage_ramdisk']]
entries += [('opi/busybox', 0o100755, (TARGET / 'busybox').read_bytes()),
            ('opi/sh', 0o120777, b'busybox'),
            ('opi/watchdog', 0o100755, (TARGET / 'opi-watchdog').read_bytes()),
            ('opi/nbd-reverse-client', 0o100755, client.read_bytes()),
            ('opi-init', 0o100755, (TARGET / 'android-usb-init').read_bytes())]
entries += builder.busybox_bootstrap('opi')
if not {'opi/mkswap', 'opi/swapon'}.issubset({entry[0] for entry in entries}):
    raise ValueError('Rebuild BusyBox with compressed-swap setup applets before preparing Android')
if args.live_kmsg:
    entries.append(('opi/kmsg-forwarder', 0o100755, (TARGET / 'opi-kmsg-forwarder').read_bytes()))
config = (TARGET / 'kernel-usbnet.config').read_text()
if ' opi_recovery_init' not in (TARGET / 'System.usbnet.map').read_text():
    raise ValueError('Stage the recovery-capable USB kernel before preparing Android')
for name in ['USB_ETH', 'USB_SUNXI_HCI', 'USB_SUNXI_USB_MANAGER', 'BLK_DEV_NBD',
             'SWAP', 'ZRAM', 'ZSMALLOC']:
    if f'CONFIG_{name}=y\n' not in config:
        raise ValueError('Required built-in userspace-boot driver missing: ' + name)
fstab = subprocess.check_output(['debugfs', '-R', 'cat /etc/fstab.sun50iw9p1',
                                 str(TARGET / 'modified/vendor_usbnet_a.img')], stderr=subprocess.DEVNULL)
if b'first_stage_mount,logical,slotselect' not in fstab or b'fileencryption=' in fstab:
    raise ValueError('Unexpected USB test-image fstab')
entries.append(('first_stage_ramdisk/fstab.sun50iw9p1', 0o100644, fstab))
# Concatenated newc archives preserve the original Android ownership/modes and
# add the vendor first-stage fstab before our independent USB bootstrap layer.
raw = ((TARGET / 'ramdisk-original.cpio').read_bytes()
       + (TARGET / 'vendor-ramdisk-original.cpio').read_bytes()
       + builder.archive(entries))
ramdisk = gzip.compress(raw, mtime=0)
(TARGET / 'android-usb-initramfs.gz').write_bytes(ramdisk)
source = (TARGET / 'vendor-usb.dts').read_text()
if source.count('boot_devices = "virtual/block/nbd0";') != 1:
    raise ValueError('Unexpected Android boot device property')
source = source.replace('boot_devices = "virtual/block/nbd0";', 'boot_devices = "opi-usb-boot";')
source, count = re.subn(r'\n\t\t\tvbmeta \{.*?\n\t\t\t\};', '', source, flags=re.S)
if count != 1:
    raise ValueError('Expected the stock vbmeta DT node; experimental image is not AVB-verified')
needle = 'watchdog@30090a0 {'
if source.count(needle) != 1:
    raise ValueError('Unexpected watchdog node')
source = source.replace(needle, needle + '\n            status = "disabled";', 1)
source = source.replace('secmon@40000000 {', '''boot-trace@4f900000 {
            reg = <0 0x4f900000 0 0x1000>;
            no-map;
        };
        secmon@40000000 {''', 1)
(TARGET / 'vendor-android-usb.dts').write_text(source)
subprocess.run([shutil.which('dtc') or str(ROOT / 'build/kernel-out/scripts/dtc/dtc'), '-I', 'dts', '-O', 'dtb',
                '-o', str(TARGET / 'vendor-android-usb.dtb'), str(TARGET / 'vendor-android-usb.dts')],
               check=True, stderr=subprocess.DEVNULL)
params = ('console=null mem=1024M '
          'rdinit=/opi-init panic=0 clk_ignore_unused cpuidle.off=1 '
          'nbd.nbds_max=1 nbd.max_part=32 nbd.boot_platform=1 zram.num_devices=1 '
          'g_ether.idVendor=0x1f3a g_ether.idProduct=0xefea '
          'g_ether.iProduct=OrangePi-Android-USB '
          'g_ether.dev_addr=02:1f:3a:00:00:02 g_ether.host_addr=02:1f:3a:00:00:01 '
          'androidboot.hardware=sun50iw9p1 androidboot.slot_suffix=_a '
          'androidboot.boot_devices=opi-usb-boot androidboot.force_normal_boot=1 '
          'androidboot.dynamic_partitions=true androidboot.dynamic_partitions_retrofit=true '
          'androidboot.selinux=permissive androidboot.verifiedbootstate=orange '
          'androidboot.vbmeta.device_state=unlocked androidboot.flash.locked=0 '
          'androidboot.serialno=OPiZero2WUSB androidboot.opi_usb_boot=1 '
          'firmware_class.path=/vendor/etc/firmware buildvariant=userdebug nokaslr opi_diag opi_recovery')
if args.live_kmsg:
    params += ' opi_live_kmsg=1'
text = (f'setenv bootargs {params}\n'
        'setenv initrd_high 0xffffffffffffffff\n'
        'setenv fdt_high 0xffffffffffffffff\n'
        'mw.l 0x4f900004 1\n'
        'mw.l 0x030090b4 0x16aa0001\n'
        'mw.l 0x030090b8 0x16aa00b1\n'
        'mw.l 0x030090b0 0x000014af\n'
        'fdt addr 0x4f800000\nfdt resize 65536\n'
        'mw.l 0x4f900004 3\n'
        f'booti 0x40080000 0x4ff00000:0x{len(ramdisk):x} 0x4f800000\n').encode()
(TARGET / 'boot-android-usb.txt').write_bytes(text)
body = struct.pack('>II', len(text), 0) + text
fields = [0x27051956, 0, 0, len(body), 0, 0, zlib.crc32(body), 5, 2, 6, 0, b'OrangePi experimental Android']
fields[1] = zlib.crc32(struct.pack('>7I4B32s', *fields))
(TARGET / 'boot-android-usb.scr').write_bytes(struct.pack('>7I4B32s', *fields) + body)
regions = [(0x40000000, 0x80000, 'monitor'),
           (0x40080000, (TARGET / 'Image.usbnet').stat().st_size, 'kernel'),
           (0x4a000000, 0x200000, 'bootloader'),
           (0x4f800000, (TARGET / 'vendor-android-usb.dtb').stat().st_size + 65536, 'DTB with growth'),
           (0x4f900000, 0x1000, 'marker'), (0x4fb00000, 0x1000, 'uEnv'),
           (0x4fc00000, len(text) + 72, 'script'),
           (0x4ff00000, len(ramdisk), 'Android initramfs')]
for before, after in zip(sorted(regions), sorted(regions)[1:]):
    if before[0] + before[1] > after[0]:
        raise ValueError('Overlapping RAM regions: ' + before[2] + ', ' + after[2])
if any(a < 0x40000000 or a + n > 0x80000000 for a, n, _ in regions):
    raise ValueError('Payload outside the confirmed 1 GiB RAM range')
files = ['Image.usbnet', 'System.usbnet.map', 'kernel-usbnet.config', 'vendor-android-usb.dtb',
         'android-usb-initramfs.gz', 'boot-android-usb.scr', 'diagnostic-marker.bin',
         'modified/usbnet-disk-update.json']
paths = ['prepared/android/arm64/' + name for name in files]
paths += ['prepared/bootloader/u-boot-watchdog-safe.bin', 'prepared/linux/boot-usb.uEnv']
manifest = {'files': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in paths},
            'instrumented_nbd_client': args.trace_nbd,
            'root_disk_tcp_port': 5555, 'adb_tcp_port': 5555,
            'storage_lifetime_guard': 'Android12 SockDiag ADB-port exception for root-owned sockets',
            'live_kernel_logging': args.live_kmsg,
            'watchdog_reboot_override_requested': True,
            'status': 'prepared only; no userspace boot attempted', 'verified_boot': False,
            'selinux': 'permissive (upstream image setting)', 'thermal_syscfg_bit16_clear_required': True,
            'ram_regions': [{'address': hex(a), 'bytes': n, 'name': label} for a, n, label in regions]}
(TARGET / 'userspace-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Prepared separate experimental Android payload:', len(ramdisk), 'compressed ramdisk bytes; not launched')
