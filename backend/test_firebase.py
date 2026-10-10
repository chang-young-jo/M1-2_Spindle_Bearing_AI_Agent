
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, firestore

# Firebase 인증키 위치
BASE_DIR = Path(__file__).resolve().parent
KEY_FILE = BASE_DIR / "firebase-service-account.json"

def main():
    if not KEY_FILE.exists():
        print("오류: Firebase 인증키 파일이 없습니다.")
        return

    # Firebase 연결
    cred = credentials.Certificate(str(KEY_FILE))

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)

    db = firestore.client()

    # 연결 확인을 위한 테스트 문서 저장
    db.collection("connection_test").document("python_test").set({
        "status": "success",
        "message": "M1-2 Firebase 연결 성공"
    })

    print("Firebase 연결 성공!")
    print("Firestore 테스트 데이터 저장 완료!")

if __name__ == "__main__":
    main()
