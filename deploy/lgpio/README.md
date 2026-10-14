# lgpio backend (vendored)

`python3-lgpio` + `liblgpio1`, built by Raspberry Pi for Debian trixie/armhf
and binary-compatible with this image's `/usr/bin/python3` (3.13).

Why vendored: gpiozero's `Button` needs edge detection, and the only backend
that can deliver it here is `lgpio` (it uses `/dev/gpiochip*`). RPi.GPIO and
gpiozero's pure-Python `native` factory both fall back to the legacy
`/sys/class/gpio` interface, whose line numbering on this kernel is not
BCM-based, so `export_store` rejects the pins ("invalid GPIO 6") and
`Button()` raises `RuntimeError: Failed to add edge detection`.

The image has no network at first boot, so the packages ship in the tree and
`deploy/install.sh` installs them when `lgpio` is missing.

Source: http://archive.raspberrypi.com/debian/pool/main/l/lg-gpio/
