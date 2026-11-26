# Android 12L on Orange Pi Zero 2W — no SD card

Run **Android 12L / 12.1 (ARM64, OmniROM tablet)** on an **Orange Pi Zero 2W, 1 GB**
using its **USB0** cable. The computer uploads the boot files, then serves an
8 GiB Android disk over that same cable. **Keep the computer and disk server
running while Android runs.** No SD card, USB drive, keyboard or serial adapter
is needed for the supported factory firmware setup.

**Hardware tested:** the exact public image passed fresh boot, Wi-Fi/ADB, clean
shutdown and reboot with settings/file persistence on a Zero 2W 1 GB with a Linux host.
This is still an early prerelease; see [tested scope](docs/validation.md).

## Download and start

1. Download **[android12l-usb-v0.1.0.tar.gz](https://github.com/PotemkinCo/Android12L-on-OrangePiZero2W/releases/download/v0.1.0/android12l-usb-v0.1.0.tar.gz)**
   and **[SHA256SUMS](https://github.com/PotemkinCo/Android12L-on-OrangePiZero2W/releases/download/v0.1.0/SHA256SUMS)**.
   Use the release asset, **not GitHub's “Source code” ZIP**. Allow 10 GiB free disk space.
2. Install the [host prerequisites](docs/host-setup.md), verify, and extract:

   ```sh
   awk '$2 == "android12l-usb-v0.1.0.tar.gz" { print }' SHA256SUMS | shasum -a 256 -c
   tar xzf android12l-usb-v0.1.0.tar.gz
   cd android12l-usb-v0.1.0
   bash tools/build-native-fel.sh
   bash tools/build-board-tools.sh
   ```

3. **Once per factory board**, disconnect it, run the following command, then
   connect **only that board**, with **no SD card**, to the endmost USB-C port
   marked **USB0**, using a data cable:

   ```sh
   python3 tools/prepare-board.py --apply
   ```

   This saves a private **per-board SPI backup** under `backups/`, validates the
   known factory layout, and changes only the 128 KiB boot environment to
   `bootcmd=efex`. Power-on will then wait for the computer instead of starting
   the built-in demo Linux. It does not install Android into SPI or erase the
   factory OS. Unknown layouts/commands are refused. Keep your backup; automatic
   restoration from Boot ROM is not implemented. Details: [board setup](docs/board-setup.md).

4. Unplug the board for five seconds, reconnect **USB0**, then run:

   ```sh
   python3 tools/start-android-usb.py
   ```

   When the USB Ethernet adapter appears, enable **DHCP** for that adapter:
   [exact Linux/macOS steps](docs/host-setup.md#usb-network).
   It receives `192.168.246.1/30`; the board is `192.168.246.2`.
   Wait for **“Android boot completed”**. Boot takes several minutes; first boot
   may take longer. The public image starts with empty user data and no saved Wi-Fi.

## Control, Wi-Fi, and stop

```sh
adb connect 192.168.246.2:5555
adb -s 192.168.246.2:5555 shell getprop sys.boot_completed  # must print 1
adb -s 192.168.246.2:5555 shell input keyevent 224        # wake the screen
adb -s 192.168.246.2:5555 exec-out screencap -p > screen.png
python3 tools/connect-wifi.py  # prompts privately; optional, after Android boots
```

[Display/control options and troubleshooting](docs/usage.md).

Shut down cleanly before unplugging or switching off the computer:

```sh
adb disconnect 192.168.246.2:5555
python3 tools/stop-android-usb.py
```

This flushes Android, verifies actual USB recovery, and only then releases its
identified disk server. Do not kill the server or copy the live disk image.
Android apps/settings persist in `data/android-arm64.img` on the computer.

## Unattended reboot (no unplugging)

After the one-time board setup, run this **from the same extracted folder that
started Android**. Configure USB Ethernet DHCP to reconnect automatically first.

```sh
adb disconnect 192.168.246.2:5555  # if using a separate ADB server, supply its -P port
python3 tools/stop-android-usb.py && python3 tools/start-android-usb.py
```

The stop tool requests normal Android shutdown, keeps the disk served until
actual USB Boot ROM recovery is verified, releases only its owned server, and
checks clean filesystem checkpoints. The launcher then uploads the boot files
and starts Android from the same disk, preserving apps/settings. **No cable
reconnect or button press is needed.** This complete cycle passed on Linux.
The `&&` prevents starting again if shutdown or filesystem checks fail.

Kernel reboot/panic/emergency watchdog recovery was also hardware tested. It
returns the board to USB recovery, **not automatically to Android**; the host
launcher must run again. After a failure,
`python3 tools/stop-android-usb.py --already-in-fel` can verify recovery and clean
up its owned server, but refuses
an unclean filesystem. Do not ignore that error or kill a possibly mounted disk
server. Recovery from every hardware/power/USB failure is not guaranteed.

## Measured performance

Measured on **Zero 2W, 1 GB**, with a **Linux x86_64 host and SSD**, using the
exact v0.1.0 public image. These are measurements, not minimum guarantees.

| Metric | Result |
| --- | --- |
| First boot, empty user data | **5m40s** (339.6 s) |
| Subsequent boot | **4m35s** (275.3 s) |
| Android-visible RAM | **979 MiB** (1,002,216 KiB; hardware has 1 GB) |
| RAM available after fresh boot | **396 MiB** (405,216 KiB, `MemAvailable`) |
| RAM unavailable estimate | **583 MiB** (`MemTotal − MemAvailable`; includes Android/kernel) |
| Compressed swap | **512 MiB logical ZRAM**, **256 MiB compressed-memory limit** |
| Settings activity launch, warm | **2.734 s** |
| Sequential filesystem write / read | **14.85 / 14.45 MiB/s** |
| Random 4 KiB read | **2,381 IOPS**, **0.420 ms** |
| Random 4 KiB write + fsync | **714 IOPS**, **1.400 ms** |

Boot timing includes FEL uploads/readback and Android startup. RAM is a snapshot;
`MemTotal − MemAvailable` is not summed app RSS. Storage used a single **16 MiB
O_DIRECT** test on Android F2FS: board page cache was bypassed, **host SSD caching
still applies**. Host/cable, workload and background activity affect results;
network throughput, long-duration performance and macOS performance are unmeasured.
[Raw results](docs/hardware-validation.json) · [Benchmark reproduction](docs/build.md#reproduce-the-android-filesystem-measurement).

## What is included

- Android 12L/API 32 ARM64 tablet image, based on [OmniROM 12.1 v3](https://blogs.yajatkumar.com/2024/12/omnirom-121-v3-tablet-arm64-for-orange.html).
- Modified Linux 5.4.125, matching graphics/Wi-Fi modules, USB disk boot,
  512 MiB compressed RAM swap, and software recovery without unplugging.
- Portable Python host tools, native uploader sources, per-file checksums,
  patches, build inputs and [source/build documentation](docs/build.md).
- Fresh user data: no accounts, saved networks, or additional installed test apps.

**Development image:** userdebug, permissive SELinux, unlocked/AVB-disabled;
root control and unauthenticated ADB are limited to the USB link. This is not a
hardened daily-use image. Bluetooth is disabled in this profile.

[Actual Android screenshot](docs/android-home.png) · [Hardware results](docs/hardware-validation.json).

See [tested scope and limitations](docs/validation.md). Other board/RAM variants
and actual macOS execution are not verified. No Wi-Fi boot or standalone boot:
the computer supplies the disk throughout the session.

Original project code uses [Apache-2.0](LICENSE), except where file headers say
otherwise. Third-party components retain their licenses: [notices](NOTICE.md).
