# Third-party notices and sources

The repository's Apache-2.0 LICENSE applies to original project contributions
unless a file carries another license. It does not relicense third-party
binaries, source code, firmware, or Linux patches.

- **Android/OmniROM**: Yajat Kumar's OmniROM12.1v3 ARM64 tablet build for Zero2W,
  based on AOSP/OmniROM. Original notice/license files remain in the system/vendor
  images. Upstream source manifest: https://github.com/YAJATapps/android_apollo-p2_local_manifest/tree/omni-12.1
- **Linux5.4.125 and modules**: Orange Pi source commit recorded in
  `src/provenance.json`, GPL-2.0 and component-specific notices. Full baseline
  source, complete project patch and build config are supplied alongside the
  binaries. See `licenses/Linux-COPYING` and source file headers.
- **BusyBox1.36.1**: GPL-2.0, full source/config supplied; `licenses/BusyBox-LICENSE`.
- **GNU C Library2.43**: bootstrap helpers/BusyBox are statically linked against
  Ubuntu2.43-2ubuntu2cross1. LGPL-2.1-or-later and component-specific notices;
  see `licenses/glibc-COPYRIGHT` and `licenses/LGPL-2.1`. Full upstream source
  and Ubuntu2.43-2ubuntu2 packaging patches are in the source archive. Helper
  sources and static relink/build commands are supplied so they can be rebuilt
  against a replacement C library.
- **U-Boot2024.10**: GPL-2.0 and component-specific notices. Full source, MuntsOS
  recipe/patch/config supplied; `licenses/U-Boot-LICENSE`. Our binary adjustment
  changes the watchdog DTB property, not executable code.
- **Trusted Firmware-A**: retained from the MuntsOS boot bundle;
  `licenses/TF-A-LICENSE`, upstream https://www.trustedfirmware.org/projects/tf-a/ .
- **sunxi-tools**: pinned upstream source is vendored under `tools/sunxi-tools-source`,
  retaining `LICENSE.md` and file notices. See `licenses/sunxi-tools-LICENSE.md`.
- **Wi-Fi firmware/configuration and graphics userspace**: retained from the
  board-specific upstream distribution. Manufacturer Wi-Fi INI comes from
  https://github.com/orangepi-xunlong/firmware at commit
  `9941d88cbbd88ab494b56edc8311b618eeda9761`; corresponding source/receipt included.
- **Compiler**: Android Clang r416183b1 is downloaded from Android's official
  source host when rebuilding; it is not bundled in the runtime archive.

See docs/build.md and src/provenance.json for exact inputs, hashes and limits of
reproducibility. No accounts, private SPI backups or configured user networks
are included in the public release.
