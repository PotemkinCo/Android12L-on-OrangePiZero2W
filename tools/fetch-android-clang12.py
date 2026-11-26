#!/usr/bin/env python3
"""Fetch selected official Android compiler files and verify Git blob IDs."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / 'tools/clang12'
BASE = 'https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+/refs/heads/android12-release/clang-r416183b1/'

def tree(path):
    text = path.read_text()
    return {x['name']: x for x in json.loads(text[4:])['entries']}

def fetch(item):
    folder, name = item
    tree_name = 'include' if folder == 'lib64/clang/12.0.7/include' else folder
    entry = tree(ROOT / f'references/android/toolchain12/{tree_name}-tree.json')[name]
    output = DEST / folder / name
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file() or output.is_symlink():
        data = str(output.readlink()).encode() if output.is_symlink() else output.read_bytes()
        actual = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
        if actual == entry['id']:
            print(folder + '/' + name, 'already verified', flush=True)
            return
    encoded = output.with_suffix(output.suffix + '.base64-download')
    subprocess.run(['curl', '-fLsS', '--connect-timeout', '15', '--max-time', '180',
                    BASE + folder + '/' + name + '?format=TEXT', '-o', str(encoded)], check=True)
    data = base64.b64decode(encoded.read_bytes(), validate=True)
    actual = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
    if actual != entry['id']:
        raise ValueError('Git blob hash mismatch: ' + name)
    if output.is_symlink():
        output.unlink()
    if entry['mode'] == 0o120000:
        output.symlink_to(data.decode())
    else:
        output.write_bytes(data)
        output.chmod(0o755 if folder == 'bin' else 0o644)
    encoded.unlink()
    print(folder + '/' + name, len(data), 'bytes; Git blob verified', flush=True)

items = [('bin', name) for name in ['clang-12', 'lld', 'llvm-ar', 'llvm-nm',
         'llvm-objcopy', 'llvm-objdump', 'llvm-readobj', 'llvm-readelf', 'llvm-size', 'llvm-strip']]
items += [('lib64', name) for name in ['libc++.so.1', 'libc++abi.so.1', 'libxml2.so.2.9.10']]
items += [('lib64/clang/12.0.7/include', name) for name in
          ['stdarg.h', 'stddef.h', 'stdint.h', 'stdbool.h', 'limits.h', 'float.h',
           'unwind.h', '__stddef_max_align_t.h']]
with ThreadPoolExecutor(max_workers=4) as pool:
    list(pool.map(fetch, items))
for name, target in [('clang', 'clang-12'), ('clang++', 'clang-12'), ('ld.lld', 'lld')]:
    path = DEST / 'bin' / name
    if path.is_symlink():
        path.unlink()
    path.symlink_to(target)
print('Selected Android Clang r416183b1 files staged locally; system compiler unchanged', flush=True)
