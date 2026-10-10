
from pathlib import Path
import os

import firebase_admin
from firebase_admin import credentials, firestore
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, Field
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel

from datetime import datetime, timezone
from typing import Any

# --------------------------------------------------
# 1. FastAPI 서버 생성
# --------------------------------------------------

app = FastAPI(
    title="Spindle Bearing AI Agent",
    description="공작기계 주축 진동 데이터 분석 API",
    version="1.0.0"
)

# 개발 단계 CORS 설정
# 배포 단계에서는 실제 프론트엔드 주소로 제한합니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:5500"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# 2. Firebase 연결
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

KEY_FILE = BASE_DIR / "firebase-service-account.json"

if not firebase_admin._apps:
    if KEY_FILE.exists():
        cred = credentials.Certificate(str(KEY_FILE))
        firebase_admin.initialize_app(cred)
    else:
        # Render 배포 시 환경 변수 기반 인증
        import json
        service_account = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")

        if not service_account:
            raise RuntimeError("Firebase 인증 정보가 없습니다.")

        cred = credentials.Certificate(json.loads(service_account))
        firebase_admin.initialize_app(cred)

db = firestore.client()

# OpenAI 환경 변수 로드
load_dotenv(BASE_DIR / ".env")

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-4.1-mini"
)

# --------------------------------------------------
# 3. 서버 상태 확인
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "status": "running",
        "service": "Spindle Bearing AI Agent",
        "message": "FastAPI 서버가 정상 작동 중입니다."
    }

# --------------------------------------------------
# 4. 진동 데이터 목록 조회
# --------------------------------------------------

@app.get("/api/data")
def get_data(
    rpm: int | None = Query(default=None),
    axis: str | None = Query(default=None)
):
    try:
        query = db.collection("data")

        if rpm is not None:
            query = query.where("rpm", "==", rpm)

        if axis is not None:
            axis = axis.upper()
            if axis not in ("X", "Y", "Z"):
                raise HTTPException(
                    status_code=422,
                    detail="axis는 X, Y, Z 중 하나여야 합니다."
                )
            query = query.where("axis", "==", axis)

        records = []

        for doc in query.stream():
            record = doc.to_dict()
            record["id"] = doc.id
            records.append(record)

        records.sort(
            key=lambda x: (
                x.get("elapsed_seconds", 0),
                x.get("axis", "")
            )
        )

        return {
            "count": len(records),
            "data": records
        }

    except HTTPException:
        raise
    except Exception as e:
        print("데이터 조회 오류:", str(e))
        raise HTTPException(
            status_code=500,
            detail="데이터 조회 중 오류가 발생했습니다."
        )

# --------------------------------------------------
# 5. 진동 데이터 요약
# --------------------------------------------------

@app.get("/api/data/summary")
def get_summary():
    try:
        docs = db.collection("data").stream()
        records = [doc.to_dict() for doc in docs]

        if not records:
            return {
                "count": 0,
                "message": "저장된 데이터가 없습니다."
            }

        values = [
            float(r["value"])
            for r in records
            if r.get("value") is not None
        ]

        if not values:
            return {
                "count": len(records),
                "message": "유효한 RMS 값이 없습니다."
            }

        rpm_summary = {}

        for rpm in (1000, 2000, 3000):
            subset = [
                float(r["value"])
                for r in records
                if r.get("rpm") == rpm
                and r.get("value") is not None
            ]

            if subset:
                rpm_summary[str(rpm)] = {
                    "count": len(subset),
                    "average_rms": round(
                        sum(subset) / len(subset), 6
                    ),
                    "max_rms": round(max(subset), 6),
                    "min_rms": round(min(subset), 6)
                }

        return {
            "count": len(records),
            "unit": "m/s²",
            "average_rms": round(
                sum(values) / len(values), 6
            ),
            "max_rms": round(max(values), 6),
            "min_rms": round(min(values), 6),
            "rpm_summary": rpm_summary
        }

    except Exception as e:
        print("데이터 요약 오류:", str(e))
        raise HTTPException(
            status_code=500,
            detail="데이터 요약 중 오류가 발생했습니다."
        )


# --------------------------------------------------
# 6. 데이터 입력 형식 정의
# --------------------------------------------------

class VibrationData(BaseModel):
    date: str = Field(min_length=1)
    value: float = Field(ge=0)
    memo: str = ""
    rpm: Optional[int] = Field(default=None, gt=0)
    axis: Optional[str] = None


# --------------------------------------------------
# 7. 새로운 진동 데이터 추가 (CREATE)
# --------------------------------------------------

@app.post("/api/data", status_code=201)
def create_data(data: VibrationData):
    try:
        record = data.model_dump()

        if record["axis"] is not None:
            record["axis"] = record["axis"].upper()

            if record["axis"] not in ("X", "Y", "Z"):
                raise HTTPException(
                    status_code=422,
                    detail="axis는 X, Y, Z만 가능합니다."
                )

        doc_ref = db.collection("data").document()
        doc_ref.set(record)

        return {
            "message": "데이터 추가 성공",
            "id": doc_ref.id,
            "data": record
        }

    except HTTPException:
        raise
    except Exception as e:
        print("데이터 추가 오류:", str(e))
        raise HTTPException(
            status_code=500,
            detail="데이터 추가 실패"
        )


# --------------------------------------------------
# 8. 진동 데이터 수정 (UPDATE)
# --------------------------------------------------

@app.put("/api/data/{data_id}")
def update_data(data_id: str, data: VibrationData):
    try:
        doc_ref = db.collection("data").document(data_id)
        snapshot = doc_ref.get()

        if not snapshot.exists:
            raise HTTPException(
                status_code=404,
                detail="해당 데이터가 없습니다."
            )

        record = data.model_dump()

        if record["axis"] is not None:
            record["axis"] = record["axis"].upper()

            if record["axis"] not in ("X", "Y", "Z"):
                raise HTTPException(
                    status_code=422,
                    detail="axis는 X, Y, Z만 가능합니다."
                )

        # 기존 RMS 데이터의 보조 필드도 함께 동기화
        if "acc_rms_m_s2" in snapshot.to_dict():
            record["acc_rms_m_s2"] = record["value"]

        doc_ref.update(record)

        return {
            "message": "데이터 수정 성공",
            "id": data_id
        }

    except HTTPException:
        raise
    except Exception as e:
        print("데이터 수정 오류:", str(e))
        raise HTTPException(
            status_code=500,
            detail="데이터 수정 실패"
        )


# --------------------------------------------------
# 9. 진동 데이터 삭제 (DELETE)
# --------------------------------------------------

@app.delete("/api/data/{data_id}")
def delete_data(data_id: str):
    try:
        doc_ref = db.collection("data").document(data_id)
        snapshot = doc_ref.get()

        if not snapshot.exists:
            raise HTTPException(
                status_code=404,
                detail="해당 데이터가 없습니다."
            )

        doc_ref.delete()

        return {
            "message": "데이터 삭제 성공",
            "id": data_id
        }

    except HTTPException:
        raise
    except Exception as e:
        print("데이터 삭제 오류:", str(e))
        raise HTTPException(
            status_code=500,
            detail="데이터 삭제 실패"
        )



# --------------------------------------------------
# 10. AI 채팅 요청 데이터 형식
# --------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


# --------------------------------------------------
# 11. RPM별 / 방향별 진동 데이터 요약
# --------------------------------------------------

def build_vibration_context():
    docs = db.collection("data").stream()
    records = [doc.to_dict() for doc in docs]

    if not records:
        return "저장된 진동 데이터가 없습니다."

    lines = [
        "공작기계 V-MCT 주축 진동 분석 데이터",
        f"전체 데이터 수: {len(records)}개",
        "측정 단위: 가속도 RMS (m/s²)",
        "각 값은 0.1초 구간의 RMS입니다.",
    ]

    for rpm in (1000, 2000, 3000):
        for axis in ("X", "Y", "Z"):
            values = [
                float(r["value"])
                for r in records
                if r.get("rpm") == rpm
                and r.get("axis") == axis
                and r.get("value") is not None
            ]

            if not values:
                continue

            average = sum(values) / len(values)

            lines.append(
                f"{rpm} RPM / {axis}방향: "
                f"데이터 {len(values)}개, "
                f"평균 RMS {average:.6f}, "
                f"최대 {max(values):.6f}, "
                f"최소 {min(values):.6f}"
            )

    return "\n".join(lines)


# --------------------------------------------------
# 12. AI 채팅 API
# --------------------------------------------------


@app.post("/api/chat")
def chat(request: ChatRequest):
    try:
        context = build_vibration_context()
        collection = db.collection("conversations")

        # 기존 대화가 있으면 불러오기
        previous_messages = []
        conversation_ref = None

        if request.conversation_id:
            conversation_ref = collection.document(
                request.conversation_id
            )
            snapshot = conversation_ref.get()

            if not snapshot.exists:
                raise HTTPException(
                    status_code=404,
                    detail="대화 기록이 없습니다."
                )

            previous_messages = snapshot.to_dict().get(
                "messages", []
            )

        # GPT에 전달할 대화 내용 구성
        messages = []

        for msg in previous_messages[-10:]:
            role = msg.get("role")
            content = msg.get("content")

            if role in ("user", "assistant") and isinstance(
                content, str
            ):
                messages.append({
                    "role": role,
                    "content": content
                })

        messages.append({
            "role": "user",
            "content": request.message
        })

        system_prompt = f"""
당신은 공작기계 주축 진동 분석 전문 AI 비서입니다.

다음은 실제 측정 데이터에서 계산한 진동 요약입니다.

{context}

답변 규칙:
1. 한국어로 답변합니다.
2. 제공된 측정 데이터를 근거로 설명합니다.
3. RMS 단위는 m/s²입니다.
4. RPM 및 X/Y/Z 방향별 차이를 분석합니다.
5. 없는 측정값을 추측하지 않습니다.
6. RMS만으로 베어링 결함을 확정하지 않습니다.
7. BSF 관련 측정 결과가 없으면 분석 불가를 설명합니다.
8. 이전 대화 문맥을 참고하되 실제 측정값을 우선합니다.
"""

        response = client.responses.create(
            model=OPENAI_MODEL,
            instructions=system_prompt,
            input=messages,
            max_output_tokens=700
        )

        answer = response.output_text

        now = datetime.now(timezone.utc).isoformat()

        new_messages = previous_messages + [
            {
                "role": "user",
                "content": request.message
            },
            {
                "role": "assistant",
                "content": answer
            }
        ]

        if conversation_ref is None:
            conversation_ref = collection.document()

            conversation_ref.set({
                "title": request.message[:50],
                "messages": new_messages,
                "created_at": now,
                "updated_at": now
            })
        else:
            conversation_ref.update({
                "messages": new_messages,
                "updated_at": now
            })

        return {
            "question": request.message,
            "answer": answer,
            "model": OPENAI_MODEL,
            "conversation_id": conversation_ref.id
        }

    except HTTPException:
        raise
    except Exception as e:
        print("AI 채팅 오류:", str(e))
        raise HTTPException(
            status_code=500,
            detail="AI 답변 생성 중 오류가 발생했습니다."
        )


# --------------------------------------------------
# 13. 대화 기록 저장 데이터 형식
# --------------------------------------------------

class ConversationCreate(BaseModel):
    title: str = Field(default="새 대화", min_length=1)
    messages: list[dict[str, Any]] = Field(
        default_factory=list
    )


# --------------------------------------------------
# 14. 대화 기록 저장
# --------------------------------------------------

@app.post("/api/conversations", status_code=201)
def create_conversation(data: ConversationCreate):
    try:
        now = datetime.now(timezone.utc).isoformat()

        record = {
            "title": data.title,
            "messages": data.messages,
            "created_at": now,
            "updated_at": now
        }

        doc_ref = db.collection("conversations").document()
        doc_ref.set(record)

        return {
            "message": "대화 저장 성공",
            "id": doc_ref.id,
            "data": record
        }

    except Exception as e:
        print("대화 저장 오류:", str(e))
        raise HTTPException(
            status_code=500,
            detail="대화 저장 실패"
        )


# --------------------------------------------------
# 15. 대화 기록 목록 조회
# --------------------------------------------------

@app.get("/api/conversations")
def get_conversations():
    try:
        records = []

        for doc in db.collection("conversations").stream():
            data = doc.to_dict()
            records.append({
                "id": doc.id,
                "title": data.get("title", "새 대화"),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "message_count": len(
                    data.get("messages", [])
                )
            })

        records.sort(
            key=lambda x: x.get("updated_at") or "",
            reverse=True
        )

        return {
            "count": len(records),
            "conversations": records
        }

    except Exception as e:
        print("대화 조회 오류:", str(e))
        raise HTTPException(
            status_code=500,
            detail="대화 목록 조회 실패"
        )


# --------------------------------------------------
# 16. 특정 대화 기록 불러오기
# --------------------------------------------------

@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    try:
        doc = (
            db.collection("conversations")
            .document(conversation_id)
            .get()
        )

        if not doc.exists:
            raise HTTPException(
                status_code=404,
                detail="대화 기록이 없습니다."
            )

        return {
            "id": doc.id,
            **doc.to_dict()
        }

    except HTTPException:
        raise
    except Exception as e:
        print("대화 불러오기 오류:", str(e))
        raise HTTPException(
            status_code=500,
            detail="대화 불러오기 실패"
        )


# --------------------------------------------------
# 17. 대화 기록 삭제
# --------------------------------------------------

@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str):
    try:
        doc_ref = (
            db.collection("conversations")
            .document(conversation_id)
        )

        if not doc_ref.get().exists:
            raise HTTPException(
                status_code=404,
                detail="대화 기록이 없습니다."
            )

        doc_ref.delete()

        return {
            "message": "대화 삭제 성공",
            "id": conversation_id
        }

    except HTTPException:
        raise
    except Exception as e:
        print("대화 삭제 오류:", str(e))
        raise HTTPException(
            status_code=500,
            detail="대화 삭제 실패"
        )
