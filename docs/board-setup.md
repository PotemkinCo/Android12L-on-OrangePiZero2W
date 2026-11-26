# One-time board setup

This path supports the factory Zero2W SPI layout used by the tested1GB board.
The factory demo Linux otherwise boots from16MiB SPI even when no SD is inserted.
Its U-Boot briefly exposes a maintenance USB interface during power-on.

`prepare-board.py --apply` waits for that window using the native catcher, sends
only the legacy F0/00 identification/hold handshake, then uses read-only F3/03
commands to back up all16MiB. It checks the boot header, GPT CRCs, exact env
partition location/size, environment CRC, and known original boot command.
Two independent environment reads must match the backup before a write.

The only write is F3/01 to logical sector2592 for256 sectors (128KiB), physical
0x240000. It replaces `bootcmd=run setargs_nand boot_normal` with `bootcmd=efex`
and updates the environment CRC, preserving other fields. Readback must match;
a detected write failure triggers an attempt to restore the preceding environment.
No erase-all, key, efuse or private-partition handshake is sent.

The change persists across power cycles and makes the factory bootloader enter
Boot ROM FEL instead of launching demo Linux. Android itself lives on the host.
It requires one physical unplug/reconnect after the change. This is the only
persistent board change required by the project. Skip setup on a board already
configured this way. A board already in ROM FEL can start directly with the launcher.

Backups are unique to the board, owner-only, excluded from Git and releases.
Keep them. Automatic restoration from ROM FEL is not implemented; do not assume
the factory-maintenance writer can talk to ROM. Restoring the original requires
a suitable SPI recovery method. Failed persistent writes can require hardware
recovery. The program intentionally refuses unknown factory layouts/boot commands
rather than inventing offsets. Only one board may be attached during setup.

Without `--apply`, the tool performs the backup/read-only checks and writes
nothing to the board. It still needs the factory maintenance connection.
