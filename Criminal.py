import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer
from google import genai
import torch
import pymysql
import json
import os
import warnings
from pathlib import Path
from dotenv import load_dotenv
import requests
import xml.etree.ElementTree as ET

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_KEY") or os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

DB_PERSIST_PATH = os.getenv("CRIMINAL_PRECEDENT_DB_PATH", str(BASE_DIR / "chromadb_snunlp"))
COLLECTION_NAME = "legal_data_snunlp"
LAW_API_KEY = os.getenv("LAW_API_KEY", "workohl2")

MYSQL_CONFIG = {
    'host': os.getenv('DB_HOST', '155.230.235.248'),
    'port': int(os.getenv('DB_PORT', 32065)),
    'user': os.getenv('DB_USER', 'jsy1098'),
    'password': os.getenv('DB_PASSWORD', ''),
    'charset': 'utf8mb4'
}
MYSQL_DB_NAME = os.getenv('DB_NAME', 'finalDB')


def init_mysql_db():
    print("MySQL 데이터베이스 초기화를 시작합니다.")
    conn = pymysql.connect(
        host=MYSQL_CONFIG['host'],
        port=MYSQL_CONFIG['port'],
        user=MYSQL_CONFIG['user'],
        password=MYSQL_CONFIG['password'],
        charset=MYSQL_CONFIG['charset']
    )
    cursor = conn.cursor()

    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {MYSQL_DB_NAME}")
    conn.select_db(MYSQL_DB_NAME)

    table_create_sql = """
    CREATE TABLE IF NOT EXISTS chat_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id VARCHAR(255) NOT NULL,
        raw_user_input TEXT NOT NULL,
        refined_query TEXT NOT NULL,
        retrieved_cases TEXT,
        ai_response TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    cursor.execute(table_create_sql)
    conn.commit()
    conn.close()
    print("MySQL 테이블 세팅이 완료되었습니다.")


def get_user_chat_history(user_id, limit=3):
    conn = pymysql.connect(
        host=MYSQL_CONFIG['host'],
        port=MYSQL_CONFIG['port'],
        user=MYSQL_CONFIG['user'],
        password=MYSQL_CONFIG['password'],
        database=MYSQL_DB_NAME,
        charset=MYSQL_CONFIG['charset']
    )
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    select_sql = """
    SELECT raw_user_input, ai_response 
    FROM chat_logs 
    WHERE user_id = %s 
    ORDER BY created_at DESC 
    LIMIT %s
    """
    cursor.execute(select_sql, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()

    rows = list(rows)
    rows.reverse()

    history_text = ""
    if rows:
        history_text += "과거 대화 맥락:\n"
        for row in rows:
            history_text += f"사용자: {row['raw_user_input']}\n"
            history_text += f"AI: {row['ai_response']}\n\n"

    return history_text


def save_log_to_mysql(user_id, raw_input, refined_query, retrieved_cases, ai_response):
    conn = pymysql.connect(
        host=MYSQL_CONFIG['host'],
        port=MYSQL_CONFIG['port'],
        user=MYSQL_CONFIG['user'],
        password=MYSQL_CONFIG['password'],
        database=MYSQL_DB_NAME,
        charset=MYSQL_CONFIG['charset']
    )
    cursor = conn.cursor()

    cases_summary = [f"{case['precedId']}_{case['case_name']}" for case in retrieved_cases]
    cases_json = json.dumps(cases_summary, ensure_ascii=False)

    insert_sql = """
    INSERT INTO chat_logs (user_id, raw_user_input, refined_query, retrieved_cases, ai_response) 
    VALUES (%s, %s, %s, %s, %s)
    """
    cursor.execute(insert_sql, (user_id, raw_input, refined_query, cases_json, ai_response))
    conn.commit()
    conn.close()


def rewrite_query(user_query):
    prompt_text = (
        "다음 사용자의 일상적인 질문을 법률 검색 시스템에 입력하기 적합한 공식적인 법률 용어와 명확한 문장으로 재작성하십시오.\n"
        "단, 질문의 원래 의도를 절대 훼손하지 마십시오.\n"
        "출력은 오직 재작성된 질문 문장 하나만 반환하십시오.\n\n"
        f"원본 질문: {user_query}"
    )
    response = client.models.generate_content(
        model='gemini-3.1-flash-lite',
        contents=prompt_text
    )
    return response.text.strip()


def _extract_node_text(node):
    if node is None:
        return ""
    return " ".join(part.strip() for part in node.itertext() if part and part.strip())


def _build_original_case_text(root):
    sections = []
    seen_texts = set()
    section_paths = [
        ("사건번호", ".//사건번호"),
        ("사건명", ".//사건명"),
        ("선고일자", ".//선고일자"),
        ("법원명", ".//법원명"),
        ("사건종류명", ".//사건종류명"),
        ("판시사항", ".//판시사항"),
        ("판결요지", ".//판결요지"),
        ("참조조문", ".//참조조문"),
        ("참조판례", ".//참조판례"),
        ("주문", ".//주문"),
        ("이유", ".//이유"),
        ("판례이유", ".//판례이유"),
        ("판결문전문", ".//판결문전문"),
        ("전문", ".//전문"),
    ]

    for label, path in section_paths:
        text = _extract_node_text(root.find(path))
        if not text or text in seen_texts:
            continue
        sections.append(f"[{label}]\n{text}")
        seen_texts.add(text)

    if sections:
        return "\n\n".join(sections)

    return _extract_node_text(root)


CASE_DETAIL_CACHE = {}
INVALID_CASE_RESPONSE_MARKERS = (
    "일치하는 판례가 없습니다",
    "판례명을 확인",
    "유효하지 않은",
    "서비스키",
    "인증키",
)


def _extract_preced_id(value):
    if value is None:
        return ""

    value_str = str(value).strip()
    if not value_str:
        return ""

    # 판례 본문 조회는 판례일련번호(숫자)만 허용한다.
    return value_str if value_str.isdigit() else ""


def _resolve_preced_id(raw_id, meta):
    meta = meta or {}
    candidate_keys = (
        "precedId",
        "preced_id",
        "판례일련번호",
        "prec_id",
    )

    for key in candidate_keys:
        extracted = _extract_preced_id(meta.get(key))
        if extracted:
            return extracted

    # ids에 chunk suffix(예: 238253_0)가 붙는 경우를 위해 마지막 fallback으로만 사용.
    # 메타데이터에 명시된 일련번호가 없으면, raw id가 숫자일 때만 사용한다.
    return _extract_preced_id(raw_id)


def _is_invalid_case_response(root, original_text):
    status_text = _extract_node_text(root.find('.//성공여부')).lower()
    if status_text in ("false", "n", "no", "0"):
        return True

    message_candidates = [
        _extract_node_text(root.find('.//메시지')),
        _extract_node_text(root.find('.//message')),
        original_text,
    ]
    merged_message = " ".join(token for token in message_candidates if token).lower()
    return any(marker.lower() in merged_message for marker in INVALID_CASE_RESPONSE_MARKERS)


def get_case_detail_by_id(preced_id):
    preced_id_str = _extract_preced_id(preced_id)

    if not preced_id_str:
        return {}

    if preced_id_str in CASE_DETAIL_CACHE:
        return CASE_DETAIL_CACHE[preced_id_str]

    url = "https://www.law.go.kr/DRF/lawService.do"
    params = {
        "OC": LAW_API_KEY,
        "target": "prec",
        "type": "XML",
        "ID": preced_id_str,
    }

    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        original_text = _build_original_case_text(root)

        # API 실패 메시지가 본문으로 노출되지 않도록 즉시 폴백한다.
        if _is_invalid_case_response(root, original_text):
            return {}

        case_detail = {
            "caseNumber": _extract_node_text(root.find('.//사건번호')) or preced_id_str,
            "case_name": _extract_node_text(root.find('.//사건명')),
            "originalText": original_text,
        }
        CASE_DETAIL_CACHE[preced_id_str] = case_detail
        return case_detail
    except (requests.exceptions.RequestException, ET.ParseError):
        return {}


def search_criminal_cases(keyword, n_results=5):
    """키워드로 형사 판례를 검색하고 상위 N개 반환"""
    device_type = 'cuda' if torch.cuda.is_available() else 'cpu'
    model_sbert = SentenceTransformer('snunlp/KR-SBERT-V40K-klueNLI-augSTS', device=device_type)
    cross_encoder = CrossEncoder('bongsoo/albert-small-kor-cross-encoder-v1', device=device_type)
    
    chroma_client = chromadb.PersistentClient(path=DB_PERSIST_PATH)
    collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)
    
    refined_query = rewrite_query(keyword)
    user_embedding = model_sbert.encode(refined_query).tolist()
    
    results = collection.query(
        query_embeddings=[user_embedding],
        n_results=15
    )
    
    if not results['metadatas'][0]:
        return []
    
    cross_inp = []
    cases_temp = []
    
    for i in range(len(results['metadatas'][0])):
        meta = results['metadatas'][0][i]
        doc_text = results['documents'][0][i]
        case_name = meta.get('caseName', '알 수 없음')
        raw_case_id = results['ids'][0][i]
        preced_id = _resolve_preced_id(raw_case_id, meta)
        case_number = _extract_preced_id(meta.get('caseNumber')) or preced_id or str(raw_case_id)
        
        cross_inp.append([refined_query, doc_text])
        cases_temp.append({
            "precedId": preced_id or str(raw_case_id),
            "caseNumber": case_number,
            "case_name": case_name,
            "description": doc_text,
            "originalText": doc_text,
            "source": "db"
        })
    
    cross_scores = cross_encoder.predict(cross_inp)
    scored_cases = list(zip(cross_scores, cases_temp))
    scored_cases.sort(key=lambda x: x[0], reverse=True)

    top_cases = []
    for _, case in scored_cases[:n_results]:
        case_detail = get_case_detail_by_id(case['precedId'])
        original_text = case_detail.get('originalText') or case['originalText']
        top_cases.append({
            **case,
            "precedId": _extract_preced_id(case.get('precedId')) or case.get('precedId'),
            "caseNumber": case_detail.get('caseNumber') or case['caseNumber'],
            "case_name": case_detail.get('case_name') or case['case_name'],
            "description": original_text,
            "originalText": original_text,
        })

    return top_cases


def generate_gemini_answer(user_id, user_query, retrieved_cases):
    chat_history = get_user_chat_history(user_id)

    context_text = ""
    for idx, case in enumerate(retrieved_cases):
        case_num = case.get('real_case_number', case['precedId'])
        context_text += f"[판례 {idx + 1}] 사건번호: {case['case_num']} / 사건명: {case['case_name']} / 요약: {case['output_text']}\n\n"

    prompt_text = (
        "당신은 전문적이고 친절한 AI 법률 어시스턴트입니다. "
        "반드시 아래에 제공된 참고 판례만을 바탕으로 사용자의 질문에 대한 종합적인 답변을 한국어로 작성하십시오. "
        "거짓된 정보를 지어내지 마시고, 답변에는 어떤 판례를 참고했는지 일련번호(precedId)와 함께 명확히 언급하십시오.\n"
        "또한 제공된 과거 대화 맥락이 있다면 이를 고려하여 자연스럽게 답변하십시오.\n\n"
        f"{chat_history}"
        f"현재 질문:\n{user_query}\n\n"
        f"참고 판례:\n{context_text}\n"
        "최종 답변:\n"
    )

    response = client.models.generate_content(
        model='gemini-3.1-flash-lite',
        contents=prompt_text
    )
    return response.text.strip()

def get_case_number_by_id(preced_id):#    일련번호를 통해 국가법령정보 API에서 사건번호를 조회하는 함수
    preced_id_str = str(preced_id)
    case_detail = get_case_detail_by_id(preced_id_str)
    return case_detail.get("caseNumber") or f"조회불가(일련번호:{preced_id_str})"

def main():
    init_mysql_db()

    device_type = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"현재 인식된 연산 장치: {device_type.upper()}")

    print("AI 모델(SentenceTransformer) 및 리랭킹 모델 로딩 중...")
    model_sbert = SentenceTransformer('snunlp/KR-SBERT-V40K-klueNLI-augSTS', device=device_type)
    cross_encoder = CrossEncoder('bongsoo/albert-small-kor-cross-encoder-v1', device=device_type)

    print("ChromaDB에 연결합니다.")
    chroma_client = chromadb.PersistentClient(path=DB_PERSIST_PATH)
    collection = chroma_client.get_or_create_collection(name=COLLECTION_NAME)

    print("데이터베이스 연결 완료. 총 데이터 개수:", collection.count())

    DISTANCE_THRESHOLD = 100.0

    current_user_id = input("\n웹에서 로그인한 구글 이메일을 입력하세요 (테스트용): ")
    print(f"[{current_user_id}] 사용자의 세션을 시작합니다.")

    while True:
        raw_user_input = input("\n질문을 입력하세요 (종료하려면 exit 입력): ")
        if raw_user_input.lower() == 'exit':
            break

        print("\n단계 1: 질의 재작성 중...")
        refined_query = rewrite_query(raw_user_input)
        print("원본 질문:", raw_user_input)
        print("재작성된 질의:", refined_query)

        print("\n단계 2: 벡터 DB에서 1차 후보군 15건 검색 중...")

        user_embedding = model_sbert.encode(refined_query).tolist()

        results = collection.query(
            query_embeddings=[user_embedding],
            n_results=15
        )

        if not results['metadatas'][0]:
            print("데이터베이스가 비어있거나 검색 결과가 없습니다.")
            continue

        best_distance = results['distances'][0][0]
        if best_distance > DISTANCE_THRESHOLD:
            print(f"가장 유사한 판례의 거리({round(best_distance, 4)})가 한계치({DISTANCE_THRESHOLD})를 초과했습니다.")
            print("안전한 법률 조언을 위해 답변 생성을 중단합니다. 질문을 더 구체적으로 작성해 주세요.")
            continue

        print("\n단계 4: 크로스 인코더를 통한 정밀 리랭킹 중...")
        cross_inp = []
        cases_temp = []

        for i in range(len(results['metadatas'][0])):
            meta = results['metadatas'][0][i]
            doc_text = results['documents'][0][i]
            case_name = meta.get('caseName', '알 수 없음')
            raw_case_id = results['ids'][0][i]
            preced_id = _resolve_preced_id(raw_case_id, meta)
            case_number = _extract_preced_id(meta.get('caseNumber')) or preced_id or str(raw_case_id)

            cross_inp.append([refined_query, doc_text])
            cases_temp.append({
                "precedId": preced_id or str(raw_case_id),
                "caseNumber": case_number,
                "case_name": case_name,
                "output_text": doc_text
            })

        cross_scores = cross_encoder.predict(cross_inp)

        scored_cases = list(zip(cross_scores, cases_temp))
        scored_cases.sort(key=lambda x: x[0], reverse=True)

        top_5_cases = [case for score, case in scored_cases[:5]]

        print("\n[상위 5개 판례 검색 결과]")
        for idx, case in enumerate(top_5_cases):
            real_case_number = get_case_number_by_id(case['precedId'])
            case['real_case_number'] = real_case_number
            print(f"{idx + 1}. 사건번호: {real_case_number}")
            print(f"   사건명: {case['case_name']}")
            print(f"   판례 요약: {case['output_text']}\n")

        print("단계 5: 최종 답변 생성 중 (과거 맥락 포함)...")
        final_answer = generate_gemini_answer(current_user_id, refined_query, top_5_cases)

        print("\n최종 법률 분석 리포트")
        print(final_answer)

        print("\n단계 6: 대화 기록을 MySQL에 저장하는 중...")
        try:
            save_log_to_mysql(current_user_id, raw_user_input, refined_query, top_5_cases, final_answer)
            print("저장 완료.")
        except Exception as e:
            print("데이터베이스 저장 실패:", e)


if __name__ == "__main__":
    main()