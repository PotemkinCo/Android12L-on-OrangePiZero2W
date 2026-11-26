# Validation status — v0.1.0

Updated 2026-11-26 after testing the exact publicly downloadable image.

## Public image: hardware checks passed

A disposable copy was extracted from the published runtime archive and all 184
initial file checksums passed before boot. Public archive SHA256:
`ebe0745d84086e083269fb5eb1d4bf2f57f12cfad8cbfb3a0841bb372df2a41f`.
Initial disk SHA256: `7db1e965cf509afaecc6328f0457504a6fc1c4194f5f3778c7947c914f83e05a`.
The archive was not changed during testing.

On the physical Orange Pi Zero 2W 1 GB, with a Linux x86_64 host:

- Fresh Android 12L / API 32 ARM64 boot completed in approximately 340 seconds.
- Real 1280×720 home screen, working ADB/root console and Settings UI.
- Initially zero accounts, no saved Wi-Fi, and no additional test application.
- Compressed RAM swap 524,284 KiB; MemAvailable 405,216 KiB (about 396 MiB) after boot.
- Published Wi-Fi helper connected using private stdin; Android marked Internet
  VALIDATED. DNS/ping succeeded for GitHub, Google and Cloudflare, and HTTP TCP
  to 1.1.1.1 returned 301. USB disk/control remained available.
- Normal shutdown reached actual USB Boot ROM before stopping its owned server.
  Both F2FS checkpoint CRCs/footer copies passed, latest flags 0xc5 clean-unmount.
- Initialized reboot completed in approximately 275 seconds. A synced file's
  SHA256 matched and saved Wi-Fi reconnected automatically with Internet access.
- The USB-only debug firewall was verified before any manual rule application.

[Actual home screenshot](android-home.png) was captured before Wi-Fi setup and
contains no personal network/account details. [Machine-readable results](hardware-validation.json).
A sleeping display can produce a black screenshot; wake it with ADB keyevent 224.

## Final Android filesystem performance

A bounded, single 16 MiB O_DIRECT test on Android F2FS measured:

| Operation | Result |
| --- | --- |
| Sequential write | 14.85 MiB/s |
| Sequential read | 14.45 MiB/s |
| Random 4 KiB read | 2,381 IOPS / 0.420 ms |
| Random 4 KiB write + fsync | 714 IOPS / 1.400 ms |

This bypasses the board page cache; host SSD caching still applies. It is one
short run, not a throughput guarantee, a cold-storage test or long-duration
reliability testing. Results depend on host/cable. Source and reproduction
commands are in tools/storage-benchmark.c and docs/build.md.

## Other verified/offline checks

Restart, panic and emergency watchdog recovery were previously hardware tested.
The underlying boot stack preserved its root disk through Android VPN socket
cleanup. No VPN app is included in this public image.

The public disk was assembled from system-only inputs plus newly formatted
F2FS userdata, ext4 metadata and FAT16 media_data. No previously booted user
partitions were copied. GPT/LP geometry and checksums, full empty partition
readbacks, filesystem types/checkpoints/fsck, all archive hashes/gzip CRCs and
privacy checks passed before publication. Native Linux USB tools compile.
Four provisioning refusal/edit-boundary tests pass; the candidate also matches
the earlier hardware-tested SPI environment operation exactly.

## Still unverified

The new generalized first-time factory setup wrapper has not had its own full
run on another factory board; its underlying maintenance/write protocol was
hardware tested and its backup/validation/edit logic checked offline. Therefore
v0.1.0 remains an early prerelease. Actual macOS USB execution, other board/RAM
variants, interactive scrcpy, Bluetooth, HDMI/audio/cameras and long-duration
reliability remain unverified. Bluetooth is disabled by the readiness helper.

Archives retain their build-time pending-validation notes; this document and
the release-page update are the current test status. Download hashes are unchanged.
