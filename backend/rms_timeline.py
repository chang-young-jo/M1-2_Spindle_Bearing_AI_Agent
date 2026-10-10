
"""
Spindle Bearing AI Agent
RAW vibration data - RMS timeline analysis

Input:
    .lst file with Time, X방향, Y방향, Z방향 columns

Output:
    rms_timeline.png
    rms_timeline.csv

Usage:
    python backend/rms_timeline.py "data/DATA_spindle_bearing_d,d,ng_0-3000rpm.lst"
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser(
        description="Plot vibration RMS over time"
    )

    parser.add_argument(
        "file",
        help="RAW vibration .lst file"
    )

    parser.add_argument(
        "--window",
        type=float,
        default=0.5,
        help="RMS calculation window in seconds"
    )

    parser.add_argument(
        "--outdir",
        default="rms_results",
        help="Output folder"
    )

    args = parser.parse_args()

    filepath = Path(args.file)

    if not filepath.is_file():
        parser.error(
            f"File not found: {filepath}"
        )

    if args.window <= 0:
        parser.error(
            "Window must be greater than zero"
        )

    print("Loading RAW vibration data...")

    df = pd.read_csv(
        filepath,
        usecols=[
            "Time",
            "X방향",
            "Y방향",
            "Z방향"
        ]
    )

    for col in df.columns:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    df = df.dropna()

    if len(df) < 2:
        parser.error(
            "Not enough valid data"
        )

    time = df["Time"].to_numpy()

    if np.any(np.diff(time) <= 0):
        parser.error(
            "Time must be strictly increasing"
        )

    sample_rate = 1 / np.median(
        np.diff(time)
    )

    window_samples = max(
        1,
        int(round(sample_rate * args.window))
    )

    print(
        f"Sample rate: {sample_rate:.0f} Hz"
    )

    print(
        f"Total duration: "
        f"{time[-1] - time[0]:.2f} s"
    )

    results = []

    for start in range(
        0,
        len(df),
        window_samples
    ):
        end = min(
            start + window_samples,
            len(df)
        )

        if end - start < 2:
            continue

        segment = df.iloc[start:end]

        row = {
            "time_s": float(
                segment["Time"].mean()
            )
        }

        for axis in [
            "X방향",
            "Y방향",
            "Z방향"
        ]:
            values = segment[
                axis
            ].to_numpy(dtype=float)

            row[axis + "_RMS"] = float(
                np.sqrt(
                    np.mean(values ** 2)
                )
            )

        results.append(row)

    result_df = pd.DataFrame(results)

    outdir = Path(args.outdir)

    outdir.mkdir(
        parents=True,
        exist_ok=True
    )

    csv_path = (
        outdir / "rms_timeline.csv"
    )

    png_path = (
        outdir / "rms_timeline.png"
    )

    result_df.to_csv(
        csv_path,
        index=False,
        encoding="utf-8-sig"
    )

    fig, ax = plt.subplots(
        figsize=(13, 6)
    )

    for axis, label in [
        ("X방향", "X RMS"),
        ("Y방향", "Y RMS"),
        ("Z방향", "Z RMS")
    ]:
        ax.plot(
            result_df["time_s"],
            result_df[axis + "_RMS"],
            label=label,
            linewidth=1.5
        )

    ax.set_title(
        "Spindle Vibration RMS Timeline"
    )

    ax.set_xlabel(
        "Time (seconds)"
    )

    ax.set_ylabel(
        "RMS (raw signal units)"
    )

    ax.grid(
        alpha=0.3
    )

    ax.legend()

    fig.tight_layout()

    fig.savefig(
        png_path,
        dpi=160
    )

    plt.close(fig)

    print()
    print("Analysis completed.")
    print(f"CSV: {csv_path}")
    print(f"Graph: {png_path}")
    print()
    print(
        "NOTE: RMS changes can suggest operating "
        "transitions, but cannot independently "
        "determine spindle RPM."
    )


if __name__ == "__main__":
    main()
