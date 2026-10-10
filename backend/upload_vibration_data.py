
from pathlib import Path
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

BASE_DIR = Path(__file__).resolve().parent.parent

CSV_FILE = BASE_DIR / "data" / "vibration_ai_data.csv"
KEY_FILE = BASE_DIR / "backend" / "firebase-service-account.json"

def main():
    if not CSV_FILE.exists():
        print("오류: vibration_ai_data.csv 파일이 없습니다.")
        return

    if not KEY_FILE.exists():
        print("오류: Firebase 인증키 파일이 없습니다.")
        return

    if not firebase_admin._apps:
        cred = credentials.Certificate(str(KEY_FILE))
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    df = pd.read_csv(CSV_FILE)

    print(f"업로드 대상: {len(df)}개")

    # M1-2 과제에서 요구하는 data 컬렉션 사용
    collection = db.collection("data")

    for i, row in df.iterrows():
        record = row.to_dict()

        # 재실행해도 동일 데이터가 중복 생성되지 않도록 고정 ID 사용
        doc_id = f"vibration_{i+1:04d}"

        collection.document(doc_id).set(record)

        if (i + 1) % 50 == 0:
            print(f"{i+1}개 저장 완료")

    print("Firebase 데이터 업로드 완료!")
    print(f"총 {len(df)}개 저장")

if __name__ == "__main__":
    main()
