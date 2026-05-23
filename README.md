# AI 이의 있소!

교통사고/법률 상담 시나리오를 기반으로
사건 경위 정리, 핵심 키워드 추출, 관련 법령 검색, 유사 판례 조회,
CCTV 위치 탐색, 사용자 기록 저장/재분석을 제공하는 웹 서비스입니다.

프론트엔드는 React + Vite,
백엔드는 FastAPI 기반으로 구성되어 있습니다.

## 1) 주요 기능

- 사건 경위 입력 및 정리
- 첨부 문서 변환(HWP/HWPX/DOC/DOCX/PDF) 및 내용 활용
- Gemini 기반 키워드 추출
- 법령 검색 및 상세 보기
- 유사 판례 검색
- CCTV 주변 탐색(주소 기반)
- 사용자 기록 저장/조회/재분석/삭제

## 2) 기술 스택

### Frontend

- React
- Vite
- React Router
- Axios
- Styled Components

### Backend

- FastAPI
- Uvicorn
- ChromaDB
- sentence-transformers, torch
- Google GenAI
- PyMySQL
- requests, aiohttp

## 3) 프로젝트 구조

```text
my-react-app/
├─ src/                    # 프론트엔드 소스
├─ public/                 # 정적 파일
├─ backend/                # 백엔드 소스
│  ├─ auth.py              # 인증/기록/키워드/법령/판례 API
│  ├─ document_transform.py# 문서 변환 API
│  ├─ cctv.py              # CCTV 검색 API
│  └─ requirements.txt     # 백엔드 의존성
├─ run_servers.py          # 백엔드 서버 일괄 실행 스크립트
└─ package.json            # 프론트엔드 의존성/스크립트
```

## 4) 사전 준비

- Node.js 18+ 권장
- Python 3.10+ 권장
- MySQL 사용 가능 환경
- (선택) HWP/HWPX 변환 사용 시 Windows + 한글(HWP) COM 환경

## 5) 설치

### 5-1. 프론트엔드 설치

프로젝트 루트에서 실행:

```bash
npm install
```

### 5-2. 백엔드 설치

프로젝트 루트에서 가상환경 생성/활성화 후 설치:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
```

문서 변환 기능을 사용하는 경우, 환경에 따라 아래 패키지가 추가로 필요할 수 있습니다.

```bash
pip install fastapi uvicorn python-dotenv python-multipart PyPDF2 aspose-words pywin32 google-auth cryptography
```

## 6) 환경 변수 설정

프로젝트 루트에 .env 파일을 만들고 최소 아래 값을 설정하세요.

```env
# Google
GOOGLE_CLIENT_ID=
GEMINI_API_KEY=
GOOGLE_MAPS_API_KEY=

# MySQL
DB_HOST=
DB_PORT=3306
DB_USER=
DB_PASSWORD=
DB_NAME=

# Optional
PUBLIC_LEGAL_API_URL=
PUBLIC_LEGAL_API_KEY=
DOCUMENT_API_BASE_URL=http://localhost:8001

# Optional (Chroma/model path)
CRIMINAL_DB_PATH=backend/criminal_law_db
CIVIL_DB_PATH=backend/civil_law_db
CRIMINAL_COLLECTION_NAME=criminal_laws
CIVIL_COLLECTION_NAME=civil_laws
SBERT_MODEL_NAME=snunlp/KR-SBERT-V40K-klueNLI-augSTS
CROSS_ENCODER_MODEL_NAME=bongsoo/albert-small-kor-cross-encoder-v1
```

참고:

- 일부 모듈은 GEMINI_KEY도 함께 참조합니다.
- 프론트엔드에서는 기본적으로 다음 주소를 사용합니다.
	- 인증/기록/검색 API: http://localhost:8000
	- 분석 API 기본값: http://localhost:3000 (VITE_API_URL로 변경 가능)

## 7) 실행 방법

### 7-1. 백엔드 실행

프로젝트 루트에서:

```bash
python run_servers.py
```

기본적으로 다음 서버가 실행됩니다.

- auth: http://127.0.0.1:8000 (필수)
- document_transform: http://127.0.0.1:8001 (선택)
- cctv: http://127.0.0.1:8003 (선택)

### 7-2. 프론트엔드 실행

별도 터미널에서 프로젝트 루트:

```bash
npm run dev
```

브라우저에서 Vite 안내 주소(일반적으로 http://localhost:5173)로 접속합니다.

## 8) 주요 API 요약

auth 서버(8000):

- POST /api/auth/google
- POST /api/law-search
- POST /api/case-search
- POST /api/extract-keywords
- POST /api/records
- GET /api/records
- PATCH /api/records/{record_id}/location
- POST /api/records/{record_id}/rerun
- DELETE /api/records/{record_id}
- GET /api/health

cctv 서버(8003):

- POST /api/cctv/search
- GET /api/health

document_transform 서버(8001):

- POST /transform

## 9) 자주 발생하는 이슈

- GOOGLE_CLIENT_ID 미설정
	- auth 서버 시작 시 오류가 발생합니다. .env에 GOOGLE_CLIENT_ID를 설정하세요.

- DB 연결 실패
	- DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME 값을 확인하세요.

- 문서 변환 실패
	- HWP/HWPX는 Windows COM 환경(pywin32 + 한글 설치/설정) 영향을 받습니다.
	- DOC/DOCX는 aspose-words 설치를 확인하세요.

- 지도/지오코딩 실패
	- GOOGLE_MAPS_API_KEY 및 키 제한(도메인/서비스 활성화)을 확인하세요.

## 10) GitHub 업로드 시 권장 제외

- .venv/
- dist/
- backend/chromadb_snunlp/
- backend/civil_law_db/
- backend/criminal_law_db/
- backend/upload_storage/
- backend/temp_storage/
- .env

이미 .gitignore에 반영되어 있는지 확인 후 업로드를 진행하세요.
