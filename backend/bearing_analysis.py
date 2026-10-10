"""Spindle bearing characteristic frequencies and FFT peak matching.

This module does not diagnose bearing damage on frequency matching alone.
Run: python backend/bearing_analysis.py (from the project root)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from typing import Iterable


@dataclass(frozen=True)
class BearingSpec:
    ball_count: int = 25
    ball_diameter_mm: float = 8.731
    pitch_diameter_mm: float = 89.0
    contact_angle_deg: float = 18.0

    def validate(self) -> None:
        if self.ball_count < 1:
            raise ValueError("볼 개수는 1개 이상이어야 합니다.")
        if self.ball_diameter_mm <= 0 or self.pitch_diameter_mm <= 0:
            raise ValueError("볼 직경과 PCD는 양수여야 합니다.")
        if not (0 <= self.contact_angle_deg < 90):
            raise ValueError("접촉각은 0도 이상 90도 미만이어야 합니다.")
        if self.ball_diameter_mm >= self.pitch_diameter_mm:
            raise ValueError("볼 직경은 PCD보다 작아야 합니다.")


def theoretical_frequencies(rpm: float, spec: BearingSpec | None = None) -> dict[str, float]:
    """Return theoretical frequencies in Hz (stationary outer race assumption)."""
    spec = spec or BearingSpec()
    spec.validate()
    if not math.isfinite(rpm) or rpm <= 0:
        raise ValueError("RPM은 유한한 양수여야 합니다.")

    fr = rpm / 60.0
    ratio = (spec.ball_diameter_mm / spec.pitch_diameter_mm) * math.cos(
        math.radians(spec.contact_angle_deg)
    )
    n = spec.ball_count
    return {
        "FTF": 0.5 * fr * (1 - ratio),
        "BPFO": 0.5 * n * fr * (1 - ratio),
        "BPFI": 0.5 * n * fr * (1 + ratio),
        "BSF": (spec.pitch_diameter_mm / (2 * spec.ball_diameter_mm)) * fr * (1 - ratio**2),
    }


def match_frequency(
    theoretical_hz: float,
    measured_hz: float,
    tolerance_hz: float = 1.0,
) -> dict:
    """Match frequencies inclusively when |measured - theoretical| <= tolerance."""
    for name, value in (
        ("theoretical_hz", theoretical_hz),
        ("measured_hz", measured_hz),
        ("tolerance_hz", tolerance_hz),
    ):
        if not math.isfinite(value):
            raise ValueError(f"{name}은 유한한 숫자여야 합니다.")
    if theoretical_hz < 0 or measured_hz < 0 or tolerance_hz < 0:
        raise ValueError("주파수와 허용오차는 음수일 수 없습니다.")
    delta = abs(measured_hz - theoretical_hz)
    return {
        "theoretical_hz": round(theoretical_hz, 4),
        "measured_hz": round(measured_hz, 4),
        "difference_hz": round(delta, 4),
        "tolerance_hz": tolerance_hz,
        "matched": delta <= tolerance_hz + 1e-10,
        "judgement": "주파수 일치" if delta <= tolerance_hz + 1e-10 else "주파수 불일치",
    }


def analyze_fft_peaks(
    rpm: float,
    peak_frequencies_hz: Iterable[float],
    spec: BearingSpec | None = None,
    tolerance_hz: float = 1.0,
) -> dict:
    """Match each defect frequency to the closest provided FFT peak.

    Input peaks must be detected from actual spectra elsewhere; this function
    does not perform an FFT and does not infer peak amplitudes.
    """
    spec = spec or BearingSpec()
    peaks = [float(p) for p in peak_frequencies_hz]
    if any(not math.isfinite(p) or p < 0 for p in peaks):
        raise ValueError("FFT 피크 주파수는 0 이상의 유한한 값이어야 합니다.")
    theoretical = theoretical_frequencies(rpm, spec)
    matches = {}
    for defect, expected in theoretical.items():
        if peaks:
            closest = min(peaks, key=lambda p: abs(p - expected))
            matches[defect] = match_frequency(expected, closest, tolerance_hz)
        else:
            matches[defect] = {
                "theoretical_hz": round(expected, 4),
                "measured_hz": None,
                "difference_hz": None,
                "tolerance_hz": tolerance_hz,
                "matched": False,
                "judgement": "측정 피크 없음 (판정 불가)",
            }
    return {
        "rpm": rpm,
        "bearing_spec": asdict(spec),
        "peak_count": len(peaks),
        "frequency_matches": matches,
        "caution": "주파수 일치만으로 베어링 결함을 확정할 수 없습니다.",
    }


if __name__ == "__main__":
    spec = BearingSpec()
    print("=== 2000 RPM 이론 결함 주파수 (Hz) ===")
    print(json.dumps(theoretical_frequencies(2000, spec), ensure_ascii=False, indent=2))
    print("\n=== 사용자가 제시한 BSF 측정값 일치 판정 ===")
    print(json.dumps(match_frequency(168.41, 168.34), ensure_ascii=False, indent=2))
    print("\n=== 실제 FFT 피크가 주어졌을 때의 사용 예시 ===")
    print(json.dumps(analyze_fft_peaks(2000, [168.34], spec), ensure_ascii=False, indent=2))
