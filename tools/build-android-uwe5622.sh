#!/usr/bin/env bash
# Build optional Wi-Fi modules against the staged USB-network kernel.
# Generated external-module objects never replace the proven kernel payload.
set -euo pipefail
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$task_root"
export PATH="$task_root/tools/clang12/bin:$task_root/tools/build-host/usr/bin:$PATH"
if [[ -d "$task_root/tools/build-host/usr/share/bison" ]]; then export BISON_PKGDATADIR="$task_root/tools/build-host/usr/share/bison"; fi
output_dir="$task_root/build/android-kernel-usbnet-out"
wifi_dir="$task_root/build/uwe5622-external"
python3 - <<'PY'
from pathlib import Path
import shutil
out = Path('build/android-kernel-usbnet-out')
stage = Path('prepared/android/arm64/kernel-usbnet-clang12-build')
for built, saved in [('arch/arm64/boot/Image', 'Image'), ('Module.symvers', 'Module.symvers'), ('.config', 'kernel.config')]:
    if (out / built).read_bytes() != (stage / saved).read_bytes():
        raise SystemExit('Finish and stage the matching kernel before building Wi-Fi modules')
source = Path('build/android-kernel-src/drivers/net/wireless/uwe5622')
target = Path('build/uwe5622-external')
if not target.exists():
    shutil.copytree(source, target)
PY
build_args=(-C build/android-kernel-src O="$output_dir" ARCH=arm64 LLVM=1 LLVM_IAS=1
    CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu-
    KERNEL_SRC_DIR="$task_root/build/android-kernel-src" KERNEL_OUT_DIR="$output_dir"
    KCFLAGS='-Wno-error -Wno-error=unknown-warning-option')
includes="-I$wifi_dir/unisocwcn/include -I$wifi_dir/unisocwcn/platform -I$wifi_dir/unisocwcn/platform/rf"
make "${build_args[@]}" -j4 M="$wifi_dir/unisocwcn" \
    CONFIG_AW_WIFI_DEVICE_UWE5622=y UNISOC_FW_PATH_CONFIG=/vendor/etc/firmware/ \
    EXTRA_CFLAGS="$includes" modules
make "${build_args[@]}" -j4 M="$wifi_dir/unisocwifi" CONFIG_WLAN_UWE5622=m \
    UNISOC_WIFI_CUS_CONFIG=/vendor/etc/firmware/ \
    UNISOC_BSP_INCLUDE="$wifi_dir/unisocwcn/include" \
    KBUILD_EXTRA_SYMBOLS="$wifi_dir/unisocwcn/Module.symvers" modules
python3 - <<'PY'
from pathlib import Path
import hashlib, json, shutil, subprocess
out = Path('build/android-kernel-usbnet-out')
files = [Path('build/uwe5622-external/unisocwcn/uwe5622_bsp_sdio.ko'),
         Path('build/uwe5622-external/unisocwifi/sprdwl_ng.ko')]
versions = {}
for path in [out / 'Module.symvers', Path('build/uwe5622-external/unisocwcn/Module.symvers')]:
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 2:
            value = int(fields[0], 16)
            if fields[1] in versions and versions[fields[1]] != value:
                raise ValueError('Conflicting exported CRC: ' + fields[1])
            versions[fields[1]] = value
stage = Path('prepared/android/arm64/wifi-uwe5622')
stage.mkdir(exist_ok=True)
for path in files:
    for line in subprocess.check_output(['modprobe', '--dump-modversions', str(path)], text=True).splitlines():
        crc, name = line.split()
        if versions.get(name) != int(crc, 16):
            raise ValueError('Wi-Fi imported symbol mismatch: ' + name)
    shutil.copy2(path, stage / path.name)
receipt = {'kernel_sha256': hashlib.sha256((out / 'arch/arm64/boot/Image').read_bytes()).hexdigest(),
           'firmware_directory': '/vendor/etc/firmware/',
           'wifi_configuration_directory': '/vendor/etc/firmware/',
           'modules': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
           'status': 'built and import-CRC checked; chip identification and loading not verified'}
(stage / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('Prepared Wi-Fi module candidates; board verification remains pending')
PY
