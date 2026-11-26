#!/usr/bin/env python3
"""Upload the diagnostic, verify RAM samples, then start it with a watchdog."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import time
from opi_initcall_stop import plan_stop

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / 'prepared/android/arm64'
FEL = str(ROOT / 'tools/host-sunxi-fel.sh')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bootloader-only', action='store_true')
parser.add_argument('--serial', action='store_true')
parser.add_argument('--cdc', action='store_true', help='use the separate ACM+ECM diagnostic profile')
parser.add_argument('--usbnet', action='store_true', help='use the separate ECM network diagnostic profile')
parser.add_argument('--userspace', action='store_true', help='use the prepared Android userspace profile')
parser.add_argument('--linux', action='store_true', help='check RAM, then launch the preserved Linux console profile')
parser.add_argument('--stop-before', help='RAM-only diagnostic: stop at the named serial-kernel initcall stub')
parser.add_argument('--fix-thermal-syscfg', action='store_true',
                    help='volatile H616 THS prerequisite: clear only SYS_CFG bit16 and verify readback')
args = parser.parse_args()
if sum([args.serial, args.cdc, args.usbnet, args.userspace, args.bootloader_only, args.linux]) > 1:
    parser.error('choose one diagnostic profile')
if args.stop_before and not args.serial:
    parser.error('--stop-before requires --serial')
if args.fix_thermal_syscfg and (args.linux or args.bootloader_only):
    parser.error('--fix-thermal-syscfg is only for the Android kernel diagnostics')
if args.stop_before:
    profile = json.loads((TARGET / 'serial-test-manifest.json').read_text())
    if args.stop_before in profile.get('blacklisted_initcalls', []):
        parser.error('cannot stop at a blacklisted initcall')
kernel_name = 'Image.usbnet' if args.usbnet or args.userspace else 'Image.cdc' if args.cdc else 'Image.serial' if args.serial else 'Image.debug'
kernel_path = ROOT / 'prepared/linux/files/OrangePiZero2W.img' if args.linux else TARGET / kernel_name
stop_plan = plan_stop(TARGET, args.stop_before) if args.stop_before else None


def fel(*args, capture=False, timeout=180):
    result = subprocess.run([FEL, *map(str, args)], check=True, cwd=ROOT,
                            timeout=timeout, stdout=subprocess.PIPE if capture else None,
                            text=True)
    if capture:
        print(result.stdout, end='', flush=True)
        return result.stdout


def reset_to_fel():
    fel('writel', '0x030090b4', '0x16aa0001',
        'writel', '0x030090b8', '0x16aa0011',
        'writel', '0x030090b0', '0x14af', timeout=5)
    time.sleep(3)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            fel('version', capture=True, timeout=2)
            return
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            time.sleep(.5)
    raise RuntimeError('No live FEL response after the bounded RAM-training reset')


def check_ram_addressing(attempt):
    base = 0x46000000
    addresses = [base] + [base ^ (1 << bit) for bit in range(12, 30)]
    # Every address is inside the confirmed 1 GiB aperture and avoids the
    # loaded TF-A/U-Boot images. Distinct patterns expose ignored address bits.
    writes, reads, checks = [], [], []
    for address in addresses:
        expected = hashlib.shake_256(f'opi-ram-{address:x}'.encode()).digest(4096)
        source = TARGET / f'ram-probe-{address:x}.bin'
        output = ROOT / 'logs' / f'ram-probe-{attempt}-{address:x}.bin'
        source.write_bytes(expected)
        writes += ['write', hex(address), str(source)]
        reads += ['read', hex(address), '0x1000', str(output)]
        checks.append((address, expected, output))
    fel(*writes, timeout=10)
    fel(*reads, timeout=10)
    failures = [(address, expected, output.read_bytes()) for address, expected, output in checks
                if output.read_bytes() != expected]
    if failures:
        address, expected, actual = failures[0]
        print('RAM alias/pattern failure at', hex(address), 'attempt', attempt,
              'expected first word', expected[:4].hex(), 'actual', actual[:4].hex(), flush=True)
        # A CPU load via SRAM code is independent of the bulk RAM-read path.
        fel('readl', hex(address), capture=True, timeout=5)
        return False
    # Also verify a contiguous transfer spanning two adjacent 4 KiB pages.
    expected = checks[0][1] + checks[1][1]
    source = TARGET / 'ram-probe-contiguous.bin'
    output = ROOT / 'logs' / f'ram-probe-{attempt}-contiguous.bin'
    source.write_bytes(expected)
    fel('write', hex(base), source, 'read', hex(base), '0x2000', output, timeout=10)
    if output.read_bytes() != expected:
        print('Contiguous RAM transfer verification failed', flush=True)
        return False
    print('RAM addressing verified:', len(addresses), 'distinct pages and contiguous transfer', flush=True)
    return True


for attempt in range(1, 5):
    print('Initializing and checking RAM; attempt', attempt, flush=True)
    fel('writel', '0x030090b4', '0x16aa0001',
        'writel', '0x030090b8', '0x16aa00b1',
        'writel', '0x030090b0', '0x14af', timeout=5)
    fel('-v', 'spl', 'prepared/bootloader/u-boot-watchdog-safe.bin', timeout=25)
    valid = check_ram_addressing(attempt)
    if valid:
        state = fel('writel', '0x030090b8', '0x16aa0000',
                    'readl', '0x030090b8', capture=True, timeout=5)
        modes = re.findall(r'0x([0-9a-fA-F]{8})', state)
        if not modes or int(modes[-1], 16) & 1:
            raise RuntimeError('Could not suspend watchdog for the verified USB upload')
        break
    print('Rejecting this RAM initialization; no kernel launched', flush=True)
    reset_to_fel()
else:
    raise RuntimeError('No valid RAM initialization in four attempts; staying in recovery')
if not args.linux:
    print('Reading thermal SYS_CFG 0x03000000; bit16 must be clear for H616 THS', flush=True)
    state = fel('readl', '0x03000000', capture=True, timeout=5)
    values = re.findall(r'0x([0-9a-fA-F]{8})', state)
    if len(values) != 1:
        raise RuntimeError('Cannot identify the thermal SYS_CFG register value')
    before = int(values[0], 16)
    after = before
    written = False
    if args.fix_thermal_syscfg and before & (1 << 16):
        after = before & ~(1 << 16)
        fel('writel', '0x03000000', hex(after), timeout=5)
        written = True
        state = fel('readl', '0x03000000', capture=True, timeout=5)
        values = re.findall(r'0x([0-9a-fA-F]{8})', state)
        if len(values) != 1 or int(values[0], 16) != after:
            raise RuntimeError('Thermal SYS_CFG one-bit correction readback failed; no kernel launched')
        print('Verified volatile thermal SYS_CFG correction:', hex(before), '->', hex(after), flush=True)
    if (args.cdc or args.usbnet or args.userspace) and after & (1 << 16):
        raise RuntimeError('USB network profile needs the thermal prerequisite; use --fix-thermal-syscfg')
    (ROOT / 'logs/diagnostic-thermal-syscfg.json').write_text(json.dumps({
        'address': '0x03000000', 'bit': 16, 'before': before, 'after': after,
        'fix_requested': args.fix_thermal_syscfg, 'write_performed': written,
        'persistent_write': False,
        'reference': 'https://lists.infradead.org/pipermail/linux-arm-kernel/2024-February/904631.html',
    }, indent=2) + '\n')
payloads = [
    (0x40080000, kernel_path),
    (0x4f800000, TARGET / 'vendor-diagnostic.dtb'),
    (0x4ff00000, TARGET / 'kernel-test-initramfs.gz'),
    (0x4f900000, TARGET / 'diagnostic-marker.bin'),
    (0x4fc00000, TARGET / 'boot-diagnostic.scr'),
]
if args.serial:
    payloads[2] = (0x4ff00000, TARGET / 'serial-test-initramfs.gz')
    payloads[4] = (0x4fc00000, TARGET / 'boot-serial-test.scr')
if args.cdc:
    payloads[2] = (0x4ff00000, TARGET / 'cdc-test-initramfs.gz')
    payloads[4] = (0x4fc00000, TARGET / 'boot-cdc-test.scr')
if args.usbnet:
    payloads[2] = (0x4ff00000, TARGET / 'usbnet-test-initramfs.gz')
    payloads[4] = (0x4fc00000, TARGET / 'boot-usbnet-test.scr')
if args.userspace:
    payloads[1] = (0x4f800000, TARGET / 'vendor-android-usb.dtb')
    payloads[2] = (0x4ff00000, TARGET / 'android-usb-initramfs.gz')
    payloads[4] = (0x4fc00000, TARGET / 'boot-android-usb.scr')
if args.linux:
    payloads = [(0x40080000, kernel_path),
                (0x4fa00000, ROOT / 'prepared/linux/files/OrangePiZero2W.dtb'),
                (0x4ff00000, ROOT / 'prepared/linux/usb-init-overlay.cpio'),
                (0x4fc00000, ROOT / 'prepared/linux/boot-usb.scr')]
if args.bootloader_only:
    payloads = [(0x4f900000, TARGET / 'diagnostic-marker.bin'),
                (0x4e000000, TARGET / 'flush-marker.bin'),
                (0x4fc00000, TARGET / 'boot-watchdog-probe.scr')]
ranges = [(0x40000000, 0x80000, 'monitor'), (0x4a000000, 0x200000, 'bootloader'),
          (0x4fb00000, 45, 'uEnv')]
for address, path in payloads:
    size = path.stat().st_size + (65536 if path.suffix == '.dtb' else 0)
    ranges.append((address, size, path.name))
for previous, current in zip(sorted(ranges), sorted(ranges)[1:]):
    if previous[0] + previous[1] > current[0]:
        raise RuntimeError('RAM payload overlap: ' + previous[2] + ', ' + current[2])
if any(address < 0x40000000 or address + size > 0x80000000 for address, size, _ in ranges):
    raise RuntimeError('Payload outside confirmed RAM bounds')
command = ['-p']
for address, path in payloads:
    command += ['write', hex(address), str(path)]
# Keep the uEnv last among file writes: this sets the SPL handoff fields.
command += ['write', '0x4fb00000', 'prepared/linux/boot-usb.uEnv']
fel(*command)

checks = []
if not args.bootloader_only:
    kernel = kernel_path.read_bytes()
    for offset in [0, (len(kernel) // 2) & ~0xfff, len(kernel) - 65536]:
        checks.append((0x40080000 + offset, kernel[offset:offset + 65536], f'kernel-{offset:x}'))
for address, path in (payloads if args.bootloader_only else payloads[1:]):
    checks.append((address, path.read_bytes(), path.name))
checks.append((0x4fb00000, (ROOT / 'prepared/linux/boot-usb.uEnv').read_bytes(), 'uenv'))
for address, expected, name in checks:
    output = ROOT / 'logs' / ('diagnostic-readback-' + name)
    # Linux usbfs can reject one large receive URB (default shared pool 16 MB).
    # Bound every FEL read, retaining full byte-for-byte payload verification.
    if len(expected) > 1024 * 1024:
        with output.open('wb') as destination:
            part = output.with_name(output.name + '.part')
            for offset in range(0, len(expected), 1024 * 1024):
                size = min(1024 * 1024, len(expected) - offset)
                fel('read', hex(address + offset), hex(size), part, timeout=15)
                data = part.read_bytes()
                if data != expected[offset:offset + size]:
                    raise RuntimeError('Chunked RAM readback mismatch: ' + name)
                destination.write(data)
        part.unlink()
    else:
        fel('read', hex(address), hex(len(expected)), output, timeout=40)
    if output.read_bytes() != expected:
        raise RuntimeError('RAM readback mismatch: ' + name + '; staying in FEL')
    print('RAM readback verified:', name, len(expected), 'bytes', flush=True)

handoff = ROOT / 'logs/diagnostic-spl-handoff.bin'
fel('read', '0x20000', '0x40', handoff, timeout=5)
address, length = struct.unpack_from('<II', handoff.read_bytes(), 0x18)
if (address, length) != (0x4fb00000, 45):
    raise RuntimeError('SPL uEnv handoff does not match the uploaded environment')
print('SPL uEnv handoff verified', hex(address), length, flush=True)
header = handoff.read_bytes()
reported_mib = struct.unpack_from('<I', header, 0x24)[0]
if header[0x14:0x17] != b'SPL' or header[0x17] < 3 or not 128 <= reported_mib <= 16384:
    raise RuntimeError('Invalid SPL DRAM handoff; refusing to launch')
# This project targets the confirmed 1 GiB board. U-Boot trusts this field
# when placing its own allocations and the initramfs, before Linux's mem= cap.
limited_mib = min(reported_mib, 1024)
bounded_handoff = ROOT / 'logs/diagnostic-spl-handoff-capped.bin'
fel('writel', '0x20024', hex(limited_mib),
    'read', '0x20000', '0x40', bounded_handoff, timeout=5)
expected_header = bytearray(header)
struct.pack_into('<I', expected_header, 0x24, limited_mib)
if bounded_handoff.read_bytes() != expected_header:
    raise RuntimeError('SPL RAM-size handoff readback mismatch')
print('SPL RAM handoff:', reported_mib, 'MiB reported; capped to', limited_mib, 'MiB before U-Boot', flush=True)

if stop_plan:
    address = stop_plan['physical_address']
    output = ROOT / 'logs/diagnostic-initcall-stop-readback.bin'
    fel('read', hex(address), '4', output, timeout=5)
    if output.read_bytes() != struct.pack('<I', stop_plan['original_word']):
        raise RuntimeError('Initcall stub RAM bytes do not match the verified Image')
    fel('writel', hex(address), hex(stop_plan['replacement_word']),
        'read', hex(address), '4', output, timeout=5)
    if output.read_bytes() != struct.pack('<I', stop_plan['replacement_word']):
        raise RuntimeError('RAM-only initcall stop patch readback failed')
    (ROOT / 'logs/diagnostic-initcall-stop.json').write_text(json.dumps(stop_plan, indent=2) + '\n')
    print('Verified RAM-only stop before initcall', stop_plan['initcall_index'],
          stop_plan['function'], hex(address), flush=True)

if args.linux:
    state = fel('writel', '0x030090b8', '0x16aa0000',
                'readl', '0x030090b8', capture=True, timeout=5)
    values = re.findall(r'0x([0-9a-fA-F]{8})', state)
    if not values or int(values[-1], 16) & 1:
        raise RuntimeError('Watchdog did not confirm disabled for the preserved Linux profile')
    print('Verified Linux payload and RAM handoff; starting TF-A/U-Boot', flush=True)
    fel('reset64', '0x40000000', timeout=5)
    raise SystemExit(0)

state = fel('writel', '0x030090b4', '0x16aa0001',
            'writel', '0x030090b8', '0x16aa00b1',
            'writel', '0x030090b0', '0x000014af',
            'readl', '0x030090b8', capture=True, timeout=5)
values = re.findall(r'0x([0-9a-fA-F]{8})', state)
if not values or int(values[-1], 16) & 0xf1 != 0xb1:
    raise RuntimeError('Watchdog did not confirm enabled; not starting the bootloader')
print('Watchdog readback confirms enabled; starting TF-A/U-Boot', flush=True)
fel('reset64', '0x40000000', timeout=5)
