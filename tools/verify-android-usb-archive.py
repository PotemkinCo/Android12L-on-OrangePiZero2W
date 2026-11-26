#!/usr/bin/env python3
"""Read a private Android export without extracting it; verify every checksum."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('archive', type=Path)
args = parser.parse_args()
archive = args.archive
if not archive.name.endswith('.tar.gz'):
    parser.error('expected a .tar.gz export')
prefix = archive.name[:-7]
actual = {}
expected = None
with gzip.open(archive, 'rb') as compressed:
    with tarfile.open(fileobj=compressed, mode='r|') as stream:
        for member in stream:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or path.parts[0] != prefix:
                raise ValueError('Unexpected archive path: ' + member.name)
            if member.uid or member.gid or member.mode & 0o077:
                raise ValueError('Nonprivate archive metadata: ' + member.name)
            if member.isdir():
                continue
            if not member.isfile() or member.size > 8 * 1024**3:
                raise ValueError('Unexpected archive member: ' + member.name)
            name = str(path.relative_to(prefix))
            if name in actual:
                raise ValueError('Duplicate archive member: ' + name)
            source = stream.extractfile(member)
            digest = hashlib.sha256()
            checksum_data = bytearray()
            while block := source.read(8 * 1024**2):
                digest.update(block)
                if name == 'SHA256SUMS':
                    checksum_data.extend(block)
                    if len(checksum_data) > 1024**2:
                        raise ValueError('Oversized checksum manifest')
            actual[name] = digest.hexdigest()
            if name == 'SHA256SUMS':
                expected = {}
                for line in checksum_data.decode().splitlines():
                    value, filename = line.split('  ', 1)
                    if filename in expected or len(value) != 64:
                        raise ValueError('Invalid checksum manifest')
                    expected[filename] = value
    # Consume the gzip footer too, including its CRC and uncompressed-size check.
    while compressed.read(8 * 1024**2):
        pass
if expected is None or set(actual) - {'SHA256SUMS'} != set(expected):
    raise ValueError('Archive file set does not match checksum manifest')
for name, value in expected.items():
    if actual[name] != value:
        raise ValueError('Checksum mismatch: ' + name)
digest = hashlib.sha256()
with archive.open('rb') as source:
    while block := source.read(8 * 1024**2):
        digest.update(block)
print(json.dumps({'status': 'all file checksums, private metadata and gzip CRC verified',
                  'archive': archive.name, 'archive_bytes': archive.stat().st_size,
                  'archive_sha256': digest.hexdigest(), 'files_verified': len(expected),
                  'disk_sha256': actual['data/android-arm64.img']}, indent=2))
