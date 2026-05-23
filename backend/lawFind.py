import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer
from google import genai
import torch
import os
import warnings
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from dotenv import load_dotenv

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")

# API 설정
GEMINI_API_KEY = os.getenv("GEMINI_KEY") or os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

# 크로마DB 경로 설정 (실제 경로에 맞게 수정 필요)
CRIMINAL_DB_PATH = os.getenv("CRIMINAL_DB_PATH", str(BASE_DIR / "criminal_law_db"))
CRIMINAL_COLLECTION_NAME = "criminal_laws"

CIVIL_DB_PATH = os.getenv("CIVIL_DB_PATH", str(BASE_DIR / "civil_law_db"))
CIVIL_COLLECTION_NAME = "civil_laws"

# 법령명 API 캐싱 딕셔너리 (중복 호출 방지)
LAW_NAME_CACHE = {}


def get_korean_law_name(law_id):
    law_id_str = str(law_id)

    # 이미 캐시에 법령명이 있다면 바로 반환
    if law_id_str in LAW_NAME_CACHE:
        return LAW_NAME_CACHE[law_id_str]

    # 1차 시도: 일반 법령(target=law)으로 XML 요청
    url_law = f"https://www.law.go.kr/DRF/lawService.do?OC=workohl2&target=law&ID={law_id_str}&type=XML"

    # 2차 시도: 시행 법령(target=eflaw)으로 XML 요청
    url_eflaw = f"https://www.law.go.kr/DRF/lawService.do?OC=workohl2&target=eflaw&ID={law_id_str}&type=XML"

    urls_to_try = [url_law, url_eflaw]

    for url in urls_to_try:
        try:
            response = requests.get(url, timeout=3)
            if response.status_code == 200:
                # XML 데이터 파싱
                root = ET.fromstring(response.content)

                # XPath를 사용하여 법령명_한글 태그 검색
                law_name_node = root.find('.//법령명_한글')

                if law_name_node is not None and law_name_node.text:
                    law_name = law_name_node.text.strip()
                    LAW_NAME_CACHE[law_id_str] = law_name
                    return law_name
        except Exception:
            # 네트워크 오류나 파싱 오류 발생 시 다음 URL 시도
            continue

    # 모든 API 호출 실패 시 기본 반환값
    return f"형사법령(번호:{law_id_str})"


def rewrite_query(user_query):
    prompt_text = (
        "다음 사용자의 질문을 법령 검색 시스템에 입력하기 적합한 공식적인 법률 용어와 명확한 문장으로 재작성하십시오.\n"
        "단, 질문의 원래 의도를 절대 훼손하지 마십시오.\n"
        "출력은 오직 재작성된 질문 문장 하나만 반환하십시오.\n\n"
        f"원본 질문: {user_query}"
    )
    response = client.models.generate_content(
        model='gemini-3.1-flash-lite',
        contents=prompt_text
    )
    return response.text.strip()


def generate_gemini_answer(user_query, retrieved_statutes):
    context_text = ""
    for idx, stat in enumerate(retrieved_statutes):
        context_text += f"[법령 {idx + 1}] 분류: {stat['domain']} / 법령명: {stat['law_title']} / 내용: {stat['content']}\n\n"

    prompt_text = (
        "당신은 전문적이고 친절한 AI 법률 어시스턴트입니다. "
        "반드시 아래에 제공된 참고 법령 조문만을 바탕으로 사용자의 질문에 대한 종합적인 답변을 한국어로 작성하십시오. "
        "거짓된 정보를 지어내지 마시고, 답변에는 어떤 법령을 참고했는지 법령명과 함께 명확히 언급하십시오.\n\n"
        f"현재 질문:\n{user_query}\n\n"
        f"참고 법령:\n{context_text}\n"
        "최종 답변:\n"
    )

    response = client.models.generate_content(
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

        # 도메인별 법령명 처리
        if domain_label == "형사법":
            law_id = meta.get('law_id')
            if law_id:
                # 크로마DB에 저장된 법령일련번호를 통해 API에서 한글 법령명 추출 (XML 방식)
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


def main():
    device_type = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"현재 인식된 연산 장치: {device_type.upper()}")

    print("AI 모델(SentenceTransformer) 및 리랭킹 모델 로딩 중...")
    model_sbert = SentenceTransformer('snunlp/KR-SBERT-V40K-klueNLI-augSTS', device=device_type)
    cross_encoder = CrossEncoder('bongsoo/albert-small-kor-cross-encoder-v1', device=device_type)

    print("두 개의 ChromaDB에 연결합니다.")
    criminal_client = chromadb.PersistentClient(path=CRIMINAL_DB_PATH)
    criminal_collection = criminal_client.get_collection(name=CRIMINAL_COLLECTION_NAME)

    civil_client = chromadb.PersistentClient(path=CIVIL_DB_PATH)
    civil_collection = civil_client.get_collection(name=CIVIL_COLLECTION_NAME)

    print(f"데이터베이스 연결 완료. 형사법 DB: {criminal_collection.count()}건, 민사법 DB: {civil_collection.count()}건")

    while True:
        raw_user_input = input("\n질문을 입력하세요 (종료하려면 exit 입력): ")
        if raw_user_input.lower() == 'exit':
            break

        print("\n단계 1: 질의 재작성 중...")
        refined_query = rewrite_query(raw_user_input)
        print("원본 질문:", raw_user_input)
        print("재작성된 질의:", refined_query)

        print("\n단계 2: 형사 및 민사 벡터 DB에서 후보군 통합 검색 중 (법제처 API 연동)...")
        user_embedding = model_sbert.encode(refined_query).tolist()

        criminal_candidates = get_chroma_results(criminal_collection, user_embedding, "형사법", n_results=10)
        civil_candidates = get_chroma_results(civil_collection, user_embedding, "민사법", n_results=10)

        combined_candidates = criminal_candidates + civil_candidates

        if not combined_candidates:
            print("데이터베이스가 비어있거나 검색 결과가 없습니다.")
            continue

        print("\n단계 3: 크로스 인코더를 통한 정밀 리랭킹 중...")
        cross_inp = []

        for candidate in combined_candidates:
            cross_inp.append([refined_query, candidate['content']])

        cross_scores = cross_encoder.predict(cross_inp)

        scored_statutes = list(zip(cross_scores, combined_candidates))
        scored_statutes.sort(key=lambda x: x[0], reverse=True)

        top_5_statutes = [statute for score, statute in scored_statutes[:5]]

        print("\n[상위 5개 법령 조문 검색 결과]")
        for idx, stat in enumerate(top_5_statutes):
            print(f"{idx + 1}. 분야: {stat['domain']} / 법령명: {stat['law_title']}")
            print(f"   내용: {stat['content']}...\n")

        print("단계 4: 최종 답변 생성 중...")
        final_answer = generate_gemini_answer(refined_query, top_5_statutes)

        print("\n최종 법률 분석 리포트")
        print(final_answer)


if __name__ == "__main__":
    main()
