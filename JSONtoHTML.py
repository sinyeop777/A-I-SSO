import os
import requests


def format_date(date_str):
    if date_str and len(date_str) == 8:
        return f"{date_str[:4]}년 {int(date_str[4:6])}월 {int(date_str[6:])}일"
    return date_str


def fetch_and_convert_to_html(prec_id, api_key="workohl2", output_dir="./legal_html_output"):
    # 출력 폴더가 없으면 생성
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # API URL 설정
    url = f"https://www.law.go.kr/DRF/lawService.do?OC={api_key}&target=prec&ID={prec_id}&type=JSON"

    try:
        # API 호출 및 JSON 파싱
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"API 호출 또는 JSON 파싱 중 오류가 발생했습니다: {e}")
        return

    prec = data.get("PrecService", {})
    if not prec:
        print("유효한 판례 데이터가 없습니다.")
        return

    # 데이터 추출
    case_num = prec.get("사건번호", "")
    case_name = prec.get("사건명", "")
    court = prec.get("법원명", "")
    date_val = format_date(prec.get("선고일자", ""))
    case_type = prec.get("사건종류명", "")
    judgement_type = prec.get("판결유형", "")
    summary_points = prec.get("판시사항", "")
    summary_judgement = prec.get("판결요지", "")
    ref_law = prec.get("참조조문", "")
    ref_case = prec.get("참조판례", "")
    content = prec.get("판례내용", "")

    # HTML 템플릿 생성
    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>{court} {case_num} 판결</title>
    <style>
        body {{ font-family: 'Malgun Gothic', sans-serif; line-height: 1.6; padding: 20px; background-color: #f8f9fa; }}
        .container {{ max-width: 900px; margin: 0 auto; background-color: #fff; padding: 40px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        h1 {{ text-align: center; border-bottom: 2px solid #34495e; padding-bottom: 15px; color: #2c3e50; }}
        .metadata-table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; font-size: 14px; }}
        .metadata-table th, .metadata-table td {{ border: 1px solid #ddd; padding: 10px; }}
        .metadata-table th {{ background-color: #edf2f7; width: 20%; text-align: left; }}
        .section-title {{ color: #2980b9; border-left: 4px solid #2980b9; padding-left: 10px; margin-top: 30px; }}
        .content-box {{ background-color: #f8f9fa; border: 1px solid #e9ecef; padding: 20px; border-radius: 4px; }}
    </style>
</head>
<body>
<div class="container">
    <h1>{court} {date_val} 선고 {case_num} 판결 [{case_name}]</h1>
    <table class="metadata-table">
        <tr><th>사건번호</th><td>{case_num}</td><th>사건명</th><td>{case_name}</td></tr>
        <tr><th>법원명</th><td>{court}</td><th>선고일자</th><td>{date_val}</td></tr>
        <tr><th>사건종류</th><td>{case_type}</td><th>판결유형</th><td>{judgement_type}</td></tr>
    </table>
    <h2 class="section-title">판시사항</h2><div class="content-box">{summary_points}</div>
    <h2 class="section-title">판결요지</h2><div class="content-box">{summary_judgement}</div>
    <h2 class="section-title">참조조문 및 참조판례</h2>
    <div class="content-box"><strong>[참조조문]</strong><br/>{ref_law}<br/><br/><strong>[참조판례]</strong><br/>{ref_case}</div>
    <h2 class="section-title">판례내용 (전문)</h2><div class="content-box">{content}</div>
</div>
</body>
</html>"""

    # 파일 이름 설정 및 저장
    filename = f"{prec_id}_{case_num}.html".replace(" ", "")
    output_path = os.path.join(output_dir, filename)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"변환 완료: {output_path}")


# 함수 실행 (판례 일련번호 228541 조회)
fetch_and_convert_to_html("238253")