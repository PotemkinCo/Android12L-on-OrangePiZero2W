#!/usr/bin/env bash
set -euo pipefail
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$task_root"
python3 - "$@" <<'PY'
import hashlib,json
import sys
from pathlib import Path
serial=any(x in ('--serial','--check-serial') for x in sys.argv[1:])
linux='--linux' in sys.argv[1:]
cdc=any(x in ('--cdc','--check-cdc') for x in sys.argv[1:])
usbnet=any(x in ('--usbnet','--check-usbnet') for x in sys.argv[1:])
userspace=any(x in ('--userspace','--check-userspace') for x in sys.argv[1:])
name='userspace-manifest.json' if userspace else 'usbnet-test-manifest.json' if usbnet else 'cdc-test-manifest.json' if cdc else 'serial-test-manifest.json' if serial else 'diagnostic-manifest.json'
m=json.loads((Path('prepared/android/arm64')/name).read_text())
if linux:
    expected_bootloader=m['files']['prepared/bootloader/u-boot-watchdog-safe.bin']
    m=json.loads(Path('prepared/ramboot-manifest.json').read_text())
    m['files']['prepared/bootloader/u-boot-watchdog-safe.bin']=expected_bootloader
for name,expected in m['files'].items():
    if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=expected:
        raise SystemExit('Checksum mismatch: '+name)
print('Linux baseline payloads verified.' if linux else
      'Android userspace payloads verified.' if userspace else
      'Diagnostic payloads verified; automatic watchdog recovery is enabled.',flush=True)
PY
if { [ "${1:-}" = --check ] || [ "${1:-}" = --check-serial ] || [ "${1:-}" = --check-cdc ] || [ "${1:-}" = --check-usbnet ] || [ "${1:-}" = --check-userspace ]; } && [ "$#" = 1 ]; then exit 0; fi
exec python3 "$task_root/tools/upload-android-diagnostic.py" "$@"
