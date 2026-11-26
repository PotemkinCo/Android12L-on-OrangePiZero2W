#!/usr/bin/env python3
"""Assemble a new8GiB GPT disk from stock system files and empty filesystems."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import uuid
import zlib

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--stock',type=Path,required=True)
p.add_argument('--filesystems',type=Path,required=True)
p.add_argument('--layout',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
for name,offset,magic in [('userdata',1024,b'\x10\x20\xf5\xf2'),
                          ('metadata',1080,b'\x53\xef'),('media_data',54,b'FAT16')]:
    with (a.filesystems/(name+'.img')).open('rb') as source:
        source.seek(offset)
        if source.read(len(magic))!=magic:raise ValueError('Wrong filesystem type: '+name)
layout=json.loads(a.layout.read_text());sectors=8*1024**3//512
table=bytearray(128*128)
for i,part in enumerate(layout):
    start=part['offset']//512;end=start+part['bytes']//512-1
    if part['offset']%512 or part['bytes']%512 or start<2048 or end>sectors-34:
        raise ValueError('Invalid partition geometry')
    if i and part['offset']<layout[i-1]['offset']+layout[i-1]['bytes']:
        raise ValueError('Overlapping partitions')
    row=struct.pack('<16s16sQQQ72s',uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4').bytes_le,
                    uuid.uuid4().bytes_le,start,end,0,part['name'].encode('utf-16le'))
    table[i*128:(i+1)*128]=row
disk_id=uuid.uuid4().bytes_le
def header(current,backup,entries):
    h=bytearray(struct.pack('<8sIIIIQQQQ16sQIII',b'EFI PART',0x10000,92,0,0,current,backup,
                          34,sectors-34,disk_id,entries,128,128,zlib.crc32(table)&0xffffffff))
    struct.pack_into('<I',h,16,zlib.crc32(h)&0xffffffff)
    return h.ljust(512,b'\0')
sources={'super':'super.raw.img','boot_a':'boot.fex','vendor_boot_a':'vendor_boot.fex',
         'vbmeta_a':'vbmeta.fex','vbmeta_system_a':'vbmeta_system.fex',
         'vbmeta_vendor_a':'vbmeta_vendor.fex','dtbo_a':'dtbo.fex'}
a.output.parent.mkdir(parents=True,exist_ok=True)
with a.output.open('xb') as out:
    out.truncate(sectors*512)
    mbr=bytearray(512);mbr[446:462]=struct.pack('<B3sB3sII',0,b'\0\2\0',0xee,b'\xff'*3,1,sectors-1);mbr[510:]=b'\x55\xaa'
    out.seek(0);out.write(mbr);out.write(header(1,sectors-1,2));out.write(table)
    out.seek((sectors-33)*512);out.write(table);out.write(header(sectors-1,1,sectors-33))
    def copy(source,offset,length):
        if source.stat().st_size>length:raise ValueError('Partition overflow: '+str(source))
        out.seek(offset)
        with source.open('rb') as incoming:
            while block:=incoming.read(8*1024**2):out.write(block)
    for part in layout:
        name=part['name']
        source=a.filesystems/(name+'.img') if name in {'metadata','userdata','media_data'} else a.stock/sources[name] if name in sources else None
        if source:copy(source,part['offset'],part['bytes'])
    # Use the pinned LP metadata to locate both matching customized vendors.
    with (a.stock/'super.raw.img').open('rb') as source:
        source.seek(12288);h=source.read(128);hs=struct.unpack_from('<I',h,8)[0];ts=struct.unpack_from('<I',h,44)[0]
        source.seek(12288);h=source.read(hs);t=source.read(ts)
    test=bytearray(h);test[12:44]=bytes(32)
    if hashlib.sha256(test).digest()!=h[12:44] or hashlib.sha256(t).digest()!=h[48:80]:raise ValueError('LP CRC')
    po,pc,ps=struct.unpack_from('<III',h,80);eo,ec,es=struct.unpack_from('<III',h,92)
    replacements={'vendor_a':'modified/vendor_usbnet_a.img','vendor_dlkm_a':'modified/vendor_dlkm_usbnet_a.img'}
    done=set()
    for i in range(pc):
        row=t[po+i*ps:po+(i+1)*ps];name=row[:36].split(b'\0')[0].decode()
        if name not in replacements:continue
        first,count=struct.unpack_from('<II',row,40)
        if count!=1 or first>=ec:raise ValueError('LP extent count')
        size,kind,block,device=struct.unpack_from('<QIQI',t,eo+first*es)
        if kind or device or block*512+size*512>layout[0]['bytes']:raise ValueError('LP extent')
        source=a.stock/replacements[name]
        if source.stat().st_size!=size*512:raise ValueError('LP source size')
        copy(source,layout[0]['offset']+block*512,size*512);done.add(name)
    if done!=set(replacements):raise ValueError('Missing vendor partition')
    out.flush();os.fsync(out.fileno())
print('Created fresh Android disk; no previously booted userdata was copied.')
