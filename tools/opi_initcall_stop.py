"""Plan a four-byte, RAM-only stop at a verified ARM64 initcall jump stub."""
import hashlib
import re
import struct


def plan_stop(target, name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError('Use one plain initcall function name')
    image = (target / 'Image.serial').read_bytes()
    map_data = (target / 'System.serial.map').read_bytes()
    symbols = {parts[2]: int(parts[0], 16) for row in map_data.decode().splitlines()
               if len(parts := row.split()) == 3}
    start, end = (symbols[k] - symbols['_text'] for k in ['__initcall_start', '__initcall_end'])
    if not 0 <= start < end <= len(image) or (end - start) % 8:
        raise ValueError('Invalid initcall table bounds')
    pointers = struct.unpack('<' + str((end - start) // 8) + 'Q', image[start:end])
    candidates = [(symbol, value) for symbol, value in symbols.items()
                  if symbol.endswith('.cfi_jt')
                  and symbol.split('$', 1)[0].split('.', 1)[0] == name]
    if len(candidates) == 1:
        symbol, virtual = candidates[0]
        body = symbols[symbol.removesuffix('.cfi_jt')]
    elif not candidates:
        # LTO omits individual names for some CFI stubs. An exact initcall
        # table variable plus its independently named body still identifies
        # one slot and one branch; no nearest-symbol/address guessing.
        pattern = re.compile(r'__initcall_.*_' + re.escape(name) + r'(?:early|rootfs|[0-9]s?)')
        slots = [(n, v - symbols['_text']) for n, v in symbols.items() if pattern.fullmatch(n)]
        if len(slots) != 1 or name not in symbols:
            raise ValueError(f'Expected one verified initcall slot/body for {name}')
        symbol, slot = slots[0]
        if not start <= slot < end or (slot - start) % 8:
            raise ValueError('Named initcall slot is outside its table')
        virtual = pointers[(slot - start) // 8]
        body = symbols[name]
    else:
        raise ValueError(f'Expected one initcall jump stub for {name}, found {len(candidates)}')
    offset = virtual - symbols['_text']
    if not symbols['_text'] <= virtual < symbols['_etext']:
        raise ValueError('Initcall jump stub is outside permanent kernel text')
    if not 0 <= offset <= len(image) - 4 or offset % 4:
        raise ValueError('Jump stub is outside the aligned Image range')
    original = struct.unpack_from('<I', image, offset)[0]
    if original & 0xfc000000 != 0x14000000:
        raise ValueError('Jump stub is not an unconditional AArch64 branch')
    immediate = original & 0x03ffffff
    if immediate & 0x02000000:
        immediate -= 1 << 26
    if virtual + immediate * 4 != body:
        raise ValueError('Jump stub does not target its matching function body')
    if pointers.count(virtual) != 1:
        raise ValueError('Selected stub is not one unique initcall table entry')
    return {'function': name, 'symbol': symbol, 'initcall_index': pointers.index(virtual) + 1,
            'physical_address': 0x40080000 + offset, 'original_word': original,
            'replacement_word': 0x14000000,  # b . ; watchdog reset remains enabled
            'image_sha256': hashlib.sha256(image).hexdigest(),
            'map_sha256': hashlib.sha256(map_data).hexdigest(),
            'persistent_write': False}
