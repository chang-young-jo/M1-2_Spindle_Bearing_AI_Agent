
from pathlib import Path
import numpy as np
import pandas as pd

# 1. 프로젝트 경로
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

SOURCE_FILE = DATA_DIR / "DATA_spindle_bearing_d,d,ng_0-3000rpm.lst"
OUTPUT_FILE = DATA_DIR / "vibration_ai_data.csv"

# 2. 측정 조건
FS = 25600
WINDOW_SEC = 0.1
WINDOW_SAMPLES = int(FS * WINDOW_SEC)

# RPM별 안정 분석 구간
RPM_RANGES = {
    1000: (2.0, 8.0),
    2000: (12.0, 18.0),
    3000: (22.0, 28.0),
}


def main():
    print("원본 진동 데이터 읽는 중...")

    # 원본 데이터: 시간, A, X, Y, Z
    df = pd.read_csv(SOURCE_FILE, sep=None, engine="python")
    df.columns = df.columns.str.strip()

    print("원본 데이터 행 수:", len(df))
    print("컬럼:", list(df.columns))

    # 첫 열은 시간, 세 번째~다섯 번째 열은 X/Y/Z
    time_col = df.columns[0]
    axis_cols = {
        "X": df.columns[2],
        "Y": df.columns[3],
        "Z": df.columns[4],
    }

    for col in [time_col, *axis_cols.values()]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    records = []

    # 3. RPM별 데이터 계산
    for rpm, (start, end) in RPM_RANGES.items():
        section = df[
            (df[time_col] >= start) &
            (df[time_col] < end)
        ].reset_index(drop=True)

        expected_samples = int((end - start) * FS)

        if len(section) != expected_samples:
            raise ValueError(
                f"{rpm} RPM 구간 표본 수 오류: "
                f"{len(section)}개 / 예상 {expected_samples}개"
            )

        for window_idx in range(
            len(section) // WINDOW_SAMPLES
        ):
            start_idx = window_idx * WINDOW_SAMPLES
            end_idx = start_idx + WINDOW_SAMPLES
            window = section.iloc[start_idx:end_idx]

            for axis, col in axis_cols.items():
                signal = window[col].to_numpy(dtype=float)

                if not np.isfinite(signal).all():
                    raise ValueError("진동 데이터에 결측값이 있습니다.")

                rms = np.sqrt(np.mean(signal ** 2))
                peak = np.max(np.abs(signal))

                # 실제 측정 날짜가 아닌 경과 시간
                elapsed = start + window_idx * WINDOW_SEC

                records.append({
                    "date": f"T+{elapsed:.1f}s",
                    "value": round(float(rms), 6),
                    "memo": f"{rpm}RPM_{axis}",
                    "elapsed_seconds": round(elapsed, 3),
                    "rpm": rpm,
                    "axis": axis,
                    "acc_rms_m_s2": round(float(rms), 6),
                    "acc_peak_m_s2": round(float(peak), 6),
                })

    # 4. CSV 저장
    result = pd.DataFrame(records)
    result.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n데이터 변환 완료!")
    print("생성 데이터:", len(result), "개")
    print("저장 위치:", OUTPUT_FILE)
    print(result.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
