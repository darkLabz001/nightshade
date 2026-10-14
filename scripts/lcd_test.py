#!/usr/bin/env python3
"""Standalone Waveshare 1.44-inch (ST7735S, 128x128) LCD HAT panel test.

Drives the panel directly, bypassing Nightshade, to isolate the glass from the
application. Cycles solid colours and a test pattern, then leaves the pattern
up.

The panel is driven by the same fast GPIO bit-bang helper the app uses
(``nightshade/bitbang.py``): the bcm2835 hardware SPI peripheral does not drive
this HAT, so software bit-banding on the GPIO lines is the proven method (see
``docs/validation.md``).

Stop Nightshade first so the GPIO lines are free:

    sudo systemctl stop nightshade
    /usr/bin/python3 /home/kali/nightshade/scripts/lcd_test.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nightshade import bitbang

DC, RST, BL = 25, 27, 24
WIDTH = HEIGHT = 128
X_OFF, Y_OFF = 1, 2   # GRAM origin of the visible window

# RaspyJack's LCD_1in44 sequence -- the known-good reference for this HAT.
INIT = [
    (0xB1, [0x01, 0x2C, 0x2D]), (0xB2, [0x01, 0x2C, 0x2D]),
    (0xB3, [0x01, 0x2C, 0x2D, 0x01, 0x2C, 0x2D]), (0xB4, [0x07]),
    (0xC0, [0xA2, 0x02, 0x84]), (0xC1, [0xC5]), (0xC2, [0x0A, 0x00]),
    (0xC3, [0x8A, 0x2A]), (0xC4, [0x8A, 0xEE]), (0xC5, [0x0E]),
    (0xE0, [0x0f, 0x1a, 0x0f, 0x18, 0x2f, 0x28, 0x20, 0x22,
            0x1f, 0x1b, 0x23, 0x37, 0x00, 0x07, 0x02, 0x10]),
    (0xE1, [0x0f, 0x1b, 0x0f, 0x17, 0x33, 0x2c, 0x29, 0x2e,
            0x30, 0x30, 0x39, 0x3f, 0x00, 0x07, 0x03, 0x10]),
    (0xF0, [0x01]), (0xF6, [0x00]), (0x3A, [0x05]),
]


class Panel:
    def __init__(self):
        self.bus = bitbang.load()
        if self.bus is None:
            raise SystemExit('could not load the bit-bang helper; build '
                             'nightshade/nslcd_bitbang.c (deploy/install.sh)')
        self.bus.pin(BL, 1)
        self.bus.pin(RST, 1); time.sleep(.1)
        self.bus.pin(RST, 0); time.sleep(.1)
        self.bus.pin(RST, 1); time.sleep(.1)
        for register, data in INIT:
            self.command(register, data)
        self.command(0x36, [0x68]); time.sleep(.2)   # MADCTL: BGR + MY|MV
        self.command(0x11); time.sleep(.12)          # Sleep out
        self.command(0x29); time.sleep(.12)          # Display on

    def command(self, register, data=None):
        self.bus.write(0, [register])
        if data:
            self.bus.write(1, data)

    def show_rgb565(self, pixels):
        self.command(0x2A, [X_OFF >> 8, X_OFF & 255,
                            (X_OFF + WIDTH - 1) >> 8, (X_OFF + WIDTH - 1) & 255])
        self.command(0x2B, [Y_OFF >> 8, Y_OFF & 255,
                            (Y_OFF + HEIGHT - 1) >> 8, (Y_OFF + HEIGHT - 1) & 255])
        self.command(0x2C)
        self.bus.write(1, pixels)

    def fill(self, color):
        self.show_rgb565(bytes([(color >> 8) & 0xFF, color & 0xFF]) * WIDTH * HEIGHT)

    def play(self):
        for name, color in [('red', 0xF800), ('green', 0x07E0), ('blue', 0x001F),
                            ('white', 0xFFFF), ('black', 0x0000)]:
            print('solid', name, flush=True)
            self.fill(color); time.sleep(1.5)
        print('test pattern', flush=True)
        self.show_rgb565(rgb565(test_pattern()))
        print('left showing test pattern', flush=True)

    def close(self):
        try:
            self.bus.pin(BL, 0)
            self.bus.close()
        except Exception:
            pass


def rgb565(image):
    from PIL import Image, ImageChops
    r, g, b = image.convert('RGB').split()
    high = ImageChops.add(r.point(lambda v: v & 248), g.point(lambda v: v >> 5))
    low = ImageChops.add(g.point(lambda v: (v & 28) << 3), b.point(lambda v: v >> 3))
    return Image.merge('LA', (high, low)).tobytes()


def test_pattern():
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (WIDTH, HEIGHT), 'black')
    draw = ImageDraw.Draw(image)
    bars = ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue', 'black']
    width = WIDTH // len(bars)
    for index, color in enumerate(bars):
        draw.rectangle([index * width, 0, (index + 1) * width, HEIGHT], fill=color)
    draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline='orange', width=4)
    return image


def main():
    panel = Panel()
    try:
        panel.play()
    finally:
        panel.close()


if __name__ == '__main__':
    main()
