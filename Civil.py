import os
import json
import warnings
import asyncio
import aiohttp
import requests
import xml.etree.ElementTree as ET
import torch
import pymysql
import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer
from google import genai
from pathlib import Path
from dotenv import load_dotenv

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_KEY") or os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

# 국가법령정보센터 API 인증키를 입력하세요
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
    CREATE TABLE IF NOT EXISTS chat_logs_civil (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id VARCHAR(255) NOT NULL,
        raw_user_input TEXT NOT NULL,
        refined_query TEXT NOT NULL,
        api_keyword TEXT NOT NULL,
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
    conn = pymysql.connect(**MYSQL_CONFIG, database=MYSQL_DB_NAME)
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    select_sql = """
    SELECT raw_user_input, ai_response 
    FROM chat_logs_civil 
    WHERE user_id = %s 
    ORDER BY created_at DESC LIMIT %s
    """
    cursor.execute(select_sql, (user_id, limit))
    rows = list(cursor.fetchall())
    conn.close()
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
    cursor.execute(insert_sql, (
        str(user_id),
        str(raw_input),
        str(refined_query),
        str(cases_json),
        str(ai_response)
    ))

    conn.commit()
    conn.close()


def rewrite_and_extract_keyword(user_query):
    prompt_text = (
        "다음 사용자의 질문을 분석하여 두 가지를 JSON 형식으로 반환하십시오.\n"
        "1. refined_query: 법률 검색에 적합한 명확한 공식 법률 문장\n"
        "2. api_keyword: 국가법령정보센터 API 목록 검색에 사용할 가장 핵심적인 단어 1~2개 (예: 손해배상, 자동차)\n\n"
        f"원본 질문: {user_query}\n\n"
        "출력형식: {\"refined_query\": \"...\", \"api_keyword\": \"...\"}"
    )
    response = client.models.generate_content(model='gemini-3.1-flash-lite', contents=prompt_text)
    try:
        cleaned_text = response.text.strip().replace("```json", "").replace("```", "")
        result = json.loads(cleaned_text)
        return result['refined_query'], result['api_keyword']
    except:
        return user_query, user_query.split()[0]


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


async def search_civil_cases_async(keyword, n_results=5):
    """키워드로 민사 판례를 검색하고 상위 N개 반환 (비동기)"""
    refined_query, api_keyword = rewrite_and_extract_keyword(keyword)
    
    # 국가법령정보센터 API에서 판례 ID 목록 조회
    url = "https://www.law.go.kr/DRF/lawSearch.do"
    params = {
        "OC": LAW_API_KEY,
        "target": "prec",
        "type": "XML",
        "search": 2,
        "query": api_keyword,
        "display": 20
    }
    response = requests.get(url, params=params)
    root = ET.fromstring(response.content)
    
    case_ids = []
    for prec in root.findall('.//prec'):
        case_type = prec.find('사건종류명')
        if case_type is not None and case_type.text == '민사':
            serial_no = prec.find('판례일련번호').text
            case_name = prec.find('사건명').text
            case_ids.append({"id": serial_no, "name": case_name})
    
    if not case_ids:
        return []
    
    # 비동기로 본문 데이터 가져오기
    detailed_cases = await fetch_all_details(case_ids[:n_results])
    
    # 반환 형식 통일
    result_cases = []
    for case in detailed_cases:
        result_cases.append({
            "precedId": case['id'],
            "caseNumber": case.get('case_number') or case['id'],
            "case_name": case['name'],
            "description": case['text'],
            "originalText": case['text'],
            "source": "web"
        })
    
    return result_cases


def fetch_civil_case_ids(keyword, max_display=20):
    print(f"API 목록 검색 요청 중 (키워드: {keyword})...")
    url = "https://www.law.go.kr/DRF/lawSearch.do"
    params = {
        "OC": LAW_API_KEY,
        "target": "prec",
        "type": "XML",
        "search": 2,
        "query": keyword,
        "display": max_display
    }
    response = requests.get(url, params=params)
    root = ET.fromstring(response.content)

    case_ids = []
    for prec in root.findall('.//prec'):
        case_type = prec.find('사건종류명')
        if case_type is not None and case_type.text == '민사':
            serial_no = prec.find('판례일련번호').text
            case_name = prec.find('사건명').text
            case_ids.append({"id": serial_no, "name": case_name})

    return case_ids


async def fetch_case_detail_async(session, case_info):
    url = "https://www.law.go.kr/DRF/lawService.do"
    params = {
        "OC": LAW_API_KEY,
        "target": "prec",
        "ID": case_info["id"],
        "type": "XML"
    }
    try:
        async with session.get(url, params=params) as response:
            xml_text = await response.text()
            root = ET.fromstring(xml_text)

            case_number = _extract_node_text(root.find('.//사건번호')) or case_info["id"]
            case_name = _extract_node_text(root.find('.//사건명')) or case_info["name"]
            content_text = _build_original_case_text(root)

            return {
                "id": case_info["id"],
                "case_number": case_number,
                "name": case_name,
                "text": content_text.strip()
            }
    except Exception as e:
        return None


async def fetch_all_details(case_list):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_case_detail_async(session, case) for case in case_list]
        results = await asyncio.gather(*tasks)
        return [res for res in results if res and res["text"]]


def generate_gemini_answer(user_id, user_query, retrieved_cases):
    chat_history = get_user_chat_history(user_id)
    context_text = ""
    for idx, case in enumerate(retrieved_cases):
        context_text += f"[판례 {idx + 1}] 일련번호: {case['precedId']} / 사건명: {case['case_name']}\n본문: {case['output_text']}\n\n"

    prompt_text = (
        "당신은 전문적이고 친절한 AI 법률 어시스턴트입니다. "
        "반드시 아래에 제공된 참고 판례만을 바탕으로 사용자의 질문에 대한 종합적인 답변을 한국어로 작성하십시오. "
        "거짓된 정보를 지어내지 마시고, 답변에는 어떤 판례를 참고했는지 일련번호(precedId)와 함께 명확히 언급하십시오.\n"
        f"{chat_history}"
        f"현재 질문:\n{user_query}\n\n"
        f"참고 판례:\n{context_text}\n"
        "최종 답변:\n"
    )
    response = client.models.generate_content(model='gemini-3.1-flash-lite', contents=prompt_text)
    return response.text.strip()


def main():
    init_mysql_db()

    device_type = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"현재 인식된 연산 장치: {device_type.upper()}")

    print("AI 모델(SentenceTransformer) 및 리랭킹 모델 로딩 중...")
    model_sbert = SentenceTransformer('snunlp/KR-SBERT-V40K-klueNLI-augSTS', device=device_type)
    cross_encoder = CrossEncoder('bongsoo/albert-small-kor-cross-encoder-v1', device=device_type)

    current_user_id = input("\n웹에서 로그인한 구글 이메일을 입력하세요 (테스트용): ")
    print(f"[{current_user_id}] 사용자의 세션을 시작합니다.")

    while True:
        raw_user_input = input("\n민사 질문을 입력하세요 (종료하려면 exit 입력): ")
        if raw_user_input.lower() == 'exit':
            break

        print("\n단계 1: 질의 분석 및 검색 키워드 추출 중...")
        refined_query, api_keyword = rewrite_and_extract_keyword(raw_user_input)
        print("재작성된 질의:", refined_query)
        print("추출된 API 키워드:", api_keyword)

        print("\n단계 2: 국가법령정보센터 목록 API 호출 (민사 사건 필터링)...")
        case_ids = fetch_civil_case_ids(api_keyword, max_display=20)

        if not case_ids:
            print("해당 키워드로 검색된 민사 판례가 없습니다. 다른 키워드로 질문해 주세요.")
            continue

        print(f"총 {len(case_ids)}건의 민사 판례 일련번호 확보 완료. 비동기 본문 다운로드를 시작합니다.")

        print("\n단계 3: 본문 API 병렬 호출 중 (속도 최적화)...")
        detailed_cases = asyncio.run(fetch_all_details(case_ids))
        print(f"총 {len(detailed_cases)}건의 판례 본문 데이터 수집 성공.")

        print("\n단계 4: 실시간 인메모리 벡터 데이터베이스 구성 중...")
        chroma_client = chromadb.Client()
        temp_collection = chroma_client.create_collection(name="temp_civil_cases")

        docs = [case['text'] for case in detailed_cases]
        metas = [{"caseName": case['name']} for case in detailed_cases]
        ids = [case['id'] for case in detailed_cases]

        # 모델을 사용하여 텍스트 리스트를 벡터 리스트로 직접 변환합니다.
        embeddings = model_sbert.encode(docs).tolist()
        temp_collection.add(documents=docs, metadatas=metas, ids=ids, embeddings=embeddings)

        print("\n단계 5: 사용자의 질문과 실시간 벡터 유사도 검사 중...")
        # 사용자 질문도 동일하게 직접 벡터로 변환합니다.
        user_embedding = model_sbert.encode([refined_query]).tolist()
        results = temp_collection.query(query_embeddings=user_embedding, n_results=5)

        print("\n단계 6: 크로스 인코더를 통한 정밀 리랭킹 중...")
        cross_inp = []
        cases_temp = []

        for i in range(len(results['metadatas'][0])):
            meta = results['metadatas'][0][i]
            doc_text = results['documents'][0][i]
            case_id = results['ids'][0][i]

            cross_inp.append([refined_query, doc_text])
            cases_temp.append({
                "precedId": case_id,
                "case_name": meta['caseName'],
                "output_text": doc_text
            })

        cross_scores = cross_encoder.predict(cross_inp)
        scored_cases = list(zip(cross_scores, cases_temp))
        scored_cases.sort(key=lambda x: x[0], reverse=True)
        top_3_cases = [case for score, case in scored_cases[:3]]

        print("\n[가장 유사한 상위 3개 판례 추출 완료]")
        for idx, case in enumerate(top_3_cases):
            print(f"{idx + 1}. 일련번호: {case['precedId']} - {case['case_name']}")

        print("\n단계 7: 최종 답변 생성 중...")
        final_answer = generate_gemini_answer(current_user_id, refined_query, top_3_cases)

        print("\n=== 최종 법률 분석 리포트 ===")
        print(final_answer)

        print("\n단계 8: 대화 기록을 MySQL에 저장하는 중...")
        try:
            save_log_to_mysql(current_user_id, raw_user_input, refined_query, api_keyword, top_3_cases, final_answer)
            print("저장 완료.")
        except Exception as e:
            print("데이터베이스 저장 실패:", e)

        chroma_client.delete_collection("temp_civil_cases")


if __name__ == "__main__":
    main()