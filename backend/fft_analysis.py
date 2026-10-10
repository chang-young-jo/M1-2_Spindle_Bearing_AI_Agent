"""Standalone spindle RAW FFT and envelope spectrum analysis.
Usage: python backend/fft_analysis.py path/to/recording.lst --start 0 --end 10 --rpm 2000
Requires: numpy, scipy, pandas (see existing project environment).
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.signal import butter, sosfiltfilt, hilbert, find_peaks

FS = 25600.0
BEARING = dict(n=25, ball_d=8.731, pcd=89.0, contact_deg=18.0)

def theoretical_frequencies(rpm: float) -> dict[str, float]:
    p = BEARING
    ratio = p['ball_d'] / p['pcd'] * np.cos(np.deg2rad(p['contact_deg']))
    fr = rpm / 60.0
    return {'FTF': fr / 2 * (1-ratio), 'BPFO': p['n'] * fr / 2 * (1-ratio),
            'BPFI': p['n'] * fr / 2 * (1+ratio),
            'BSF': p['pcd'] / (2*p['ball_d']) * fr * (1-ratio**2)}

def spectrum(signal: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(signal, dtype=np.float64)
    x = x - np.mean(x)
    w = np.hanning(len(x))
    y = np.abs(np.fft.rfft(x * w)) * (2.0 / np.sum(w))
    if len(y):
        y[0] /= 2
        if len(x) % 2 == 0: y[-1] /= 2
    return np.fft.rfftfreq(len(x), 1/fs), y

def envelope_spectrum(x: np.ndarray, fs: float, low: float, high: float):
    if not (0 < low < high < fs/2):
        raise ValueError('Envelope band must be inside (0, Nyquist).')
    sos = butter(4, [low, high], btype='bandpass', fs=fs, output='sos')
    filtered = sosfiltfilt(sos, x)
    envelope = np.abs(hilbert(filtered))
    return spectrum(envelope, fs)

def peak_matches(freq: np.ndarray, amp: np.ndarray, theories: dict[str, float], tolerance: float = 1.0):
    # Peaks found on spectrum, then compare nearest peak inside tolerance.
    idx, _ = find_peaks(amp)
    result = {}
    for name, target in theories.items():
        candidates = idx[np.abs(freq[idx]-target) <= tolerance]
        if len(candidates):
            best = candidates[np.argmax(amp[candidates])]
            result[name] = {'theoretical_hz': round(target, 3), 'measured_hz': round(float(freq[best]), 3),
                            'difference_hz': round(abs(float(freq[best])-target), 3),
                            'amplitude': float(amp[best]), 'matched': True}
        else:
            result[name] = {'theoretical_hz': round(target, 3), 'measured_hz': None,
                            'difference_hz': None, 'amplitude': None, 'matched': False}
    return result

def analyze(path: str, start: float, end: float, rpm: float, band_low: float = 1000,
            band_high: float = 10000, tolerance: float = 1.0) -> dict:
    if not (0 <= start < end and rpm > 0 and tolerance > 0):
        raise ValueError('Require 0 <= start < end, positive RPM and tolerance.')
    frame = pd.read_csv(path, usecols=['Time', 'X방향', 'Y방향', 'Z방향'])
    time = frame['Time'].to_numpy(dtype=np.float64)
    if len(time) < 3 or np.any(np.diff(time) <= 0):
        raise ValueError('Time must be strictly increasing.')
    actual_fs = 1.0 / np.median(np.diff(time))
    if abs(actual_fs-FS)/FS > 0.01:
        raise ValueError(f'Unexpected sample rate {actual_fs:.2f} Hz; expected ~{FS} Hz.')
    segment = frame.loc[(frame['Time'] >= start) & (frame['Time'] < end)]
    if len(segment) < 1024:
        raise ValueError('Selected segment must have at least 1024 samples.')
    theories = theoretical_frequencies(rpm)
    result = {'file': Path(path).name, 'start_s': start, 'end_s': end,
              'samples': len(segment), 'sample_rate_hz': FS, 'rpm_assumed': rpm,
              'tolerance_hz': tolerance, 'envelope_band_hz': [band_low, band_high],
              'theoretical_hz': theories, 'axes': {}}
    for axis in ('X방향', 'Y방향', 'Z방향'):
        x = segment[axis].to_numpy(dtype=np.float64)
        f, a = spectrum(x, FS)
        ef, ea = envelope_spectrum(x, FS, band_low, band_high)
        result['axes'][axis] = {'rms_raw_units': float(np.std(x)),
                                'fft_matches': peak_matches(f, a, theories, tolerance),
                                'envelope_fft_matches': peak_matches(ef, ea, theories, tolerance)}
    result['caveat'] = ('Frequency proximity alone does not confirm bearing damage. '
                        'RPM must match actual selected time segment; units are unverified. '
                        'Envelope band is a provisional setting and must be validated.')
    return result

def main():
    p = argparse.ArgumentParser(description='Spindle vibration FFT and envelope FFT')
    p.add_argument('file')
    p.add_argument('--start', type=float, default=0)
    p.add_argument('--end', type=float, default=10)
    p.add_argument('--rpm', type=float, required=True)
    p.add_argument('--band-low', type=float, default=1000)
    p.add_argument('--band-high', type=float, default=10000)
    p.add_argument('--tolerance', type=float, default=1.0)
    p.add_argument('--output', default='fft_result.json')
    args = p.parse_args()
    result = analyze(args.file, args.start, args.end, args.rpm, args.band_low, args.band_high, args.tolerance)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Saved {args.output}: {result['samples']} samples, {result['start_s']}–{result['end_s']} s")
    for axis, data in result['axes'].items():
        print(axis, 'RMS(raw units):', round(data['rms_raw_units'], 4))
        for mode in ('fft_matches', 'envelope_fft_matches'):
            print(' ', mode, ', '.join(f'{k}={v["measured_hz"]}' for k,v in data[mode].items() if v['matched']) or 'no frequency matches')

if __name__ == '__main__':
    main()
