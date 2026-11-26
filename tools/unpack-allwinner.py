#!/usr/bin/env python3
"""Extract selected regular payloads from an unencrypted IMAGEWTY v3 image.

Format reference: YuzukiTsuru/OpenixCard IMAGEWTY.h. Every file range and
output name is checked; no firmware is executed or written to a device.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--select", nargs="*", default=["boot.fex", "vendor_boot.fex", "super.fex", "sunxi.fex", "sys_config.fex", "sys_partition.fex", "env.fex", "dtbo.fex", "vbmeta.fex"])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    total = args.image.stat().st_size
    entries = []
    with args.image.open("rb") as source:
        header = source.read(1024)
        if header[:8] != b"IMAGEWTY" or struct.unpack_from("<I", header, 8)[0] != 0x300:
            raise ValueError("Expected unencrypted IMAGEWTY v3")
        stride, count = struct.unpack_from("<I", header, 32)[0], struct.unpack_from("<I", header, 60)[0]
        if stride != 1024 or not 1 <= count <= 1000 or (count + 1) * stride > total:
            raise ValueError("Invalid item table")
        names = set()
        for index in range(count):
            source.seek((index + 1) * stride)
            record = source.read(stride)
            name_length, record_size = struct.unpack_from("<II", record)
            if name_length != 256 or record_size != stride:
                raise ValueError("Unexpected item format")
            name = record[36:292].split(b"\0", 1)[0].decode("ascii")
            stored, original, offset = struct.unpack_from("<QQQ", record, 292)
            if not name or Path(name).name != name or name in names or "\\" in name:
                raise ValueError("Unsafe or duplicate payload name")
            names.add(name)
            if original > stored or offset < (count + 1) * stride or offset + stored > total:
                raise ValueError("Payload range outside image")
            entries.append({"name": name, "offset": offset, "stored_bytes": stored, "bytes": original})
        for entry in entries:
            if entry["name"] not in args.select:
                continue
            output = args.output / entry["name"]
            source.seek(entry["offset"])
            remaining, digest = entry["bytes"], hashlib.sha256()
            with output.open("xb") as dest:
                while remaining:
                    data = source.read(min(1048576, remaining))
                    if not data:
                        raise EOFError("Short image payload")
                    dest.write(data); digest.update(data); remaining -= len(data)
            entry["sha256"] = digest.hexdigest()
            print(entry["name"], entry["bytes"], entry["sha256"])
    (args.output / "image-manifest.json").write_text(json.dumps({"image": args.image.name, "entries": entries}, indent=2) + "\n")


if __name__ == "__main__":
    main()
