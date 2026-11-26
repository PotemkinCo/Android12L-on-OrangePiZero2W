#!/usr/bin/env bash
# Build only the host-side USB uploader; does not access or write the board.
set -euo pipefail
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$(uname -s)" = Darwin ] && command -v brew >/dev/null 2>&1; then
  for task_dep in libusb zlib dtc; do
    task_prefix=$(brew --prefix "$task_dep")
    export PKG_CONFIG_PATH="$task_prefix/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
  done
fi
pkg-config --exists libusb-1.0 zlib
# Debian packages may provide libfdt without a pkg-config file.
task_fdt_flags=()
if ! pkg-config --exists libfdt; then
  task_fdt_flags=(LIBFDT_LIBS=-lfdt)
fi
make -B -C "$task_root/tools/sunxi-tools-source" CC="${CC:-cc}" "${task_fdt_flags[@]}" sunxi-fel
task_output="$task_root/tools/native/$(uname -s)-$(uname -m)"
mkdir -p "$task_output"
cp "$task_root/tools/sunxi-tools-source/sunxi-fel" "$task_output/sunxi-fel"
chmod 755 "$task_output/sunxi-fel"
printf 'Built native USB uploader: %s\n' "$task_output/sunxi-fel"
