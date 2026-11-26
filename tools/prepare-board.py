#!/usr/bin/env python3
"""Back up and configure a supported factory SPI environment for USB startup."""
import argparse
import ctypes as c
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import time
import zlib
ROOT = Path(__file__).resolve().parents[1]
SECTOR = 2592
SIZE = 131072

def digest(data):
    return hashlib.sha256(data).hexdigest()

class USB:
    def __init__(self):
        library = ctypes.util.find_library("usb-1.0")
        if not library:
            brew = subprocess.run(['which','brew'],capture_output=True,text=True)
            if brew.returncode == 0:
                prefix = subprocess.check_output(['brew','--prefix','libusb'],text=True).strip()
                library = str(Path(prefix)/'lib/libusb-1.0.dylib')
        if not library: raise RuntimeError('libusb not found; install the host prerequisites')
        self.lib = c.CDLL(library)
        lib = self.lib
        lib.libusb_init.argtypes = [c.POINTER(c.c_void_p)]
        lib.libusb_exit.argtypes = [c.c_void_p]
        lib.libusb_open_device_with_vid_pid.argtypes = [c.c_void_p, c.c_uint16, c.c_uint16]
        lib.libusb_open_device_with_vid_pid.restype = c.c_void_p
        lib.libusb_get_device.argtypes = [c.c_void_p]
        lib.libusb_get_device.restype = c.c_void_p
        lib.libusb_get_device_descriptor.argtypes = [c.c_void_p, c.c_void_p]
        lib.libusb_claim_interface.argtypes = [c.c_void_p, c.c_int]
        lib.libusb_release_interface.argtypes = [c.c_void_p, c.c_int]
        lib.libusb_close.argtypes = [c.c_void_p]
        lib.libusb_bulk_transfer.argtypes = [c.c_void_p, c.c_ubyte, c.c_void_p, c.c_int, c.POINTER(c.c_int), c.c_uint]
        lib.libusb_error_name.argtypes = [c.c_int]
        lib.libusb_error_name.restype = c.c_char_p
        self.context = c.c_void_p()
        self.handle = None
        self.claimed = False
        self.tag = 0x454e5600
        self.check(lib.libusb_init(c.byref(self.context)))
        try:
            self.handle = lib.libusb_open_device_with_vid_pid(self.context, 0x1f3a, 0xefe8)
            if not self.handle:
                raise RuntimeError("No accessible Allwinner vendor USB device")
            descriptor = c.create_string_buffer(18)
            self.check(lib.libusb_get_device_descriptor(lib.libusb_get_device(self.handle), descriptor))
            if struct.unpack_from("<HHH", descriptor.raw, 8) != (0x1f3a, 0xefe8, 0xffff):
                raise RuntimeError("Not the expected vendor U-Boot USB interface")
            self.check(lib.libusb_claim_interface(self.handle, 0))
            self.claimed = True
        except Exception:
            self.close()
            raise

    def check(self, result):
        if result:
            raise RuntimeError(self.lib.libusb_error_name(result).decode())

    def transfer(self, endpoint, value):
        incoming = bool(endpoint & 0x80)
        size = value if incoming else len(value)
        buffer = c.create_string_buffer(size) if incoming else c.create_string_buffer(value, size)
        done = c.c_int()
        self.check(self.lib.libusb_bulk_transfer(self.handle, endpoint, buffer, size, c.byref(done), 10000))
        if done.value != size:
            raise RuntimeError(f"Short USB transfer: {done.value}/{size}")
        return buffer.raw

    def env_command(self, payload=None):
        subcommand = 3 if payload is None else 1
        if payload is not None and len(payload) != SIZE:
            raise ValueError("Only the exact 128 KiB environment partition may be written")
        self.tag += 1
        cmd = bytearray(16)
        cmd[0:2] = bytes((0xf3, subcommand))
        struct.pack_into("<II", cmd, 4, SECTOR, SIZE // 512)
        cbw = struct.pack("<4sIIBBB16s", b"USBC", self.tag, SIZE, 0x80 if payload is None else 0, 0, 16, cmd)
        self.transfer(0x02, cbw)
        data = self.transfer(0x81, SIZE) if payload is None else self.transfer(0x02, payload)
        status = self.transfer(0x81, 13)
        magic, tag, residue, result = struct.unpack("<4sIIB", status)
        if magic != b"USBS" or tag != self.tag or result:
            raise RuntimeError(f"Invalid environment status: {magic!r}, {tag}, {result}")
        return data if payload is None else None

    def close(self):
        if self.handle:
            if self.claimed:
                self.lib.libusb_release_interface(self.handle, 0)
            self.lib.libusb_close(self.handle)
            self.handle = None
        if self.context:
            self.lib.libusb_exit(self.context)
            self.context = c.c_void_p()


def prepare(original):
    if len(original) != SIZE or struct.unpack_from('<I', original)[0] != zlib.crc32(original[4:]) & 0xffffffff:
        raise ValueError('Invalid environment size/CRC; refusing change')
    old = b'bootcmd=run setargs_nand boot_normal'
    if original.count(old + b'\0') != 1:
        raise ValueError('Unknown factory boot command; refusing change')
    candidate = bytearray(original)
    offset = candidate.index(old + b'\0')
    candidate[offset:offset+len(old)] = b'bootcmd=efex'.ljust(len(old), b' ')
    struct.pack_into('<I', candidate, 0, zlib.crc32(candidate[4:]) & 0xffffffff)
    return bytes(candidate)

def validate_backup(backup):
    if len(backup) != 16*1024**2 or backup[4:12] != b'eGON.BT0':
        raise ValueError('Unknown SPI format; refusing change')
    # Factory logical GPT begins at physical0xfc000. Check header/table CRCs
    # and require the tested env physical address and exact128KiB size.
    base=0xfc000; header=backup[base+512:base+1024]
    if header[:8] != b'EFI PART': raise ValueError('Missing factory GPT')
    size,crc=struct.unpack_from('<II',header,12);h=bytearray(header[:size]);h[16:20]=bytes(4)
    if not 92 <= size <= 512 or zlib.crc32(h)&0xffffffff != crc: raise ValueError('GPT header CRC')
    lba,count,stride,crc=struct.unpack_from('<QIII',header,72)
    if count>128 or stride!=128: raise ValueError('Unknown GPT layout')
    table=backup[base+lba*512:base+lba*512+count*stride]
    if len(table)!=count*stride or zlib.crc32(table)&0xffffffff!=crc: raise ValueError('GPT table CRC')
    found=[]
    for i in range(count):
        row=table[i*stride:(i+1)*stride]
        if row[56:128].decode('utf-16le').rstrip('\0')=='env':found.append(struct.unpack_from('<QQ',row,32))
    if found!=[(SECTOR,SECTOR+SIZE//512-1)] or base+SECTOR*512!=0x240000:
        raise ValueError('Unknown environment partition; refusing change')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='write only the checked boot environment after saving a per-board backup')
    args=parser.parse_args()
    native=ROOT/'tools/native'/subprocess.check_output(['uname','-s'],text=True).strip()
    native=Path(str(native)+'-'+subprocess.check_output(['uname','-m'],text=True).strip())
    catcher=native/'catch-fel';reader=native/'read-spi-usb'
    if not catcher.is_file() or not reader.is_file(): raise RuntimeError('Run bash tools/build-board-tools.sh first')
    os.umask(0o077)
    backupdir=ROOT/'backups'/time.strftime('%Y%m%d-%H%M%S');backupdir.mkdir(parents=True,exist_ok=False)
    print('Connect USB0 now, or unplug/reconnect it. Waiting120s for factory maintenance mode.',flush=True)
    subprocess.run([str(catcher),'120','--legacy-hold'],check=True)
    backupfile=backupdir/'spi-original.bin'
    subprocess.run([str(reader),'0','32768',str(backupfile),'--physical'],check=True)
    backup=backupfile.read_bytes();validate_backup(backup)
    original=backup[0x240000:0x260000];candidate=prepare(original)
    (backupdir/'env-original.bin').write_bytes(original);(backupdir/'env-usb.bin').write_bytes(candidate)
    receipt={'spi_sha256':digest(backup),'original_env_sha256':digest(original),'candidate_sha256':digest(candidate),'written':False}
    receiptfile=backupdir/'receipt.json';receiptfile.write_text(json.dumps(receipt,indent=2)+'\n')
    usb=USB()
    try:
        if usb.env_command()!=original or usb.env_command()!=original: raise RuntimeError('Independent environment reads disagree; no write')
        if args.apply:
            try:
                usb.env_command(candidate)
                if usb.env_command()!=candidate: raise RuntimeError('Write verification failed')
            except Exception:
                usb.env_command(original)
                if usb.env_command()!=original: raise RuntimeError('Rollback verification failed; preserve backup')
                raise
            receipt['written']=True;receiptfile.write_text(json.dumps(receipt,indent=2)+'\n')
            print('Verified bootcmd=efex. Unplug for5s, reconnect USB0, then run the Android launcher.')
        else: print('Backup/read-only validation complete. Nothing written; --apply is required to change startup.')
        print('Keep your private per-board backup:',backupdir)
    finally:usb.close()

if __name__=='__main__':main()
