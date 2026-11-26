#!/usr/bin/env bash
set -euo pipefail
command -v nmcli >/dev/null || { echo 'NetworkManager/nmcli is required.' >&2; exit 1; }
task_iface=$(python3 - <<'PY'
from pathlib import Path
import time
deadline=time.monotonic()+600
while time.monotonic()<deadline:
    for net in Path('/sys/class/net').iterdir():
        for parent in (net.resolve(),*net.resolve().parents):
            try:
                if (parent/'idVendor').read_text().strip()=='1f3a' and (parent/'idProduct').read_text().strip()=='efea':
                    print(net.name);raise SystemExit(0)
            except (FileNotFoundError,PermissionError):pass
    time.sleep(1)
raise SystemExit('No Orange Pi USB Ethernet interface in600s')
PY
)
task_profile=opi-android-usb
if ! nmcli connection show "$task_profile" >/dev/null 2>&1; then
    nmcli connection add type ethernet ifname "$task_iface" con-name "$task_profile" \
        ipv4.method auto ipv4.never-default yes ipv4.ignore-auto-dns yes \
        ipv6.method disabled connection.autoconnect yes
fi
nmcli connection modify "$task_profile" connection.interface-name "$task_iface" \
    ipv4.method auto ipv4.never-default yes ipv4.ignore-auto-dns yes ipv6.method disabled
nmcli --wait 30 connection up "$task_profile"
