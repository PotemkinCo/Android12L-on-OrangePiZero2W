#!/usr/bin/env python3
"""Build a separate, relocatable USB storage RAM-boot profile."""
import argparse
import hashlib
import ipaddress
import json
import re
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parent.parent


def archive(entries):
    data = bytearray()
    for inode, entry in enumerate(entries + [("TRAILER!!!", 0, b"")], 1):
        name, mode, payload, *device = entry
        if len(device) not in (0, 2):
            raise ValueError("Expected optional device major/minor pair")
        rmajor, rminor = device or (0, 0)
        name = name.encode() + b"\0"
        fields = [inode, mode, 0, 0, 1, 0, len(payload), 0, 0, rmajor, rminor, len(name), 0]
        data.extend(b"070701" + b"".join(f"{x:08x}".encode() for x in fields) + name)
        data.extend(b"\0" * (-len(data) % 4))
        data.extend(payload)
        data.extend(b"\0" * (-len(data) % 4))
    data.extend(b"\0" * (-len(data) % 512))
    return data


def busybox_bootstrap(prefix="bin"):
    """Command links and initial device nodes work before /proc is mounted."""
    table = (ROOT / "build/busybox-1.36.1/include/applet_tables.h").read_text()
    names = re.findall(r'"([^"\\]*)"\s*"\\0"', table)
    if not {"mount", "mkdir", "sh"}.issubset(names):
        raise ValueError("BusyBox applet table is incomplete")
    entries = [(prefix + "/" + name, 0o120777, b"busybox")
               for name in names if name not in ("sh", "busybox")]
    entries += [("dev/null", 0o020666, b"", 1, 3),
                ("dev/console", 0o020600, b"", 5, 1),
                ("dev/kmsg", 0o020600, b"", 1, 11),
                ("dev/mem", 0o020600, b"", 1, 1),
                ("dev/tty", 0o020666, b"", 5, 0)]
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subnet", default="192.168.246.0/30")
    args = parser.parse_args()
    subnet = ipaddress.ip_network(args.subnet)
    if subnet.version != 4 or subnet.prefixlen != 30 or not subnet.is_private:
        parser.error("Use a private IPv4 /30 subnet")
    host, board = [str(x) for x in subnet.hosts()]
    target = ROOT / "prepared/storage"
    link = f"OPI_HOST_IP={host}\nOPI_BOARD_IP={board}\nOPI_CONTROL_PORT=2323\nOPI_DISK_PORT=10809\n".encode()
    payload = archive([
        ("storage", 0o040755, b""),
        ("storage-init", 0o100755, (target / "storage-init").read_bytes()),
        ("storage/link.conf", 0o100644, link),
        ("storage/nbd.ko", 0o100644, (target / "nbd.ko").read_bytes()),
        ("storage/nbd-reverse-client", 0o100755, (target / "nbd-reverse-client").read_bytes()),
    ])
    (target / "storage-overlay.cpio").write_bytes(payload)
    text = ("setenv bootargs console=ttyS0,115200 rdinit=/storage-init panic=10 BOARDNAME=OrangePiZero2W\n"
            "fdt addr 0x4fa00000\nfdt resize 65536\n"
            f"booti 0x40080000 0x4ff00000:0x{len(payload):x} 0x4fa00000\n").encode()
    (target / "boot-storage.txt").write_bytes(text)
    body = struct.pack(">II", len(text), 0) + text
    fields = [0x27051956, 0, 0, len(body), 0, 0, zlib.crc32(body), 5, 2, 6, 0, b"OrangePi USB storage RAM boot"]
    header = struct.pack(">7I4B32s", *fields)
    fields[1] = zlib.crc32(header)
    (target / "boot-storage.scr").write_bytes(struct.pack(">7I4B32s", *fields) + body)
    paths = ["prepared/bootloader/files/u-boot/u-boot-sunxi-with-spl.bin", "prepared/linux/files/OrangePiZero2W.img", "prepared/linux/files/OrangePiZero2W.dtb", "prepared/linux/boot-usb.uEnv", "prepared/storage/storage-overlay.cpio", "prepared/storage/boot-storage.scr"]
    manifest = {"files": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}, "subnet": str(subnet), "host": host, "board": board, "disk_port": 10809, "control_port": 2323, "storage_writes": False}
    (target / "boot-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built USB storage boot: board {board}, DHCP host {host}, overlay {len(payload)} bytes")


if __name__ == "__main__":
    main()
