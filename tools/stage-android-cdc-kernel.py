#!/usr/bin/env python3
"""Validate and stage the separate Clang12 ACM+ECM kernel, preserving serial."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--usbnet', action='store_true', help='stage the Ethernet-only kernel')
args = parser.parse_args()
profile = 'usbnet' if args.usbnet else 'cdc'
OUT = ROOT / 'build' / ('android-kernel-' + profile + '-out')
TARGET = ROOT / 'prepared/android/arm64'
image = (OUT / 'arch/arm64/boot/Image').read_bytes()
config = (OUT / '.config').read_text()
required = ['USB_ETH' if args.usbnet else 'USB_CDC_COMPOSITE', 'USB_SUNXI_HCI',
            'USB_SUNXI_USB_MANAGER', 'CFI_CLANG']
if not args.usbnet:
    required.append('U_SERIAL_CONSOLE')
for name in required:
    if f'CONFIG_{name}=y\n' not in config:
        raise ValueError('Required CDC kernel option missing: ' + name)
if '# CONFIG_USB_G_SERIAL is not set\n' not in config:
    raise ValueError('CDC kernel must not include the competing serial gadget')
if image[56:60] != b'ARM\x64' or struct.unpack_from('<Q', image, 8)[0] != 0x80000:
    raise ValueError('Unexpected ARM64 Image header or text offset')
symbols = {p[2]: int(p[0], 16) for row in (OUT / 'System.map').read_text().splitlines()
           if len(p := row.split()) == 3}
start, end = (symbols[k] - symbols['_text'] for k in ['__initcall_start', '__initcall_end'])
if not 0 <= start < end <= len(image) or (end - start) % 8:
    raise ValueError('Invalid initcall table')
pointers = struct.unpack('<' + str((end - start) // 8) + 'Q', image[start:end])
stubs = [value for name, value in symbols.items() if name.endswith('.cfi_jt')]
if not stubs or not pointers or any(not symbols['_text'] <= value < symbols['_etext']
                                    for value in stubs + list(pointers)):
    raise ValueError('CFI stubs or initcall pointers outside permanent text')
patch_sha256 = hashlib.sha256((TARGET.parent / 'patches/usb-boot-kernel.patch').read_bytes()).hexdigest()


def copy_if_changed(source, destination):
    # Re-running the metadata check must not truncate an identical live payload.
    if destination.exists() and source.read_bytes() == destination.read_bytes():
        return
    shutil.copy2(source, destination)


snapshot = TARGET / ('kernel-' + profile + '-clang12-build')
snapshot.mkdir(exist_ok=True)
for source, name in [('arch/arm64/boot/Image', 'Image'), ('System.map', 'System.map'),
                     ('.config', 'kernel.config'), ('Module.symvers', 'Module.symvers'),
                     ('vmlinux', 'vmlinux')]:
    copy_if_changed(OUT / source, snapshot / name)
for name, staged in [('Image', 'Image.' + profile), ('System.map', 'System.' + profile + '.map'),
                     ('kernel.config', 'kernel-' + profile + '.config')]:
    copy_if_changed(snapshot / name, TARGET / staged)
receipt = {'compiler': 'Android Clang/LLD 12.0.7 r416183b1',
           'source_commit': '3a4a29414d558664847202f4d8919b8ab8bcf4a8',
           'source_patch_sha256': patch_sha256,
           'initcall_count': len(pointers), 'named_cfi_stubs': len(stubs),
           'status': 'build and layout checks passed; hardware verification pending',
           'files': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in snapshot.iterdir() if p.name != 'build-receipt.json'}}
(snapshot / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('Staged separate', profile, 'kernel:', len(image), 'bytes;', len(pointers),
      'initcalls;', len(stubs), 'CFI stubs checked')
