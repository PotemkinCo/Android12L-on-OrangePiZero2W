"""Offline safety checks; never open USB or write board storage."""
import runpy
from pathlib import Path
import struct
import unittest
import zlib

api=runpy.run_path(str(Path(__file__).resolve().parents[1]/'tools/prepare-board.py'))

class EnvironmentTests(unittest.TestCase):
    def original(self):
        data=bytearray(131072)
        value=b'bootcmd=run setargs_nand boot_normal\0other=preserve-me\0\0'
        data[4:4+len(value)]=value
        struct.pack_into('<I',data,0,zlib.crc32(data[4:])&0xffffffff)
        return bytes(data)

    def test_only_boot_command_and_crc_change(self):
        original=self.original();candidate=api['prepare'](original)
        self.assertEqual(len(original),len(candidate))
        end=4+len(b'bootcmd=run setargs_nand boot_normal')
        self.assertEqual(original[end:],candidate[end:])
        self.assertEqual(candidate[4:16],b'bootcmd=efex')
        self.assertEqual(struct.unpack_from('<I',candidate)[0],zlib.crc32(candidate[4:])&0xffffffff)

    def test_reject_bad_crc(self):
        data=bytearray(self.original());data[-1]^=1
        with self.assertRaises(ValueError):api['prepare'](data)

    def test_reject_unknown_command(self):
        data=bytearray(self.original());data[12]^=1
        struct.pack_into('<I',data,0,zlib.crc32(data[4:])&0xffffffff)
        with self.assertRaises(ValueError):api['prepare'](data)

    def test_reject_wrong_backup(self):
        with self.assertRaises(ValueError):api['validate_backup'](bytes(16*1024**2))

if __name__=='__main__':unittest.main()
