#!/bin/bash
# One-shot repair of the Nightshade SD card's root-owned provisioning files.
#
# Why this exists: the card is powered off by pulling the plug. The last cut hit
# between install.sh writing the systemd units and ext4 flushing them to the
# card, so six files were left as 0-byte stubs:
#
#   /etc/systemd/system/nightshade.service
#   /etc/systemd/system/nightshade-firstboot.service
#   /usr/local/sbin/nightshade-firstboot.sh
#   /etc/modprobe.d/spidev-bufsiz.conf
#   /etc/udev/rules.d/99-nightshade-gpiomem.rules
#   /usr/lib/tmpfiles.d/nightshade.conf
#
# The enable symlinks survived, so systemd still tried to start the units -- but
# an empty unit has no ExecStart, so nothing ran and the panel stayed dark.
# install.sh now calls sync() so this cannot happen again.
#
# Run on the host, with the card mounted, as root:
#
#   sudo bash deploy/repair-card.sh            # card at /media/blight/ROOTFS
#   sudo bash deploy/repair-card.sh /mnt/root  # or wherever it is mounted
#
set -euo pipefail

R=${1:-/media/blight/ROOTFS}
SRC="$R/opt/nightshade/deploy"

if [ "$(id -u)" -ne 0 ]; then
    echo "This must run as root (it writes into the card's /etc)." >&2
    echo "Re-run as:  sudo bash $0 ${1:-}" >&2
    exit 1
fi
[ -d "$SRC" ] || { echo "!! $SRC not found -- is the card mounted?" >&2; exit 1; }
[ -s "$SRC/nightshade.service" ] || { echo "!! $SRC/nightshade.service is empty/missing" >&2; exit 1; }

echo "Repairing $R from $SRC"
install -m 644 "$SRC/nightshade.service"           "$R/etc/systemd/system/nightshade.service"
install -m 644 "$SRC/nightshade-firstboot.service" "$R/etc/systemd/system/nightshade-firstboot.service"
install -m 755 "$SRC/nightshade-firstboot.sh"      "$R/usr/local/sbin/nightshade-firstboot.sh"
install -m 644 "$SRC/spidev-bufsiz.conf"           "$R/etc/modprobe.d/spidev-bufsiz.conf"
install -m 644 "$SRC/99-nightshade-gpiomem.rules"  "$R/etc/udev/rules.d/99-nightshade-gpiomem.rules"
install -m 644 "$SRC/nightshade.tmpfiles.conf"     "$R/usr/lib/tmpfiles.d/nightshade.conf"

# The card's kali account is uid 1000, gid 1003. The tree was staged from the
# host, so the uid already matches but the group may not.
chown -R 1000:1003 "$R/home/kali/nightshade" 2>/dev/null || true
chown -R 1000:1003 "$R/home/kali/.local/state/nightshade" 2>/dev/null || true

# Flush before the card is unplugged. This is the whole point of the fix.
sync

echo
echo "== provisioning files =="
for f in \
  "$R/etc/systemd/system/nightshade.service" \
  "$R/etc/systemd/system/nightshade-firstboot.service" \
  "$R/usr/local/sbin/nightshade-firstboot.sh" \
  "$R/etc/modprobe.d/spidev-bufsiz.conf" \
  "$R/etc/udev/rules.d/99-nightshade-gpiomem.rules" \
  "$R/usr/lib/tmpfiles.d/nightshade.conf" ; do
    stat -c '  %6s bytes  mode %a  %n' "$f"
done
echo "== application =="
stat -c '  %6s bytes  %n' "$R/home/kali/nightshade/nightshade/hardware.py"
echo
echo "Done. Eject safely before pulling the card:"
echo "  sudo umount /media/blight/BOOT /media/blight/ROOTFS"
