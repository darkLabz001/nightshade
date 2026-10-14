/* nslcd_bitbang.c - fast software SPI (bit-bang) for the Waveshare LCD HAT.
 *
 * Why this exists
 * ---------------
 * The bcm2835 hardware SPI peripheral does not drive this panel. Every
 * combination of clock (62.5 kHz .. 8 MHz), SPI mode (0..3) and chip-select
 * strategy (kernel CS, held low, SPI_NO_CS) leaves the glass white, while the
 * very same bytes written by toggling the GPIO lines produce a pixel-perfect
 * image. The peripheral is genuinely clocking (transfer timing matches the
 * requested rate) and CS can be held low, so the fault is in the signal the
 * hardware SPI emits, not in the wiring or the panel.
 *
 * Python-level bit-banging is correct but ~5 s per 128x128 frame, far too slow
 * for an interface. This helper writes the GPIO registers directly through
 * /dev/gpiomem, which reaches ~75-90 fps for a full frame.
 *
 * Wiring (BCM): MOSI 10, SCLK 11, DC 25, RST 27, BL 24, CS 8.
 */
#include <stdint.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>

/* Offsets into the GPIO block exposed by /dev/gpiomem. */
#define GPFSEL0 0
#define GPSET0  7
#define GPCLR0  10

#define PIN_MOSI 10
#define PIN_SCLK 11
#define PIN_DC   25
#define PIN_RST  27
#define PIN_BL   24
#define PIN_CS   8

static volatile uint32_t *gpio = 0;
static volatile uint32_t *gset;
static volatile uint32_t *gclr;

static void set_output(int n) {
    int reg = n / 10;
    int shift = (n % 10) * 3;
    uint32_t v = gpio[reg];
    v &= ~(7u << shift);
    v |= (1u << shift);          /* ALT0 = output */
    gpio[reg] = v;
}

/* Map /dev/gpiomem and take over the display lines.
 *
 * CS is driven low and kept there: the ST7735 wants chip select asserted for
 * the whole command/parameter/pixel stream. Releasing it between writes is one
 * of the things that only the vendor/RaspyJack drivers may get away with.
 * Returns 0 on success, negative on failure. */
int bb_init(void) {
    int fd = open("/dev/gpiomem", O_RDWR | O_SYNC);
    if (fd < 0) return -1;
    void *m = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (m == MAP_FAILED) return -2;
    gpio = (volatile uint32_t *)m;
    gset = gpio + GPSET0;
    gclr = gpio + GPCLR0;
    int pins[6] = { PIN_MOSI, PIN_SCLK, PIN_DC, PIN_RST, PIN_BL, PIN_CS };
    for (int i = 0; i < 6; i++) set_output(pins[i]);
    *gclr = (1u << PIN_CS);      /* CS low                     */
    *gset = (1u << PIN_RST);     /* RST high (idle)            */
    *gclr = (1u << PIN_BL);      /* backlight off until asked  */
    return 0;
}

/* Drive an arbitrary display line. Used for RST/BL/DC by the caller. */
void bb_pin(int n, int v) {
    if (v) *gset = (1u << n);
    else   *gclr = (1u << n);
}

/* Shift out len bytes with the D/C line at level dc (1=data, 0=command). */
void bb_write(int dc, const unsigned char *buf, int len) {
    volatile uint32_t *set = gset;
    volatile uint32_t *clr = gclr;
    const uint32_t mosi = (1u << PIN_MOSI);
    const uint32_t sclk = (1u << PIN_SCLK);
    if (dc) *set = (1u << PIN_DC); else *clr = (1u << PIN_DC);
    for (int i = 0; i < len; i++) {
        unsigned char b = buf[i];
        for (int k = 7; k >= 0; k--) {
            if ((b >> k) & 1) *set = mosi; else *clr = mosi;
            *set = sclk;
            *clr = sclk;
        }
    }
}
