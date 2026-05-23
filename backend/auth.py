from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import requests as http_requests
import pymysql
import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer
from google import genai
import torch
import warnings
import os
import time
import logging
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import shutil
import uuid
from PyPDF2 import PdfReader
import tempfile
import asyncio


# .env에서 API 키/DB 설정을 로드한다.
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")
warnings.filterwarnings("ignore")

# 크로마DB 경로 및 모델 경로 환경변수화 (없으면 기본값)
CRIMINAL_DB_PATH = os.getenv("CRIMINAL_DB_PATH", str(BASE_DIR / "criminal_law_db"))
CRIMINAL_COLLECTION_NAME = os.getenv("CRIMINAL_COLLECTION_NAME", "criminal_laws")
CIVIL_DB_PATH = os.getenv("CIVIL_DB_PATH", str(BASE_DIR / "civil_law_db"))
CIVIL_COLLECTION_NAME = os.getenv("CIVIL_COLLECTION_NAME", "civil_laws")
SBERT_MODEL_NAME = os.getenv("SBERT_MODEL_NAME", "snunlp/KR-SBERT-V40K-klueNLI-augSTS")
CROSS_ENCODER_MODEL_NAME = os.getenv("CROSS_ENCODER_MODEL_NAME", "bongsoo/albert-small-kor-cross-encoder-v1")
GEMINI_API_KEY = (os.getenv("GEMINI_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()

# 모델/DB 클라이언트 전역 캐싱
_model_sbert = None
_cross_encoder = None
_criminal_collection = None
_civil_collection = None
_genai_client = None
LAW_NAME_CACHE = {}

def get_model_sbert():
    global _model_sbert
    if _model_sbert is None:
        device_type = 'cuda' if torch.cuda.is_available() else 'cpu'
        _model_sbert = SentenceTransformer(SBERT_MODEL_NAME, device=device_type)
    return _model_sbert

def get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        device_type = 'cuda' if torch.cuda.is_available() else 'cpu'
        _cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL_NAME, device=device_type)
    return _cross_encoder

def get_criminal_collection():
    global _criminal_collection
    if _criminal_collection is None:
        client = chromadb.PersistentClient(path=CRIMINAL_DB_PATH)
        _criminal_collection = client.get_collection(name=CRIMINAL_COLLECTION_NAME)
    return _criminal_collection

def get_civil_collection():
    global _civil_collection
    if _civil_collection is None:
        client = chromadb.PersistentClient(path=CIVIL_DB_PATH)
        _civil_collection = client.get_collection(name=CIVIL_COLLECTION_NAME)
    return _civil_collection

def get_genai_client():
    global _genai_client
    if _genai_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY (or GEMINI_KEY) is required")
        _genai_client = genai.Client(api_key=GEMINI_API_KEY)
    return _genai_client

def get_korean_law_name(law_id):
    law_id_str = str(law_id)
    if law_id_str in LAW_NAME_CACHE:
        return LAW_NAME_CACHE[law_id_str]
    url_law = f"https://www.law.go.kr/DRF/lawService.do?OC=workohl2&target=law&ID={law_id_str}&type=XML"
    url_eflaw = f"https://www.law.go.kr/DRF/lawService.do?OC=workohl2&target=eflaw&ID={law_id_str}&type=XML"
    urls_to_try = [url_law, url_eflaw]
    for url in urls_to_try:
        try:
            response = http_requests.get(url, timeout=3)
            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                law_name_node = root.find('.//법령명_한글')
                if law_name_node is not None and law_name_node.text:
                    law_name = law_name_node.text.strip()
                    LAW_NAME_CACHE[law_id_str] = law_name
                    return law_name
        except Exception:
            continue
    return f"형사법령(번호:{law_id_str})"

def rewrite_query(user_query):
    prompt_text = (
        "다음 사용자의 질문을 법령 검색 시스템에 입력하기 적합한 공식적인 법률 용어와 명확한 문장으로 재작성하십시오.\n"
        "단, 질문의 원래 의도를 절대 훼손하지 마십시오.\n"
        "출력은 오직 재작성된 질문 문장 하나만 반환하십시오.\n\n"
        f"원본 질문: {user_query}"
    )
    response = get_genai_client().models.generate_content(
        model='gemini-3.1-flash-lite',
        contents=prompt_text
    )
    return response.text.strip()

def get_chroma_results(collection, user_embedding, domain_label, n_results=10):
    results = collection.query(
        query_embeddings=[user_embedding],
        n_results=n_results
    )
    parsed_results = []
    if not results['metadatas'][0]:
        return parsed_results
    for i in range(len(results['metadatas'][0])):
        meta = results['metadatas'][0][i]
        doc_text = results['documents'][0][i]
        doc_id = results['ids'][0][i]
        if domain_label == "형사법":
            law_id = meta.get('law_id')
            if law_id:
                law_title = get_korean_law_name(law_id)
            else:
                law_title = meta.get('source', '형사법령')
        else:
            law_title = meta.get('statute_name', '민사법령')
        parsed_results.append({
            "statute_id": doc_id,
            "domain": domain_label,
            "law_title": law_title,
            "content": doc_text,
            "distance": results['distances'][0][i]
        })
    return parsed_results

app = FastAPI()

@app.post("/api/law-search")
async def law_search(
    query: str = Body(..., embed=True),
    case_type: str = Body("all", embed=True),
    n_results: int = Body(20, embed=True)
):
    """
    키워드(질문)로 법령 검색 결과 반환
    Request: { "query": "...", "case_type": "criminal" | "civil" | "all", "n_results": 20 }
    Response: { "results": [ { statute_id, domain, law_title, content, distance } ] }
    """
    try:
        refined_query = rewrite_query(query)
        model_sbert = get_model_sbert()
        cross_encoder = get_cross_encoder()
        user_embedding = model_sbert.encode(refined_query).tolist()

        normalized_case_type = (case_type or "all").strip().lower()
        if normalized_case_type not in {"civil", "criminal", "all"}:
            raise HTTPException(status_code=400, detail="case_type은 civil, criminal, all 중 하나여야 합니다.")

        combined_candidates = []
        if normalized_case_type in {"criminal", "all"}:
            criminal_collection = get_criminal_collection()
            criminal_candidates = get_chroma_results(criminal_collection, user_embedding, "형사법", n_results=10)
            combined_candidates.extend(criminal_candidates)

        if normalized_case_type in {"civil", "all"}:
            civil_collection = get_civil_collection()
            civil_candidates = get_chroma_results(civil_collection, user_embedding, "민사법", n_results=10)
            combined_candidates.extend(civil_candidates)

        if not combined_candidates:
            return {"results": []}
        cross_inp = [[refined_query, c['content']] for c in combined_candidates]
        cross_scores = cross_encoder.predict(cross_inp)
        scored_statutes = list(zip(cross_scores, combined_candidates))
        scored_statutes.sort(key=lambda x: x[0], reverse=True)
        top_statutes = [statute for score, statute in scored_statutes[:n_results]]
        return {"results": top_statutes}
    except Exception as e:
        logger.exception(f"law-search 오류: {e}")
        raise HTTPException(status_code=500, detail=f"law-search 오류: {str(e)}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger("backend.auth")

if not logger.handlers:
    # 로그 레벨은 환경변수로 조절하고, 콘솔/파일 핸들러를 함께 사용한다.
    log_level = os.getenv("AUTH_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    log_file_path = Path(__file__).resolve().with_name("auth.log")
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
PUBLIC_LEGAL_API_URL = os.getenv("PUBLIC_LEGAL_API_URL")
PUBLIC_LEGAL_API_KEY = os.getenv("PUBLIC_LEGAL_API_KEY")
DOCUMENT_API_BASE_URL = os.getenv("DOCUMENT_API_BASE_URL", "http://localhost:8001")

if not GOOGLE_CLIENT_ID:
    raise RuntimeError("환경변수 GOOGLE_CLIENT_ID 가 설정되지 않았습니다.")


class GoogleTokenRequest(BaseModel):
    # Google One-Tap 로그인에서 받은 JWT credential 토큰.
    token: str


class RecordCreateRequest(BaseModel):
    # 기록 생성 요청의 사용자/사건 payload.
    google_sub: str
    record_case: str = "traffic_case"
    case_type: str = "civil"
    payload_case: dict
    location_case: str = ""


class RecordReplayRequest(BaseModel):
    # 저장 기록 재분석 요청 시 사용자 소유권 검증용.
    google_sub: str


class RecordLocationUpdateRequest(BaseModel):
    # CCTV 페이지에서 누적 주소 문자열을 업데이트할 때 사용.
    google_sub: str
    location_case: str


def get_db_connection():
    # 트랜잭션 제어를 위해 autocommit=False로 연결한다.
    return pymysql.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        port=int(os.getenv("DB_PORT", 3306)),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def safe_json_loads(value):
    # DB JSON 문자열/객체를 일관된 dict로 변환한다.
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def fallback_title(story: str) -> str:
    # AI 제목 생성 실패 시 사용할 안전한 기본 제목 생성기.
    cleaned = " ".join((story or "").split())
    if not cleaned:
        return "새 사건 기록"
    max_len = 24
    return cleaned[:max_len] + ("..." if len(cleaned) > max_len else "")


def generate_record_title(story: str, file_paths: list[str]) -> str:
    # 나의 기록 제목은 AI를 사용하지 않고 입력 본문 기반 규칙으로 생성한다.
    _ = file_paths
    return fallback_title(story)


def get_legal_analysis_from_public_api(story: str, file_paths: list[str]) -> tuple[list[str], list[dict]]:
    # 공공 법률 API 응답을 프론트 스키마(법령명/판례 목록)로 정규화한다.
    if not PUBLIC_LEGAL_API_URL or not PUBLIC_LEGAL_API_KEY:
        logger.info("공공법률정보 API 설정이 없어 빈 결과를 반환합니다.")
        return [], []

    try:
        query = story
        if file_paths:
            query = f"{story}\n첨부문서: {'; '.join(file_paths)}"

        response = http_requests.get(
            PUBLIC_LEGAL_API_URL,
            params={
                "serviceKey": PUBLIC_LEGAL_API_KEY,
                "query": query[:1500],
            },
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()

        items = data.get("items", []) if isinstance(data, dict) else []
        related_laws = []
        cases = []
        for item in items[:8]:
            law_name = item.get("lawName") or item.get("law")
            if law_name:
                related_laws.append(law_name)

            case_no = item.get("caseNo") or item.get("caseNumber") or "미상"
            verdict = item.get("verdict") or "참고"
            summary = item.get("summary") or item.get("content") or ""
            similarity = item.get("similarity")
            if similarity is None:
                similarity = max(50, 90 - (len(cases) * 5))

            cases.append(
                {
                    "caseNumber": case_no,
                    "verdict": verdict,
                    "similarity": int(similarity),
                    "description": summary[:300],
                }
            )

        deduped_laws = list(dict.fromkeys(related_laws))
        return deduped_laws, cases
    except Exception:
        logger.exception("공공법률정보 API 호출 실패")
        return [], []


def upsert_user(google_sub: str, email: str, name: str, picture_url: str | None):
    # Google 로그인 시 users 테이블에 신규/갱신 저장한다.
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (google_sub, email, name, picture_url, last_login_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    email = VALUES(email),
                    name = VALUES(name),
                    picture_url = VALUES(picture_url),
                    last_login_at = NOW()
                """,
                (google_sub, email, name, picture_url),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("users 업서트 실패")
        raise
    finally:
        conn.close()


def serialize_record(row: dict) -> dict:
    # DB row를 프론트 전달용 직렬화 객체로 변환한다.
    payload = safe_json_loads(row.get("payload_case"))

    created_at = row.get("created_at")
    updated_at = row.get("updated_at")
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    if isinstance(updated_at, datetime):
        updated_at = updated_at.isoformat()

    return {
        "id": row.get("id"),
        "google_sub": row.get("google_sub"),
        "record_case": row.get("record_case"),
        "case_type": row.get("case_type") or "civil",
        "payload_case": payload,
        "location_case": row.get("location_case") or "",
        "created_at": created_at,
        "updated_at": updated_at,
        "title": payload.get("title") or "제목 없음",
        "story": payload.get("story") or "",
        "file_paths": payload.get("file_paths") or [],
        "file_summaries": payload.get("file_summaries") or [],
        "extracted_keywords": payload.get("extracted_keywords") or {},
    }


@app.post("/api/auth/google")
async def google_login(request: GoogleTokenRequest):
    try:
        logger.debug("google_login called. token_length=%d", len(request.token))

        # 구글 JWT 토큰 검증 (서명/발급자/audience/만료 기본 검증 포함).
        user_info = id_token.verify_oauth2_token(
            request.token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID
        )

        # 프론트 타이머를 위해 만료 시각(exp)을 다시 계산한다.
        exp = user_info.get("exp", 0)
        now = int(time.time())

        if now > exp:
            logger.warning(
                "토큰 만료됨: email=%s exp=%s now=%s",
                user_info.get("email"), exp, now
            )
            raise HTTPException(
                status_code=401,
                detail="TOKEN_EXPIRED"  # 프론트에서 이 코드로 만료 구분
            )

        # 만료까지 남은 시간(초)을 함께 반환한다.
        expires_in = exp - now
        logger.info(
            "로그인 성공: %s (만료까지 %ds)",
            user_info.get("email"), expires_in
        )

        user_data = {
            "id":         user_info["sub"],
            "name":       user_info["name"],
            "email":      user_info["email"],
            "picture":    user_info["picture"],
            "expires_at": exp,        # 만료 시각 Unix timestamp → 프론트로 전달
        }

        try:
            # 로그인 성공 사용자를 DB에 업서트한다.
            upsert_user(
                google_sub=user_info["sub"],
                email=user_info.get("email", ""),
                name=user_info.get("name", ""),
                picture_url=user_info.get("picture"),
            )
        except Exception:
            raise HTTPException(status_code=500, detail="사용자 정보를 저장하지 못했습니다.")

        return {
            "success":    True,
            "user":       user_data,
            "expires_in": expires_in, # 남은 시간(초) → 프론트 타이머용
        }

    except HTTPException:
        raise

    except ValueError as e:
        err_str = str(e)
        logger.warning("토큰 검증 실패: %s", err_str)

        # verify_oauth2_token이 만료 토큰도 ValueError로 던짐
        if "Token expired" in err_str or "expired" in err_str.lower():
            raise HTTPException(status_code=401, detail="TOKEN_EXPIRED")

        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다.")

    except Exception:
        logger.exception("google_login 처리 중 예상치 못한 오류")
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다.")


@app.get("/api/health")
async def health_check():
    # 인증 API 헬스체크 엔드포인트.
    return {"status": "ok"}


@app.post("/api/records")
async def create_record(request: RecordCreateRequest):
    if not request.google_sub.strip():
        raise HTTPException(status_code=401, detail="로그인 사용자 정보가 필요합니다.")

    # payload를 정규화하고 제목을 생성한다.
    payload_case = request.payload_case or {}
    story = str(payload_case.get("story") or payload_case.get("polishedStory") or "")
    file_paths = payload_case.get("file_paths") or payload_case.get("files") or []
    if not isinstance(file_paths, list):
        file_paths = []

    title = generate_record_title(story, file_paths)
    payload_case["title"] = title
    payload_case["story"] = story
    payload_case["file_paths"] = file_paths
    case_type = request.case_type if request.case_type in {"civil", "criminal"} else "civil"

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_records (google_sub, record_case, case_type, payload_case, location_case)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    request.google_sub,
                    request.record_case,
                    case_type,
                    json.dumps(payload_case, ensure_ascii=False),
                    request.location_case or "",
                ),
            )
            record_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("기록 생성 실패")
        raise HTTPException(status_code=500, detail="기록 저장 중 오류가 발생했습니다.")
    finally:
        conn.close()

    return {
        "success": True,
        "record_id": record_id,
        "title": title,
        "case_type": case_type,
    }


@app.get("/api/records")
async def list_records(google_sub: str, q: str = ""):
    if not google_sub.strip():
        raise HTTPException(status_code=401, detail="로그인 사용자 정보가 필요합니다.")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            if q.strip():
                # 제목/본문/장소를 LIKE로 검색한다.
                query = """
                    SELECT id, google_sub, record_case, payload_case, location_case, created_at, updated_at
                    , case_type
                    FROM user_records
                    WHERE google_sub = %s
                      AND (
                          JSON_UNQUOTE(JSON_EXTRACT(payload_case, '$.title')) LIKE %s
                          OR JSON_UNQUOTE(JSON_EXTRACT(payload_case, '$.story')) LIKE %s
                          OR location_case LIKE %s
                      )
                    ORDER BY updated_at DESC
                """
                like_q = f"%{q.strip()}%"
                cursor.execute(query, (google_sub, like_q, like_q, like_q))
            else:
                query = """
                    SELECT id, google_sub, record_case, payload_case, location_case, created_at, updated_at
                    , case_type
                    FROM user_records
                    WHERE google_sub = %s
                    ORDER BY updated_at DESC
                """
                cursor.execute(query, (google_sub,))

            rows = cursor.fetchall()
        return {"records": [serialize_record(row) for row in rows]}
    except Exception:
        logger.exception("기록 조회 실패")
        raise HTTPException(status_code=500, detail="기록 조회 중 오류가 발생했습니다.")
    finally:
        conn.close()


@app.patch("/api/records/{record_id}/location")
async def update_record_location(record_id: int, request: RecordLocationUpdateRequest):
    if not request.google_sub.strip():
        raise HTTPException(status_code=401, detail="로그인 사용자 정보가 필요합니다.")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE user_records
                SET
                    location_case = %s,
                    payload_case = JSON_SET(payload_case, '$.location_case', %s)
                WHERE id = %s AND google_sub = %s
                """,
                (request.location_case.strip(), request.location_case.strip(), record_id, request.google_sub),
            )
            affected = cursor.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("기록 location 업데이트 실패")
        raise HTTPException(status_code=500, detail="기록 업데이트 중 오류가 발생했습니다.")
    finally:
        conn.close()

    if affected == 0:
        raise HTTPException(status_code=404, detail="해당 기록을 찾을 수 없습니다.")

    return {"success": True}


@app.post("/api/records/{record_id}/rerun")
async def rerun_record(record_id: int, request: RecordReplayRequest):
    if not request.google_sub.strip():
        raise HTTPException(status_code=401, detail="로그인 사용자 정보가 필요합니다.")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, google_sub, record_case, payload_case, location_case, created_at, updated_at
                    , case_type
                FROM user_records
                WHERE id = %s AND google_sub = %s
                LIMIT 1
                """,
                (record_id, request.google_sub),
            )
            row = cursor.fetchone()
    except Exception:
        logger.exception("재실행용 기록 조회 실패")
        raise HTTPException(status_code=500, detail="기록 조회 중 오류가 발생했습니다.")
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="해당 기록을 찾을 수 없습니다.")

    record = serialize_record(row)
    story = record.get("story", "")
    file_paths = record.get("file_paths", [])

    # 저장된 사건 본문으로 법령/판례 분석을 재생성한다.
    related_laws, cases = get_legal_analysis_from_public_api(story, file_paths)

    return {
        "success": True,
        "record": record,
        "result_payload": {
            "polishedStory": story,
            "savedFilePaths": file_paths,
            "relatedLaws": related_laws,
            "cases": cases,
            "recordId": record["id"],
            "locationCase": record.get("location_case") or "",
            "caseType": record.get("case_type") or "civil",
            "generatedTitle": record.get("title") or "제목 없음",
            "extractedKeywords": {
                "success": True,
                "keywords": record.get("extracted_keywords") or {},
                "file_summaries": record.get("file_summaries") or [],
                "message": "저장된 분석 결과",
            },
        },
    }


@app.delete("/api/records/{record_id}")
async def delete_record(record_id: int, google_sub: str):
    # 사용자 소유 기록만 삭제할 수 있도록 google_sub 조건을 함께 사용한다.
    if not google_sub.strip():
        raise HTTPException(status_code=401, detail="로그인 사용자 정보가 필요합니다.")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM user_records WHERE id = %s AND google_sub = %s",
                (record_id, google_sub),
            )
            affected = cursor.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("기록 삭제 실패")
        raise HTTPException(status_code=500, detail="기록 삭제 중 오류가 발생했습니다.")
    finally:
        conn.close()

    if affected == 0:
        raise HTTPException(status_code=404, detail="해당 기록을 찾을 수 없습니다.")

    return {"success": True}


# ========== PDF 텍스트 추출 및 키워드 추출 기능 ==========

def extract_text_from_pdf(pdf_content: bytes) -> str:
    """
    PDF 바이너리 데이터에서 텍스트를 추출합니다.
    
    Args:
        pdf_content (bytes): PDF 파일의 바이너리 데이터
    
    Returns:
        str: 추출된 텍스트
    """
    try:
        from io import BytesIO
        pdf_file = BytesIO(pdf_content)
        pdf_reader = PdfReader(pdf_file)
        
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        
        return text.strip()
    except Exception as e:
        logger.exception(f"PDF 텍스트 추출 실패: {e}")
        return ""


def convert_document_to_pdf(file_content: bytes, file_name: str) -> bytes:
    """
    문서 파일을 PDF로 변환합니다. (document_transform 서버 이용)
    
    Args:
        file_content (bytes): 원본 파일의 바이너리 데이터
        file_name (str): 파일명
    
    Returns:
        bytes: PDF 파일의 바이너리 데이터 또는 빈 bytes
    """
    try:
        # 임시 파일 생성
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as tmp_file:
            tmp_file.write(file_content)
            tmp_path = tmp_file.name
        
        try:
            # document_transform 서버에 전송
            with open(tmp_path, "rb") as f:
                files = {"file": (file_name, f)}
                response = http_requests.post(
                    f"{DOCUMENT_API_BASE_URL}/transform",
                    files=files,
                    timeout=30
                )
            
            if response.status_code == 200:
                return response.content
            else:
                logger.warning(f"문서 변환 실패: status_code={response.status_code}")
                return b""
        finally:
            # 임시 파일 정리
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    
    except Exception as e:
        logger.exception(f"문서 변환 중 오류: {e}")
        return b""


@app.post("/api/extract-keywords")
async def extract_keywords(
    prompt: str = Form(...),
    files: list[UploadFile] = File(default=[])
):
    """
    사건 프롬프트와 첨부 파일(선택사항)에서 핵심 키워드를 추출합니다.
    
    Request:
        prompt (str): 사용자 사건 프롬프트
        file (UploadFile): 첨부 문서 (선택사항)
    
    Response:
        {
            "success": bool,
            "keywords": dict,
            "message": str,
            "file_text": str (추출된 파일 텍스트)
        }
    """
    try:
        if not prompt or not prompt.strip():
            raise HTTPException(status_code=400, detail="사건 프롬프트가 필요합니다.")

        logger.info(
            "키워드 요청 수신: prompt_len=%d, prompt_preview=%s",
            len(prompt.strip()),
            prompt.strip().replace("\n", " ")[:120],
        )
        
        merged_file_texts = []
        file_documents = []

        # 파일이 있으면 파일별로 처리
        if files:
            logger.info("첨부 파일 %d개 처리 시작", len(files))

            for file in files:
                if not file or not file.filename:
                    continue

                logger.info("파일 처리 중: %s", file.filename)
                pdf_content = b""
                file_text = ""

                file_content = await file.read()
                if not file_content:
                    file_documents.append(
                        {
                            "file_name": file.filename,
                            "text": "",
                            "status": "empty",
                        }
                    )
                    continue

                file_ext = os.path.splitext(file.filename)[1].lower()
                logger.info("첨부 파일 정보: name=%s, ext=%s, size=%d", file.filename, file_ext, len(file_content))

                if file_ext == ".pdf":
                    pdf_content = file_content
                else:
                    logger.info("문서 변환 중: %s", file.filename)
                    pdf_content = convert_document_to_pdf(file_content, file.filename)
                    if not pdf_content:
                        logger.warning("문서 변환 실패: %s", file.filename)

                if pdf_content:
                    file_text = extract_text_from_pdf(pdf_content)
                    logger.info("파일에서 %d 자 텍스트 추출: %s", len(file_text), file.filename)

                if file_text:
                    merged_file_texts.append(f"[{file.filename}]\n{file_text[:2500]}")

                file_documents.append(
                    {
                        "file_name": file.filename,
                        "text": file_text[:7000] if file_text else "",
                        "status": "ok" if file_text else "no_text",
                    }
                )
        else:
            logger.info("첨부 파일 없음 - 사용자 입력 프롬프트만으로 키워드 추출 진행")

        combined_file_text = "\n\n".join(merged_file_texts)

        # gemini.py의 함수 호출하여 핵심 키워드 추출
        from backend.gemini import extract_keywords_from_case
        from backend.gemini_record import summarize_attached_documents
        
        result = extract_keywords_from_case(
            user_prompt=prompt.strip(),
            file_text=combined_file_text[:8000] if combined_file_text else ""
        )

        summary_result = summarize_attached_documents(
            user_prompt=prompt.strip(),
            file_documents=file_documents,
        )
        file_summaries = summary_result.get("file_summaries", [])
        
        if result.get("success"):
            logger.info("키워드 추출 성공: %s", result.get("message"))
        else:
            logger.warning("키워드 추출 실패: %s", result.get("message"))

        logger.info(
            "키워드 결과 payload: %s",
            json.dumps(result.get("keywords", []), ensure_ascii=False)[:1200],
        )
        
        return {
            "success": result.get("success", False),
            "keywords": result.get("keywords", []),
            "message": result.get("message", "처리 완료"),
            "file_text_length": len(combined_file_text),
            "file_text_preview": combined_file_text[:500] if combined_file_text else "",
            "file_summaries": file_summaries,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"키워드 추출 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"키워드 추출 중 오류가 발생했습니다: {str(e)}")


@app.post("/api/case-search")
async def case_search(
    query: str = Body(..., embed=True),
    case_type: str = Body("civil", embed=True),
    n_results: int = Body(20, embed=True)
):
    """
    키워드로 판례(형사/민사) 검색
    Request: { "query": "...", "case_type": "criminal" | "civil", "n_results": 20 }
    Response: { "cases": [ { caseNumber, case_name, description, source } ] }
    """
    try:
        if case_type == "criminal":
            from backend.Criminal import search_criminal_cases
            cases = search_criminal_cases(query, n_results=n_results)
            logger.info(f"형사 판례 검색 완료: {len(cases)}건")
            return {"cases": cases}
        else:  # civil
            from backend.Civil import search_civil_cases_async
            cases = await search_civil_cases_async(query, n_results=n_results)
            logger.info(f"민사 판례 검색 완료: {len(cases)}건")
            return {"cases": cases}
    except Exception as e:
        logger.exception(f"판례 검색 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"판례 검색 중 오류: {str(e)}")