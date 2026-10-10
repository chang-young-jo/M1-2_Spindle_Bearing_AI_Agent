"""Spindle Bearing AI Agent — FastAPI backend (local / Render)."""
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import firebase_admin
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import credentials, firestore
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator
from bearing_analysis import analyze_fft_peaks

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
logger = logging.getLogger(__name__)

app = FastAPI(title='Spindle Bearing AI Agent', description='공작기계 주축 진동 데이터 분석 API', version='1.1.0')
local_origins = ['http://localhost:5500', 'http://127.0.0.1:5500', 'http://localhost:3000', 'https://m1-2spindlebearingaiagent-frontend.vercel.app']
extra_origins = [s.strip().rstrip('/') for s in os.getenv('FRONTEND_ORIGINS', '').split(',') if s.strip()]
app.add_middleware(CORSMiddleware, allow_origins=local_origins + extra_origins,
                   allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
                   allow_headers=['Content-Type'])

if not firebase_admin._apps:
    raw_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', '').strip()
    key_file = BASE_DIR / 'firebase-service-account.json'
    if raw_json:
        try:
            cred = credentials.Certificate(json.loads(raw_json))
        except (ValueError, TypeError) as exc:
            raise RuntimeError('FIREBASE_SERVICE_ACCOUNT_JSON 형식이 올바르지 않습니다.') from exc
    elif key_file.is_file():
        cred = credentials.Certificate(str(key_file))
    else:
        raise RuntimeError('Firebase 인증 정보가 없습니다. 로컬 JSON 또는 FIREBASE_SERVICE_ACCOUNT_JSON을 설정하세요.')
    firebase_admin.initialize_app(cred)

db = firestore.client()
api_key = os.getenv('OPENAI_API_KEY', '').strip()
client = OpenAI(api_key=api_key) if api_key else None
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')
ORIGINAL_RECORD_ID = re.compile(r'^vibration_\d{4}$')


def protect_original(data_id: str) -> None:
    if ORIGINAL_RECORD_ID.fullmatch(data_id):
        raise HTTPException(status_code=403, detail='원본 측정 데이터는 수정하거나 삭제할 수 없습니다.')


def numeric_records(records: list[dict]) -> list[dict]:
    clean = []
    for record in records:
        try:
            value = float(record.get('value'))
            if value >= 0 and value < float('inf'):
                clean.append({**record, 'value': value})
        except (ValueError, TypeError):
            continue
    return clean


def summarize(values: list[float]) -> dict:
    return {'count': len(values), 'average_rms': round(sum(values) / len(values), 6),
            'max_rms': round(max(values), 6), 'min_rms': round(min(values), 6)}


@app.get('/')
def home():
    return {'status': 'running', 'service': 'Spindle Bearing AI Agent',
            'message': 'FastAPI 서버가 정상 작동 중입니다.'}


@app.get('/api/data')
def get_data(rpm: int | None = Query(default=None), axis: str | None = Query(default=None)):
    if axis is not None:
        axis = axis.upper()
        if axis not in ('X', 'Y', 'Z'):
            raise HTTPException(status_code=422, detail='axis는 X, Y, Z 중 하나여야 합니다.')
    try:
        records = []
        for doc in db.collection('data').stream():
            record = doc.to_dict() or {}
            if rpm is not None and record.get('rpm') != rpm:
                continue
            if axis is not None and record.get('axis') != axis:
                continue
            records.append({'id': doc.id, **record})
        records.sort(key=lambda x: (float(x.get('elapsed_seconds') or 0), str(x.get('axis') or '')))
        return {'count': len(records), 'data': records}
    except Exception as exc:
        logger.exception('데이터 조회 오류')
        raise HTTPException(status_code=500, detail='데이터 조회 중 오류가 발생했습니다.') from exc


@app.get('/api/data/summary')
def get_summary():
    try:
        records = [doc.to_dict() or {} for doc in db.collection('data').stream()]
        valid = numeric_records(records)
        if not records:
            return {'count': 0, 'message': '저장된 데이터가 없습니다.'}
        if not valid:
            return {'count': len(records), 'message': '유효한 RMS 값이 없습니다.'}
        rpm_summary = {}
        for rpm in (1000, 2000, 3000):
            values = [r['value'] for r in valid if r.get('rpm') == rpm]
            if values:
                rpm_summary[str(rpm)] = summarize(values)
        result = summarize([r['value'] for r in valid])
        result.update({'count': len(records), 'unit': 'm/s²', 'rpm_summary': rpm_summary})
        return result
    except Exception as exc:
        logger.exception('데이터 요약 오류')
        raise HTTPException(status_code=500, detail='데이터 요약 중 오류가 발생했습니다.') from exc


class VibrationData(BaseModel):
    date: str = Field(min_length=1)
    value: float = Field(ge=0, allow_inf_nan=False)
    memo: str = ''
    rpm: int | None = Field(default=None, gt=0)
    axis: str | None = None

    @field_validator('axis')
    @classmethod
    def validate_axis(cls, value):
        if value is None:
            return None
        value = value.upper()
        if value not in ('X', 'Y', 'Z'):
            raise ValueError('axis는 X, Y, Z만 가능합니다.')
        return value


@app.post('/api/data', status_code=201)
def create_data(data: VibrationData):
    try:
        record = data.model_dump()
        doc_ref = db.collection('data').document()
        doc_ref.set(record)
        return {'message': '데이터 추가 성공', 'id': doc_ref.id, 'data': record}
    except Exception as exc:
        logger.exception('데이터 추가 오류')
        raise HTTPException(status_code=500, detail='데이터 추가 실패') from exc


@app.put('/api/data/{data_id}')
def update_data(data_id: str, data: VibrationData):
    protect_original(data_id)
    try:
        doc_ref = db.collection('data').document(data_id)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            raise HTTPException(status_code=404, detail='해당 데이터가 없습니다.')
        record = data.model_dump()
        if 'acc_rms_m_s2' in (snapshot.to_dict() or {}):
            record['acc_rms_m_s2'] = record['value']
        doc_ref.update(record)
        return {'message': '데이터 수정 성공', 'id': data_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception('데이터 수정 오류')
        raise HTTPException(status_code=500, detail='데이터 수정 실패') from exc


@app.delete('/api/data/{data_id}')
def delete_data(data_id: str):
    protect_original(data_id)
    try:
        doc_ref = db.collection('data').document(data_id)
        if not doc_ref.get().exists:
            raise HTTPException(status_code=404, detail='해당 데이터가 없습니다.')
        doc_ref.delete()
        return {'message': '데이터 삭제 성공', 'id': data_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception('데이터 삭제 오류')
        raise HTTPException(status_code=500, detail='데이터 삭제 실패') from exc


class BearingAnalyzeRequest(BaseModel):
    rpm: float = Field(gt=0)
    peak_frequencies_hz: list[float] = Field(default_factory=list, max_length=20000)
    tolerance_hz: float = Field(default=1.0, ge=0, le=100)


@app.post('/api/bearing/analyze')
def bearing_analyze(request: BearingAnalyzeRequest):
    try:
        return analyze_fft_peaks(
            rpm=request.rpm,
            peak_frequencies_hz=request.peak_frequencies_hz,
            tolerance_hz=request.tolerance_hz,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    bearing_analysis: dict[str, Any] | None = None


def build_vibration_context():
    records = [doc.to_dict() or {} for doc in db.collection('data').stream()]
    if not records:
        return '저장된 진동 데이터가 없습니다.'
    valid = numeric_records(records)
    lines = ['공작기계 V-MCT 주축 진동 분석 데이터', f'전체 데이터 수: {len(records)}개',
             '측정 단위: 가속도 RMS (m/s²)', '각 값은 0.1초 구간의 RMS입니다.']
    for rpm in (1000, 2000, 3000):
        for axis in ('X', 'Y', 'Z'):
            values = [r['value'] for r in valid if r.get('rpm') == rpm and r.get('axis') == axis]
            if values:
                lines.append(f'{rpm} RPM / {axis}방향: 데이터 {len(values)}개, '
                             f'평균 RMS {sum(values)/len(values):.6f}, '
                             f'최대 {max(values):.6f}, 최소 {min(values):.6f}')
    return '\n'.join(lines)


@app.post('/api/chat')
def chat(request: ChatRequest):
    if client is None:
        raise HTTPException(status_code=503, detail='OPENAI_API_KEY가 설정되지 않았습니다.')
    try:
        context = build_vibration_context()
        if request.bearing_analysis is not None:
            # A user-supplied analysis is not a verified measurement. Recalculate matches
            # server-side from only the RPM and candidate peak frequencies.
            supplied = request.bearing_analysis
            try:
                analysis = analyze_fft_peaks(
                    rpm=float(supplied['rpm']),
                    peak_frequencies_hz=supplied['peak_frequencies_hz'],
                    tolerance_hz=1.0,
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise HTTPException(status_code=422, detail='bearing_analysis 형식이 올바르지 않습니다.') from exc
            context += ('\n추가로 전달된 FFT 후보 피크 분석 결과(측정 출처 미검증):\n'
                        + json.dumps(analysis, ensure_ascii=False))
        collection = db.collection('conversations')
        previous_messages = []
        conversation_ref = None
        if request.conversation_id:
            conversation_ref = collection.document(request.conversation_id)
            snapshot = conversation_ref.get()
            if not snapshot.exists:
                raise HTTPException(status_code=404, detail='대화 기록이 없습니다.')
            previous_messages = (snapshot.to_dict() or {}).get('messages', [])
        messages = []
        for msg in previous_messages[-10:]:
            role, content = msg.get('role'), msg.get('content')
            if role in ('user', 'assistant') and isinstance(content, str):
                messages.append({'role': role, 'content': content})
        messages.append({'role': 'user', 'content': request.message})
        system_prompt = f'''당신은 공작기계 주축 진동 분석 전문 AI 비서입니다.
다음은 실제 측정 데이터에서 계산한 진동 요약입니다.
{context}
답변 규칙:
1. 한국어로 답변합니다.
2. 제공된 측정 데이터를 근거로 설명합니다.
3. RMS 단위는 m/s²입니다.
4. RPM 및 X/Y/Z 방향별 차이를 분석합니다.
5. 없는 측정값을 추측하지 않습니다.
6. RMS만으로 베어링 결함을 확정하지 않습니다.
7. FFT 후보 피크가 제공되지 않으면 BSF 등 결함 주파수 측정 결과는 없다고 설명합니다.
9. 제공된 FFT 후보 피크와 이론 주파수 차이가 ±1 Hz 이내면 주파수 일치로 판단합니다. 주파수 일치만으로 베어링 결함을 확정하지 않습니다.
10. 별도로 제공된 FFT 후보 피크는 측정 출처가 검증되지 않은 입력값임을 명시합니다.
8. 이전 대화 문맥을 참고하되 실제 측정값을 우선합니다.'''
        response = client.responses.create(model=OPENAI_MODEL, instructions=system_prompt,
                                           input=messages, max_output_tokens=700)
        answer = response.output_text
        now = datetime.now(timezone.utc).isoformat()
        new_messages = previous_messages + [
            {'role': 'user', 'content': request.message},
            {'role': 'assistant', 'content': answer}]
        if conversation_ref is None:
            conversation_ref = collection.document()
            conversation_ref.set({'title': request.message[:50], 'messages': new_messages,
                                  'created_at': now, 'updated_at': now})
        else:
            conversation_ref.update({'messages': new_messages, 'updated_at': now})
        return {'question': request.message, 'answer': answer, 'model': OPENAI_MODEL,
                'conversation_id': conversation_ref.id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception('AI 채팅 오류')
        raise HTTPException(status_code=500, detail='AI 답변 생성 중 오류가 발생했습니다.') from exc


class ConversationCreate(BaseModel):
    title: str = Field(default='새 대화', min_length=1)
    messages: list[dict[str, Any]] = Field(default_factory=list)


@app.post('/api/conversations', status_code=201)
def create_conversation(data: ConversationCreate):
    try:
        now = datetime.now(timezone.utc).isoformat()
        record = {'title': data.title, 'messages': data.messages,
                  'created_at': now, 'updated_at': now}
        doc_ref = db.collection('conversations').document()
        doc_ref.set(record)
        return {'message': '대화 저장 성공', 'id': doc_ref.id, 'data': record}
    except Exception as exc:
        logger.exception('대화 저장 오류')
        raise HTTPException(status_code=500, detail='대화 저장 실패') from exc


@app.get('/api/conversations')
def get_conversations():
    try:
        records = []
        for doc in db.collection('conversations').stream():
            data = doc.to_dict() or {}
            records.append({'id': doc.id, 'title': data.get('title', '새 대화'),
                            'created_at': data.get('created_at'),
                            'updated_at': data.get('updated_at'),
                            'message_count': len(data.get('messages', []))})
        records.sort(key=lambda x: x.get('updated_at') or '', reverse=True)
        return {'count': len(records), 'conversations': records}
    except Exception as exc:
        logger.exception('대화 조회 오류')
        raise HTTPException(status_code=500, detail='대화 목록 조회 실패') from exc


@app.get('/api/conversations/{conversation_id}')
def get_conversation(conversation_id: str):
    try:
        doc = db.collection('conversations').document(conversation_id).get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail='대화 기록이 없습니다.')
        return {'id': doc.id, **(doc.to_dict() or {})}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception('대화 불러오기 오류')
        raise HTTPException(status_code=500, detail='대화 불러오기 실패') from exc


@app.delete('/api/conversations/{conversation_id}')
def delete_conversation(conversation_id: str):
    try:
        doc_ref = db.collection('conversations').document(conversation_id)
        if not doc_ref.get().exists:
            raise HTTPException(status_code=404, detail='대화 기록이 없습니다.')
        doc_ref.delete()
        return {'message': '대화 삭제 성공', 'id': conversation_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception('대화 삭제 오류')
        raise HTTPException(status_code=500, detail='대화 삭제 실패') from exc
