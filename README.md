# Android 12L on Orange Pi Zero 2W — no SD card

Run **Android 12L / 12.1 (ARM64, OmniROM tablet)** on an **Orange Pi Zero 2W, 1 GB**
using its **USB0** cable. The computer uploads the boot files, then serves an
8 GiB Android disk over that same cable. **Keep the computer and disk server
running while Android runs.** No SD card, USB drive, keyboard or serial adapter
is needed for the supported factory firmware setup.

**Prerelease:** the boot stack is hardware verified; this fresh, empty-userdata
public image has passed offline checks but still needs its own board boot test.

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

See [tested scope and limitations](docs/validation.md). Other board/RAM variants
and actual macOS execution are not verified. No Wi-Fi boot or standalone boot:
the computer supplies the disk throughout the session.

Original project code uses [Apache-2.0](LICENSE), except where file headers say
otherwise. Third-party components retain their licenses: [notices](NOTICE.md).
