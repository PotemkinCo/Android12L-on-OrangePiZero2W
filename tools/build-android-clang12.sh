#!/bin/bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_dir"
export PATH="$project_dir/tools/clang12/bin:$project_dir/tools/build-host/usr/bin:$PATH"
if [[ -d "$project_dir/tools/build-host/usr/share/bison" ]]; then export BISON_PKGDATADIR="$project_dir/tools/build-host/usr/share/bison"; fi
profile=serial
if [[ $# -eq 1 && $1 == --cdc ]]; then
    profile=cdc
elif [[ $# -eq 1 && $1 == --usbnet ]]; then
    profile=usbnet
elif [[ $# -ne 0 ]]; then
    echo 'Usage: build-android-clang12.sh [--cdc|--usbnet]' >&2
    exit 2
fi
output_dir="$project_dir/build/android-kernel-clang12-out"
if [[ $profile == cdc ]]; then
    output_dir="$project_dir/build/android-kernel-cdc-out"
elif [[ $profile == usbnet ]]; then
    output_dir="$project_dir/build/android-kernel-usbnet-out"
fi
mkdir -p "$output_dir"
if [[ ! -f "$output_dir/.config" ]]; then
    cp prepared/android/arm64/kernel-serial.config "$output_dir/.config"
fi
if [[ $profile == cdc ]]; then
    build/android-kernel-src/scripts/config --file "$output_dir/.config" \
        --disable USB_G_SERIAL --enable USB_CDC_COMPOSITE
elif [[ $profile == usbnet ]]; then
    build/android-kernel-src/scripts/config --file "$output_dir/.config" \
        --disable USB_G_SERIAL --disable USB_CDC_COMPOSITE --enable USB_ETH \
        --disable USB_ETH_RNDIS --enable MACVLAN
fi
build_args=(-C build/android-kernel-src O="$output_dir" ARCH=arm64 LLVM=1 LLVM_IAS=1
    CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu-
    KERNEL_SRC_DIR="$project_dir/build/android-kernel-src" KERNEL_OUT_DIR="$output_dir"
    KCFLAGS='-Wno-error -Wno-error=unknown-warning-option')
clang --version
ld.lld --version
make "${build_args[@]}" olddefconfig
if [[ $profile == cdc ]]; then
    test "$(sed -n '/^CONFIG_USB_CDC_COMPOSITE=/p' "$output_dir/.config")" = CONFIG_USB_CDC_COMPOSITE=y
    test "$(sed -n '/^CONFIG_U_SERIAL_CONSOLE=/p' "$output_dir/.config")" = CONFIG_U_SERIAL_CONSOLE=y
    test "$(sed -n '/^# CONFIG_USB_G_SERIAL is not set$/p' "$output_dir/.config")" = '# CONFIG_USB_G_SERIAL is not set'
elif [[ $profile == usbnet ]]; then
    test "$(sed -n '/^CONFIG_USB_ETH=/p' "$output_dir/.config")" = CONFIG_USB_ETH=y
    test "$(sed -n '/^CONFIG_MACVLAN=/p' "$output_dir/.config")" = CONFIG_MACVLAN=y
    test "$(sed -n '/^# CONFIG_USB_CDC_COMPOSITE is not set$/p' "$output_dir/.config")" = '# CONFIG_USB_CDC_COMPOSITE is not set'
fi
make "${build_args[@]}" -j8 Image modules
