"""Bounded, in-memory analysis of uploaded spindle vibration CSV/LST files."""
import csv
import io
import math

import numpy as np
from scipy.signal import butter, hilbert, sosfiltfilt, find_peaks

SAMPLE_RATE = 25600
MAX_UPLOAD_BYTES = 70 * 1024 * 1024
SEGMENTS = [(1000, 2, 7), (2000, 12, 17), (3000, 22, 27)]
RMS_SEGMENTS = [(1000, 2, 8), (2000, 12, 18), (3000, 22, 28)]
BALLS, BALL_DIAMETER, PITCH_DIAMETER = 25, 8.731, 89.0
CONTACT_ANGLE = math.radians(18)


def theoretical_frequencies(rpm):
    fr = rpm / 60.0
    ratio = BALL_DIAMETER / PITCH_DIAMETER * math.cos(CONTACT_ANGLE)
    return {
        'FTF': fr * (1 - ratio) / 2,
        'BPFO': BALLS * fr * (1 - ratio) / 2,
        'BPFI': BALLS * fr * (1 + ratio) / 2,
        'BSF': PITCH_DIAMETER / (2 * BALL_DIAMETER) * fr * (1 - ratio ** 2),
    }


def display_hz(value):
    return int(math.floor(float(value) + 0.5))


def _peaks(signal, fs, envelope=False):
    signal = np.asarray(signal, dtype=np.float64)
    signal = signal - np.mean(signal)
    if envelope:
        # 1–8 kHz exploratory demodulation band; not a validated diagnosis.
        sos = butter(4, [1000, 8000], btype='bandpass', fs=fs, output='sos')
        signal = np.abs(hilbert(sosfiltfilt(sos, signal)))
        signal = signal - np.mean(signal)
    n = len(signal)
    spectrum = np.abs(np.fft.rfft(signal * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, 1 / fs)
    peaks, _ = find_peaks(spectrum)
    return freqs, spectrum, peaks


def _candidate(freqs, spectrum, peaks, target):
    # Compare unrounded values, never the integer display values.
    eligible = peaks[np.abs(freqs[peaks] - target) <= 1.0]
    if eligible.size == 0:
        return {'theoretical_hz': display_hz(target), 'measured_hz': None, 'matched': False}
    idx = int(eligible[np.argmax(spectrum[eligible])])
    background = spectrum[(freqs >= max(0, target - 15)) & (freqs <= target + 15) &
                          (np.abs(freqs - target) > 2)]
    noise = float(np.median(background)) if background.size else 0.0
    snr = 20 * math.log10(max(float(spectrum[idx]), 1e-15) / max(noise, 1e-15))
    return {'theoretical_hz': display_hz(target), 'measured_hz': display_hz(freqs[idx]),
            'matched': bool(abs(float(freqs[idx]) - target) <= 1.0),
            'snr_db': round(snr, 1), 'exploratory_strong_peak': bool(snr >= 6.0)}


def _analyze_window(rpm, axis, values, fs, rms_values):
    values = np.asarray(values, dtype=np.float64)
    rms = float(np.sqrt(np.mean(values * values)))
    # Split the same 5-second window into non-overlapping 0.1-second blocks.
    # This allows a like-for-like comparison of aggregation methods.
    block_size = int(round(fs * 0.1))
    if block_size <= 0 or len(values) % block_size != 0:
        raise ValueError('0.1초 RMS 비교를 위해서는 구간 샘플 수가 2560의 배수여야 합니다.')
    blocks = values.reshape(-1, block_size)
    block_rms = np.sqrt(np.mean(blocks * blocks, axis=1))
    arithmetic_mean = float(np.mean(block_rms))
    quadratic_mean = float(np.sqrt(np.mean(block_rms * block_rms)))
    # Firebase comparison: 60 consecutive 0.1-second RMS blocks (6 seconds).
    rms_values = np.asarray(rms_values, dtype=np.float64)
    expected_rms_samples = 60 * block_size
    if len(rms_values) != expected_rms_samples:
        raise ValueError(f'{rpm} RPM {axis}방향 6초 RMS 데이터가 부족합니다: '
                         f'{len(rms_values)}/{expected_rms_samples} samples')
    rms_blocks = rms_values.reshape(60, block_size)
    rms_block_values = np.sqrt(np.mean(rms_blocks * rms_blocks, axis=1))
    firebase_mean = float(np.mean(rms_block_values))
    firebase_total_rms = float(np.sqrt(np.mean(rms_values * rms_values)))
    theory = theoretical_frequencies(rpm)
    results = {}
    for method in ('FFT', 'Envelope FFT'):
        freq, amp, peaks = _peaks(values, fs, envelope=(method == 'Envelope FFT'))
        results[method] = {name: _candidate(freq, amp, peaks, target)
                           for name, target in theory.items()}
    return {'rpm': rpm, 'axis': axis, 'sample_count': len(values),
            'rms_m_s2': round(rms, 6),
            'rms_0_1s_mean_m_s2': round(arithmetic_mean, 6),
            'rms_0_1s_quadratic_mean_m_s2': round(quadratic_mean, 6),
            'rms_0_1s_block_count': len(block_rms),
            'firebase_comparison_rms_0_1s_mean_m_s2': round(firebase_mean, 6),
            'firebase_comparison_rms_6s_m_s2': round(firebase_total_rms, 6),
            'firebase_comparison_block_count': len(rms_block_values),
            'frequency_candidates': results}


def analyze_raw_file(binary_file, filename, fs=SAMPLE_RATE):
    if not filename.lower().endswith(('.lst', '.csv')):
        raise ValueError('CSV 또는 LST 파일만 업로드할 수 있습니다.')
    if fs != SAMPLE_RATE:
        raise ValueError('현재 자동 분석은 샘플링 주파수 25600 Hz만 지원합니다.')
    # The upload is already bounded by the API before this function is called.
    text = io.TextIOWrapper(binary_file, encoding='utf-8-sig', errors='strict', newline='')
    windows = {(rpm, axis): [] for rpm, _, _ in SEGMENTS for axis in ('X', 'Y', 'Z')}
    rms_windows = {(rpm, axis): [] for rpm, _, _ in RMS_SEGMENTS for axis in ('X', 'Y', 'Z')}
    total_rows = 0
    try:
        reader = csv.reader(text)
        header = next(reader, None)
        if not header or len(header) < 5:
            raise ValueError('첫 행은 Time,A,X,Y,Z 형식의 컬럼 제목이어야 합니다.')
        for row in reader:
            if len(row) < 5:
                raise ValueError(f'{total_rows + 2}행에 5개 열이 없습니다.')
            try:
                t = float(row[0])
                x, y, z = (float(row[i]) for i in (2, 3, 4))
            except (ValueError, OverflowError) as exc:
                raise ValueError(f'{total_rows + 2}행에 숫자가 아닌 측정값이 있습니다.') from exc
            if not all(math.isfinite(v) for v in (t, x, y, z)):
                raise ValueError(f'{total_rows + 2}행에 유효하지 않은 숫자가 있습니다.')
            total_rows += 1
            for rpm, start, end in SEGMENTS:
                if start <= t < end:
                    for axis, value in zip(('X', 'Y', 'Z'), (x, y, z)):
                        windows[(rpm, axis)].append(value)
                    break
            for rpm, start, end in RMS_SEGMENTS:
                if start <= t < end:
                    for axis, value in zip(('X', 'Y', 'Z'), (x, y, z)):
                        rms_windows[(rpm, axis)].append(value)
                    break
            if total_rows > 2_000_000:
                raise ValueError('최대 200만 행까지 분석할 수 있습니다.')
    except UnicodeError as exc:
        raise ValueError('UTF-8 인코딩 CSV/LST 파일을 사용해 주세요.') from exc
    finally:
        text.detach()
    results = []
    for rpm, start, end in SEGMENTS:
        for axis in ('X', 'Y', 'Z'):
            values = windows[(rpm, axis)]
            if len(values) < int((end - start) * fs * 0.9):
                raise ValueError(f'{rpm} RPM {axis}방향 데이터가 부족합니다. 측정 시간/샘플링 주파수를 확인하세요.')
            results.append(_analyze_window(rpm, axis, values, fs, rms_windows[(rpm, axis)]))
    return {'source': 'uploaded_raw_analyzed_in_memory', 'filename': filename,
            'sample_rate_hz': fs, 'total_rows': total_rows,
            'segments': [{'rpm': rpm, 'start_s': a, 'end_s': b} for rpm, a, b in SEGMENTS],
            'firebase_comparison_segments': [
                {'rpm': rpm, 'start_s': a, 'end_s': b} for rpm, a, b in RMS_SEGMENTS],
            'frequency_display': 'integer_hz', 'matching_tolerance_hz': 1,
            'diagnostic_notice': '탐색용 FFT 및 Envelope FFT 피크 결과이며 결함 확정이 아닙니다. '
                                 'Envelope 대역 1–8 kHz 및 SNR 기준은 검증되지 않은 초기 설정입니다.',
            'results': results}
