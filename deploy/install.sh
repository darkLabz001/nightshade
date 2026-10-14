#!/bin/bash
set -euo pipefail
# Install Nightshade for the Kali (kali) target on the Pi Zero 2 W.
if [ "$(id -u)" -ne 0 ]; then echo 'Run with sudo'; exit 1; fi
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(dirname "$HERE")"
USER_NAME=kali
HOME_DIR=/home/$USER_NAME
TARGET=$HOME_DIR/nightshade
STATE=$HOME_DIR/.local/state/nightshade
BOOT_CONFIG=/boot/firmware/config.txt

install -d -o "$USER_NAME" -g "$USER_NAME" "$STATE"
[ -f "$BOOT_CONFIG" ] || { echo "$BOOT_CONFIG not found"; exit 1; }

# Vendored GPIO backend. gpiozero's Button needs edge detection and lgpio is
# the only backend that can provide it on this image (see deploy/lgpio/), so
# install the bundled packages when lgpio is absent. No network required.
if ! python3 -c 'import lgpio' 2>/dev/null; then
    for deb in "$PROJECT"/deploy/lgpio/liblgpio1_*.deb "$PROJECT"/deploy/lgpio/python3-lgpio_*.deb; do
        [ -f "$deb" ] || continue
        echo "Installing $(basename "$deb")"
        dpkg -i "$deb"
    done
    ldconfig
fi

# Python dependencies: Pillow, spidev and gpiozero are required. lgpio is the
# backend for the eight HAT buttons; without it the panel still runs and the
# web UI can drive every key, so a miss here is loud but never fatal.
# On Kali/armhf install them with:
#   apt-get install -y python3-pil python3-spidev python3-gpiozero \
#       fonts-dejavu-core
# The lgpio packages are vendored under deploy/lgpio (Debian trixie, armhf).
python3 - <<'PY'
import importlib.util
required = ['PIL', 'spidev', 'gpiozero']
missing = [m for m in required if importlib.util.find_spec(m) is None]
if missing:
    raise SystemExit('Missing Python modules: ' + ', '.join(missing))
try:
    import lgpio
    print('Python deps present; GPIO backend: lgpio')
except Exception as exc:
    print('WARNING: lgpio unavailable (%s). The panel still runs; only the '
          'HAT buttons need it. See deploy/lgpio/README.md.' % exc)
PY

# Copy the application into place (skip when the source is already the target).
install -d -o "$USER_NAME" -g "$USER_NAME" "$TARGET"
if [ "$PROJECT" = "$TARGET" ]; then
    echo "Source already at $TARGET; skipping copy"
else
    cp -a "$PROJECT/." "$TARGET/"
fi
find "$TARGET" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
chown -R "$USER_NAME:$USER_NAME" "$TARGET"

# Build the fast GPIO bit-bang helper (software SPI). The bcm2835 hardware SPI
# peripheral does not drive this HAT's panel, so the display is clocked out by
# toggling the GPIO lines from a small C helper (see nightshade/nslcd_bitbang.c
# and nightshade/bitbang.py). It is built here rather than at runtime because
# the service runs with ProtectHome=read-only and cannot write into its own
# package directory.
if command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1; then
    CC=$(command -v cc || command -v gcc)
    "$CC" -O3 -shared -fPIC -o "$TARGET/nightshade/libnslcd_bitbang.so" \
        "$TARGET/nightshade/nslcd_bitbang.c"
    chown "$USER_NAME:$USER_NAME" "$TARGET/nightshade/libnslcd_bitbang.so"
    echo "Built display bit-bang helper: $TARGET/nightshade/libnslcd_bitbang.so"
else
    echo "WARNING: no C compiler found; the display bit-bang helper was not built"
fi

# Enable SPI for the LCD HAT.
grep -q '^dtparam=spi=on' "$BOOT_CONFIG" || printf '\n# Nightshade LCD\ndtparam=spi=on\n' >> "$BOOT_CONFIG"

# Let a whole 240x240 RGB565 frame go out as one SPI message, so the panel is
# never deselected part-way through a write (see nightshade/hardware.py).
install -m 644 "$PROJECT/deploy/spidev-bufsiz.conf" /etc/modprobe.d/spidev-bufsiz.conf

# GPIO access for the non-root service account. On the Raspberry Pi kernel the
# raspberrypi-gpiomem driver exposes /dev/gpiomem under the "rpi-gpiomem" udev
# subsystem, which the stock rules do not cover; without this the gpio group
# cannot open it and RPi.GPIO falls back to /dev/mem (root only).
install -m 644 "$PROJECT/deploy/99-nightshade-gpiomem.rules" /etc/udev/rules.d/99-nightshade-gpiomem.rules
install -m 644 "$PROJECT/deploy/nightshade.tmpfiles.conf" /usr/lib/tmpfiles.d/nightshade.conf
udevadm control --reload 2>/dev/null || true
udevadm trigger --subsystem-match=rpi-gpiomem 2>/dev/null || true
udevadm trigger --subsystem-match=spidev 2>/dev/null || true
udevadm trigger --subsystem-match=gpio 2>/dev/null || true
if [ -e /dev/gpiomem ]; then chown root:gpio /dev/gpiomem; chmod 0660 /dev/gpiomem; fi
if [ -e /dev/spidev0.0 ]; then chown root:spi /dev/spidev0.0; chmod 0660 /dev/spidev0.0; fi
if [ -e /dev/gpiochip0 ]; then chown root:gpio /dev/gpiochip0; chmod 0660 /dev/gpiochip0; fi

# Install the service.
install -m 644 "$PROJECT/deploy/nightshade.service" /etc/systemd/system/nightshade.service

# The OTA unit. It runs as root outside the sandboxed service
# on purpose: applying an update writes to /opt, /etc, /boot
# and the home tree. The Settings menu starts it; the tool
# (scripts/ota_update.py) only triggers it and tails the log.
install -m 644 "$PROJECT/deploy/nightshade-ota.service" /etc/systemd/system/nightshade-ota.service

# Install the first-boot provisioning script/unit. Keeping these in the repo
# means the "do not wait for the network" fix survives a reflash of the root
# filesystem. Takes effect on the next boot.
install -d /usr/local/sbin
install -m 755 "$PROJECT/deploy/nightshade-firstboot.sh" /usr/local/sbin/nightshade-firstboot.sh
install -m 644 "$PROJECT/deploy/nightshade-firstboot.service" /etc/systemd/system/nightshade-firstboot.service

# This card is powered off by pulling the plug, and every file above was written
# with live page cache. ext4 keeps delayed allocations, so an unclean power cut
# was truncating freshly written units to 0 bytes -- which left nightshade.service
# empty and the next boot with no panel at all. Flush before the service starts.
sync

systemctl daemon-reload
systemctl enable --now nightshade.service
# Flush the application copy and unit files too: the panel is often unplugged
# within seconds of the splash appearing.
sync
systemctl --no-pager status nightshade.service
