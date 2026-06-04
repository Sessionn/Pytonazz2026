from __future__ import annotations

import math
import threading
from array import array

import discord

_SAMPLE_RATE = 48_000.0
_CHANNELS = 2
_PCM_MIN = -32768
_PCM_MAX = 32767
_BIQUAD_Q = 0.7071067811865476


def _clamp_sample(value: float) -> int:
    if value < _PCM_MIN:
        return _PCM_MIN
    if value > _PCM_MAX:
        return _PCM_MAX
    return int(round(value))


class _Biquad:
    def __init__(self):
        self.b0 = 1.0
        self.b1 = 0.0
        self.b2 = 0.0
        self.a1 = 0.0
        self.a2 = 0.0
        self.z1_l = 0.0
        self.z2_l = 0.0
        self.z1_r = 0.0
        self.z2_r = 0.0
        self.enabled = False

    def reset(self) -> None:
        self.z1_l = 0.0
        self.z2_l = 0.0
        self.z1_r = 0.0
        self.z2_r = 0.0

    def _apply_coeffs(self, b0: float, b1: float, b2: float, a0: float, a1: float, a2: float) -> None:
        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0
        self.enabled = True

    def _disable(self) -> None:
        self.enabled = False
        self.b0 = 1.0
        self.b1 = 0.0
        self.b2 = 0.0
        self.a1 = 0.0
        self.a2 = 0.0
        self.reset()

    def configure(self, kind: str, cutoff_hz: float, gain_db: float = 0.0, q: float = _BIQUAD_Q) -> None:
        cutoff = max(20.0, min((_SAMPLE_RATE / 2.0) - 100.0, float(cutoff_hz)))
        if kind in {"lowpass", "highpass"} and cutoff_hz <= 0.0:
            self._disable()
            return
        if kind in {"peaking", "low_shelf", "high_shelf"} and abs(gain_db) < 0.01:
            self._disable()
            return

        w0 = 2.0 * math.pi * cutoff / _SAMPLE_RATE
        cos_w0 = math.cos(w0)
        sin_w0 = math.sin(w0)
        alpha = sin_w0 / (2.0 * max(1e-6, q))

        if kind == "lowpass":
            b0 = (1.0 - cos_w0) / 2.0
            b1 = 1.0 - cos_w0
            b2 = (1.0 - cos_w0) / 2.0
            a0 = 1.0 + alpha
            a1 = -2.0 * cos_w0
            a2 = 1.0 - alpha
            self._apply_coeffs(b0, b1, b2, a0, a1, a2)
            return

        if kind == "highpass":
            b0 = (1.0 + cos_w0) / 2.0
            b1 = -(1.0 + cos_w0)
            b2 = (1.0 + cos_w0) / 2.0
            a0 = 1.0 + alpha
            a1 = -2.0 * cos_w0
            a2 = 1.0 - alpha
            self._apply_coeffs(b0, b1, b2, a0, a1, a2)
            return

        a = 10.0 ** (gain_db / 40.0)

        if kind == "peaking":
            b0 = 1.0 + (alpha * a)
            b1 = -2.0 * cos_w0
            b2 = 1.0 - (alpha * a)
            a0 = 1.0 + (alpha / a)
            a1 = -2.0 * cos_w0
            a2 = 1.0 - (alpha / a)
            self._apply_coeffs(b0, b1, b2, a0, a1, a2)
            return

        shelf_s = 1.0
        shelf_alpha = (sin_w0 / 2.0) * math.sqrt((a + (1.0 / a)) * ((1.0 / shelf_s) - 1.0) + 2.0)
        beta = 2.0 * math.sqrt(a) * shelf_alpha

        if kind == "low_shelf":
            b0 = a * ((a + 1.0) - ((a - 1.0) * cos_w0) + beta)
            b1 = 2.0 * a * ((a - 1.0) - ((a + 1.0) * cos_w0))
            b2 = a * ((a + 1.0) - ((a - 1.0) * cos_w0) - beta)
            a0 = (a + 1.0) + ((a - 1.0) * cos_w0) + beta
            a1 = -2.0 * ((a - 1.0) + ((a + 1.0) * cos_w0))
            a2 = (a + 1.0) + ((a - 1.0) * cos_w0) - beta
            self._apply_coeffs(b0, b1, b2, a0, a1, a2)
            return

        if kind == "high_shelf":
            b0 = a * ((a + 1.0) + ((a - 1.0) * cos_w0) + beta)
            b1 = -2.0 * a * ((a - 1.0) + ((a + 1.0) * cos_w0))
            b2 = a * ((a + 1.0) + ((a - 1.0) * cos_w0) - beta)
            a0 = (a + 1.0) - ((a - 1.0) * cos_w0) + beta
            a1 = 2.0 * ((a - 1.0) - ((a + 1.0) * cos_w0))
            a2 = (a + 1.0) - ((a - 1.0) * cos_w0) - beta
            self._apply_coeffs(b0, b1, b2, a0, a1, a2)
            return

        self._disable()

    def process_left(self, sample: float) -> float:
        if not self.enabled:
            return sample
        out = sample * self.b0 + self.z1_l
        self.z1_l = sample * self.b1 + self.z2_l - self.a1 * out
        self.z2_l = sample * self.b2 - self.a2 * out
        return out

    def process_right(self, sample: float) -> float:
        if not self.enabled:
            return sample
        out = sample * self.b0 + self.z1_r
        self.z1_r = sample * self.b1 + self.z2_r - self.a1 * out
        self.z2_r = sample * self.b2 - self.a2 * out
        return out


class LivePCMTransform(discord.AudioSource):
    """Volume, tone filters ed EQ live su PCM stereo 48kHz senza riavviare FFmpeg."""

    def __init__(self, source: discord.AudioSource, volume: float = 0.5):
        self.source = source
        self._lock = threading.Lock()
        self._source_ended = False
        self._output_chunk_frames = 960
        self._pcm_buffer = array("h")
        self._buffer_cursor = 0.0

        self._target_volume = float(volume)
        self._current_volume = float(volume)

        self._target_highpass_hz = 0.0
        self._current_highpass_hz = 0.0
        self._target_lowpass_hz = 20_000.0
        self._current_lowpass_hz = 20_000.0
        self._target_highpass_mix = 0.0
        self._current_highpass_mix = 0.0
        self._target_lowpass_mix = 0.0
        self._current_lowpass_mix = 0.0

        self._target_low_gain = 0.0
        self._current_low_gain = 0.0
        self._target_mid_gain = 0.0
        self._current_mid_gain = 0.0
        self._target_high_gain = 0.0
        self._current_high_gain = 0.0
        self._target_presence_gain = 0.0
        self._current_presence_gain = 0.0

        self._target_preset_highpass_hz = 0.0
        self._current_preset_highpass_hz = 0.0
        self._target_preset_lowpass_hz = 20_000.0
        self._current_preset_lowpass_hz = 20_000.0
        self._target_preset_highpass_mix = 0.0
        self._current_preset_highpass_mix = 0.0
        self._target_preset_lowpass_mix = 0.0
        self._current_preset_lowpass_mix = 0.0

        self._target_preset_low_gain = 0.0
        self._current_preset_low_gain = 0.0
        self._target_preset_mid_gain = 0.0
        self._current_preset_mid_gain = 0.0
        self._target_preset_high_gain = 0.0
        self._current_preset_high_gain = 0.0
        self._target_pan_rate_hz = 0.0
        self._current_pan_rate_hz = 0.0
        self._target_pan_depth = 0.0
        self._current_pan_depth = 0.0
        self._pan_phase = 0.0
        self._target_playback_rate = 1.0
        self._current_playback_rate = 1.0
        self._target_reverb_mix = 0.0
        self._current_reverb_mix = 0.0
        self._target_reverb_decay = 0.0
        self._current_reverb_decay = 0.0
        self._reverb_delay_l = [0.0] * int(_SAMPLE_RATE * 0.11)
        self._reverb_delay_r = [0.0] * int(_SAMPLE_RATE * 0.17)
        self._reverb_pos_l = 0
        self._reverb_pos_r = 0

        self._highpass = _Biquad()
        self._lowpass = _Biquad()
        self._preset_highpass = _Biquad()
        self._preset_lowpass = _Biquad()
        self._low_eq = _Biquad()
        self._mid_eq = _Biquad()
        self._high_eq = _Biquad()
        self._presence_eq = _Biquad()
        self._preset_low_eq = _Biquad()
        self._preset_mid_eq = _Biquad()
        self._preset_high_eq = _Biquad()

    @staticmethod
    def _slew(current: float, target: float, amount: float) -> float:
        delta = target - current
        if abs(delta) < 1e-4:
            return target
        return current + (delta * amount)

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        cleanup = getattr(self.source, "cleanup", None)
        if callable(cleanup):
            cleanup()

    def _append_pcm_chunk(self, chunk: bytes) -> int:
        pcm = array("h")
        pcm.frombytes(chunk)
        self._pcm_buffer.extend(pcm)
        return len(pcm) // _CHANNELS

    def _pull_source_chunk(self) -> int:
        if self._source_ended:
            return 0
        chunk = self.source.read()
        if not chunk:
            self._source_ended = True
            return 0
        frames = self._append_pcm_chunk(chunk)
        if frames > 0:
            self._output_chunk_frames = frames
        return frames

    def _buffer_frames(self) -> int:
        return len(self._pcm_buffer) // _CHANNELS

    def _ensure_frames_for_rate(self, rate: float) -> int:
        if self._buffer_frames() == 0:
            self._pull_source_chunk()
        frames_out = max(1, self._output_chunk_frames)
        needed = self._buffer_cursor + (frames_out * max(0.5, rate)) + 2.0
        while self._buffer_frames() < needed and not self._source_ended:
            if self._pull_source_chunk() == 0:
                break
        return frames_out

    def _sample_at(self, frame_index: float) -> tuple[float, float]:
        total_frames = self._buffer_frames()
        if total_frames <= 0:
            return 0.0, 0.0
        if total_frames == 1:
            return float(self._pcm_buffer[0]), float(self._pcm_buffer[1])

        clamped = max(0.0, min((total_frames - 1) - 1e-6, frame_index))
        base = int(clamped)
        frac = clamped - base
        next_frame = min(base + 1, total_frames - 1)
        left_a = float(self._pcm_buffer[(base * _CHANNELS)])
        right_a = float(self._pcm_buffer[(base * _CHANNELS) + 1])
        left_b = float(self._pcm_buffer[(next_frame * _CHANNELS)])
        right_b = float(self._pcm_buffer[(next_frame * _CHANNELS) + 1])
        left = left_a + ((left_b - left_a) * frac)
        right = right_a + ((right_b - right_a) * frac)
        return left, right

    def _trim_buffer(self) -> None:
        drop_frames = max(0, int(self._buffer_cursor) - 2)
        if drop_frames <= 0:
            return
        drop_samples = drop_frames * _CHANNELS
        del self._pcm_buffer[:drop_samples]
        self._buffer_cursor -= drop_frames

    def set_volume(self, volume: float) -> None:
        with self._lock:
            self._target_volume = max(0.0, min(2.0, float(volume)))

    def set_tone_filters(self, highpass_hz: float = 0.0, lowpass_hz: float = 0.0) -> None:
        with self._lock:
            highpass = max(0.0, float(highpass_hz))
            lowpass = max(0.0, float(lowpass_hz))
            self._target_highpass_hz = max(20.0, highpass) if highpass > 0.0 else 20.0
            self._target_lowpass_hz = max(200.0, min(20_000.0, lowpass)) if lowpass > 0.0 else 20_000.0
            self._target_highpass_mix = 1.0 if highpass > 0.0 else 0.0
            self._target_lowpass_mix = 0.0 if lowpass >= 19_900.0 or lowpass <= 0.0 else 1.0

    def set_eq(self, low: float = 0.0, mid: float = 0.0, high: float = 0.0) -> None:
        with self._lock:
            self._target_low_gain = max(-12.0, min(12.0, float(low)))
            self._target_mid_gain = max(-12.0, min(12.0, float(mid)))
            self._target_high_gain = max(-12.0, min(12.0, float(high)))

    def set_filter_preset(self, preset: dict[str, float] | None = None) -> None:
        data = preset or {}
        with self._lock:
            self._target_preset_low_gain = max(-12.0, min(12.0, float(data.get("low_gain", 0.0))))
            self._target_preset_mid_gain = max(-12.0, min(12.0, float(data.get("mid_gain", 0.0))))
            self._target_preset_high_gain = max(-12.0, min(12.0, float(data.get("high_gain", 0.0))))
            self._target_presence_gain = max(-12.0, min(12.0, float(data.get("presence_gain", 0.0))))

            preset_hp = max(0.0, float(data.get("highpass_hz", 0.0)))
            preset_lp = max(0.0, float(data.get("lowpass_hz", 20_000.0)))
            self._target_preset_highpass_hz = max(20.0, preset_hp) if preset_hp > 0.0 else 20.0
            self._target_preset_lowpass_hz = max(200.0, min(20_000.0, preset_lp)) if preset_lp > 0.0 else 20_000.0
            self._target_preset_highpass_mix = 1.0 if preset_hp > 0.0 else 0.0
            self._target_preset_lowpass_mix = 0.0 if preset_lp >= 19_900.0 or preset_lp <= 0.0 else 1.0
            self._target_pan_rate_hz = max(0.0, min(4.0, float(data.get("pan_rate_hz", 0.0))))
            self._target_pan_depth = max(0.0, min(1.0, float(data.get("pan_depth", 0.0))))
            self._target_playback_rate = max(0.5, min(1.5, float(data.get("playback_rate", 1.0))))
            self._target_reverb_mix = max(0.0, min(0.55, float(data.get("reverb_mix", 0.0))))
            self._target_reverb_decay = max(0.0, min(0.75, float(data.get("reverb_decay", 0.0))))

    def read(self) -> bytes:
        frames_out = self._ensure_frames_for_rate(self._current_playback_rate)
        if self._buffer_frames() <= 0:
            return b""

        pcm = array("h")
        with self._lock:
            self._current_volume = self._slew(self._current_volume, self._target_volume, 0.28)
            self._current_highpass_hz = self._slew(self._current_highpass_hz, self._target_highpass_hz, 0.18)
            self._current_lowpass_hz = self._slew(self._current_lowpass_hz, self._target_lowpass_hz, 0.18)
            self._current_highpass_mix = self._slew(self._current_highpass_mix, self._target_highpass_mix, 0.2)
            self._current_lowpass_mix = self._slew(self._current_lowpass_mix, self._target_lowpass_mix, 0.2)
            self._current_low_gain = self._slew(self._current_low_gain, self._target_low_gain, 0.16)
            self._current_mid_gain = self._slew(self._current_mid_gain, self._target_mid_gain, 0.16)
            self._current_high_gain = self._slew(self._current_high_gain, self._target_high_gain, 0.16)
            self._current_presence_gain = self._slew(self._current_presence_gain, self._target_presence_gain, 0.16)
            self._current_preset_highpass_hz = self._slew(self._current_preset_highpass_hz, self._target_preset_highpass_hz, 0.18)
            self._current_preset_lowpass_hz = self._slew(self._current_preset_lowpass_hz, self._target_preset_lowpass_hz, 0.18)
            self._current_preset_highpass_mix = self._slew(self._current_preset_highpass_mix, self._target_preset_highpass_mix, 0.2)
            self._current_preset_lowpass_mix = self._slew(self._current_preset_lowpass_mix, self._target_preset_lowpass_mix, 0.2)
            self._current_preset_low_gain = self._slew(self._current_preset_low_gain, self._target_preset_low_gain, 0.16)
            self._current_preset_mid_gain = self._slew(self._current_preset_mid_gain, self._target_preset_mid_gain, 0.16)
            self._current_preset_high_gain = self._slew(self._current_preset_high_gain, self._target_preset_high_gain, 0.16)
            self._current_pan_rate_hz = self._slew(self._current_pan_rate_hz, self._target_pan_rate_hz, 0.2)
            self._current_pan_depth = self._slew(self._current_pan_depth, self._target_pan_depth, 0.2)
            self._current_playback_rate = self._slew(self._current_playback_rate, self._target_playback_rate, 0.14)
            self._current_reverb_mix = self._slew(self._current_reverb_mix, self._target_reverb_mix, 0.12)
            self._current_reverb_decay = self._slew(self._current_reverb_decay, self._target_reverb_decay, 0.12)

            self._highpass.configure("highpass", self._current_highpass_hz)
            self._lowpass.configure("lowpass", self._current_lowpass_hz)
            self._low_eq.configure("low_shelf", 120.0, gain_db=self._current_low_gain)
            self._mid_eq.configure("peaking", 1000.0, gain_db=self._current_mid_gain, q=0.95)
            self._high_eq.configure("high_shelf", 8000.0, gain_db=self._current_high_gain)
            self._presence_eq.configure("peaking", 2500.0, gain_db=self._current_presence_gain, q=1.2)
            self._preset_highpass.configure("highpass", self._current_preset_highpass_hz)
            self._preset_lowpass.configure("lowpass", self._current_preset_lowpass_hz)
            self._preset_low_eq.configure("low_shelf", 120.0, gain_db=self._current_preset_low_gain)
            self._preset_mid_eq.configure("peaking", 1000.0, gain_db=self._current_preset_mid_gain, q=0.95)
            self._preset_high_eq.configure("high_shelf", 8000.0, gain_db=self._current_preset_high_gain)

            volume = self._current_volume
            highpass_mix = self._current_highpass_mix
            lowpass_mix = self._current_lowpass_mix
            preset_highpass_mix = self._current_preset_highpass_mix
            preset_lowpass_mix = self._current_preset_lowpass_mix
            playback_rate = self._current_playback_rate

            for _ in range(frames_out):
                dry_left, dry_right = self._sample_at(self._buffer_cursor)
                self._buffer_cursor += playback_rate
                left = dry_left
                right = dry_right

                if self._low_eq.enabled:
                    left = self._low_eq.process_left(left)
                    right = self._low_eq.process_right(right)
                if self._mid_eq.enabled:
                    left = self._mid_eq.process_left(left)
                    right = self._mid_eq.process_right(right)
                if self._high_eq.enabled:
                    left = self._high_eq.process_left(left)
                    right = self._high_eq.process_right(right)
                if self._presence_eq.enabled:
                    left = self._presence_eq.process_left(left)
                    right = self._presence_eq.process_right(right)
                if self._preset_low_eq.enabled:
                    left = self._preset_low_eq.process_left(left)
                    right = self._preset_low_eq.process_right(right)
                if self._preset_mid_eq.enabled:
                    left = self._preset_mid_eq.process_left(left)
                    right = self._preset_mid_eq.process_right(right)
                if self._preset_high_eq.enabled:
                    left = self._preset_high_eq.process_left(left)
                    right = self._preset_high_eq.process_right(right)

                eq_left = left
                eq_right = right

                if self._preset_highpass.enabled and preset_highpass_mix > 1e-4:
                    wet_left = self._preset_highpass.process_left(eq_left)
                    wet_right = self._preset_highpass.process_right(eq_right)
                    left = eq_left + ((wet_left - eq_left) * preset_highpass_mix)
                    right = eq_right + ((wet_right - eq_right) * preset_highpass_mix)
                else:
                    left = eq_left
                    right = eq_right

                if self._preset_lowpass.enabled and preset_lowpass_mix > 1e-4:
                    wet_left = self._preset_lowpass.process_left(left)
                    wet_right = self._preset_lowpass.process_right(right)
                    left = left + ((wet_left - left) * preset_lowpass_mix)
                    right = right + ((wet_right - right) * preset_lowpass_mix)

                if self._highpass.enabled and highpass_mix > 1e-4:
                    wet_left = self._highpass.process_left(left)
                    wet_right = self._highpass.process_right(right)
                    left = left + ((wet_left - left) * highpass_mix)
                    right = right + ((wet_right - right) * highpass_mix)

                if self._lowpass.enabled and lowpass_mix > 1e-4:
                    wet_left = self._lowpass.process_left(left)
                    wet_right = self._lowpass.process_right(right)
                    left = left + ((wet_left - left) * lowpass_mix)
                    right = right + ((wet_right - right) * lowpass_mix)

                if self._current_pan_depth > 1e-4 and self._current_pan_rate_hz > 1e-4:
                    pan = math.sin(self._pan_phase) * self._current_pan_depth
                    angle = (pan + 1.0) * (math.pi / 4.0)
                    left_gain = math.cos(angle) * math.sqrt(2.0)
                    right_gain = math.sin(angle) * math.sqrt(2.0)
                    left *= left_gain
                    right *= right_gain
                    self._pan_phase += (2.0 * math.pi * self._current_pan_rate_hz) / _SAMPLE_RATE
                    if self._pan_phase >= (2.0 * math.pi):
                        self._pan_phase -= (2.0 * math.pi)

                if self._current_reverb_mix > 1e-4:
                    wet_left = self._reverb_delay_l[self._reverb_pos_l]
                    wet_right = self._reverb_delay_r[self._reverb_pos_r]
                    self._reverb_delay_l[self._reverb_pos_l] = left + (wet_left * self._current_reverb_decay)
                    self._reverb_delay_r[self._reverb_pos_r] = right + (wet_right * self._current_reverb_decay)
                    self._reverb_pos_l = (self._reverb_pos_l + 1) % len(self._reverb_delay_l)
                    self._reverb_pos_r = (self._reverb_pos_r + 1) % len(self._reverb_delay_r)
                    dry_gain = 1.0 - (self._current_reverb_mix * 0.22)
                    left = (left * dry_gain) + (wet_left * self._current_reverb_mix)
                    right = (right * dry_gain) + (wet_right * self._current_reverb_mix)

                if abs(volume - 1.0) > 1e-6:
                    left *= volume
                    right *= volume

                pcm.append(_clamp_sample(left))
                pcm.append(_clamp_sample(right))

            self._trim_buffer()

        return pcm.tobytes()
