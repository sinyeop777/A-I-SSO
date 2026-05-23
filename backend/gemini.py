import json
import logging
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

GEMINI_MODEL   = "gemini-3.1-flash-lite"

logger = logging.getLogger(__name__)

# Ensure .env is available even when this module is executed directly.
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")


def _get_gemini_api_key() -> str:
    return (os.getenv("GEMINI_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()


def _request_gemini_keywords(
    gemini_api_key: str,
    combined_input: str,
    system_instruction: str,
    max_output_tokens: int = 512,
) -> tuple[str, str]:
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={gemini_api_key}",
        headers={"Content-Type": "application/json"},
        json={
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingBudget": 0},
            },
            "contents": [
                {"role": "user", "parts": [{"text": combined_input}]}
            ],
        },
        timeout=25,
    )
    response.raise_for_status()
    data = response.json()
    candidate = data.get("candidates", [{}])[0]
    finish_reason = candidate.get("finishReason", "")
    response_text = (
        candidate
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
        .strip()
    )
    return response_text, finish_reason


def extract_keywords_from_case(user_prompt: str, file_text: str = "") -> dict:
    """
    교통사고 사건에서 핵심 키워드 2개를 추출합니다.

    Args:
        user_prompt: 사용자가 입력한 사건 프롬프트
        file_text  : 첨부 파일에서 추출한 텍스트

    Returns:
        {
            "success":  bool,
            "keywords": ["키워드1", "키워드2"],
            "message":  str
        }
    """
    gemini_api_key = _get_gemini_api_key()
    if not gemini_api_key:
        return {
            "success":  False,
            "keywords": [],
            "message":  "Gemini API 키가 설정되지 않았습니다.",
        }

    system_instruction = """
당신은 교통사고 전문 법률 AI 어시스턴트입니다.
사건 정보를 분석하여 법률적으로 가장 중요한 핵심 키워드 2개만 추출하세요.

[선정 기준]
1. 법적 책임을 결정짓는 핵심 행위 또는 위반 사항이어야 합니다.
2. 판례·법령 검색에 직접 활용 가능한 법률 용어여야 합니다.
3. 최대 5자 이내 단어 또는 짧은 구문이어야 합니다.
4. 사건에 명시된 내용만 추출하세요. 추측하지 마세요.

응답은 반드시 아래 JSON 형식만 반환하세요:
{
    "keywords": ["키워드1", "키워드2"]
}
"""

    # ── 텍스트 청킹 ──
    prompt_part = _smart_truncate(user_prompt, 1500)
    file_part   = _smart_truncate(file_text, 5000) if file_text.strip() else ""

    combined_input = f"사건 프롬프트:\n{prompt_part}"
    if file_part:
        combined_input += f"\n\n첨부 문서 텍스트:\n{file_part}"

    logger.info("키워드 추출 시작 (입력 %d자, 파일부분 %d자)", len(combined_input), len(file_part))
    if not combined_input.strip():
        logger.warning("입력 텍스트가 비어있습니다")
        return {
            "success": False,
            "keywords": [],
            "message": "사건 설명이 없습니다.",
        }

    try:
        response_text, finish_reason = _request_gemini_keywords(
            gemini_api_key=gemini_api_key,
            combined_input=combined_input,
            system_instruction=system_instruction,
            max_output_tokens=512,
        )
        if finish_reason and finish_reason != "STOP":
            logger.warning("Gemini finishReason=%s", finish_reason)

        # MAX_TOKENS로 응답이 잘린 경우, 더 간결한 지시문으로 1회 재시도
        if finish_reason == "MAX_TOKENS":
            compact_instruction = (
                "교통사고 사건에서 법률 키워드 2개를 뽑아 "
                '{"keywords":["키워드1","키워드2"]} JSON만 반환하세요. '
                "설명/코드블록/추가 문장 금지."
            )
            retry_text, retry_finish_reason = _request_gemini_keywords(
                gemini_api_key=gemini_api_key,
                combined_input=combined_input,
                system_instruction=compact_instruction,
                max_output_tokens=512,
            )
            if retry_finish_reason and retry_finish_reason != "STOP":
                logger.warning("Gemini retry finishReason=%s", retry_finish_reason)
            if retry_text:
                response_text = retry_text

        logger.debug("Gemini 원본 응답: %s", response_text[:200])
        if not response_text:
            logger.warning("Gemini 빈 응답 반환")
            return {
                "success":  False,
                "keywords": [],
                "message":  "모델이 빈 응답을 반환했습니다.",
            }

        try:
            parsed = _parse_json_response(response_text)
            raw_keywords = parsed.get("keywords", [])
        except json.JSONDecodeError as e:
            logger.error("JSON 파싱 오류: %s", str(e))
            return {
                "success": False,
                "keywords": [],
                "message": "JSON 파싱 실패: 응답 형식이 올바르지 않습니다.",
            }

        if isinstance(raw_keywords, str):
            keywords = [
                token.strip()
                for token in re.split(r"[,/\n]", raw_keywords)
                if token.strip()
            ]
        elif isinstance(raw_keywords, list):
            keywords = [str(k).strip() for k in raw_keywords if str(k).strip()]
        else:
            keywords = []

        # 최대 2개만 사용
        keywords = keywords[:2]

        if not keywords:
            # JSON 파싱 실패 시, 일반 텍스트 응답에서 키워드 후보를 2개까지 복구 시도
            keywords = _extract_keywords_fallback(response_text)

        if not keywords:
            logger.warning("키워드 파싱 결과가 비어 있습니다. response=%s", response_text[:200])
            return {
                "success": False,
                "keywords": [],
                "message": "모델 응답에서 키워드를 추출하지 못했습니다.",
            }

        logger.info("키워드 추출 완료: %s", keywords)

        return {
            "success":  True,
            "keywords": keywords,
            "message":  "키워드 추출 성공",
        }

    except Exception as e:
        logger.exception("키워드 추출 중 오류 발생")
        return {
            "success":  False,
            "keywords": [],
            "message":  f"오류 발생: {str(e)}",
        }


def _smart_truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    front = int(max_chars * 0.6)
    back  = int(max_chars * 0.4)
    return text[:front] + "\n\n[중략]\n\n" + text[-back:]


def _parse_json_response(response_text: str) -> dict:
    cleaned = response_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    json_match = re.search(r"\{[\s\S]*\}", cleaned)
    if not json_match:
        return {"keywords": []}
    try:
        return json.loads(json_match.group())
    except Exception:
        return {"keywords": []}


def _extract_keywords_fallback(response_text: str) -> list[str]:
    cleaned = response_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    candidates = []

    # JSON 형태 일부가 살아있다면 keywords 배열 내부 값을 우선 추출
    keywords_array_match = re.search(r'"keywords"\s*:\s*\[([\s\S]*?)\]', cleaned, flags=re.IGNORECASE)
    if keywords_array_match:
        array_body = keywords_array_match.group(1)
        quoted_items = re.findall(r'"([^"\n]{1,20})"', array_body)
        candidates.extend(item.strip() for item in quoted_items if item.strip())

    # 응답이 중간에 끊겨 keywords 배열이 닫히지 않은 경우를 복구
    if not candidates:
        partial_item_match = re.search(
            r'"keywords"\s*:\s*\[\s*"([^"\n\]]{1,20})',
            cleaned,
            flags=re.IGNORECASE,
        )
        if partial_item_match:
            partial_item = partial_item_match.group(1).strip().rstrip(",")
            if partial_item:
                candidates.append(partial_item)

    # 위에서 못 찾은 경우에만 전체 따옴표 텍스트를 후보로 사용
    if not candidates:
        quoted = re.findall(r'"([^"\n]{1,20})"', cleaned)
        candidates = [q.strip() for q in quoted if q.strip()]

    if not candidates:
        # 번호 목록/불릿 응답 대응
        line_tokens = []
        for line in cleaned.splitlines():
            token = re.sub(r"^[\-\d\.)\s]+", "", line).strip()
            if 1 <= len(token) <= 20:
                line_tokens.append(token)
        candidates = line_tokens

    deduped = []
    blocked_tokens = {
        "keywords", "keyword", "키워드", "json", "응답", "response",
        "here is the json", "here is the json requested",
    }
    for item in candidates:
        normalized = item.strip().lower()
        if not normalized or normalized in blocked_tokens:
            continue
        if len(item.strip()) < 2:
            continue
        if item not in deduped:
            deduped.append(item)
    return deduped[:2]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps({
        "model": GEMINI_MODEL,
        "has_key": bool(_get_gemini_api_key()),
    }, ensure_ascii=False))
    result = extract_keywords_from_case("신호위반으로 인한 교통사고 발생. 상대방 부상.")
    print(json.dumps(result, ensure_ascii=False, indent=2))
