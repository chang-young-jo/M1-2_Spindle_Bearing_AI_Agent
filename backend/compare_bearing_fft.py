"""Compare spindle bearing frequencies using FFT, envelope FFT and peak quality.

Run from project root:
    python backend/compare_bearing_fft.py

Requires the existing backend/fft_analysis.py and one .lst file in data/.
"""
from pathlib import Path
import csv
import sys
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

try:
    from fft_analysis import FS, theoretical_frequencies, spectrum, envelope_spectrum
except ImportError:
    from backend.fft_analysis import FS, theoretical_frequencies, spectrum, envelope_spectrum

SEGMENTS = [(1000, 2, 7), (2000, 12, 17), (3000, 22, 27)]
AXES = [('X방향', 'X'), ('Y방향', 'Y'), ('Z방향', 'Z')]
FAULTS = ('FTF', 'BPFO', 'BPFI', 'BSF')
TOLERANCE_HZ = 1.0
BAND_LOW_HZ = 1000.0
BAND_HIGH_HZ = 10000.0
NOISE_HALF_WIDTH_HZ = 20.0
NOISE_GUARD_HZ = 2.0
MIN_SNR_DB = 6.0
MIN_PROMINENCE_RATIO = 3.0


def display_hz(value):
    """Round positive frequency to integer Hz for presentation only."""
    return '' if value is None else int(np.floor(float(value) + 0.5))


def noise_floor(freq, amp, target):
    """Median local spectral amplitude, excluding the target neighborhood."""
    mask = (
        (np.abs(freq - target) <= NOISE_HALF_WIDTH_HZ)
        & (np.abs(freq - target) > NOISE_GUARD_HZ)
    )
    background = np.asarray(amp[mask], dtype=float)
    background = background[np.isfinite(background) & (background >= 0)]
    if background.size < 10:
        return None
    return float(np.median(background))


def peak_at(freq, amp, peaks, prominences, target):
    """Return strongest local peak within tolerance, preserving precision."""
    nearby = peaks[np.abs(freq[peaks] - target) <= TOLERANCE_HZ]
    if len(nearby) == 0:
        return None
    idx = int(nearby[np.argmax(amp[nearby])])
    measured = float(freq[idx])
    amplitude = float(amp[idx])
    prominence = float(prominences[idx])
    floor = noise_floor(freq, amp, target)
    eps = np.finfo(float).tiny
    snr_db = None if floor is None else float(20 * np.log10(max(amplitude, eps) / max(floor, eps)))
    prominence_ratio = None if floor is None else float(prominence / max(floor, eps))
    strong = (
        snr_db is not None
        and prominence_ratio is not None
        and snr_db >= MIN_SNR_DB
        and prominence_ratio >= MIN_PROMINENCE_RATIO
    )
    return {
        'measured': measured,
        'difference': abs(measured - target),
        'amplitude': amplitude,
        'prominence': prominence,
        'noise': floor,
        'snr_db': snr_db,
        'prominence_ratio': prominence_ratio,
        'strong': strong,
    }


def analyze_spectrum(freq, amp, theory, rpm, start, end, axis_label, method):
    freq = np.asarray(freq, dtype=float)
    amp = np.asarray(amp, dtype=float)
    if len(freq) != len(amp) or len(freq) < 3:
        raise ValueError('FFT 주파수/진폭 배열이 유효하지 않습니다.')
    if not np.all(np.isfinite(freq)) or not np.all(np.isfinite(amp)):
        raise ValueError('FFT 결과에 NaN 또는 무한대가 있습니다.')
    peaks, properties = find_peaks(amp, prominence=0)
    prominence_lookup = np.zeros(len(amp), dtype=float)
    prominence_lookup[peaks] = properties['prominences']
    rows = []

    for fault in FAULTS:
        target = float(theory[fault])
        fundamental = peak_at(freq, amp, peaks, prominence_lookup, target)
        harmonics = []
        for order in (2, 3):
            harmonic_target = target * order
            if harmonic_target > float(freq[-1]):
                continue
            item = peak_at(freq, amp, peaks, prominence_lookup, harmonic_target)
            if item is not None and item['strong']:
                harmonics.append(order)

        matched = fundamental is not None
        strong = matched and fundamental['strong']
        if not matched:
            assessment = '범위 내 국소피크 없음'
        elif strong and harmonics:
            assessment = '강한 후보(고조파 동반)'
        elif strong:
            assessment = '강한 후보(추가 검증 필요)'
        else:
            assessment = '약한 국소피크(결함 근거 부족)'

        def num(value, digits=3):
            return '' if value is None else round(float(value), digits)

        rows.append({
            'RPM': rpm,
            '시작(초)': start,
            '종료(초)': end,
            '방향': axis_label,
            '분석방법': method,
            '결함유형': fault,
            '이론주파수(Hz)': display_hz(target),
            '측정피크(Hz)': display_hz(fundamental['measured']) if matched else '',
            '주파수차이(Hz)': display_hz(fundamental['difference']) if matched else '',
            '허용오차(Hz)': display_hz(TOLERANCE_HZ),
            '판정': '국소피크 일치' if matched else '범위 내 국소피크 없음',
            '피크진폭(원신호단위)': num(fundamental['amplitude'], 6) if matched else '',
            '피크돌출도': num(fundamental['prominence'], 6) if matched else '',
            '주변잡음중앙값': num(fundamental['noise'], 6) if matched else '',
            'SNR(dB)': num(fundamental['snr_db'], 2) if matched else '',
            '돌출도/잡음비': num(fundamental['prominence_ratio'], 2) if matched else '',
            '강한피크': '예' if strong else '아니오',
            '강한고조파': ','.join(f'{n}배' for n in harmonics),
            '검토결과': assessment,
        })
    return rows


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    root = Path(__file__).resolve().parent.parent
    files = sorted((root / 'data').glob('*.lst'))
    if len(files) != 1:
        sys.exit(f'오류: data 폴더에 .lst 파일이 정확히 1개 필요합니다. 현재 {len(files)}개')
    source = files[0]
    print('RAW 파일:', source.name)
    df = pd.read_csv(source, usecols=['Time'] + [name for name, _ in AXES])
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='raise')
    time = df['Time'].to_numpy(dtype=float)
    if len(time) < 2 or not np.all(np.diff(time) > 0):
        sys.exit('오류: Time 열이 유효한 증가 순서가 아닙니다.')
    measured_fs = 1 / np.median(np.diff(time))
    if abs(measured_fs - FS) / FS > 0.01:
        sys.exit(f'오류: 샘플링 레이트 {display_hz(measured_fs)} Hz가 설정값과 다릅니다.')

    results = []
    for rpm, start, end in SEGMENTS:
        section = df.loc[(df['Time'] >= start) & (df['Time'] < end)]
        if len(section) < 1024:
            sys.exit(f'오류: {rpm} RPM ({start}~{end}초) 데이터가 부족합니다.')
        theory = theoretical_frequencies(rpm)
        for axis_col, axis_label in AXES:
            values = section[axis_col].to_numpy(dtype=float)
            spectra = (
                ('FFT', spectrum(values, FS)),
                ('Envelope FFT', envelope_spectrum(values, FS, BAND_LOW_HZ, BAND_HIGH_HZ)),
            )
            for method, (freq, amp) in spectra:
                results.extend(analyze_spectrum(
                    freq, amp, theory, rpm, start, end, axis_label, method
                ))
        print(f'{rpm} RPM 분석 완료')

    output = root / 'fft_results'
    output.mkdir(parents=True, exist_ok=True)
    detail = output / 'bearing_frequency_comparison_v2.csv'
    write_csv(detail, results)

    summary = []
    for fault in FAULTS:
        rows = [r for r in results if r['결함유형'] == fault]
        strong_rows = [r for r in rows if r['강한피크'] == '예']
        strong_rpms = sorted({r['RPM'] for r in strong_rows})
        harmonic_rows = [r for r in strong_rows if r['강한고조파']]
        summary.append({
            '결함유형': fault,
            '비교건수': len(rows),
            '국소피크일치건수': sum(r['판정'] == '국소피크 일치' for r in rows),
            '강한피크건수': len(strong_rows),
            '고조파동반건수': len(harmonic_rows),
            '강한피크검출RPM': ', '.join(str(x) for x in strong_rpms),
            '회전수추종성': '3개 RPM에서 강한 후보 검출' if len(strong_rpms) == 3 else '추가 검증 필요',
            '최종진단': '확정 불가 - 추가 진단 필요',
        })
    summary_path = output / 'bearing_fault_summary_v2.csv'
    write_csv(summary_path, summary)
    print(f'상세 결과 {len(results)}건: {detail}')
    print(f'결함유형별 요약 {len(summary)}건: {summary_path}')
    print('주의: SNR 및 돌출도 임계값은 탐색용 설정이며 검증된 결함 판정 기준이 아닙니다.')
    print('주의: 주파수는 정수로 표시하지만 일치 판정은 원본 정밀도로 수행합니다.')


if __name__ == '__main__':
    main()
