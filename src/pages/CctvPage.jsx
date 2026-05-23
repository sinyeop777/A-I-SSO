import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import axios from 'axios';
import { updateRecordLocation } from '../api/apiService';
import '../styles/CctvPage.css';

// 반경 선택 UI와 백엔드 검증 로직에서 공통으로 쓰는 허용값.
const RADIUS_OPTIONS = [100, 500, 1000];
const MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY;
const CCTV_API_BASE_URL = import.meta.env.VITE_CCTV_API_URL || 'http://localhost:8003';

function CctvPage() {
  const routeLocation = useLocation();
  const [address,  setAddress]  = useState(''); //사용자가 입력하는 주소 문자열
  const [loading,  setLoading]  = useState(false); //API 호출 중 로딩 상태
  const [error,    setError]    = useState(''); //에러 메세지 저장
  const [incidentPlaces, setIncidentPlaces] = useState([]); // 누적 사건 장소 목록
  const [selectedCctvId, setSelectedCctvId] = useState(null); //목록에서 선택된 CCTV의 고유 키
  const [mapListVersion, setMapListVersion] = useState(0); // ref 변경 후 목록 강제 리렌더용
  const [isMapApiReady, setIsMapApiReady] = useState(() => Boolean(window.google?.maps));
  const mapRef     = useRef(null);   // 지도 div ref
  const mapObjRef  = useRef(null);   // Google Maps 인스턴스
  const autoLoadedRef = useRef(false);
  const incidentOverlaysRef = useRef(new Map()); // incidentId -> { centerMarker, centerInfo, circle, cctvMarkers }
  const cctvMarkersRef = useRef(new Map()); // cctvKey -> { marker, infoWindow, incidents:Set, cctv }
  const recordId = routeLocation.state?.recordId ?? null;
  const recordOwnerGoogleSub = routeLocation.state?.recordOwnerGoogleSub ?? null;
  const initialAddress = (routeLocation.state?.initialAddress ?? '').trim();

  // CCTV 데이터에 고유 id가 없을 때도 마커 Map 키를 안정적으로 만들기 위한 함수.
  const getCctvKey = (cctv) => cctv.id ?? `${cctv.lat}-${cctv.lng}-${cctv.address}`;
  // 중첩 사건에 포함된 CCTV는 빨간색, 단일 사건 CCTV는 파란색 아이콘.
  const getMarkerIcon = (isOverlapped) => ({
    url: isOverlapped
      ? 'https://maps.google.com/mapfiles/ms/icons/red-dot.png'
      : 'https://maps.google.com/mapfiles/ms/icons/blue-dot.png',
    scaledSize: new window.google.maps.Size(32, 32),
  });

  const removeIncidentVisuals = useCallback((incident) => {
    // 사건 중심점 마커/원/정보창을 먼저 제거한다.
    const overlay = incidentOverlaysRef.current.get(incident.id);
    if (overlay) {
      overlay.centerMarker?.setMap(null);
      overlay.circle?.setMap(null);
      overlay.centerInfo?.close();
      incidentOverlaysRef.current.delete(incident.id);
    }

    // 사건에 연결된 CCTV 마커 참조를 정리하고, 필요 시 마커를 제거한다.
    incident.cctvs.forEach((cctv) => {
      const cctvKey = getCctvKey(cctv);
      const cctvEntry = cctvMarkersRef.current.get(cctvKey);
      if (!cctvEntry) return;

      cctvEntry.incidents.delete(incident.id);

      if (cctvEntry.incidents.size === 0) {
        cctvEntry.infoWindow?.close();
        cctvEntry.marker?.setMap(null);
        cctvMarkersRef.current.delete(cctvKey);
        return;
      }

      cctvEntry.marker?.setIcon(getMarkerIcon(cctvEntry.incidents.size > 1));
    });
  }, []);

  const removeIncident = useCallback((incidentId) => {
    // 상태 배열에서 사건을 제거하고, 선택된 CCTV가 사라졌으면 선택을 해제한다.
    const incident = incidentPlaces.find((item) => item.id === incidentId);
    if (!incident) return;

    removeIncidentVisuals(incident);
    setMapListVersion((v) => v + 1); // 마커 제거 후 목록 갱신

    setIncidentPlaces((prev) => prev.filter((incident) => incident.id !== incidentId));
    setSelectedCctvId((prev) => {
      if (!prev) return prev;
      const cctvEntry = cctvMarkersRef.current.get(prev);
      return cctvEntry ? prev : null;
    });
  }, [incidentPlaces, removeIncidentVisuals]);

  const handleIncidentRadiusChange = useCallback(async (incidentId, radius) => {
    // 반경 변경 시 같은 주소로 재검색해 해당 사건의 CCTV 목록을 갱신한다.
    if (!RADIUS_OPTIONS.includes(radius)) return;
    const incident = incidentPlaces.find((item) => item.id === incidentId);
    if (!incident) return;
    if (incident.radius === radius) return;

    setLoading(true);
    setError('');

    try {
      const res = await axios.post(`${CCTV_API_BASE_URL}/api/cctv/search`, {
        address: incident.center.address,
        radius,
      });

      removeIncidentVisuals(incident);

      const updatedIncident = {
        ...incident,
        center: res.data.center,
        cctvs: res.data.cctvs,
        total: res.data.total,
        radius: res.data.radius ?? radius,
      };

      setIncidentPlaces((prev) => prev.map((item) => (
        item.id === incidentId ? updatedIncident : item
      )));
    } catch (err) {
      setError(
        err.response?.data?.detail || '반경 변경 중 오류가 발생했습니다.'
      );
    } finally {
      setLoading(false);
    }
  }, [incidentPlaces, removeIncidentVisuals]);

  const addIncidentToMap = useCallback((incident) => {
    // incident 상태 1건을 지도 오버레이(중심점/원/CCTV 마커들)로 렌더링한다.
    const map = mapObjRef.current;
    if (!map || !window.google) return;

    const { lat, lng, address: centerAddress } = incident.center;
    const deleteBtnId = `delete-incident-${incident.id}`;
    const radiusSelectId = `radius-select-${incident.id}`;

    const centerMarker = new window.google.maps.Marker({
      position: { lat, lng },
      map,
      title: '사건 장소',
      icon: {
        path:        window.google.maps.SymbolPath.CIRCLE,
        scale:       10,
        fillColor:   '#f0d080',
        fillOpacity: 1,
        strokeColor: '#c9a84c',
        strokeWeight: 2,
      },
    });

    const centerInfo = new window.google.maps.InfoWindow({
      content: `
        <div class="map-info">
          <b>📍 사건 장소</b><br/>
          ${centerAddress}<br/>
          <label style="display:block;margin-top:8px;font-size:12px;color:#444;">반경 선택</label>
          <select id="${radiusSelectId}" style="margin-top:4px;padding:6px 8px;border:1px solid #ddd;border-radius:8px;width:100%;">
            ${RADIUS_OPTIONS.map((value) => `<option value="${value}" ${incident.radius === value ? 'selected' : ''}>${value}m</option>`).join('')}
          </select>
          <button id="${deleteBtnId}" style="margin-top:8px;padding:6px 10px;border:none;border-radius:8px;background:#d64b4b;color:#fff;cursor:pointer;">삭제</button>
        </div>
      `,
    });

    centerMarker.addListener('click', () => centerInfo.open(map, centerMarker));

    window.google.maps.event.addListener(centerInfo, 'domready', () => {
      // InfoWindow 내부 DOM이 생성된 뒤 삭제/반경 변경 이벤트를 연결한다.
      const deleteBtn = document.getElementById(deleteBtnId);
      if (!deleteBtn) return;
      deleteBtn.onclick = () => {
        centerInfo.close();
        removeIncident(incident.id);
      };

      const radiusSelect = document.getElementById(radiusSelectId);
      if (!radiusSelect) return;
      radiusSelect.onchange = (e) => {
        const nextRadius = Number(e.target.value);
        handleIncidentRadiusChange(incident.id, nextRadius);
      };
    });

    const circle = new window.google.maps.Circle({
      map,
      center:      { lat, lng },
      radius:      incident.radius ?? 500,
      fillColor:   '#c9a84c',
      fillOpacity: 0.08,
      strokeColor: '#c9a84c',
      strokeOpacity: 0.5,
      strokeWeight: 2,
    });

    const cctvMarkers = incident.cctvs.map((cctv) => {
      const cctvKey = getCctvKey(cctv);
      const existed = cctvMarkersRef.current.get(cctvKey);

      if (existed) {
        // 이미 존재하는 CCTV 마커면 incident 집합만 갱신한다.
        existed.incidents.add(incident.id);
        existed.marker.setIcon(getMarkerIcon(existed.incidents.size > 1));
        return existed.marker;
      }

      const marker = new window.google.maps.Marker({
        position: { lat: cctv.lat, lng: cctv.lng },
        map,
        title: cctv.address,
        icon: getMarkerIcon(false),
      });

      const infoWindow = new window.google.maps.InfoWindow({
        content: `
          <div class="map-info">
            <b>📷 CCTV</b><br/>
            ${cctv.address}<br/>
            <span style="color:#888">기준점으로부터 ${cctv.distance}m</span>
          </div>
        `,
      });

      marker.addListener('click', () => infoWindow.open(map, marker));
      cctvMarkersRef.current.set(cctvKey, {
        // 마커와 정보창, 소속 incident 집합을 함께 저장한다.
        marker,
        infoWindow,
        incidents: new Set([incident.id]),
        cctv,
      });
      return marker;
    });

    incidentOverlaysRef.current.set(incident.id, {
      centerMarker,
      centerInfo,
      circle,
      cctvMarkers,
    });

    map.panTo({ lat, lng });
    if (map.getZoom() < 15) map.setZoom(15);
  }, [removeIncident, handleIncidentRadiusChange]);

  // ── Google Maps 스크립트 준비 ──
  useEffect(() => {
    // index.html에서 이미 로드되었으면 바로 준비 완료 처리.
    if (window.google?.maps) {
      setIsMapApiReady(true);
      return;
    }

    const existingScript = Array.from(document.querySelectorAll('script')).find((script) =>
      script.src.includes('maps.googleapis.com/maps/api/js')
    );

    let intervalId = null;

    const handleLoaded = () => {
      if (window.google?.maps) {
        setIsMapApiReady(true);
        setError('');
      }
    };

    const handleLoadError = () => {
      setError('지도 스크립트를 불러오지 못했습니다.');
    };

    if (existingScript) {
      // 기존 스크립트가 있으면 load/error 이벤트만 구독한다.
      existingScript.addEventListener('load', handleLoaded);
      existingScript.addEventListener('error', handleLoadError);

      // 이미 로드 완료된 스크립트인데 load 이벤트를 놓친 경우를 대비
      intervalId = window.setInterval(() => {
        if (window.google?.maps) {
          handleLoaded();
          window.clearInterval(intervalId);
        }
      }, 300);

      return () => {
        existingScript.removeEventListener('load', handleLoaded);
        existingScript.removeEventListener('error', handleLoadError);
        if (intervalId) window.clearInterval(intervalId);
      };
    }

    if (!MAPS_API_KEY) {
      setError('Google Maps API 키가 설정되지 않았습니다.');
      return;
    }

    // 동적 로드를 사용해야 하는 환경을 위해 스크립트를 직접 삽입한다.
    const script = document.createElement('script');
    script.src = `https://maps.googleapis.com/maps/api/js?key=${MAPS_API_KEY}&language=ko`;
    script.async = true;
    script.defer = true;
    script.dataset.googleMaps = 'true';
    script.addEventListener('load', handleLoaded);
    script.addEventListener('error', handleLoadError);
    document.head.appendChild(script);

    return () => {
      script.removeEventListener('load', handleLoaded);
      script.removeEventListener('error', handleLoadError);
    };
  }, []);

  // ── 지도 초기화 ──
  useEffect(() => {
    // 지도는 한 번만 생성하고 ref에 보관한다.
    if (!isMapApiReady || !window.google || !mapRef.current || mapObjRef.current) return;

    const map = new window.google.maps.Map(mapRef.current, {
      center: { lat: 37.5665, lng: 126.9780 },
      zoom:   12,
      styles: DARK_MAP_STYLE,   // 다크 테마
    });
    mapObjRef.current = map;
  }, [isMapApiReady]);

  useEffect(() => {
    // 상태에 존재하지만 아직 렌더되지 않은 incident만 지도에 추가한다.
    if (!mapObjRef.current || !window.google) return;

    let added = false;
    incidentPlaces.forEach((incident) => {
      if (!incidentOverlaysRef.current.has(incident.id)) {
        addIncidentToMap(incident);
        added = true;
      }
    });
    if (added) {
      setMapListVersion((v) => v + 1); // 마커 추가 후 목록 갱신
    }
  }, [incidentPlaces, addIncidentToMap]);

  useEffect(() => {
    // 페이지 이탈 시 생성한 모든 지도 객체를 정리해 메모리 누수를 방지한다.
    const overlays = incidentOverlaysRef.current;
    const cctvMarkerMap = cctvMarkersRef.current;

    return () => {
      overlays.forEach((overlay) => {
        overlay.centerMarker?.setMap(null);
        overlay.circle?.setMap(null);
        overlay.cctvMarkers?.forEach((marker) => marker.setMap(null));
        overlay.centerInfo?.close();
      });
      overlays.clear();
      cctvMarkerMap.clear();
      mapObjRef.current = null;
    };
  }, []);

  useEffect(() => {
    // 선택된 CCTV가 목록에서 사라졌다면 선택을 해제한다.
    if (!selectedCctvId) return;
    if (!cctvMarkersRef.current.has(selectedCctvId)) {
      setSelectedCctvId(null);
    }
  }, [incidentPlaces, selectedCctvId]);

  // 목록 항목 클릭 시 지도 중심 이동 + 해당 마커 정보창 열기.
  const handleCctvItemClick = (cctv) => {
    const map = mapObjRef.current;
    const markerKey = getCctvKey(cctv);
    const markerEntry = cctvMarkersRef.current.get(markerKey);
    const marker = markerEntry?.marker;
    if (!map || !marker || !window.google?.maps?.event) return;

    setSelectedCctvId(markerKey);
    map.panTo({ lat: cctv.lat, lng: cctv.lng });
    if (map.getZoom() < 17) {
      map.setZoom(17);
    }
    // 마커 클릭 이벤트 강제 트리거: 정보창이 열림
    window.google.maps.event.trigger(marker, 'click');
  };


  // ── 검색 요청 ──
  const handleSearch = useCallback(async (addressOverride = '') => {
    // 입력창 값 또는 외부에서 전달된 주소를 우선순위로 선택한다.
    const overrideAddress = typeof addressOverride === 'string' ? addressOverride : '';
    const targetAddress = (overrideAddress || address).trim();

    if (!targetAddress) {
      setError('사건 장소 주소를 입력해주세요.');
      return;
    }
    setLoading(true);
    setError('');

    try {
      const res = await axios.post(`${CCTV_API_BASE_URL}/api/cctv/search`, {
        address: targetAddress,
        radius: 500,
      });

      const newIncident = {
        // 랜덤 기반 임시 incident id (프론트 상태 식별용).
        id: `${Date.now()}-${Math.floor(Math.random() * 100000)}`,
        center: res.data.center,
        cctvs: res.data.cctvs,
        total: res.data.total,
        radius: res.data.radius ?? 500,
      };

      const isDuplicated = incidentPlaces.some((incident) =>
        incident.center.address === newIncident.center.address &&
        incident.center.lat === newIncident.center.lat &&
        incident.center.lng === newIncident.center.lng
      );

      if (isDuplicated) {
        setError('이미 지도에 추가된 사건 장소입니다.');
        return;
      }

      setIncidentPlaces((prev) => {
        const next = [...prev, newIncident];

        // 모든 사건 장소 주소를 ' | '로 이어서 DB에 누적 저장
        if (recordId && recordOwnerGoogleSub) {
          const saved = sessionStorage.getItem('user');
          if (saved) {
            try {
              const user = JSON.parse(saved);
              if (user?.id && user.id === recordOwnerGoogleSub) {
                const allAddresses = next
                  .map((inc) => inc.center.address)
                  .filter(Boolean)
                  .join(' | ');
                updateRecordLocation({
                  recordId,
                  googleSub: user.id,
                  locationCase: allAddresses,
                }).catch(() => {}); // 위치 저장 실패가 UX를 막지 않도록 무시
              }
            } catch {
              // sessionStorage 파싱 실패는 무시
            }
          }
        }

        return next;
      });

      if (!addressOverride) {
        setAddress('');
      } else {
        setAddress(targetAddress);
      }
    } catch (err) {
      setError(
        err.response?.data?.detail || 'CCTV 검색 중 오류가 발생했습니다.'
      );
    } finally {
      setLoading(false);
    }
  }, [address, incidentPlaces, recordId, recordOwnerGoogleSub]);

  useEffect(() => {
    // CasePage에서 전달된 초기 주소가 있으면 최초 1회 자동 검색한다.
    if (!initialAddress) return;
    if (autoLoadedRef.current) return;
    if (incidentPlaces.length > 0) return;

    autoLoadedRef.current = true;

    // ' | '로 구분된 다중 주소를 순차 검색
    const addresses = initialAddress.split('|').map((a) => a.trim()).filter(Boolean);
    if (addresses.length === 0) return;

    setAddress(addresses[0]);

    (async () => {
      for (const addr of addresses) {
        // 다중 주소를 순차 처리해 지도/리스트 상태 충돌을 줄인다.
        try {
          const res = await axios.post(`${CCTV_API_BASE_URL}/api/cctv/search`, {
            address: addr,
            radius: 500,
          });
          const newIncident = {
            id: `${Date.now()}-${Math.floor(Math.random() * 100000)}`,
            center: res.data.center,
            cctvs: res.data.cctvs,
            total: res.data.total,
            radius: res.data.radius ?? 500,
          };
          setIncidentPlaces((prev) => {
            const isDuplicated = prev.some(
              (inc) =>
                inc.center.address === newIncident.center.address &&
                inc.center.lat === newIncident.center.lat &&
                inc.center.lng === newIncident.center.lng
            );
            return isDuplicated ? prev : [...prev, newIncident];
          });
        } catch {
          // 개별 주소 검색 실패는 건너뜀
        }
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialAddress]);

  // mapListVersion이 바뀔 때마다 ref에서 최신 목록을 재계산
  const uniqueCctvList = useMemo(() =>
    // 마커 ref Map을 UI 렌더용 배열로 변환한다.
    Array.from(cctvMarkersRef.current.entries()).map(([key, value]) => ({
      key,
      ...value.cctv,
      incidentCount: value.incidents.size,
      isOverlapped: value.incidents.size > 1,
    })),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [mapListVersion]);
  const totalCctvCount = uniqueCctvList.length;


  return (
    <div className="cctv-page">
      <div className="cctv-content">

        {/* ── 제목 ── */}
        <h1 className="cctv-title">📷 주변 CCTV 위치 조회</h1>
        <p className="cctv-desc">
          사건 장소 주소를 입력하면 반경 500m 이내 CCTV 위치를 지도에 표시합니다.
        </p>

        {/* ── 주소 입력 ── */}
        <div className="cctv-search-wrap">
          <input
            className="cctv-input"
            type="text"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="예) 서울시 강남구 테헤란로 123"
          />
          <button
            className="cctv-search-btn"
            onClick={() => handleSearch()}
            disabled={loading}
          >
            {loading ? '검색 중...' : '검색'}
          </button>
        </div>

        {/* ── 오류 메시지 ── */}
        {error && <p className="cctv-error">⚠️ {error}</p>}

        {/* ── 결과 요약 ── */}
        {incidentPlaces.length > 0 && (
          <div className="cctv-summary">
            <span className="summary-addr">📍 사건 장소 {incidentPlaces.length}개</span>
            <span className="summary-count">
              반경 500m 이내 CCTV <b>{totalCctvCount}개</b>
            </span>
          </div>
        )}

        <div className="cctv-result-layout">
          {/* ── 지도 (왼쪽) ── */}
          <div className="cctv-map-panel">
            <div ref={mapRef} className="cctv-map cctv-map--show" />
          </div>

          {/* ── CCTV 목록 (오른쪽) ── */}
          <div className="cctv-list-panel">
            {uniqueCctvList.length > 0 ? (
              <div className="cctv-list">
                <h2 className="cctv-list-title">CCTV 목록</h2>
                {uniqueCctvList.map((cctv, i) => (
                  <div
                    key={cctv.key}
                    className={`cctv-item ${selectedCctvId === cctv.key ? 'cctv-item--active' : ''} ${cctv.isOverlapped ? 'cctv-item--overlap' : ''}`}
                    onClick={() => handleCctvItemClick(cctv)}
                  >
                    <span className="cctv-item-num">{i + 1}</span>
                    <div className="cctv-item-info">
                      <p className="cctv-item-addr">{cctv.address}</p>
                      <p className="cctv-item-dist">기준점으로부터 {cctv.distance}m</p>
                      {cctv.isOverlapped && (
                        <p className="cctv-overlap-badge">겹침 구간 CCTV (사건 {cctv.incidentCount}건 공통)</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="cctv-empty">주소를 검색하면 CCTV 목록이 표시됩니다.</p>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}


// ── Google Maps 다크 테마 스타일 ──
const DARK_MAP_STYLE = [
  { elementType: 'geometry',        stylers: [{ color: '#0d1526' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#0d1526' }] },
  { elementType: 'labels.text.fill',   stylers: [{ color: '#a0a8b8' }] },
  { featureType: 'road',
    elementType: 'geometry',         stylers: [{ color: '#172035' }] },
  { featureType: 'road',
    elementType: 'geometry.stroke',  stylers: [{ color: '#0d1526' }] },
  { featureType: 'road',
    elementType: 'labels.text.fill', stylers: [{ color: '#8a9ab0' }] },
  { featureType: 'water',
    elementType: 'geometry',         stylers: [{ color: '#0a1020' }] },
  { featureType: 'poi',
    elementType: 'geometry',         stylers: [{ color: '#172035' }] },
  { featureType: 'transit',
    elementType: 'geometry',         stylers: [{ color: '#172035' }] },
];

export default CctvPage;