"""Read-only clean-unmount validation for this project's F2FS userdata image.

Layout follows the matching5.4 include/linux/f2fs_fs.h. This validates checkpoint
checksums/footers and the latest clean-unmount flag, not every filesystem inode.
Call with the regular image exclusively locked and no guest mounted.
"""
import struct
import zlib

MAGIC = 0xF2F52010


def inspect_clean_userdata(disk, layout):
    part = next(p for p in layout if p['name'] == 'userdata')
    start, length = part['offset'], part['bytes']
    disk.seek(start + 1024)
    superblock = disk.read(4096)
    if (len(superblock) != 4096 or struct.unpack_from('<I', superblock)[0] != MAGIC
            or struct.unpack_from('<II', superblock, 16) != (12, 9)):
        raise ValueError('Unexpected userdata F2FS geometry')
    block, segment = 4096, 512
    checkpoint = struct.unpack_from('<I', superblock, 76)[0]
    packs = []
    for number in range(2):
        address = (checkpoint + number * segment) * block
        if address < 8192 or address + segment * block > length:
            raise ValueError('Checkpoint outside userdata partition')
        disk.seek(start + address)
        header = disk.read(block)
        if len(header) != block:
            raise ValueError('Short checkpoint header')
        version = struct.unpack_from('<Q', header)[0]
        flags, count = struct.unpack_from('<II', header, 132)
        checksum_offset = struct.unpack_from('<I', header, 164)[0]
        if not 192 <= checksum_offset <= block - 4 or not 2 <= count <= segment:
            raise ValueError('Invalid checkpoint bounds')
        stored = struct.unpack_from('<I', header, checksum_offset)[0]
        calculated = zlib.crc32(header[:checksum_offset], MAGIC ^ 0xFFFFFFFF) ^ 0xFFFFFFFF
        if stored != calculated:
            raise ValueError('F2FS checkpoint CRC mismatch')
        disk.seek(start + address + (count - 1) * block)
        if disk.read(block) != header:
            raise ValueError('F2FS checkpoint footer mismatch')
        packs.append({'pack': number, 'version': version, 'flags': hex(flags),
                      'crc_verified': True, 'matching_footer': True,
                      'clean_unmount': bool(flags & 1)})
    # Match the kernel's signed64-bit version comparison, including rollover.
    difference = (packs[1]['version'] - packs[0]['version']) & (2**64 - 1)
    latest = packs[1] if 0 < difference < 2**63 else packs[0]
    if not latest['clean_unmount'] or int(latest['flags'], 16) & 8:
        raise ValueError('Latest userdata checkpoint is not a clean, error-free unmount')
    return {'status': 'latest F2FS checkpoint clean; both CRCs and footers verified',
            'block_bytes': block, 'packs': packs, 'latest_pack': latest['pack']}
