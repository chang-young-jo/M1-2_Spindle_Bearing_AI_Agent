
"""Spindle Bearing AI Agent - FFT plotting module.

Generate six PNG graphs:
- X/Y/Z conventional FFT
- X/Y/Z Envelope FFT

Display all theoretical and measured frequencies as integer Hz.
Keep full numerical precision for calculations and matching.

Example:
python backend/fft_plot.py "data/DATA_spindle_bearing_d,d,ng_0-3000rpm.lst" --start 0 --end 5 --rpm 2000
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

try:
    from fft_analysis import (
        FS,
        theoretical_frequencies,
        spectrum,
        envelope_spectrum,
    )
except ImportError:
    from backend.fft_analysis import (
        FS,
        theoretical_frequencies,
        spectrum,
        envelope_spectrum,
    )


def hz_text(value: float) -> str:
    """Format frequency as a rounded integer for display only."""
    return f"{value:.0f}"


def plot_one(
    freq,
    amp,
    theory,
    title,
    outfile,
    max_hz,
    tolerance,
):
    """Plot one FFT spectrum and theoretical bearing frequencies."""

    mask = freq <= max_hz

    fig, ax = plt.subplots(figsize=(12, 5))

    ax.plot(
        freq[mask],
        amp[mask],
        linewidth=0.7,
    )

    peaks, _ = find_peaks(amp)

    lines = []

    for name, target in theory.items():

        if target > max_hz:
            continue

        # Theoretical frequency is displayed as integer Hz.
        ax.axvline(
            target,
            linestyle="--",
            linewidth=1.0,
            label=f"{name} {hz_text(target)} Hz",
        )

        # Matching always uses the original floating-point values.
        candidate = peaks[
            np.abs(freq[peaks] - target) <= tolerance
        ]

        if len(candidate):

            strongest = candidate[
                np.argmax(amp[candidate])
            ]

            measured = float(freq[strongest])

            ax.plot(
                measured,
                amp[strongest],
                marker="o",
                markersize=5,
            )

            lines.append(
                f"{name}: {hz_text(measured)} Hz "
                "(local peak; not confirmed fault)"
            )

        else:

            lines.append(
                f"{name}: no local peak within "
                f"±{hz_text(tolerance)} Hz"
            )

    ax.set(
        xlim=(0, max_hz),
        xlabel="Frequency (Hz)",
        ylabel="Amplitude (raw units)",
        title=title,
    )

    ax.grid(alpha=0.25)

    ax.legend(
        fontsize=8,
        loc="upper right",
    )

    fig.text(
        0.02,
        0.01,
        " | ".join(lines),
        fontsize=7,
    )

    fig.subplots_adjust(bottom=0.16)

    fig.savefig(
        outfile,
        dpi=140,
    )

    plt.close(fig)


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Generate six FFT and Envelope FFT graphs "
            "for spindle vibration RAW data"
        )
    )

    parser.add_argument("file")

    parser.add_argument(
        "--start",
        type=float,
        default=0,
    )

    parser.add_argument(
        "--end",
        type=float,
        default=5,
    )

    parser.add_argument(
        "--rpm",
        type=float,
        required=True,
    )

    parser.add_argument(
        "--max-hz",
        type=float,
        default=1000,
    )

    parser.add_argument(
        "--band-low",
        type=float,
        default=1000,
    )

    parser.add_argument(
        "--band-high",
        type=float,
        default=10000,
    )

    parser.add_argument(
        "--tolerance",
        type=float,
        default=1,
    )

    parser.add_argument(
        "--outdir",
        default="fft_graphs",
    )

    args = parser.parse_args()

    if not (
        0 <= args.start < args.end
        and args.rpm > 0
        and args.max_hz > 0
        and args.tolerance > 0
    ):
        parser.error(
            "Require 0 <= start < end and positive "
            "RPM, max-hz and tolerance."
        )

    if not (
        0 < args.band_low < args.band_high < FS / 2
    ):
        parser.error(
            "Envelope band must be between "
            "0 and Nyquist (12800 Hz)."
        )

    filepath = Path(args.file)

    if not filepath.is_file():
        parser.error(
            f"File not found: {filepath}"
        )

    frame = pd.read_csv(
        filepath,
        usecols=[
            "Time",
            "X방향",
            "Y방향",
            "Z방향",
        ],
    )

    time = frame["Time"].to_numpy(
        dtype=float
    )

    if (
        len(time) < 3
        or np.any(np.diff(time) <= 0)
    ):
        parser.error(
            "Time values must be strictly increasing."
        )

    measured_fs = 1 / np.median(
        np.diff(time)
    )

    if abs(measured_fs - FS) / FS > 0.01:
        parser.error(
            f"Sample rate {hz_text(measured_fs)} Hz "
            f"differs from expected {hz_text(FS)} Hz."
        )

    frame = frame.loc[
        (frame["Time"] >= args.start)
        & (frame["Time"] < args.end)
    ]

    if len(frame) < 1024:
        parser.error(
            "Selected interval has fewer than 1024 samples."
        )

    out = Path(args.outdir)

    out.mkdir(
        parents=True,
        exist_ok=True,
    )

    theory = theoretical_frequencies(
        args.rpm
    )

    axes = [
        ("X방향", "X"),
        ("Y방향", "Y"),
        ("Z방향", "Z"),
    ]

    for axis, label in axes:

        values = frame[axis].to_numpy(
            dtype=float
        )

        f, a = spectrum(
            values,
            FS,
        )

        ef, ea = envelope_spectrum(
            values,
            FS,
            args.band_low,
            args.band_high,
        )

        modes = [
            ("FFT", f, a),
            ("Envelope_FFT", ef, ea),
        ]

        for mode, ff, aa in modes:

            path = out / f"{label}_{mode}.png"

            plot_one(
                freq=ff,
                amp=aa,
                theory=theory,
                title=(
                    f"{label} "
                    f"{mode.replace('_', ' ')} | "
                    f"{args.start:g}-{args.end:g}s | "
                    f"assumed {args.rpm:g} RPM"
                ),
                outfile=path,
                max_hz=args.max_hz,
                tolerance=args.tolerance,
            )

            print(
                f"Saved: {path}"
            )

    print(
        "Note: local frequency peaks do not establish "
        "a bearing defect. Verify actual RPM and units."
    )


if __name__ == "__main__":
    main()
