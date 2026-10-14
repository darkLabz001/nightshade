"""Fast software-SPI transport for the Waveshare LCD HAT.

The bcm2835 hardware SPI peripheral does not drive this panel: every clock,
mode and chip-select combination leaves the glass white, while the same bytes
toggled out on the GPIO lines are pixel-perfect (see docs/validation.md). The
display is therefore driven by ``nslcd_bitbang.c``, a tiny helper that writes
the GPIO registers directly. Python bit-banging is correct but ~5 s per frame;
the helper reaches ~75-90 fps for a full 128x128 frame.

The shared object is built at install time (see deploy/install.sh) because the
service runs with ``ProtectHome=read-only`` and cannot compile into its own
package directory. :func:`load` still falls back to compiling into a writable
cache directory for ad-hoc/manual runs.
"""
import ctypes
import logging
import os
import subprocess
import tempfile

LOG = logging.getLogger('nightshade')

_HERE = os.path.dirname(os.path.abspath(__file__))
_SOURCE = os.path.join(_HERE, 'nslcd_bitbang.c')
_SO_NAME = 'libnslcd_bitbang.so'


def _candidates():
    # Env override first (handy for testing), then the package dir where
    # install.sh leaves it, then writable scratch locations.
    paths = []
    override = os.environ.get('NIGHTSHADE_BITBANG_SO')
    if override:
        paths.append(override)
    paths.append(os.path.join(_HERE, _SO_NAME))
    paths.append('/opt/nightshade/nightshade/' + _SO_NAME)
    paths.append('/run/nightshade/' + _SO_NAME)
    paths.append(os.path.join(tempfile.gettempdir(), _SO_NAME))
    return paths


def _compile(out_path):
    for compiler in ('cc', 'gcc'):
        try:
            subprocess.check_call(
                [compiler, '-O3', '-shared', '-fPIC', '-o', out_path, _SOURCE],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return out_path
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError as exc:
            LOG.warning('display: %s failed to build bit-bang helper (%s)',
                        compiler, exc)
            return None
    return None


def load():
    """Return a ready :class:`BitBang`, or ``None`` if it cannot be provided."""
    if not os.path.exists(_SOURCE):
        LOG.warning('display: bit-bang source %s missing', _SOURCE)
    for path in _candidates():
        if os.path.exists(path):
            try:
                return BitBang(path)
            except OSError as exc:
                LOG.warning('display: %s unusable (%s)', path, exc)
    # Nothing prebuilt: try to compile somewhere writable.
    for path in _candidates()[1:]:
        try:
            if _compile(path) and os.path.exists(path):
                LOG.info('display: built bit-bang helper at %s', path)
                return BitBang(path)
        except OSError as exc:
            LOG.warning('display: could not build bit-bang helper at %s (%s)',
                        path, exc)
    return None


class BitBang:
    """A spidev-like transport backed by direct GPIO register writes.

    Only the small surface the driver needs is implemented: ``write(dc, data)``
    to shift out a command or data payload, ``pin`` to drive RST/BL/DC, and
    ``close``.
    """

    def __init__(self, path):
        self.path = path
        self._lib = ctypes.CDLL(path)
        self._lib.bb_init.restype = ctypes.c_int
        self._lib.bb_pin.argtypes = [ctypes.c_int, ctypes.c_int]
        self._lib.bb_pin.restype = None
        self._lib.bb_write.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        self._lib.bb_write.restype = None
        rc = self._lib.bb_init()
        if rc != 0:
            raise OSError('bb_init failed (rc=%d) opening /dev/gpiomem' % rc)
        # Kept for interface parity with spidev; the helper has no clock
        # divider, so these are informational only.
        self.max_speed_hz = 0
        self.mode = 0

    def pin(self, bcm, value):
        self._lib.bb_pin(int(bcm), 1 if value else 0)

    def write(self, dc, data):
        buf = bytes(data)
        if buf:
            self._lib.bb_write(1 if dc else 0, buf, len(buf))

    def close(self):
        # Nothing to release: the pins stay as GPIO outputs, which is exactly
        # what the next run wants.
        pass
