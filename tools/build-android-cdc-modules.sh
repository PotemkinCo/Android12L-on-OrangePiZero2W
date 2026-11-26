#!/usr/bin/env bash
set -euo pipefail
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$task_root"
export PATH="$task_root/tools/clang12/bin:$task_root/tools/build-host/usr/bin:$PATH"
if [[ -d "$task_root/tools/build-host/usr/share/bison" ]]; then export BISON_PKGDATADIR="$task_root/tools/build-host/usr/share/bison"; fi
profile=cdc
if [[ $# -eq 1 && $1 == --usbnet ]]; then profile=usbnet; elif [[ $# -ne 0 ]]; then exit 2; fi
output_dir="$task_root/build/android-kernel-$profile-out"
module_dir="$task_root/build/android-kernel-src/modules/gpu/mali-bifrost/driver/drivers/gpu/arm/midgard"
python3 - "$profile" <<'PY'
from pathlib import Path
import sys
profile=sys.argv[1]
for current, staged in [('arch/arm64/boot/Image', 'Image.'+profile), ('Module.symvers', 'kernel-'+profile+'-clang12-build/Module.symvers')]:
    if (Path('build/android-kernel-'+profile+'-out') / current).read_bytes() != (Path('prepared/android/arm64') / staged).read_bytes():
        raise SystemExit('Stage the completed matching CDC kernel before building its modules')
PY
build_args=(-C build/android-kernel-src O="$output_dir" ARCH=arm64 LLVM=1 LLVM_IAS=1
    CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu-
    KERNEL_SRC_DIR="$task_root/build/android-kernel-src" KERNEL_OUT_DIR="$output_dir"
    KCFLAGS='-Wno-error -Wno-error=unknown-warning-option')
make "${build_args[@]}" -j4 M="$module_dir" \
    EXTRA_CFLAGS="-I$module_dir/../../../../include -I$module_dir/../../../../tests/include" modules
cp "$module_dir/mali_kbase.ko" "prepared/android/arm64/mali-kbase-$profile.ko"
make "${build_args[@]}" INSTALL_MOD_PATH="$task_root/prepared/android/arm64/kernel-$profile-root" DEPMOD=true modules_install
