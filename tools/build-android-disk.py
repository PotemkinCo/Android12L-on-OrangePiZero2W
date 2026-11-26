#!/usr/bin/env python3
"""Create a new regular GPT image for the Android USB experiment."""
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / "prepared/android/arm64"
DISK = ROOT / "data/android-arm64.img"
PARTS = [
    ("super", "3G", "super.raw.img"),
    ("metadata", "16M", "filesystems/metadata.img"),
    ("userdata", "2G", "filesystems/userdata.img"),
    ("media_data", "16M", "filesystems/media_data.img"),
    ("boot_a", "64M", "boot.fex"),
    ("boot_b", "64M", None),
    ("vendor_boot_a", "32M", "vendor_boot.fex"),
    ("vendor_boot_b", "32M", None),
    ("misc", "16M", None),
    ("vbmeta_a", "128K", "vbmeta.fex"),
    ("vbmeta_b", "128K", None),
    ("vbmeta_system_a", "64K", "vbmeta_system.fex"),
    ("vbmeta_system_b", "64K", None),
    ("vbmeta_vendor_a", "64K", "vbmeta_vendor.fex"),
    ("vbmeta_vendor_b", "64K", None),
    ("frp", "1M", None),
    ("dtbo_a", "2M", "dtbo.fex"),
    ("dtbo_b", "2M", None),
]


def copy(source, output, offset, length):
    if source.stat().st_size > length:
        raise ValueError("Source does not fit partition: " + str(source))
    output.seek(offset)
    with source.open("rb") as incoming:
        while data := incoming.read(1048576):
            output.write(data)


def main():
    with DISK.open("xb") as output:
        output.truncate(8 * 1024**3)
    command = ["sgdisk", "--clear"]
    for number, (name, size, _) in enumerate(PARTS, 1):
        command += [f"--new={number}:0:+{size}", f"--change-name={number}:{name}", f"--typecode={number}:8300"]
    subprocess.run(command + [str(DISK)], check=True, stdout=subprocess.DEVNULL)
    table = json.loads(subprocess.check_output(["sfdisk", "--json", str(DISK)]))["partitiontable"]
    sector_size = table["sectorsize"]
    manifest = []
    with DISK.open("r+b") as output:
        for (name, _, source), partition in zip(PARTS, table["partitions"], strict=True):
            if partition["name"] != name:
                raise ValueError("Unexpected GPT partition ordering")
            offset, length = partition["start"] * sector_size, partition["size"] * sector_size
            if source:
                copy(ANDROID / source, output, offset, length)
            manifest.append({"name": name, "offset": offset, "bytes": length})
        # The LP metadata is unchanged; replace only the modified vendor extent.
        with (ANDROID / "super.raw.img").open("rb") as super_image:
            super_image.seek(12288)
            header = super_image.read(128)
            header_size = struct.unpack_from("<I", header, 8)[0]
            table_size = struct.unpack_from("<I", header, 44)[0]
            super_image.seek(12288 + header_size)
            tables = super_image.read(table_size)
        p_start, p_count, p_stride = struct.unpack_from("<III", header, 80)
        e_start, e_count, e_stride = struct.unpack_from("<III", header, 92)
        for index in range(p_count):
            p = tables[p_start + index * p_stride:p_start + (index + 1) * p_stride]
            if p[:36].split(b"\0")[0] != b"vendor_a":
                continue
            first, count = struct.unpack_from("<II", p, 40)
            if count != 1 or first >= e_count:
                raise ValueError("Expected one vendor extent")
            sectors, kind, block, device = struct.unpack_from("<QIQI", tables, e_start + first * e_stride)
            if kind or device:
                raise ValueError("Unsupported vendor extent")
            copy(ANDROID / "modified/vendor_a.img", output, manifest[0]["offset"] + block * 512, sectors * 512)
    (ANDROID / "disk-layout.json").write_text(json.dumps(manifest, indent=2) + "\n")
    subprocess.run(["sgdisk", "--verify", str(DISK)], check=True)
    print("Created portable Android disk:", DISK.name)


if __name__ == "__main__":
    main()
