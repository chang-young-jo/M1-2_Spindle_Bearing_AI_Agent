
"""Generate FFT graphs for all three spindle RPM segments."""

import subprocess
import sys
from pathlib import Path


def main():
    project_root = Path(__file__).resolve().parent.parent
    data_folder = project_root / "data"
    plot_script = project_root / "backend" / "fft_plot.py"

    # 실제 확인된 운전 조건과 안정 구간
    segments = [
        (1000, 2, 7),
        (2000, 12, 17),
        (3000, 22, 27),
    ]

    # 파일명에 공백, 쉼표 등이 있어도 자동 검색
    raw_files = list(data_folder.glob("*.lst"))

    if len(raw_files) != 1:
        print(
            f"오류: data 폴더의 LST 파일이 "
            f"{len(raw_files)}개입니다."
        )
        print("RAW 데이터 파일을 하나만 남겨주세요.")
        return

    raw_file = raw_files[0]

    if not plot_script.is_file():
        print("오류: backend/fft_plot.py가 없습니다.")
        return

    print(f"RAW 파일: {raw_file.name}")
    print("분석 시작")

    for rpm, start, end in segments:
        output_folder = (
            project_root / "fft_graphs" / f"{rpm}rpm"
        )

        command = [
            sys.executable,
            str(plot_script),
            str(raw_file),
            "--start", str(start),
            "--end", str(end),
            "--rpm", str(rpm),
            "--outdir", str(output_folder),
        ]

        print()
        print(
            f"===== {rpm} RPM / "
            f"{start}~{end}초 분석 ====="
        )

        result = subprocess.run(
            command,
            cwd=project_root,
            check=False,
        )

        if result.returncode != 0:
            print(f"{rpm} RPM 분석 실패")
            return

        expected = [
            output_folder / f"{axis}_{mode}.png"
            for axis in ("X", "Y", "Z")
            for mode in ("FFT", "Envelope_FFT")
        ]

        missing = [
            path for path in expected
            if not path.is_file()
        ]

        if missing:
            print("생성되지 않은 그래프:")
            for path in missing:
                print(path)
            return

        print(f"{rpm} RPM 그래프 6개 생성 완료")

    print()
    print("전체 분석 완료: FFT 그래프 18개 생성")


if __name__ == "__main__":
    main()
