#!/usr/bin/env python3
"""Update only known vendor extents in the project's unserved Android image."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / 'prepared/android/arm64'
DISK = ROOT / 'data/android-arm64.img'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check', action='store_true', help='validate every offset/hash without writing')
args = parser.parse_args()


def sha(data):
    return hashlib.sha256(data).hexdigest()


layout = json.loads((TARGET / 'disk-layout.json').read_text())
table = json.loads(subprocess.check_output(['sfdisk', '--json', str(DISK)]))['partitiontable']
actual = [{'name': p['name'], 'offset': p['start'] * table['sectorsize'],
           'bytes': p['size'] * table['sectorsize']} for p in table['partitions']]
if actual != layout or layout[0]['name'] != 'super':
    raise ValueError('GPT layout does not match the generated project disk')
super_offset = layout[0]['offset']
metadata_source = TARGET / 'super.raw.img'
with metadata_source.open('rb') as file:
    file.seek(12288)
    initial = file.read(128)
    if struct.unpack_from('<I', initial)[0] != 0x414c5030:
        raise ValueError('Invalid LP metadata header')
    header_size = struct.unpack_from('<I', initial, 8)[0]
    tables_size = struct.unpack_from('<I', initial, 44)[0]
    if not 128 <= header_size <= 512 or not 0 < tables_size < 65536:
        raise ValueError('Invalid LP metadata bounds')
    file.seek(12288)
    header = file.read(header_size)
    tables = file.read(tables_size)
check_header = bytearray(header)
check_header[12:44] = bytes(32)
if bytes.fromhex(sha(check_header)) != header[12:44] or bytes.fromhex(sha(tables)) != header[48:80]:
    raise ValueError('LP metadata checksum mismatch')
p_start, p_count, p_stride = struct.unpack_from('<III', header, 80)
e_start, e_count, e_stride = struct.unpack_from('<III', header, 92)
if p_stride < 52 or e_stride < 24 or p_start + p_count * p_stride > len(tables) or e_start + e_count * e_stride > len(tables):
    raise ValueError('Invalid LP partition/extent tables')
sources = {'vendor_a': TARGET / 'modified/vendor_usbnet_a.img',
           'vendor_dlkm_a': TARGET / 'modified/vendor_dlkm_usbnet_a.img'}
receipt_file = TARGET / 'modified/usbnet-disk-update.json'
previous_receipt = json.loads(receipt_file.read_text()) if receipt_file.exists() else None
verified_status = 'written, fsynced and full extent readbacks verified; Android boot unverified'
changes = []
for number in range(p_count):
    part = tables[p_start + number * p_stride:p_start + (number + 1) * p_stride]
    name = part[:36].split(b'\0')[0].decode()
    if name not in sources:
        continue
    first, count = struct.unpack_from('<II', part, 40)
    if count != 1 or first >= e_count:
        raise ValueError('Expected one linear extent for ' + name)
    sectors, kind, block, device = struct.unpack_from('<QIQI', tables, e_start + first * e_stride)
    size = sectors * 512
    if kind or device or block * 512 + size > layout[0]['bytes'] or sources[name].stat().st_size != size:
        raise ValueError('Unexpected extent mapping or image size for ' + name)
    allowed = [TARGET / ('partitions/' + name + '.img')]
    if name == 'vendor_a':
        allowed.append(TARGET / 'modified/vendor_a.img')
    else:
        allowed += [TARGET / 'modified/vendor_dlkm_a.img', TARGET / 'modified/vendor_dlkm_cdc_a.img']
    changes.append({'name': name, 'offset': super_offset + block * 512, 'bytes': size,
                    'source': sources[name], 'allowed': allowed})
if {c['name'] for c in changes} != set(sources):
    raise ValueError('Did not locate both intended vendor partitions')
for previous, current in zip(sorted(changes, key=lambda c: c['offset']), sorted(changes, key=lambda c: c['offset'])[1:]):
    if previous['offset'] + previous['bytes'] > current['offset']:
        raise ValueError('Partition updates overlap')
fd = os.open(DISK, (os.O_RDONLY if args.check else os.O_RDWR) | os.O_NOFOLLOW)
with os.fdopen(fd, 'rb' if args.check else 'r+b') as disk:
    fcntl.flock(disk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if not stat.S_ISREG(os.fstat(disk.fileno()).st_mode):
        raise ValueError('Backing image must be a regular file')
    disk.seek(super_offset + 12288)
    if disk.read(header_size + tables_size) != header + tables:
        raise ValueError('Backing-disk LP metadata differs from the pinned source')
    for change in changes:
        disk.seek(change['offset'])
        change['before_sha256'] = sha(disk.read(change['bytes']))
        change['after_sha256'] = sha(change['source'].read_bytes())
        allowed = {sha(p.read_bytes()) for p in change['allowed'] if p.exists()}
        allowed.add(change['after_sha256'])
        if (previous_receipt and previous_receipt.get('status') == verified_status
                and previous_receipt.get('disk') == str(DISK.relative_to(ROOT))):
            matches = [p for p in previous_receipt.get('partitions', [])
                       if all(p.get(k) == change[k] for k in ('name', 'offset', 'bytes'))
                       and p.get('source') == str(change['source'].relative_to(ROOT))]
            if len(matches) == 1:
                digest = matches[0].get('after_sha256', '')
                if len(digest) == 64 and all(c in '0123456789abcdef' for c in digest):
                    allowed.add(digest)
        if change['before_sha256'] not in allowed:
            raise ValueError('Unknown existing partition contents; refusing update: ' + change['name'])
    receipt = {'disk': str(DISK.relative_to(ROOT)), 'status': 'validated; not written',
               'partitions': [{k: str(v.relative_to(ROOT)) if k == 'source' else v
                               for k, v in c.items() if k != 'allowed'} for c in changes]}
    if not args.check:
        if previous_receipt:
            history = TARGET / 'modified/disk-update-history'
            history.mkdir(exist_ok=True)
            old_text = receipt_file.read_bytes()
            (history / (sha(old_text) + '.json')).write_bytes(old_text)
        receipt_file.write_text(json.dumps(receipt, indent=2) + '\n')
        for change in changes:
            if change['before_sha256'] == change['after_sha256']:
                continue
            disk.seek(change['offset'])
            with change['source'].open('rb') as source:
                while chunk := source.read(1048576):
                    disk.write(chunk)
        disk.flush()
        os.fsync(disk.fileno())
        for change in changes:
            disk.seek(change['offset'])
            if sha(disk.read(change['bytes'])) != change['after_sha256']:
                raise ValueError('Partition readback mismatch: ' + change['name'])
        receipt['status'] = verified_status
        receipt_file.write_text(json.dumps(receipt, indent=2) + '\n')
print('Validated' if args.check else 'Updated and verified', ', '.join(c['name'] for c in changes))
