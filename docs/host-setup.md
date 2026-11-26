# Host setup

Use Python 3.10+, a C compiler, make, pkg-config, libusb, zlib, libfdt, and ADB.
The ready-to-run release includes sunxi-tools source, so you do not need to
compile Android or a kernel. Native uploader compilation takes seconds.

## Ubuntu/Debian

```sh
sudo apt-get update
sudo apt-get install python3 gcc make pkg-config libusb-1.0-0-dev zlib1g-dev libfdt-dev adb perl
printf '%s\n' 'SUBSYSTEM=="usb", ATTR{idVendor}=="1f3a", MODE="0660", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/70-orangepi-usb.rules
sudo udevadm control --reload-rules
```

Reconnect USB after installing that rule. It grants the active local desktop
session USB access. Headless sessions may need an administrator to grant device
access separately; do not run the Android disk server as root to work around it.

## macOS

Install Apple's command-line tools (`xcode-select --install` if `cc` is absent)
and Homebrew, then:

```sh
brew install python libusb zlib dtc pkgconf
brew install --cask android-platform-tools
```

Run both native build helpers from the extracted release as shown in the README.
The Linux ELF uploader is not used on macOS. `OPI_SUNXI_FEL` can explicitly select
an existing compatible native uploader. macOS execution is currently unverified.

## USB network

The board supplies DHCP over standard USB Ethernet (ECM). The USB adapter must
receive **192.168.246.1, mask255.255.255.252**, with **no router and no DNS**.
Android is **192.168.246.2**. Do not configure Internet sharing.

**Linux with NetworkManager:** while the launcher is running, open a second
terminal in the extracted folder and run:

```sh
bash tools/setup-usb-network-linux.sh
```

It discovers the Orange Pi adapter and activates a USB-only DHCP profile with
no default route or DNS. It does not change your Wi-Fi/default connection.
Subsequent boots can reuse that profile. Other Linux network managers must
configure the same adapter for DHCP; the helper requires NetworkManager.

**macOS:** when the new USB Ethernet service appears, open Network settings,
select that service, then TCP/IP and **Configure IPv4: Using DHCP**. Apply the
change. Verify192.168.246.1 is assigned. On newer releases TCP/IP is under
Details; older versions use System Preferences → Network. If no USB Ethernet
service appears, that host/driver combination needs investigation; it is not
currently hardware-verified by this project.

If192.168.246.0/30 already belongs to another network, do not start this image;
that subnet is compiled into this profile. No automatic subnet migration exists.
