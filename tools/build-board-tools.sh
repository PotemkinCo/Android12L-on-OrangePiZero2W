#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$(uname -s)" = Darwin ] && command -v brew >/dev/null 2>&1; then
    export PKG_CONFIG_PATH="$(brew --prefix libusb)/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
fi
output="$root/tools/native/$(uname -s)-$(uname -m)"
mkdir -p "$output"
for program in catch-fel read-spi-usb; do
    # pkg-config intentionally expands compiler/linker flags.
    cc -std=c11 -O2 -Wall -Wextra "$root/tools/$program.c" -o "$output/$program" $(pkg-config --cflags --libs libusb-1.0)
done
printf 'Native board preparation tools built.\n'
