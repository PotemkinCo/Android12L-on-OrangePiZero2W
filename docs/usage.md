# Use and troubleshooting

The release contains no saved Wi-Fi. After boot, `python3 tools/connect-wifi.py`
asks for an SSID and password privately, then sends them through the USB root
console. No host credential file or password argument is created. Android saves
its network in its writable disk. Wait for Wi-Fi association; `adb shell cmd wifi
status` reports it. Internet uses Wi-Fi, while disk/control remain on USB.

ADB commands in the README use the normal host server. If you intentionally use
another ADB server, supply its `-P` port consistently. Connect only after the
launcher reports boot completion. Disconnect this board before normal shutdown
to avoid an automatic reconnect attempt through the host's default network while
USB is absent. Never kill a shared ADB server containing unrelated devices.

A PNG screenshot works without HDMI. If it is black, first run
`adb -s 192.168.246.2:5555 shell input keyevent 224` to wake the display. To operate the UI remotely, scrcpy is an
optional upstream tool (`brew install scrcpy` or your Linux package manager),
then `scrcpy -s 192.168.246.2:5555`. Interactive streaming has not yet been tested
on this image. ADB `shell input tap X Y` and `shell am start -a
android.settings.SETTINGS` are also available. No monitor is required for boot.

## Diagnose a failed start

- `python3 tools/start-android-usb.py --check` checks local boot asset hashes.
- No FEL: use USB0, a data cable, no SD; complete the one-time factory setup.
  ROM identity is1f3a:efe8/bcd02b3; factory maintenance is the same VID/PID with
  bcdffff. They are different protocols. Unknown factory layouts are refused.
- No192.168.246.1: configure the new USB adapter for DHCP. The disk server waits
  for that address. Existing host VPN/firewall policy may need investigation;
  these tools do not modify host firewall or default routing.
- Upload readback/RAM failure: the loader retries bounded RAM initialization;
  it does not run a payload whose checks fail. See `logs/portable-android-upload.log`.
- Framework still starting: see `logs/portable-android-control.log` and
  `logs/portable-android-disk.log`. A launcher timeout deliberately leaves its
  server alive because Android might have mounted the image.
- Failure recovery returns the board to FEL through a hardware watchdog. After
  an abnormal failure, inspect the writable disk before reusing it. A fresh
  archive is a clean starting point. Do not mistake automatic recovery for a
  guaranteed clean filesystem shutdown.

## Limits

Only Zero2W1GB is hardware tested. The USB gadget exposes Ethernet, with ADB over
TCP; do not reconfigure it to MTP or a different USB function while mounted.
Keep ADB on5555: the established disk flow uses the same device-local port to
survive Android VPN socket cleanup. New ADB connections use a separate listener.
Bluetooth is disabled; HDMI hardware, audio, cameras and other peripherals are
not validated by this USB-only work. Performance depends on the host disk/cable.

The shipped system is permissive userdebug with USB-only privileged debug ports.
It is a development/test device, not a security baseline. Kernel/system versions
are old; no promise of current security patches or Play certification is made.
