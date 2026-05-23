import os
import logging
import pymysql
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# ── DB 연결 설정 ──
def get_db_connection():
    # CCTV 테이블 조회용 MySQL 연결을 생성한다.
    return pymysql.connect(
        host     = os.getenv("DB_HOST"),
        user     = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        database = os.getenv("DB_NAME"),
        port     = int(os.getenv("DB_PORT", 3306)),
        charset  = "utf8mb4",
        cursorclass = pymysql.cursors.DictCursor
    )


# ── 요청 바디 모델 ──
class AddressRequest(BaseModel):
    address: str  # 사건 장소 주소
    # 허용 반경은 엔드포인트에서 100/500/1000으로 검증한다.
    radius: int = 500


# ════════════════════════════════════════
# STEP 1: 주소 → 위도/경도 (Geocoding API)
# ════════════════════════════════════════
def geocode_address(address: str) -> dict:
    # Google Geocoding API로 주소를 좌표로 변환한다.
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": address,
        "key":     GOOGLE_MAPS_API_KEY,
        "language": "ko",
        "region":   "KR",
    }
    res  = requests.get(url, params=params)
    data = res.json()

    if data["status"] != "OK":
        logger.error(f"Geocoding 실패 - status: {data['status']}, error_message: {data.get('error_message', 'N/A')}, API_KEY 설정됨: {bool(GOOGLE_MAPS_API_KEY)}")
        raise Exception(f"Geocoding 실패: {data['status']} - {data.get('error_message', '')}")

    location = data["results"][0]["geometry"]["location"]
    # 주소 컴포넌트에서 '구' 단위를 추출해 1차 필터에 사용한다.
    gu = ""
    for component in data["results"][0]["address_components"]:
        if "sublocality_level_1" in component["types"] or \
           "political" in component["types"]:
            if "구" in component["long_name"]:
                gu = component["long_name"]
                break

    return {
        "lat": location["lat"],
        "lng": location["lng"],
        "gu":  gu,
    }


# ════════════════════════════════════════
# STEP 2: DB에서 반경 500m CCTV 조회
# 1차: 같은 구 필터링
# 2차: ST_Distance_Sphere로 500m 이내 계산
# ════════════════════════════════════════
def get_nearby_cctvs(lat: float, lng: float, gu: str, radius: int) -> list:
    # 반경 내 CCTV를 거리순으로 조회한다.
    conn   = get_db_connection()
    cursor = conn.cursor()

    try:
        # gu가 있으면 같은 구로 1차 필터 후 거리 계산
        # gu가 없으면 전체에서 거리 계산
        if gu:
            query = """
                SELECT
                    id,
                    `주소` AS address,
                    CAST(`위도` AS DECIMAL(10,7)) AS lat,
                    CAST(`경도` AS DECIMAL(10,7)) AS lng,
                    (
                        6371000 * ACOS(
                            LEAST(1,
                                COS(RADIANS(%s)) * COS(RADIANS(CAST(`위도` AS DECIMAL(10,7))))
                                * COS(RADIANS(CAST(`경도` AS DECIMAL(10,7))) - RADIANS(%s))
                                + SIN(RADIANS(%s)) * SIN(RADIANS(CAST(`위도` AS DECIMAL(10,7))))
                            )
                        )
                    ) AS distance
                FROM cctv
                WHERE `주소` LIKE %s
                HAVING distance <= %s
                ORDER BY distance ASC
            """
            cursor.execute(query, (lat, lng, lat, f"%{gu}%", radius))
        else:
            query = """
                SELECT
                    id,
                    `주소` AS address,
                    CAST(`위도` AS DECIMAL(10,7)) AS lat,
                    CAST(`경도` AS DECIMAL(10,7)) AS lng,
                    (
                        6371000 * ACOS(
                            LEAST(1,
                                COS(RADIANS(%s)) * COS(RADIANS(CAST(`위도` AS DECIMAL(10,7))))
                                * COS(RADIANS(CAST(`경도` AS DECIMAL(10,7))) - RADIANS(%s))
                                + SIN(RADIANS(%s)) * SIN(RADIANS(CAST(`위도` AS DECIMAL(10,7))))
                            )
                        )
                    ) AS distance
                FROM cctv
                HAVING distance <= %s
                ORDER BY distance ASC
            """
            cursor.execute(query, (lat, lng, lat, radius))

        rows = cursor.fetchall()
        logger.info(f"조회된 CCTV 수: {len(rows)}")
        return rows

    finally:
        cursor.close()
        conn.close()


# ════════════════════════════════════════
# 메인 엔드포인트
# POST /api/cctv/search
# ════════════════════════════════════════
@app.post("/api/cctv/search")
async def search_cctv(request: AddressRequest):
    # 기본 입력 검증.
    if not request.address.strip():
        raise HTTPException(status_code=400, detail="주소를 입력해주세요.")

    if request.radius not in (100, 500, 1000):
        raise HTTPException(status_code=400, detail="반경은 100m, 500m, 1000m 중 하나여야 합니다.")

    logger.info(f"주소 수신: {request.address}")

    # STEP 1: 주소 → 위도/경도
    try:
        geo = geocode_address(request.address)
        logger.info(f"Geocoding 결과: {geo}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # STEP 2: DB에서 지정 반경 CCTV 조회
    try:
        cctvs = get_nearby_cctvs(geo["lat"], geo["lng"], geo["gu"], request.radius)
    except Exception as e:
        logger.error(f"DB 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="CCTV 조회 중 오류가 발생했습니다.")

    return {
        "success": True,
        "center": {
            "lat": geo["lat"],
            "lng": geo["lng"],
            "address": request.address,
        },
        "radius": request.radius,
        "cctvs": [
            {
                "id":       row["id"],
                "address":  row["address"],
                "lat":      float(row["lat"]),
                "lng":      float(row["lng"]),
                "distance": round(float(row["distance"]), 1),
            }
            for row in cctvs
        ],
        "total": len(cctvs),
    }


# ── 서버 상태 확인 ──
@app.get("/api/health")
async def health_check():
    # 헬스체크 엔드포인트.
    return {"status": "ok"}


# ── 실행 ──
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("cctv:app", host="0.0.0.0", port=8003, reload=True)