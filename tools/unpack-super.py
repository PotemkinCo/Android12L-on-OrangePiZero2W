#!/usr/bin/env python3
"""Extract one-device Android logical partitions, validating LP checksums/ranges.

Reference: AOSP system/core/fs_mgr/liblp/include/liblp/metadata_format.h.
Input must already be expanded from Android sparse format.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    size, results = args.image.stat().st_size, []
    with args.image.open("rb") as source:
        source.seek(4096)
        geometry = bytearray(source.read(4096))
        magic, length = struct.unpack_from("<II", geometry)
        if magic != 0x616C4467 or length != 52:
            raise ValueError("Bad LP geometry")
        checksum = bytes(geometry[8:40]); geometry[8:40] = b"\0" * 32
        if hashlib.sha256(geometry[:length]).digest() != checksum:
            raise ValueError("LP geometry checksum failed")
        maximum, slots, block_size = struct.unpack_from("<III", geometry, 40)
        if not 128 <= maximum <= 4 * 1024 * 1024 or not 1 <= slots <= 8 or block_size % 512:
            raise ValueError("Unsupported LP geometry")
        source.seek(12288)
        metadata = source.read(maximum)
        magic, major, minor, header_size = struct.unpack_from("<IHHI", metadata)
        if magic != 0x414C5030 or major != 10 or minor > 2 or header_size not in (128, 256):
            raise ValueError("Unsupported LP header")
        header = bytearray(metadata[:header_size])
        checksum = bytes(header[12:44]); header[12:44] = b"\0" * 32
        if hashlib.sha256(header).digest() != checksum:
            raise ValueError("LP header checksum failed")
        table_size = struct.unpack_from("<I", header, 44)[0]
        if table_size + header_size > maximum:
            raise ValueError("LP tables exceed metadata")
        tables = metadata[header_size:header_size + table_size]
        if hashlib.sha256(tables).digest() != header[48:80]:
            raise ValueError("LP table checksum failed")

        def table(offset, minimum_size, limit):
            start, count, stride = struct.unpack_from("<III", header, offset)
            if stride < minimum_size or count > limit or start + count * stride > len(tables):
                raise ValueError("Invalid LP table descriptor")
            return [tables[start + i * stride:start + (i + 1) * stride] for i in range(count)]

        partitions = table(80, 52, 128)
        extents = table(92, 24, 4096)
        devices = table(116, 64, 8)
        if len(devices) != 1:
            raise ValueError("Only one backing super device is supported")
        names = set()
        for partition in partitions:
            name = partition[:36].split(b"\0")[0].decode("ascii")
            attributes, first, count, group = struct.unpack_from("<IIII", partition, 36)
            if not re.fullmatch(r"[a-zA-Z0-9_]+", name) or name in names or first + count > len(extents):
                raise ValueError("Invalid partition name or extents")
            names.add(name)
            total = 0
            with (args.output / (name + ".img")).open("xb") as output:
                for extent in extents[first:first + count]:
                    sectors, kind, sector_offset, device = struct.unpack_from("<QIQI", extent)
                    amount, offset = sectors * 512, sector_offset * 512
                    if kind == 1:
                        output.seek(amount, 1)
                    elif kind == 0 and device == 0 and offset + amount <= size:
                        source.seek(offset)
                        remaining = amount
                        while remaining:
                            data = source.read(min(1048576, remaining))
                            if not data:
                                raise EOFError("Short logical extent")
                            output.write(data); remaining -= len(data)
                    else:
                        raise ValueError("Unsupported extent or out-of-range data")
                    total += amount
                output.truncate(total)
            results.append({"name": name, "bytes": total, "attributes": attributes, "extents": count, "group": group})
            print(name, total, "bytes")
    (args.output / "partitions.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
