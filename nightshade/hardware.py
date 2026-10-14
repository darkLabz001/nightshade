"""SPI display and debounced HAT input. BCM numbering throughout."""
import logging
import time

try:
    from . import bitbang
except ImportError:  # pragma: no cover - imported as a standalone module
    import bitbang

LOG = logging.getLogger('nightshade')

PINS = {'UP': 6, 'DOWN': 19, 'LEFT': 5, 'RIGHT': 26, 'OK': 13,
        'KEY1': 21, 'KEY2': 20, 'KEY3': 16}


def _lgpio_chip():
    """Pick the gpiochip that hosts the SoC GPIO header.

    gpiozero defaults to chip 0 for every Pi but the 5, which is right on
    Raspberry Pi OS. It is not something we can rely on here: on this kernel
    the legacy sysfs GPIO numbers are not BCM-based (``export_store: invalid
    GPIO 6` in the kernel log), which means some other gpiochip was registered
    ahead of the Broadcom controller. Probe the real chips and prefer the one
    that looks like the SoC controller, then the one with the most lines.
    """
    try:
        import lgpio
        best = None
        for index in range(8):
            try:
                handle = lgpio.gpiochip_open(index)
            except Exception:
                continue
            if not isinstance(handle, int) or handle < 0:
                continue
            try:
                raw = list(lgpio.gpio_get_chip_info(handle))
            except Exception:
                raw = []
            finally:
                try:
                    lgpio.gpiochip_close(handle)
                except Exception:
                    pass
            if not raw:
                continue
            # lgpio documents [status, lines, name, label]. Classify by type so
            # the probe still parses if a binding ever omits the status field.
            numbers = [v for v in raw if isinstance(v, int) and not isinstance(v, bool)]
            labels = [v for v in raw if isinstance(v, str)]
            status = numbers[0] if len(numbers) > 1 else 0
            lines = numbers[-1] if numbers else 0
            name = labels[0] if labels else ''
            label = labels[1] if len(labels) > 1 else ''
            if status < 0:
                continue
            LOG.info('gpio: /dev/gpiochip%d name=%s label=%s lines=%s',
                     index, name, label, lines)
            text = ('%s %s' % (name, label)).lower()
            score = 1000 if any(tag in text for tag in ('bcm', 'pinctrl', '3f200000')) else 0
            score += lines
            if best is None or score > best[0]:
                best = (score, index)
        if best is not None:
            return best[1]
    except Exception as exc:
        LOG.info('gpio: chip probe failed (%s); using lgpio default', exc)
    return None


# Where a spare override file may live on the (FAT) boot partition. It lets the
# panel be re-tuned from a card reader -- drop a line in, reboot, and the app
# picks it up -- without editing anything root-owned on the ext4 rootfs.
_PANEL_OVERRIDE_FILES = (
    '/boot/firmware/nightshade-panel.conf',
    '/boot/nightshade-panel.conf',
)

_OUT_PIN_NAMES = {25: 'DC', 27: 'RST', 24: 'BL'}


def _panel_overrides():
    """Read optional display overrides from the boot partition.

    Recognised keys (``#`` comments and blank lines are ignored)::

        type=ST7789_240|ST7735_128
        madctl=0x60
        invert=0|1
        xoff=0
        yoff=0
        speed=8000000

    A missing file is not an error. Values are returned already typed.
    """
    values = {}
    for path in _PANEL_OVERRIDE_FILES:
        try:
            text = open(path, 'r', encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        LOG.info('display: panel overrides from %s', path)
        for line in text.splitlines():
            line = line.split('#', 1)[0].strip()
            if not line or '=' not in line:
                continue
            key, _, raw = line.partition('=')
            key, raw = key.strip().lower(), raw.strip()
            if key not in ('type', 'madctl', 'invert', 'xoff', 'yoff', 'speed'):
                continue
            try:
                if key == 'type':
                    values[key] = raw
                elif key == 'invert':
                    values[key] = bool(int(raw, 0))
                else:
                    values[key] = int(raw, 0)
            except ValueError:
                LOG.warning('display: ignoring bad override %s=%s', key, raw)
        break
    return values


class _RPiPin:
    """A display control line driven through RPi.GPIO.

    Both references known to paint this HAT correctly -- the vendor sample and
    RaspyJack -- drive DC/RST/BL through RPi.GPIO's /dev/gpiomem mmap. That
    backend writes the GPIO register directly, so a level change is in place the
    instant the call returns, with no syscall per edge. That is the only
    remaining difference between our driver and the references, so match them.
    """

    def __init__(self, gpio, bcm, initial=False):
        self._gpio = gpio
        self._bcm = int(bcm)
        gpio.setup(self._bcm, gpio.OUT)
        gpio.output(self._bcm, gpio.HIGH if initial else gpio.LOW)

    def on(self):
        self._gpio.output(self._bcm, self._gpio.HIGH)

    def off(self):
        self._gpio.output(self._bcm, self._gpio.LOW)

    def read(self):
        """Actual pin level. RPi.GPIO can read a line it has set as output."""
        return int(self._gpio.input(self._bcm))

    def close(self):
        try:
            self._gpio.setup(self._bcm, self._gpio.IN)
        except Exception:
            pass


def _out_pin(bcm, initial=False):
    """Return a pin object for a display control line, or None to fall back."""
    try:
        import RPi.GPIO as GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        LOG.info('display: %s (GPIO %d) via RPi.GPIO',
                 _OUT_PIN_NAMES.get(bcm, '?'), bcm)
        return _RPiPin(GPIO, bcm, initial)
    except Exception as exc:
        LOG.info('display: RPi.GPIO could not take GPIO %d (%s); using gpiozero',
                 bcm, exc)
        return None


def _pin_factory():
    """Prefer lgpio, then RPi.GPIO. Both drive the same header pins.

    lgpio talks to /dev/gpiochip* directly. RPi.GPIO reaches the same pins
    through /dev/gpiomem but implements edge detection via the legacy
    /sys/class/gpio interface, whose numbering is not BCM-based on this
    kernel, so buttons only work reliably on lgpio.
    """
    try:
        from gpiozero.pins.lgpio import LGPIOFactory
        chip = _lgpio_chip()
        factory = LGPIOFactory(chip=0 if chip is None else chip)
        LOG.info('gpio: lgpio active on /dev/gpiochip%d', factory.chip)
        return factory
    except Exception as exc:
        LOG.info('lgpio unavailable (%s); trying RPi.GPIO', exc)
    try:
        from gpiozero.pins.rpigpio import RPiGPIOFactory
        return RPiGPIOFactory()
    except Exception as exc:
        LOG.info('RPi.GPIO unavailable (%s); using gpiozero default pins', exc)
    return None


class _SpiBus:
    """Last-resort transport wrapping spidev with the bit-bang interface.

    The bcm2835 hardware SPI does not drive this HAT's panel (see bitbang.py),
    so this exists only so the driver still loads and can be diagnosed on a
    board where the peripheral does work. It presents the same ``write(dc,
    data)`` surface as :class:`bitbang.BitBang`.
    """

    def __init__(self, spi, dc_pin):
        self._spi = spi
        self._dc = dc_pin

    def write(self, dc, data):
        if dc:
            self._dc.on()
        else:
            self._dc.off()
        self._spi.writebytes(list(data))

    def close(self):
        try:
            self._spi.close()
        except Exception:
            pass


class Hat:
    def __init__(self, config, emit):
        from gpiozero import Button, DigitalOutputDevice
        self.factory = _pin_factory()
        self.devices = []
        self.spi = None
        self.bus = None
        self._bitbang = False
        try:
            self.dc = _out_pin(25) or DigitalOutputDevice(25, pin_factory=self.factory)
            self.devices.append(self.dc)
            self.reset = _out_pin(27) or DigitalOutputDevice(27, pin_factory=self.factory)
            self.devices.append(self.reset)
            self.light = _out_pin(24) or DigitalOutputDevice(
                24, initial_value=False, pin_factory=self.factory)
            self.devices.append(self.light)
            # Prove the control lines are really being driven. RPi.GPIO can read
            # back a pin it owns as an output, so a DC/RST/BL that reads high
            # then low is positive evidence the panel is being framed correctly.
            # A stuck line here would garble every frame while a flat fill
            # (which has no framing to get wrong) still looked fine.
            for _name, _pin in (('DC', self.dc), ('RST', self.reset), ('BL', self.light)):
                if hasattr(_pin, 'read'):
                    _pin.on(); _high = _pin.read()
                    _pin.off(); _low = _pin.read()
                    LOG.info('display: %s readback high=%d low=%d%s', _name, _high, _low,
                             '' if (_high, _low) == (1, 0) else '  <-- NOT DRIVING')
                else:
                    LOG.info('display: %s readback unavailable (gpiozero backend)', _name)
            self.dc.off(); self.reset.on(); self.light.on()
            overrides = _panel_overrides()
            operating_speed = int(overrides.get('speed', config.get('spi_speed', 8000000)))
            self.rotation = config.get('rotation', 0)
            self.kind = overrides.get('type', config.get('type', 'ST7789_240'))
            if self.kind not in ('ST7789_240', 'ST7735_128'):
                raise ValueError('Unsupported display type')
            self.size = 240 if self.kind == 'ST7789_240' else 128
            # GRAM origin of the visible window. The 128x128 ST7735S sits at
            # (1, 2) inside the controller's 132x162 GRAM (RaspyJack's
            # X_Adjust/Y_Adjust); the 240x240 ST7789 uses the origin. Both are
            # overridable from the boot partition.
            default_xoff = 1 if self.kind == 'ST7735_128' else 0
            default_yoff = 2 if self.kind == 'ST7735_128' else 0
            self._xoff = int(overrides.get('xoff', default_xoff))
            self._yoff = int(overrides.get('yoff', default_yoff))
            LOG.info('display: overrides=%s', overrides or 'none')
            # Transport. The bcm2835 hardware SPI peripheral does not drive
            # this panel -- every clock/mode/CS combination leaves it white,
            # while GPIO-toggled writes are pixel-perfect -- so the fast C
            # bit-bang helper is the primary path. spidev is only a fallback
            # for boards where the peripheral does work.
            self.bus = bitbang.load()
            if self.bus is not None:
                self._bitbang = True
                LOG.info('display: transport = GPIO bit-bang (%s)', self.bus.path)
            else:
                import spidev
                self.spi = spidev.SpiDev()
                self.spi.open(0, 0)
                # A ``speed=`` override is taken literally so the clock can be
                # swept from the card reader; the configured default stays
                # capped at the 8 MHz that is known clean on this wiring.
                self.spi.max_speed_hz = (
                    operating_speed if 'speed' in overrides
                    else min(operating_speed, 8000000))
                self.spi.mode = 0
                self.bus = _SpiBus(self.spi, self.dc)
                LOG.warning('display: bit-bang helper unavailable; fell back '
                            'to hardware SPI, which does not drive this panel')
            if self.size == 240:
                # Waveshare 1.3-inch LCD HAT (ST7789VW). Register values/order
                # follow the RaspyJack driver (LCD_1in44.py + LCD_Config.py),
                # which is the known-good reference for this exact HAT. They
                # match the vendor's bundled sample (raspberry-pi/lcd.c) except
                # for a few values RaspyJack tuned to stop the panel ghosting
                # and tearing a full picture (a flat fill can never reveal
                # that, which is why colours always looked fine).
                self.light.on()
                LOG.info('display: Waveshare ST7789 %dx%d init (op %d Hz)',
                         self.size, self.size, operating_speed)
                self.reset.on(); time.sleep(.1)
                self.reset.off(); time.sleep(.1)
                self.reset.on(); time.sleep(.1)
                self.command(0x36, [0x00])          # MADCTL (final value below)
                self.command(0x3A, [0x05])          # COLMOD: 16-bit RGB565
                self.command(0xB2, [0x0C,0x0C,0x00,0x33,0x33])  # Porch
                self.command(0xB7, [0x35])          # Gate control
                self.command(0xBB, [0x2B])          # VCOM (higher cuts ghosting)
                self.command(0xC0, [0x2C])          # LCM control
                self.command(0xC2, [0x01])          # VDV/VRH enable
                self.command(0xC3, [0x15])          # VRH (higher, cleaner edges)
                self.command(0xC4, [0x20])          # VDV set
                self.command(0xC6, [0x01])          # Frame rate ~111 Hz
                self.command(0xD0, [0xA4,0xA1])     # Power control 1
                self.command(0xE0, [0xD0,0x04,0x0D,0x11,0x13,0x2B,0x3F,0x54,0x4C,0x18,0x0D,0x0B,0x1F,0x23])
                self.command(0xE1, [0xD0,0x04,0x0C,0x11,0x13,0x2C,0x3F,0x44,0x51,0x2F,0x1F,0x1F,0x20,0x23])
                # Display inversion ON. Both the vendor sample and RaspyJack
                # ("ST7789 needs this for correct colors") use 0x21, so the
                # earlier switch to 0x20 was chasing the wrong fault: with the
                # bad MADCTL below the frame never landed and the panel's
                # default state merely looked "inverted". A boot-partition
                # ``invert=0`` switch to 0x20 is kept for panels that read
                # negative.
                self.command(0x20 if overrides.get('invert') is False else 0x21)
                # MADCTL last, exactly like RaspyJack's SetGramScanWay(): the
                # default scan direction U2D_R2L is 0x60 (MX|MV). Overridable so
                # a suspect panel can be swept without a rebuild.
                madctl = int(overrides.get('madctl', 0x60))
                self.command(0x36, [madctl])        # MADCTL (default MX|MV)
                self.command(0x11); time.sleep(.12) # Sleep out
                self.command(0x29); time.sleep(.12) # Display on
                if config.get('self_test'):
                    for color in (0xF800, 0x07E0, 0x001F, 0xFFFF, 0x0000):
                        self.fill(color); time.sleep(.3)
                    LOG.info('display: color self-test complete')
                LOG.info('display: panel ready (%dx%d)', self.size, self.size)
            else:
                # Waveshare 1.44-inch LCD HAT (ST7735S, 128x128). Values and
                # order follow the RaspyJack driver (LCD_1in44.py), the
                # known-good reference for this HAT: a hardware reset (not the
                # 0x01 software reset), the power/frame-rate table, the two
                # gamma curves, MADCTL 0x68 (BGR + MY|MV) and the (1, 2) GRAM
                # window origin set above. Writing a readable picture needs all
                # of these; a flat fill cannot reveal that any are wrong.
                self.light.on()
                LOG.info('display: Waveshare ST7735 %dx%d init', self.size, self.size)
                self.reset.on(); time.sleep(.1)
                self.reset.off(); time.sleep(.1)
                self.reset.on(); time.sleep(.1)
                for register, data in [
                        (0xB1,[0x01,0x2C,0x2D]), (0xB2,[0x01,0x2C,0x2D]),
                        (0xB3,[0x01,0x2C,0x2D,0x01,0x2C,0x2D]), (0xB4,[0x07]),
                        (0xC0,[0xA2,0x02,0x84]), (0xC1,[0xC5]), (0xC2,[0x0A,0x00]),
                        (0xC3,[0x8A,0x2A]), (0xC4,[0x8A,0xEE]), (0xC5,[0x0E]),
                        (0xE0,[0x0f,0x1a,0x0f,0x18,0x2f,0x28,0x20,0x22,
                               0x1f,0x1b,0x23,0x37,0x00,0x07,0x02,0x10]),
                        (0xE1,[0x0f,0x1b,0x0f,0x17,0x33,0x2c,0x29,0x2e,
                               0x30,0x30,0x39,0x3f,0x00,0x07,0x03,0x10]),
                        (0xF0,[0x01]), (0xF6,[0x00]), (0x3A,[0x05])]:
                    self.command(register, data)
                madctl = int(overrides.get('madctl', 0x68))
                self.command(0x36, [madctl]); time.sleep(.2)
                self.command(0x11); time.sleep(.12)
                self.command(0x29); time.sleep(.12)
                LOG.info('display: panel ready (%dx%d)', self.size, self.size)
            # Paint the panel as soon as the controller is up, still on the
            # conservative init clock. Until the first frame is written the
            # ST7789 shows its power-on state, which reads as a white screen;
            # this makes the panel visibly alive and keeps a stale white panel
            # from ever surviving a slow start-up.
            self.fill(0x0000)
            if config.get('hw_probe'):
                self._hw_probe()
            if config.get('pattern_test'):
                # Unmissable, orientation-revealing splash. The interface is a
                # deliberately dark theme, which on a small panel is easy to
                # mistake for an unlit backlight, so prove the panel with a
                # full-brightness page (and TOP/BOTTOM/LEFT/RIGHT labels)
                # before the interface takes over.
                self._boot_splash()
                time.sleep(4)
            # Apply the configured frame rate only once the panel is known
            # good, so a bad value can at worst leave it black, never white.
            if self.spi is not None:
                self.spi.max_speed_hz = operating_speed
            bound = 0
            for name, pin in PINS.items():
                try:
                    button = Button(pin, pull_up=True, bounce_time=.06, pin_factory=self.factory)
                except Exception as exc:
                    # A dead key must not take the panel down with it: the
                    # display is the primary output and the web UI can still
                    # drive every key through /api/key.
                    LOG.error('buttons: %s (GPIO %d) unavailable (%s)', name, pin, exc)
                    continue
                button.when_pressed = lambda key=name: emit(key)
                self.devices.append(button)
                bound += 1
            if bound != len(PINS):
                LOG.error('buttons: %d of %d bound; panel stays active',
                          bound, len(PINS))
            self.light.on()
        except Exception:
            self.close()
            raise

    def _boot_splash(self):
        """Branded DarkSec Labs boot page.

        A bright skull crest over an upright wordmark proves two things at a
        glance before the deliberately dark interface takes over: the glass is
        alive and in colour, and it is the right way up. It flows through the
        exact same rgb565 -> _blit path as the UI, so a correct splash also
        proves where the interface will land. The crest is public-domain
        artwork (see THIRD_PARTY.md) shipped alongside the app, scaled to fit
        whichever panel size is configured.
        """
        from PIL import Image, ImageDraw, ImageFont
        import os
        size = self.size
        try:
            img = Image.new('RGB', (size, size), '#05030a')
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, size - 1, size - 1), outline='#2a1840', width=max(1, size // 64))
            crest = os.path.join(os.path.dirname(__file__), 'assets', 'darkseclabs.png')
            if os.path.exists(crest):
                art = Image.open(crest).convert('RGBA')
                art.thumbnail((int(size * .72), int(size * .72)), Image.LANCZOS)
                img.paste(art, ((size - art.width) // 2, int(size * .05)), art)
            face = ImageFont.truetype(
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', max(10, int(size * .105)))
            small = ImageFont.truetype(
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', max(8, int(size * .072)))
            draw.text((size // 2, int(size * .80)), 'DARKSEC LABS', font=face, fill='#d6c8ff', anchor='mm')
            draw.line((int(size * .2), int(size * .872), int(size * .8), int(size * .872)),
                      fill='#ff2d55', width=max(1, size // 96))
            draw.text((size // 2, int(size * .93)), 'NIGHTSHADE', font=small, fill='#7a6a92', anchor='mm')
            self.show(img)
            LOG.info('display: boot splash written (darkseclabs crest)')
        except Exception as exc:
            # Never let a font or drawing problem keep the panel dark: a plain
            # bright fill is still an unmistakable "the glass works" signal.
            LOG.warning('display: splash draw failed (%s); using solid fill', exc)
            self.fill(0xCE6F)

    def _hw_probe(self):
        """Cycle the coordinate/orientation suspects with a readable page.

        A solid fill tells us nothing about placement: it looks identical no
        matter how the GRAM is addressed, which is why the panel has always
        shown clean colour flashes yet never a readable word. This repaints one
        candidate geometry at a time with a distinct solid background, a thick
        border and a big label, so even a rotated or mirrored image identifies
        itself. The correct candidate is the one whose label reads upright and
        unbroken; if none do, the fault is in the transfer, not the geometry.
        """
        from PIL import Image, ImageDraw, ImageFont
        size = self.size
        try:
            face = ImageFont.truetype(
                '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf', 56)
            small = ImageFont.truetype(
                '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 15)
        except OSError:
            face = small = ImageFont.load_default()
        candidates = [
            #  label, MADCTL, xoff, yoff, background
            ('C1', 0x00, 0, 0, '#c82828'),     # identity
            ('C2', 0x60, 0, 0, '#28b048'),     # MX+MV
            ('C3', 0xA0, 0, 0, '#2858d8'),     # MY+MV
            ('C4', 0xC0, 0, 0, '#c8a800'),     # MX+MY
            ('C5', 0x00, 0, 80, '#b028b0'),    # identity, row-shifted origin
            ('C6', 0x00, 80, 0, '#109090'),    # identity, col-shifted origin
        ]
        for _ in range(2):
            for label, madctl, xoff, yoff, background in candidates:
                LOG.info('display: probe %s MADCTL 0x%02X offset %d,%d',
                         label, madctl, xoff, yoff)
                self.command(0x36, [madctl])
                self._xoff, self._yoff = xoff, yoff
                img = Image.new('RGB', (size, size), background)
                draw = ImageDraw.Draw(img)
                draw.rectangle((3, 3, size - 4, size - 4), outline='#000000', width=10)
                draw.rectangle((0, size // 2 - 52, size - 1, size // 2 + 52),
                               fill='#ffffff')
                draw.text((size // 2, size // 2), label, font=face,
                          fill='#000000', anchor='mm')
                draw.text((size // 2, 20), 'READS UPRIGHT', font=small,
                          fill='#000000', anchor='mm')
                self.show(img)
                time.sleep(5)
        self.command(0x36, [0x60])          # back to the RaspyJack default
        self._xoff, self._yoff = 0, 0

    def command(self, register, data=None):
        self.bus.write(0, [register])
        if data:
            self.bus.write(1, data)

    def _write_pixels(self, pixels):
        """Push the frame payload.

        The bit-bang helper takes the whole buffer in one call and keeps CS
        asserted throughout, which is what the ST7735 wants. The spidev
        fallback streams 4096-byte messages, matching the reference drivers.
        """
        if self._bitbang:
            self.bus.write(1, pixels)
            return
        for start in range(0, len(pixels), 4096):
            self.bus.write(1, pixels[start:start + 4096])

    def _blit(self, pixels, x=None, y=None):
        """Push a complete RGB565 byte string into the panel window.

        ``pixels`` must already hold the whole frame. The window commands, 0x2C
        and the pixel stream have to follow each other without an appreciable
        gap: 0x2C starts the RAM write, and a slow conversion or a scheduler
        hiccup before the first pixel is what makes a full frame come out
        scrolled or torn while a solid fill -- which is invariant to any of that
        -- still looks perfect. Preparing the payload first removes the gap.
        """
        # Resolve the GRAM origin here so every write path (fills included)
        # honours the same window the probe selected.
        x = self._xoff if x is None else x
        y = self._yoff if y is None else y
        end_x, end_y = x + self.size - 1, y + self.size - 1
        self.command(0x2A, [x >> 8, x & 255, end_x >> 8, end_x & 255])
        self.command(0x2B, [y >> 8, y & 255, end_y >> 8, end_y & 255])
        self.command(0x2C)
        self.dc.on()
        self._write_pixels(pixels)

    def fill(self, color):
        self._blit(bytes([(color >> 8) & 0xFF, color & 0xFF]) * (self.size * self.size))

    def show(self, image):
        from PIL import Image
        image = image.resize((self.size, self.size), Image.Resampling.LANCZOS)
        if self.rotation:
            image = image.rotate(self.rotation, expand=False)
        # Convert fully *before* opening the RAM-write window so the pixel
        # stream starts the instant 0x2C is sent (see _blit).
        frame = rgb565(image)
        if not getattr(self, '_frame_logged', False):
            LOG.info('display: first frame written (%d bytes)', len(frame))
            self._frame_logged = True
        self._blit(frame)

    def close(self):
        if hasattr(self, 'light'):
            try: self.light.off()
            except Exception: pass
        if self.bus is not None:
            try:
                self.bus.close()
            except Exception:
                pass
        for device in reversed(self.devices):
            device.close()
        if self.factory is not None:
            self.factory.close()


def rgb565(image):
    from PIL import Image, ImageChops
    r, g, b = image.convert('RGB').split()
    high = ImageChops.add(r.point(lambda v: v & 248), g.point(lambda v: v >> 5))
    low = ImageChops.add(g.point(lambda v: (v & 28) << 3), b.point(lambda v: v >> 3))
    return Image.merge('LA', (high, low)).tobytes()
