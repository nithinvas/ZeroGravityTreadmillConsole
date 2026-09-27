"""Per-sample timestamps for a stream that carries none.

Four samples arrive together in each USB transfer. Stamping all four with the
arrival time would quantise every gait timing to the transfer interval, so the
samples are spread along a smoothed sample clock instead:

* it starts at the nominal period, then follows the period actually observed;
* each transfer pulls the clock gently towards its arrival time, absorbing USB
  delivery jitter;
* a gap too large to be jitter (a stall, a replug) snaps it back to real time;
* it never runs backwards, because downstream code measures intervals by
  subtraction.

Ported from the Android app's `FrameSync`, which carries the same tests, with one
change: times are integer microseconds, so a 1.024 ms spacing is not rounded to 1 ms.
"""

from __future__ import annotations


class SampleClock:
    #: Weight of each new observation in the mean sample period, once warmed up.
    PERIOD_SMOOTHING = 0.05
    #: Fraction of the arrival-time error corrected per transfer.
    CLOCK_CORRECTION = 0.1
    #: An inter-arrival gap this many times the mean period is a stall, not jitter.
    STALL_FACTOR = 4.0
    #: Clock error beyond this is a stall or replug; resynchronise to arrival.
    SNAP_THRESHOLD_US = 100_000.0
    #: Observations before the mean is trusted enough to reject stalls.
    WARMUP_OBSERVATIONS = 16
    #: Rejections in a row that mean the rate really changed, rather than stalled.
    MAX_REJECTIONS_IN_A_ROW = 8

    def __init__(self, nominal_period_us: float) -> None:
        if nominal_period_us <= 0:
            raise ValueError("nominal period must be positive")
        self._nominal = nominal_period_us
        self.reset()

    def reset(self) -> None:
        """Forgets all history. Call when a new segment starts."""
        self._clock: float | None = None
        self._last_arrival: int | None = None
        self._mean = self._nominal
        self._observations = 0
        self._rejected_in_a_row = 0

    @property
    def observed_period_us(self) -> float:
        return self._mean

    def stamp(self, samples: int, arrival_us: int) -> list[int]:
        """Timestamps for `samples` samples whose transfer arrived at `arrival_us`.

        The newest sample is placed at (roughly) the arrival time: the firmware
        flushes as soon as the last sample of a packet is read, so USB latency is
        the only offset, and it is small and constant.
        """
        if samples <= 0:
            raise ValueError("samples must be positive")
        self._learn_period(samples, arrival_us)

        period = self._mean
        start = self._clock
        if start is None:
            target = float(arrival_us)
        else:
            predicted = start + period * samples
            error = arrival_us - predicted
            if abs(error) > self.SNAP_THRESHOLD_US:
                target = float(arrival_us)
            else:
                target = predicted + error * self.CLOCK_CORRECTION
        end = target if start is None else max(target, start)

        # First transfer, or just snapped: lay the samples out backwards from arrival.
        if start is None or end - start > period * samples + self.SNAP_THRESHOLD_US:
            begin = end - period * samples
        else:
            begin = start
        step = (end - begin) / samples
        self._clock = end
        return [round(begin + step * (i + 1)) for i in range(samples)]

    def _learn_period(self, samples: int, arrival_us: int) -> None:
        previous = self._last_arrival
        self._last_arrival = arrival_us
        if previous is None:
            return
        observed = (arrival_us - previous) / samples
        mean = self._mean
        warmed_up = self._observations >= self.WARMUP_OBSERVATIONS
        is_stall = observed > mean * self.STALL_FACTOR

        if warmed_up and is_stall:
            # A stall is not a sample period, so it stays out of the average -- unless
            # it keeps happening, which means the stream has genuinely slowed.
            self._rejected_in_a_row += 1
            if self._rejected_in_a_row >= self.MAX_REJECTIONS_IN_A_ROW:
                self._observations = 0
                self._mean = observed
                self._rejected_in_a_row = 0
            return

        self._rejected_in_a_row = 0
        # Early observations outweigh the nominal seed: a running mean at first,
        # settling into exponential smoothing.
        self._observations += 1
        weight = max(self.PERIOD_SMOOTHING, 1.0 / self._observations)
        self._mean = mean + (observed - mean) * weight
