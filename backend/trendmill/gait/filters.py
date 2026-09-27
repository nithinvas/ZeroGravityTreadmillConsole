"""Causal filters for live signals.

A 2nd-order Butterworth low-pass, applied sample by sample. It delays the signal
by a constant amount at low frequencies; the gait engine subtracts that delay from
every event time.
"""

from __future__ import annotations

import math


class Biquad:
    """Direct form I biquad."""

    def __init__(self, b: tuple[float, float, float], a: tuple[float, float]) -> None:
        self.b0, self.b1, self.b2 = b
        self.a1, self.a2 = a
        self.reset()

    def reset(self, value: float | None = None) -> None:
        """Clears history, optionally settling at a steady `value` to avoid a start-up transient."""
        v = 0.0 if value is None else value
        self.x1 = self.x2 = v
        self.y1 = self.y2 = v
        self._primed = value is not None

    def __call__(self, x: float) -> float:
        if not self._primed:
            self.reset(x)
        y = self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2 - self.a1 * self.y1 - self.a2 * self.y2
        self.x2, self.x1 = self.x1, x
        self.y2, self.y1 = self.y1, y
        return y


def butterworth_lowpass(sample_rate_hz: float, cutoff_hz: float) -> Biquad:
    """2nd-order Butterworth low-pass (bilinear transform, Q = 1/sqrt 2)."""
    if not 0 < cutoff_hz < sample_rate_hz / 2:
        raise ValueError("cutoff must be between 0 and half the sample rate")
    w0 = 2 * math.pi * cutoff_hz / sample_rate_hz
    alpha = math.sin(w0) / math.sqrt(2)
    cos_w0 = math.cos(w0)
    a0 = 1 + alpha
    b = ((1 - cos_w0) / 2 / a0, (1 - cos_w0) / a0, (1 - cos_w0) / 2 / a0)
    a = (-2 * cos_w0 / a0, (1 - alpha) / a0)
    return Biquad(b, a)


def butterworth_delay_s(cutoff_hz: float) -> float:
    """Group delay of the 2nd-order Butterworth at low frequency: sqrt(2) / (2 pi fc)."""
    return math.sqrt(2) / (2 * math.pi * cutoff_hz)
