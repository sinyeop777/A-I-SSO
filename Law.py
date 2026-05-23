import requests
import xml.etree.ElementTree as ET


def search_latest_current_law_html(keyword):
    # 1. 법령 목록 조회 API 설정
    search_url = "https://www.law.go.kr/DRF/lawSearch.do"
    search_params = {
        "OC": "workohl2",
        "target": "eflaw",
        "query": keyword,
        "type": "XML",
        "display": 100
    }

    print(f"[{keyword}] 목록 조회를 시작합니다.")
    response = requests.get(search_url, params=search_params)

    if response.status_code != 200:
        print("API 호출에 실패했습니다. 상태 코드:", response.status_code)
        return

    # 2. XML 데이터 파싱
    root = ET.fromstring(response.content)

    latest_date = "00000000"
    target_law_id = None
    target_law_name = ""

    # 3. 조건에 맞는 법령 탐색
    for law in root.findall('.//law'):
        status_node = law.find('현행연혁코드')
        type_node = law.find('법령구분명')
        date_node = law.find('시행일자')
        id_node = law.find('법령ID')
        name_node = law.find('법령명한글')

        if None in (status_node, type_node, date_node, id_node, name_node):
            continue

        status = status_node.text.strip() if status_node.text else ""
        law_type = type_node.text.strip() if type_node.text else ""
        enforcement_date = date_node.text.strip() if date_node.text else ""
        law_id = id_node.text.strip() if id_node.text else ""
        law_name = name_node.text.strip() if name_node.text else ""

        # 조건 확인: 현행코드 여부 및 법률인지 여부
        if status == "현행" and law_type == "법률":
            if enforcement_date > latest_date:
                latest_date = enforcement_date
                target_law_id = law_id
                target_law_name = law_name

    # 4. 결과 출력 및 본문 HTML URL 생성
    if target_law_id:
        print("\n[검색 결과]")
        print(f"법령명: {target_law_name}")
        print(f"법령ID: {target_law_id}")
        print(f"최근 시행일자: {latest_date}")

        # 본문 상세 조회 URL 생성
        detail_url = f"https://www.law.go.kr/DRF/lawService.do?OC=workohl2&target=eflaw&ID={target_law_id}&type=HTML"
        print(f"생성된 상세 조회 URL: {detail_url}")

    else:
        print("\n조건(현행연혁코드='현행', 법령구분명='법률')에 맞는 법령을 찾을 수 없습니다.")


if __name__ == "__main__":
    while True:
        user_keyword = input("\n검색할 법령 키워드를 입력하세요 (종료하려면 exit 입력): ")

        if user_keyword.lower() == 'exit':
            print("프로그램을 종료합니다.")
            break

        if user_keyword.strip():
            search_latest_current_law_html(user_keyword.strip())
        else:
            print("키워드가 올바르게 입력되지 않았습니다.")