#!/usr/bin/env python3
"""Disable only U-Boot's watchdog binding in a separate RAM diagnostic bundle.

Replace the unused watchdog IRQ property with status=disabled, preserving every
payload size and all executable bytes. Original SPL, TF-A and U-Boot stay intact.
"""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import shutil

ROOT = Path(__file__).resolve().parent.parent


def properties(blob):
    magic, total, start, strings, _, _, _, _, strings_size, structure_size = struct.unpack_from('>10I', blob)
    if magic != 0xd00dfeed or total > len(blob):
        raise ValueError('Invalid FDT header')
    offset, stack, result = start, [], {}
    while offset < start + structure_size:
        token = struct.unpack_from('>I', blob, offset)[0]
        offset += 4
        if token == 1:
            end = blob.index(0, offset)
            stack.append(blob[offset:end].decode())
            offset = (end + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            header = offset
            size, nameoff = struct.unpack_from('>II', blob, offset)
            offset += 8
            if offset + size > start + structure_size or nameoff >= strings_size:
                raise ValueError('Invalid FDT property bounds')
            end = blob.index(0, strings + nameoff)
            name = blob[strings + nameoff:end].decode()
            key = ('/' + '/'.join(stack[1:]), name)
            if key in result:
                raise ValueError('Duplicate FDT property')
            result[key] = dict(header=header, offset=offset, size=size, nameoff=nameoff,
                               data=bytes(blob[offset:offset + size]))
            offset = (offset + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            return result
        else:
            raise ValueError('Invalid FDT token')
    raise ValueError('Missing FDT end token')


def main():
    source = ROOT / 'prepared/bootloader/files/u-boot/u-boot-sunxi-with-spl.bin'
    original = source.read_bytes()
    if hashlib.sha256(original).hexdigest() != '0d8f6bbcc6909c1f63b97a01e9d58cb786fa1c7f242d62012982a23795aa0276':
        raise ValueError('Unexpected original bootloader')
    spl_size = struct.unpack_from('<I', original, 16)[0]
    fit = properties(original[spl_size:])
    image = fit[('/images/fdt-1', 'data')]
    if any(path.startswith('/images/fdt-1/') or 'signature' in path for path, _ in fit):
        raise ValueError('FIT hashes/signatures need explicit handling')
    start = spl_size + image['offset']
    control = bytearray(image['data'])
    nodes = properties(control)
    node = '/soc/watchdog@30090a0'
    if nodes[(node, 'reg')]['data'] != bytes.fromhex('030090a000000020'):
        raise ValueError('Unexpected watchdog MMIO')
    if (node, 'status') in nodes:
        raise ValueError('Original watchdog already has a status property')
    irq = nodes[(node, 'interrupts')]
    if irq['size'] != 12:
        raise ValueError('Expected a 12-byte IRQ property')
    status_name = next(v['nameoff'] for (_, name), v in nodes.items() if name == 'status')
    struct.pack_into('>II', control, irq['header'], 9, status_name)
    control[irq['offset']:irq['offset'] + 12] = b'disabled\0\0\0\0'
    updated = properties(control)
    if updated[(node, 'status')]['data'] != b'disabled\0' or (node, 'interrupts') in updated:
        raise ValueError('Watchdog status patch failed validation')
    output = bytearray(original)
    output[start:start + len(control)] = control
    changed = [i for i, (a, b) in enumerate(zip(original, output, strict=True)) if a != b]
    if not changed or any(not start <= i < start + len(control) for i in changed):
        raise ValueError('Changes outside the selected control DTB')
    # Prove no executable image or SPL was changed.
    assert output[:spl_size] == original[:spl_size]
    for name in ['uboot', 'atf']:
        item = fit[('/images/' + name, 'data')]
        begin = spl_size + item['offset']
        assert output[begin:begin + item['size']] == original[begin:begin + item['size']]
    target = ROOT / 'prepared/bootloader/u-boot-watchdog-safe.bin'
    target.write_bytes(output)
    dtb = ROOT / 'prepared/bootloader/uboot-control-watchdog-disabled.dtb'
    dtb.write_bytes(control)
    subprocess.run([shutil.which('dtc') or str(ROOT / 'build/kernel-out/scripts/dtc/dtc'), '-I', 'dtb', '-O', 'dts',
                    '-o', str(dtb.with_suffix('.dts')), str(dtb)], check=True, stderr=subprocess.DEVNULL)
    receipt = dict(source_sha256=hashlib.sha256(original).hexdigest(),
                   diagnostic_sha256=hashlib.sha256(output).hexdigest(),
                   changed_bytes=len(changed), purpose='RAM diagnostics only; keep external watchdog active',
                   executable_images_unchanged=True, watchdog_node_status='disabled')
    (ROOT / 'prepared/bootloader/watchdog-diagnostic-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
