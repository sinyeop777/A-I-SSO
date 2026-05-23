import json
import os
import re

import requests

GEMINI_API_KEY = os.getenv("GEMINI_KEY") or os.getenv("GEMINI_API_KEY")
GEMINI_MODEL   = "gemini-3.1-flash-lite"


# 문서 타입별 맞춤 분석 지시
DOC_TYPE_INSTRUCTIONS = {
    "medical":  "의학적 상해 정도, 치료 기간, 진단명, 후유증 여부를 중심으로 분석하세요.",
    "accident": "사고 발생 시각, 장소, 행위자, 피해 상황, 과실 관련 내용을 중심으로 분석하세요.",
    "contract": "당사자, 주요 조항, 의무사항, 합의 금액, 위반 여부를 중심으로 분석하세요.",
    "verdict":  "사건번호, 판결 주문, 핵심 판단 이유, 형량을 중심으로 분석하세요.",
    "general":  "법적으로 중요한 사실관계와 증거가 될 수 있는 내용을 중심으로 분석하세요.",
}

DOC_TYPE_LABELS = {
    "medical":  "진단·의료 문서",
    "accident": "사고 경위 문서",
    "contract": "계약·합의 문서",
    "verdict":  "판결·결정문",
    "general":  "일반 문서",
}


# 외부 진입점
def summarize_attached_documents(user_prompt: str, file_documents: list[dict]) -> dict:
    """
    첨부 문서별 개별 요약 생성

    Args:
        user_prompt   : 사용자 사건 설명
        file_documents: [{"file_name": str, "text": str}]

    Returns:
        {
            "success"       : bool,
            "file_summaries": list[dict],
            "message"       : str
        }
    """
    if not file_documents:
        return {
            "success":        True,
            "file_summaries": [],
            "message":        "요약할 첨부 문서가 없습니다.",
        }

    if not GEMINI_API_KEY:
        return {
            "success":        False,
            "file_summaries": [],
            "message":        "Gemini API 키가 설정되지 않았습니다.",
        }

    file_summaries = []

    for doc in file_documents:
        file_name = str(doc.get("file_name") or "unknown")
        file_text = str(doc.get("text") or "").strip()

        if not file_text:
            file_summaries.append({
                "file_name": file_name,
                "doc_type":  "unknown",
                "summary":   "문서에서 텍스트를 추출하지 못했습니다.",
                "key_points":   [],
                "favorable":    [],
                "unfavorable":  [],
                "missing_info": [],
                "status":    "no_text",
            })
            continue

        result = _summarize_single_document(
            user_prompt=user_prompt,
            file_name=file_name,
            file_text=file_text,
        )
        file_summaries.append(result)

    return {
        "success":        True,
        "file_summaries": file_summaries,
        "message":        "첨부 문서별 요약 생성 완료",
    }


# 문서 1개 요약
def _summarize_single_document(user_prompt: str, file_name: str, file_text: str) -> dict:

    # ① 문서 타입 감지
    doc_type    = _detect_doc_type(file_name, file_text)
    type_label  = DOC_TYPE_LABELS[doc_type]
    type_instr  = DOC_TYPE_INSTRUCTIONS[doc_type]

    # ② 텍스트 청킹 (앞 60% + 뒤 40%)
    truncated_prompt = _smart_truncate(user_prompt, 1500)
    truncated_text   = _smart_truncate(file_text,   7000)

    system_instruction = f"""
당신은 교통사고 전문 법률 문서 분석 AI입니다.
현재 분석 대상 문서 유형: {type_label}

[분석 원칙 — 반드시 준수]
1. 문서에 명시된 사실만 분석하세요. 추측하거나 없는 내용을 추가하지 마세요.
2. 날짜, 금액, 수치, 고유명사는 원문 그대로 포함하세요.
3. 사건 설명과 연관된 내용을 우선적으로 분석하세요.
4. {type_instr}
5. 법적으로 유리한 내용과 불리한 내용을 반드시 구분하세요.

응답은 반드시 아래 JSON 형식만 반환하세요. 다른 텍스트는 포함하지 마세요:
{{
  "summary":       "문서 핵심 요약 (3~5문장, 사실만 기술)",
  "key_points":    ["법적으로 중요한 사실 포인트 (최대 5개)"],
  "favorable":     ["사건에 유리하게 작용할 수 있는 내용"],
  "unfavorable":   ["사건에 불리하게 작용할 수 있는 내용"],
  "missing_info":  ["추가 확인이 필요한 정보 또는 빠진 정보"]
}}
"""

    prompt = (
        f"[사건 설명]\n{truncated_prompt}\n\n"
        f"[첨부 문서명]\n{file_name}\n\n"
        f"[첨부 문서 내용]\n{truncated_text}"
    )

    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": system_instruction}]},
                "generationConfig": {
                    "temperature":    0.1,   # 낮을수록 일관되고 사실 기반 출력
                    "maxOutputTokens": 1500,
                },
                "contents": [
                    {"role": "user", "parts": [{"text": prompt}]},
                ],
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        response_text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            .strip()
        )

        parsed = _parse_json_response(response_text)

        return {
            "file_name":     file_name,
            "doc_type":      doc_type,
            "doc_type_label": type_label,
            "summary":       parsed.get("summary")      or "요약 결과가 비어 있습니다.",
            "key_points":    parsed.get("key_points")   if isinstance(parsed.get("key_points"),  list) else [],
            "favorable":     parsed.get("favorable")    if isinstance(parsed.get("favorable"),   list) else [],
            "unfavorable":   parsed.get("unfavorable")  if isinstance(parsed.get("unfavorable"), list) else [],
            "missing_info":  parsed.get("missing_info") if isinstance(parsed.get("missing_info"),list) else [],
            "status":        "ok",
        }

    except Exception:
        return {
            "file_name":     file_name,
            "doc_type":      doc_type,
            "doc_type_label": type_label,
            "summary":       "요약 생성 중 오류가 발생했습니다.",
            "key_points":    [],
            "favorable":     [],
            "unfavorable":   [],
            "missing_info":  [],
            "status":        "error",
        }


# 문서 타입 자동 감지
def _detect_doc_type(file_name: str, file_text: str) -> str:
    name    = file_name.lower()
    preview = file_text[:500].lower()

    medical_kw  = ["진단서", "의무기록", "상해", "치료", "입원", "수술", "병원", "의사"]
    accident_kw = ["경위서", "사고", "목격", "블랙박스", "충돌", "현장", "운전"]
    contract_kw = ["계약", "합의", "동의서", "협의", "배상", "보상", "합의금"]
    verdict_kw  = ["판결", "결정문", "선고", "사건번호", "피고", "원고", "주문"]

    if any(k in name or k in preview for k in medical_kw):
        return "medical"
    if any(k in name or k in preview for k in verdict_kw):
        return "verdict"
    if any(k in name or k in preview for k in contract_kw):
        return "contract"
    if any(k in name or k in preview for k in accident_kw):
        return "accident"
    return "general"


# 텍스트 청킹 (앞 60% + 뒤 40%)
def _smart_truncate(text: str, max_chars: int) -> str:
    """
    단순히 앞만 자르지 않고 앞뒤를 모두 반영.
    긴 문서에서 뒷부분 결론·서명 등 중요 정보 손실 방지.
    """
    if len(text) <= max_chars:
        return text

    front = int(max_chars * 0.6)
    back  = int(max_chars * 0.4)
    return text[:front] + "\n\n[중략]\n\n" + text[-back:]


# JSON 파싱
def _parse_json_response(response_text: str) -> dict:
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if not json_match:
        return {"summary": response_text}

    try:
        return json.loads(json_match.group())
    except Exception:
        return {"summary": response_text}
