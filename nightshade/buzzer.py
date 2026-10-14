"""Optional piezo buzzer on GPIO 18.

Wire a passive piezo between GPIO 18 and GND. Every sound runs
on a daemon thread so the UI never blocks; with no buzzer wired
the PWM is silent and harmless. The lgpio pin factory is shared
with the rest of the HAT code (gpiozero talks to the same chip).
"""
import threading
import time

PIN = 18

_led = None
_error = None


def _device():
    global _led, _error
    if _led is None and _error is None:
        try:
            from gpiozero import PWMLED
            from .hardware import _pin_factory
            _led = PWMLED(PIN, frequency=2000,
                          pin_factory=_pin_factory())
        except Exception as exc:
            _error = exc
            _led = None
    return _led


def _tone(freq, dur, duty=0.5):
    led = _device()
    if led is None:
        return
    try:
        led.frequency = freq
        led.value = duty
        time.sleep(dur)
        led.value = 0
    except Exception:
        pass


def click():
    """Short tick for any key press."""
    threading.Thread(target=_tone, args=(2200, 0.04),
                     daemon=True).start()


def chime():
    """Two-note chime when a job finishes."""
    def play():
        _tone(660, 0.09)
        time.sleep(0.03)
        _tone(990, 0.16)
    threading.Thread(target=play, daemon=True).start()


def alert():
    """Triple beep for a captured handshake."""
    def play():
        for _ in range(3):
            _tone(1320, 0.08)
            time.sleep(0.08)
    threading.Thread(target=play, daemon=True).start()
