"""Stream health: counters, observed rate, per-channel statistics and warnings.

Everything here is plain bookkeeping over timestamps and values, so it is tested
without any USB hardware.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import asdict, dataclass

from treadmill.protocol.constants import CHANNEL_NAMES, CHANNELS

US_PER_S = 1_000_000


@dataclass
class Counters:
    transfers: int = 0
    bytes: int = 0
    samples: int = 0
    short_transfers: int = 0
    out_of_range: int = 0
    timeouts: int = 0
    reconnects: int = 0
    queue_overflows: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


class RateMeter:
    """Samples per second over a sliding window, plus the whole-segment average.

    A rate is "samples delivered after the first transfer in the span, divided by
    the span": the first transfer's samples were taken before the span began.
    """

    def __init__(self, window_us: int = US_PER_S) -> None:
        self._window_us = window_us
        self._events: deque[tuple[int, int]] = deque()
        self._first: tuple[int, int] | None = None
        self._last_us = 0
        self._total = 0

    def reset(self) -> None:
        self._events.clear()
        self._first = None
        self._last_us = 0
        self._total = 0

    def add(self, t_us: int, samples: int) -> None:
        if self._first is None:
            self._first = (t_us, samples)
        self._last_us = t_us
        self._total += samples
        self._events.append((t_us, samples))
        cutoff = t_us - self._window_us
        # Keep one event at or before the cutoff: it anchors the start of the window.
        while len(self._events) > 1 and self._events[1][0] <= cutoff:
            self._events.popleft()

    @property
    def rate_hz(self) -> float | None:
        """Samples/s over the last window, or None until two transfers have arrived."""
        if len(self._events) < 2:
            return None
        span = self._events[-1][0] - self._events[0][0]
        if span <= 0:
            return None
        delivered = sum(n for _, n in self._events) - self._events[0][1]
        return delivered * US_PER_S / span

    @property
    def session_rate_hz(self) -> float | None:
        if self._first is None or self._last_us <= self._first[0]:
            return None
        return (self._total - self._first[1]) * US_PER_S / (self._last_us - self._first[0])

    @property
    def elapsed_s(self) -> float:
        if self._first is None:
            return 0.0
        return (self._last_us - self._first[0]) / US_PER_S


@dataclass(frozen=True)
class ChannelStats:
    name: str
    last: int
    mean: float
    minimum: int
    maximum: int
    std: float
    #: Mean absolute change between consecutive samples: the channel's noise floor.
    step_noise: float


class ChannelWindow:
    """The last `window_us` of values for one channel."""

    def __init__(self, name: str, window_us: int = US_PER_S) -> None:
        self.name = name
        self._window_us = window_us
        self._values: deque[tuple[int, int]] = deque()

    def reset(self) -> None:
        self._values.clear()

    def add(self, t_us: int, value: int) -> None:
        self._values.append((t_us, value))
        cutoff = t_us - self._window_us
        while self._values and self._values[0][0] <= cutoff:
            self._values.popleft()

    def __len__(self) -> int:
        return len(self._values)

    def stats(self) -> ChannelStats | None:
        if not self._values:
            return None
        values = [v for _, v in self._values]
        steps = [abs(b - a) for a, b in zip(values, values[1:], strict=False)]
        return ChannelStats(
            name=self.name,
            last=values[-1],
            mean=statistics.fmean(values),
            minimum=min(values),
            maximum=max(values),
            std=statistics.pstdev(values) if len(values) > 1 else 0.0,
            step_noise=statistics.fmean(steps) if steps else 0.0,
        )


def channels_look_identical(stats: list[ChannelStats], min_samples: int, samples: int) -> bool:
    """True when the four channels are indistinguishable, i.e. one channel sent four times.

    This is the signature of the firmware packing bug (`payload_index += 1`): every
    value in a packet is channel 0, so the four "channels" are consecutive samples
    of one cell and their means coincide to within that cell's own noise. Real
    load cells have zero offsets hundreds of thousands of counts apart.
    """
    if samples < min_samples or len(stats) != CHANNELS:
        return False
    means = [s.mean for s in stats]
    spread = max(means) - min(means)
    noise = statistics.median(s.step_noise for s in stats)
    return spread <= 5.0 * noise + 2.0


@dataclass(frozen=True)
class StreamWarning:
    code: str
    message: str


class StreamHealth:
    """Everything the diagnostics screen and the health log line report."""

    RATE_TOLERANCE = 0.02
    RATE_CHECK_AFTER_S = 5.0
    IDENTICAL_MIN_SAMPLES = 50

    def __init__(self, nominal_rate_hz: float) -> None:
        self.nominal_rate_hz = nominal_rate_hz
        self.counters = Counters()
        self.rate = RateMeter()
        self.channels = [ChannelWindow(name) for name in CHANNEL_NAMES]
        self.max_queue_depth = 0

    def reset_segment(self) -> None:
        """A new connection: rates and windows restart; lifetime counters do not."""
        self.rate.reset()
        for window in self.channels:
            window.reset()

    def add_sample(self, t_us: int, values: tuple[int, int, int, int]) -> None:
        for window, value in zip(self.channels, values, strict=True):
            window.add(t_us, value)

    def channel_stats(self) -> list[ChannelStats]:
        return [s for s in (w.stats() for w in self.channels) if s is not None]

    def warnings(self, streaming: bool) -> list[StreamWarning]:
        found: list[StreamWarning] = []
        stats = self.channel_stats()
        if streaming and channels_look_identical(
            stats, self.IDENTICAL_MIN_SAMPLES, min(len(w) for w in self.channels)
        ):
            found.append(StreamWarning(
                "channels_identical",
                "All four channels show the same signal. The firmware may be sending one "
                "channel only (the payload_index += 1 packing bug).",
            ))
        observed = self.rate.rate_hz
        if streaming and observed is not None and self.rate.elapsed_s >= self.RATE_CHECK_AFTER_S:
            deviation = abs(observed - self.nominal_rate_hz) / self.nominal_rate_hz
            if deviation > self.RATE_TOLERANCE:
                found.append(StreamWarning(
                    "rate_mismatch",
                    f"Observed {observed:.1f} samples/s per channel, but the configured "
                    f"nominal rate is {self.nominal_rate_hz:g}. Check the ADC clock and OSR.",
                ))
        if self.counters.short_transfers:
            found.append(StreamWarning(
                "short_transfers",
                f"{self.counters.short_transfers} USB transfers were not 64 bytes and were discarded.",
            ))
        if self.counters.out_of_range:
            found.append(StreamWarning(
                "out_of_range",
                f"{self.counters.out_of_range} values were outside the 24-bit ADC range.",
            ))
        if self.counters.queue_overflows:
            found.append(StreamWarning(
                "queue_overflow",
                f"{self.counters.queue_overflows} transfers were lost because processing fell behind.",
            ))
        return found


def finite_or_none(value: float | None) -> float | None:
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    return value
