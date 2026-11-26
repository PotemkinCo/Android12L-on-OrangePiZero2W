# Validation status — v0.1.0 prerelease

## Verified on physical Orange Pi Zero2W1GB

The boot stack has booted Android12L/API32 ARM64 without an SD card, exposed
working USB root control/ADB and a real1280×720 Android screenshot, connected
Wi-Fi with Internet, and preserved apps/settings through normal reboot. Normal
shutdown returned to actual Boot ROM before releasing the disk server; both
F2FS checkpoint CRCs/footer copies passed with clean-unmount flags.
Restart, panic and emergency watchdog recovery were tested on the hardware.
The established USB root disk survived Android network/VPN socket cleanup.

A previously initialized image took approximately4½minutes to boot, dominated
by FEL transfer and readback. This is not a fresh-image first-boot measurement.
An earlier Linux storage prototype measured about13MiB/s sequential I/O; it
is not a benchmark of the final Android USB PIO path. No final Android storage
or network throughput claim is made.

## Fresh public image — offline checks only

The public disk is newly assembled from system-only inputs plus newly formatted
empty filesystems. No previously booted userdata/metadata/media partition was
copied. GPT and LP geometry/checksums, filesystem types, clean F2FS checkpoints,
full partition readbacks, runtime asset checksums, archive integrity and public
file privacy checks are validated before publication. Native Linux host tools
compile; board-setup candidate generation matches the previously hardware-tested
operation, with malformed-input refusal unit tests.

**This newly created public disk has not yet had its own hardware boot test:**
the board is currently unavailable. That is why this is a prerelease. The new
generic per-board provisioning wrapper was checked offline; its underlying
maintenance protocol and environment write/readback were previously hardware
tested. A fresh end-to-end provisioning run on another board remains unverified.

Actual macOS native build/USB execution, other board/RAM variants, interactive
scrcpy, Bluetooth, HDMI/audio/cameras and long-duration reliability are untested.
Bluetooth is disabled by the readiness helper after framework startup. No host
power/sleep/firewall/default-route modification is performed by runtime tools.
