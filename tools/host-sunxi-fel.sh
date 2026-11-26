#!/usr/bin/env bash
# Use a native host program. The bundled ELF is only for x86_64 Linux.
set -euo pipefail
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -n "${OPI_SUNXI_FEL:-}" ]; then
  exec "$OPI_SUNXI_FEL" "$@"
elif command -v sunxi-fel >/dev/null 2>&1; then
  exec sunxi-fel "$@"
elif [ -x "$task_root/tools/native/$(uname -s)-$(uname -m)/sunxi-fel" ]; then
  exec "$task_root/tools/native/$(uname -s)-$(uname -m)/sunxi-fel" "$@"
elif [ "$(uname -s)-$(uname -m)" = Linux-x86_64 ]; then
  exec "$task_root/tools/sunxi-tools/usr/bin/sunxi-fel" "$@"
else
  printf '%s\n' 'Install a native sunxi-fel with libusb, or set OPI_SUNXI_FEL to its executable path.' >&2
  exit 1
fi
