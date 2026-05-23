import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchUserRecords, rerunRecordAnalysis, deleteUserRecord } from '../api/apiService';
import '../styles/RecordPage.css';

function RecordPage() {
  const navigate = useNavigate();
  // 서버에서 읽어온 사용자 기록 목록.
  const [records, setRecords] = useState([]);
  // 검색 입력값.
  const [search, setSearch] = useState('');
  // 초기/재조회 로딩 상태.
  const [loading, setLoading] = useState(true);
  // 특정 기록 열기 버튼의 진행 상태.
  const [openingId, setOpeningId] = useState(null);
  // 사용자에게 보여줄 에러 메시지.
  const [error, setError] = useState('');

  // 레거시/신규 구조를 모두 지원해 첨부 파일명 목록을 만든다.
  const getRecordFileNames = (record) => {
    if (Array.isArray(record.file_names) && record.file_names.length > 0) {
      return record.file_names.filter(Boolean);
    }

    if (Array.isArray(record.saved_files) && record.saved_files.length > 0) {
      return record.saved_files
        .map((file) => file?.original_name)
        .filter(Boolean);
    }

    return [];
  };

  const getRecordFileSummaries = (record) => {
    if (!Array.isArray(record.file_summaries)) {
      return [];
    }
    return record.file_summaries.filter((item) => item?.summary);
  };

  const toSummaryPreview = (value) => {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    if (!text) return '';
    return text.length > 220 ? `${text.slice(0, 220)}...` : text;
  };

  const user = useMemo(() => {
    // 렌더마다 파싱하지 않도록 로그인 정보는 메모이즈한다.
    const saved = sessionStorage.getItem('user');
    if (!saved) return null;

    try {
      const parsed = JSON.parse(saved);
      return parsed?.id ? parsed : null;
    } catch {
      return null;
    }
  }, []);

  const loadRecords = async (query = '') => {
    // 로그인 사용자 식별자가 없으면 조회하지 않는다.
    if (!user?.id) return;

    setLoading(true);
    setError('');

    try {
      const data = await fetchUserRecords({
        googleSub: user.id,
        query,
      });
      setRecords(data);
    } catch {
      setError('기록 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRecords();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSearch = () => {
    // 현재 검색어로 서버 재조회.
    loadRecords(search.trim());
  };

  const handleDeleteRecord = async (recordId) => {
    if (!user?.id) return;
    if (!window.confirm('이 기록을 삭제하시겠습니까?')) return;

    try {
      await deleteUserRecord({ recordId, googleSub: user.id });
      setRecords((prev) => prev.filter((r) => r.id !== recordId));
    } catch {
      setError('기록 삭제 중 오류가 발생했습니다.');
    }
  };

  const handleOpenRecord = async (record) => {
    // 저장 기록을 백엔드에서 재분석해 ResultPage 상태로 전달한다.
    if (!user?.id) return;

    const recordId = record?.id;
    if (!recordId) return;

    setOpeningId(recordId);
    setError('');

    try {
      const response = await rerunRecordAnalysis({
        recordId,
        googleSub: user.id,
      });

      const payload = response?.result_payload ?? {};

      navigate('/result', {
        state: {
          polishedStory: payload.polishedStory ?? '',
          savedFilePaths: payload.savedFilePaths ?? [],
          relatedLaws: payload.relatedLaws ?? [],
          cases: payload.cases ?? [],
          recordId: payload.recordId ?? recordId,
          recordOwnerGoogleSub: user.id,
          locationCase: payload.locationCase ?? '',
          generatedTitle: payload.generatedTitle ?? '제목 없음',
          extractedKeywords: payload.extractedKeywords ?? null,
          caseType: payload.caseType ?? record.case_type ?? 'civil',
          fromRecord: true,
        },
      });
    } catch {
      setError('기록을 여는 중 오류가 발생했습니다.');
    } finally {
      setOpeningId(null);
    }
  };

  if (!user) {
    return (
      <div className="record-page">
        <div className="record-panel record-panel--center">
          <p>로그인한 사용자만 이용할 수 있습니다.</p>
          <button className="record-action-btn" onClick={() => navigate('/')}>
            홈으로 이동
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="record-page">
      <div className="record-panel">
        <div className="record-head">
          <h1>나의 기록</h1>
          <p>{user.name || user.email}님의 사건 기록을 검색하고 다시 실행할 수 있습니다.</p>
        </div>

        <div className="record-search-wrap">
          <input
            className="record-search-input"
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="제목, 사건 내용, 사건 장소로 검색"
          />
          <button className="record-action-btn" onClick={handleSearch}>
            검색
          </button>
        </div>

        {error && <p className="record-error">{error}</p>}

        {loading ? (
          <p className="record-status">기록을 불러오는 중입니다...</p>
        ) : records.length === 0 ? (
          <p className="record-status">검색 결과가 없습니다.</p>
        ) : (
          <ul className="record-list">
            {records.map((record) => {
              const fileNames = getRecordFileNames(record);
              const fileSummaries = getRecordFileSummaries(record);

              return (
              <li key={record.id} className="record-item">
                <div className="record-item-main">
                  <div className="record-item-top">
                    <h3>{record.title || '제목 없음'}</h3>
                    <span className="record-date">
                      {record.updated_at ? new Date(record.updated_at).toLocaleString() : ''}
                    </span>
                  </div>

                  <div className="record-case-type">
                    {record.case_type === 'criminal' ? '형사' : '민사'}
                  </div>

                  <p className="record-story-preview">{record.story || '저장된 사건 설명이 없습니다.'}</p>

                  <div className="record-meta-row">
                    <span>첨부 파일 {record.file_paths?.length || 0}개</span>
                    <span>{record.location_case ? `사건 장소: ${record.location_case}` : '사건 장소 미입력'}</span>
                  </div>

                  {fileNames.length > 0 && (
                    <p className="record-file-names">
                      첨부 문서: {fileNames.join(', ')}
                    </p>
                  )}

                  {fileSummaries.length > 0 && (
                    <div className="record-file-names">
                      {fileSummaries.slice(0, 2).map((item, idx) => (
                        <p key={`${item.file_name}-${idx}`}>
                          {item.file_name}: {toSummaryPreview(item.summary)}
                        </p>
                      ))}
                    </div>
                  )}
                </div>

                <div className="record-btn-group">
                  <button
                    className="record-open-btn"
                    disabled={openingId === record.id}
                    onClick={() => handleOpenRecord(record)}
                  >
                    {openingId === record.id ? '여는 중...' : '기록 열기'}
                  </button>
                  <button
                    className="record-delete-btn"
                    onClick={() => handleDeleteRecord(record.id)}
                  >
                    삭제
                  </button>
                </div>
              </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

export default RecordPage;
