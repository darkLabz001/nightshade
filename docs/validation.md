# Validation — 2026-10-12

Completed:
- Six automated tests: RGB565 byte order, script allowlist, concurrent launch exclusion, script cancellation including stubborn child process, physical launch confirmation, authenticated API/Origin validation, and login rate limiting (some tests cover multiple behaviors).
- Live local simulator: sign-in, virtual joystick navigation, script execution, output retrieval, PNG mirror and logout.
- Installed on Raspberry Pi Zero 2 W / Debian 13 ARM64.
- SPI0 enabled live and persisted in boot config; boot config backed up.
- Nightshade systemd service enabled and active as user pi.
- Driver initialized without reported errors; all four included diagnostic scripts completed with exit code 0 on the Pi.
- Existing camera-stream, SSH and Tailscale services remained active.
- The user initially reported a white panel with two fuzzy lines.
- Reduced SPI speed to 8 MHz (4 MHz during initialization), removed ST7789VW software reset, and added full gamma configuration based on manufacturer references.

Still requires the user to verify:
- Physical display clarity, colors, and orientation after the driver fix.
- Physical joystick and buttons. Virtual controls are verified.

Browser visual QA could not be completed because no browser was available to the UI automation tool. LCD render images were visually inspected. Web JavaScript syntax and backend integration were checked.

Connection note: Tailscale intermittently stalled. Verified the same SSH host key at the Pi's LAN address, 192.168.1.178, and completed the display-driver update over LAN. No network settings were changed.


Follow-up display fix prepared after the user reported a white panel with two fuzzy lines:
- Confirmed the exact Waveshare 1.3-inch HAT / ST7789VM from its model, resolution and GPIO pinout.
- Replaced the prior RaspyJack-derived initialization with Waveshare's bundled Python sample sequence and set the operating SPI rate to 40 MHz.
- Updated Nightshade's initialization sequence to the manufacturer example, restored the specified 40 MHz operating speed, and retained conservative 4 MHz initialization.
- Added a labeled color-pattern page under Settings. Local rendering and all six automated tests pass.
- SSH transfer failed while the Pi was offline. The SD card was then inserted into this computer and inspected directly. The card's `/home/pi/nightshade` files matched the earlier RaspyJack profile. The Waveshare-sample driver and 40 MHz config are now installed on the SD card, with the previous files saved in `backups/20261012-waveshare-profile`; file comparisons and hashes verified the copy. Physical display verification remains pending after reinsertion.

## Root cause of the persistent white panel — 2026-10-12 (later)

Once the Pi was briefly reachable over Tailscale, the panel was exercised directly with a
standalone script (bypassing Nightshade) using the exact vendor initialization now in
`hardware.py`. The panel responded correctly: solid red/green/blue/white and the dark
Nightshade UI frame all displayed. This proved the driver sequence, GPIO pins and SPI bus
are correct and that the fault was not in the panel path.

The remaining fault was ordering: `nightshade.service` declared
`After=network-online.target tailscaled.service`, and the app only binds its web server to
the Tailscale address. On this handheld the network (and therefore Tailscale) is frequently
absent, so the service started very late and the panel sat **white (uninitialized)** until
the app finally ran. The app's own log confirmed it initialized at 16:32:06, long after boot.

Fix:
- `app.py` now creates the display first and runs the render loop immediately; the web
  server binds opportunistically in a background thread, retrying every 5 s until its
  (possibly Tailscale) address exists. A missing network no longer blocks the UI.
- `deploy/nightshade.service` no longer orders after `network-online.target`/`tailscaled.service`;
  it keeps a weak `Wants=tailscaled.service` so the VPN is still pulled up when present.
- The standalone panel test used for the live diagnosis is kept at `scripts/lcd_test.py`.
- All six automated tests still pass.

Physical confirmation after this change is pending the next boot.

## Third white-panel cause: display inversion — root cause, 2026-10-13

The 24 MHz change plus the colour self-test finally produced a decisive
observation. The panel flashed **cyan → magenta → yellow**, then black, then
white, and settled on a **plain white screen**.

Those colours are the exact bitwise inverse of what the self-test sends:

| sent | value | displayed | value |
|------|-------|-----------|-------|
| red   | 0xF800 | cyan    | 0x07FF |
| green | 0x07E0 | magenta | 0xF81F |
| blue  | 0x001F | yellow  | 0xFFE0 |
| white | 0xFFFF | black   | 0x0000 |
| black | 0x0000 | white   | 0xFFFF |

Every channel is a pure bit flip, so the pixel format, byte order, MADCTL RGB
order, wiring, SPI bus and clock were all correct all along. The panel was
*displaying the UI the whole time, inverted*: the dark `#09080e` background
renders as white, which is what every "still white" report actually was.

The offender is the vendor sample's `0x21` (INVON). This panel needs inversion
off:

- `hardware.py` now sends `0x20` (INVOFF) instead of `0x21` in the ST7789 branch.
- `scripts/lcd_test.py` matches.

The 24 MHz operating clock and the black clear at the conservative init clock are
kept: they are the verified-safe configuration, and they make a failed frame
render black rather than white.

Physical confirmation pending the next boot (colour self-test left enabled).

## Fourth cause: frame writes at 24 MHz are corrupt — 2026-10-13

With inversion off the panel flashed the correct red/green/blue, then black —
but the UI settled on "black with two fuzzy lines". The boot log was clean:

```
display: Waveshare ST7789 240x240 init (init 8000000 Hz, op 24000000 Hz)
display: color self-test complete
display: panel ready (240x240)
display: first frame written (115200 bytes)
```

No exception, DejaVu fonts present, Pillow 12.2.0, and decoding `rgb565()`'s
output back to pixels reproduces the UI exactly. So the data was correct and the
transfer was corrupting it.

The self-test is the control: it writes the **whole 240x240 panel** at 8 MHz and
those frames were visibly perfect. The UI frames take the identical write path
but at 24 MHz, and only they are wrong. Both 40 MHz and 24 MHz are therefore
unreliable on this HAT — 8 MHz is the only proven rate, and it is proven under
boot-time load (the self-test runs during startup).

That also explains the earlier reports. While inversion was on, a corrupt frame
of a mostly-dark UI inverted to a mostly-white screen ("plain white"). With
inversion fixed, the same corruption reads as near-black with smeared bright
bands ("black with two fuzzy lines").

Fix: `spi_speed` is 8 MHz in `config.json` and the `hardware.py` default, and
`scripts/lcd_test.py` defaults to the same, so the app and the standalone test
now share one verified configuration.

Physical confirmation pending the next boot.

## Second white-panel cause: the 40 MHz operating clock — 2026-10-13

A boot log captured from the card showed the ordering fix working, so the panel
was no longer uninitialised:

```
gpio: /dev/gpiochip0 name=gpiochip0 label=pinctrl-bcm2835 lines=54
gpio: lgpio active on /dev/gpiochip0
display: Waveshare ST7789 240x240 init (init 8000000 Hz, op 40000000 Hz)
display: panel ready (240x240)
Display ready (hardware=True); starting interface
display: first frame written (115200 bytes)
```

The panel was still white. Comparing the driver against the standalone test that
was *actually* observed working on the hardware (`scripts/lcd_test.py`, whose
`Panel` defaults to `speed=24_000_000`) leaves the operating clock as the only
substantive difference: the app ran its `fill()` and every frame at 40 MHz,
while the proven test ran at 24 MHz. The panel's init commands are written at a
conservative 8 MHz in both, so an overclocked bus fails only *after* the
controller is up — which is exactly the "display is on but white" symptom.

Fix:
- `config.json` and `hardware.py` now default to `spi_speed: 24000000`.
- The black clear (`fill(0x0000)`) now runs *before* the clock is raised, so a
  marginal operating clock can never leave the panel on its white power-on
  state — worst case it stays black.
- `display.self_test` is temporarily `true` so the next boot flashes
  red/green/blue/white/black once before the UI: a clean flash proves data is
  reaching the panel at the conservative init clock, independent of the frame
  clock. Turn it back to `false` once the panel is confirmed.

Physical confirmation pending the next boot.

## Fifth cause — the real one: hardware SPI does not drive this panel, 2026-10-13 (resolved)

The panel was replaced/confirmed as a **Waveshare 1.44" ST7735S 128x128** HAT,
not the 1.3" ST7789 the project had been targeting. After switching to the
ST7735 register set (RaspyJack's `LCD_1in44.py`: hardware reset, `B1..C5`,
`E0/E1`, `F0=01`, `F6=00`, `3A=05`, `36=0x68`, window origin `(1,2)`) a solid
fill still came out white over hardware SPI.

Everything below was measured on the live Pi:

| check | result |
|-------|--------|
| Backlight GPIO24 toggle | panel visibly dims/brightens — HAT seated, pins right |
| Software **bit-bang** of MOSI/SCLK (mode 0, CS held low) | **clean, correct image** |
| Hardware SPI clock (`spidiag`) | peripheral really clocks: 1 MHz→803 kbps, 62.5 kHz→50.7 kbps, 8 MHz→6.03 Mbps |
| Hardware SPI, all speeds 62.5 kHz…8 MHz | white every time |
| Hardware SPI, modes 0/1/2/3 | white every time |
| Hardware SPI, kernel CS vs `SPI_NO_CS`+CS held low vs whole-frame `writebytes2` | white every time |
| RaspyJack's exact setup (GPIO8 plain output low, no `no_cs`, 9 MHz) | white every time |
| pinmux | GPIO9/10/11 ALT0 (SPI0), GPIO8 GPIO-out CS — correct |

Bit-bang works and hardware SPI does not, at the *same byte stream, same pins,
same speeds* — and the peripheral is verified to be clocking and CS verified to
be holdable. So the fault is the signal the bcm2835 hardware-SPI path emits on
this board, not the panel, the wiring, the register set or the clock.

Fix: drive the panel the way that works, but fast. `nightshade/nslcd_bitbang.c`
toggles the GPIO lines by writing the `/dev/gpiomem` registers directly, giving
**~75-90 fps for a full 128x128 frame** (Python bit-banging managed ~0.2 fps).

- `nightshade/bitbang.py` loads the helper (via ctypes); `hardware.py` uses it as
  the primary transport and keeps spidev only as a fallback.
- `deploy/install.sh` compiles `libnslcd_bitbang.so` at install time (the
  service runs `ProtectHome=read-only`, so it cannot build into its own tree).
- `config.json` panel `type` is now `ST7735_128`; MADCTL default `0x68` and the
  window origin default `(1,2)`.
- Boot log: `display: transport = GPIO bit-bang (...)`, `Waveshare ST7735
  128x128 init`, `panel ready (128x128)`, `first frame written (32768 bytes)`.

**Confirmed on the glass: the boot splash and the Nightshade UI both display.**
All seven automated tests still pass.
