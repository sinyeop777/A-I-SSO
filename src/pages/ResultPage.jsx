import { useState, useEffect, useCallback, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { extractKeywords, searchLaws, searchCases } from '../api/apiService';

import '../styles/ResultPage.css';

// 컴포넌트 외부 상수 → 항상 동일 참조 보장 (useEffect 무한루프 방지)
const EMPTY_FILES = [];
const EMPTY_SAVED_FILE_PATHS = [];

const buildKeywordString = (keywords) => {
  if (Array.isArray(keywords) && keywords.length > 0) {
    return keywords.join(' ');
  }

  if (keywords && typeof keywords === 'object') {
    const values = Object.values(keywords).flat();
    return Array.isArray(values) ? values.join(' ') : String(values || '');
  }

  return '';
};

function ResultPage() {
  // 라우트 state로 전달된 입력/분석 데이터를 읽는다.
  const locationState = useLocation().state;
  const navigate = useNavigate();

  const polishedStory = locationState?.polishedStory ?? "";
  const files = locationState?.files ?? EMPTY_FILES;
  const savedFilePaths = locationState?.savedFilePaths ?? EMPTY_SAVED_FILE_PATHS;
  const caseType = locationState?.caseType ?? "civil";
  const fileSummaries = useMemo(
    () => locationState?.extractedKeywords?.file_summaries ?? [],
    [locationState?.extractedKeywords?.file_summaries]
  );
  const fromRecord = Boolean(locationState?.fromRecord);
  const preloadedExtractedKeywords = locationState?.extractedKeywords ?? null;

  const [viewerList, setViewerList] = useState([]);
  // 좌측 뷰어에서 현재 표시 중인 문서 인덱스.
  const [currentIndex, setCurrentIndex] = useState(0);
  // 서버 문서 변환 진행 상태.
  const [isTransforming, setIsTransforming] = useState(false);
  // 키워드 추출 상태
  const [extractedKeywords, setExtractedKeywords] = useState(preloadedExtractedKeywords);
  const [isExtracting, setIsExtracting] = useState(false);
  const [hasKeywordRequested, setHasKeywordRequested] = useState(Boolean(preloadedExtractedKeywords));
  // 법령 검색 결과 state
  const [lawResults, setLawResults] = useState([]);
  const [isLawLoading, setIsLawLoading] = useState(false);
  const [lawError, setLawError] = useState("");
  const [selectedLawIndex, setSelectedLawIndex] = useState(0);
  const [isCaseLoading, setIsCaseLoading] = useState(false);
  const keywordString = useMemo(
    () => buildKeywordString(extractedKeywords?.keywords),
    [extractedKeywords?.keywords]
  );

  // 키워드 추출 결과 기반 법령 검색
  useEffect(() => {
    // 키워드 추출이 끝나야만 검색
    if (isExtracting || !extractedKeywords || !extractedKeywords.success) {
      setLawResults([]);
      setLawError("");
      setIsLawLoading(false);
      return;
    }
    // 반드시 키워드가 있을 때만 검색
    if (!keywordString) {
      setLawResults([]);
      setLawError("");
      setIsLawLoading(false);
      return;
    }
    let cancelled = false;
    setIsLawLoading(true);
    setLawError("");
    searchLaws(keywordString, caseType, 20)
      .then((data) => {
        if (!cancelled) {
          setLawResults(data.results || []);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setLawError(err.message || "법령 검색 오류");
          setLawResults([]);
        }
      })
      .finally(() => {
        if (!cancelled) setIsLawLoading(false);
      });
    return () => { cancelled = true; };
  }, [extractedKeywords, isExtracting, keywordString, caseType]);

  useEffect(() => {
    if (lawResults.length === 0) {
      setSelectedLawIndex(0);
      return;
    }
    setSelectedLawIndex((prev) => Math.min(prev, lawResults.length - 1));
  }, [lawResults]);

  // 판례 검색 후 CasePage로 이동
  const handleGoToCase = async () => {
    if (isCaseLoading) {
      return;
    }

    if (!keywordString) {
      alert('검색할 키워드가 없습니다.');
      return;
    }

    setIsCaseLoading(true);
    try {
      const response = await searchCases(keywordString, caseType, 20);
      const searchedCases = response.cases || [];

      navigate('/case', {
        state: {
          cases: searchedCases,
          recordId: locationState?.recordId ?? null,
          recordOwnerGoogleSub: locationState?.recordOwnerGoogleSub ?? null,
          locationCase: locationState?.locationCase ?? '',
          polishedStory,
          savedFilePaths,
          extractedKeywords: extractedKeywords?.keywords,
          caseType: caseType,
        },
      });
    } catch (error) {
      console.error('판례 검색 오류:', error);
      alert('판례 검색 중 오류가 발생했습니다.');
      setIsCaseLoading(false);
    }
  };

  const normalizedKeywords = useMemo(() => {
    const raw = extractedKeywords?.keywords;

    if (Array.isArray(raw)) {
      return {
        detail: null,
        list: raw
          .map((item) => String(item).trim())
          .filter(Boolean),
      };
    }

    if (raw && typeof raw === 'object') {
      return {
        detail: raw,
        list: [],
      };
    }

    return {
      detail: null,
      list: [],
    };
  }, [extractedKeywords?.keywords]);

  // 서버 연동 파일 변환 로직
  useEffect(() => {
    let cancelled = false;
    const createdUrls = [];

    // "나의 기록"에서 진입한 경우: 첨부파일 요약을 텍스트로 보여줌
    if (fromRecord) {
      const list = [];
      // 사건 경위서(입력한 글)는 항상 첫 번째로 추가
      if (polishedStory) {
        list.push({ type: 'text', name: '입력된 사건 경위서', content: polishedStory });
      }
      // 첨부파일 요약이 있으면 그 뒤에 추가
      if (Array.isArray(fileSummaries) && fileSummaries.length > 0) {
        fileSummaries.forEach((item, idx) => {
          list.push({
            type: 'text',
            name: item.file_name || `첨부파일 ${idx + 1}`,
            content: item.summary || '',
          });
        });
      }
      setViewerList(list);
      setIsTransforming(false);
      return () => {};
    }

    // 기존 방식: 파일 원본/변환본을 뷰어로 보여줌
    const processFiles = async () => {
      setIsTransforming(true);
      const list = [];

      // 텍스트 사건 경위서를 첫 문서로 넣는다.
      if (polishedStory) {
        list.push({ type: 'text', name: '입력된 사건 경위서', content: polishedStory });
      }

      for (const file of files) {
        const fileExt = file.name.split('.').pop().toLowerCase();

        // HWP/HWPX/DOC/DOCX는 백엔드 변환 엔진을 거쳐 PDF로 표시한다.
        if (['hwp', 'hwpx', 'doc', 'docx'].includes(fileExt)) {
          try {
            const formData = new FormData();
            formData.append('file', file);

            const response = await axios.post('http://localhost:8001/transform', formData, {
              responseType: 'blob',
            });

            const transformedUrl = URL.createObjectURL(response.data);
            createdUrls.push(transformedUrl);
            list.push({ type: 'file', name: `${file.name} (PDF 변환됨)`, url: transformedUrl });
          } catch (error) {
            console.error("변환 실패:", file.name, error);
            list.push({ type: 'text', name: file.name, content: "문서 변환 중 오류가 발생했습니다." });
          }
        } else {
          // 그 외 형식은 브라우저 Blob URL로 직접 표시한다.
          const url = URL.createObjectURL(file);
          createdUrls.push(url);
          list.push({ type: 'file', name: file.name, url });
        }
      }

      if (!cancelled) {
        setViewerList(list);
        setIsTransforming(false);
      }
    };

    processFiles();

    // 언마운트 또는 deps 변경 시 Blob URL 해제
    return () => {
      cancelled = true;
      createdUrls.forEach(url => URL.revokeObjectURL(url));
    };
  }, [files, polishedStory, savedFilePaths, fromRecord, fileSummaries]);

  const extractKeywordsAfterTransform = useCallback(async () => {
    setIsExtracting(true);
    try {
      console.log('[ResultPage] 키워드 추출 중...');
      const normalizedPrompt = polishedStory?.trim()
        ? polishedStory.trim()
        : '첨부 문서를 기반으로 사건 핵심 키워드를 추출해주세요.';

      const result = await extractKeywords(normalizedPrompt, files);
      
      console.log('[ResultPage] 키워드 추출 결과:', result);
      setExtractedKeywords(result);
    } catch (error) {
      console.error('[ResultPage] 키워드 추출 오류:', error);
      setExtractedKeywords({
        success: false,
        keywords: {},
        message: '키워드 추출 중 오류가 발생했습니다',
      });
    } finally {
      setIsExtracting(false);
    }
  }, [files, polishedStory]);

  // 입력 데이터가 바뀌면 키워드 자동 추출 상태를 초기화한다.
  useEffect(() => {
    setExtractedKeywords(preloadedExtractedKeywords);
    setHasKeywordRequested(Boolean(preloadedExtractedKeywords));
  }, [files, polishedStory, preloadedExtractedKeywords]);

  // 파일 변환 완료 후 키워드 추출
  useEffect(() => {
    if (viewerList.length === 0 || hasKeywordRequested) {
      return;
    }

    console.log('[ResultPage] 파일 변환 완료 - 키워드 추출 시작');
    setHasKeywordRequested(true);
    extractKeywordsAfterTransform();
  }, [viewerList, hasKeywordRequested, extractKeywordsAfterTransform]);

  const currentItem = viewerList[currentIndex];
  const selectedLaw = lawResults[selectedLawIndex] ?? null;

  if (isTransforming) {
    return <div className="loading-container">법률 분석 엔진이 문서를 변환 중입니다...</div>;
  }

  if (viewerList.length === 0) {
    return (
      <div className="loading-container">
        표시할 문서가 없습니다.{' '}
        <button onClick={() => navigate(-1)} style={{ marginLeft: 12 }}>← 돌아가기</button>
      </div>
    );
  }

  return (
    <div className="result-split-container">
      <div className="viewer-side">
        <div className="viewer-toolbar">
          <div className="doc-info">
            <span className="doc-badge">{currentItem?.type === 'text' ? 'TEXT' : 'ORIGINAL'}</span>
            <span className="doc-name">{currentItem?.name}</span>
          </div>
          <div className="nav-btns">
            <button onClick={() => setCurrentIndex((index) => Math.max(0, index - 1))} disabled={currentIndex === 0}>이전</button>
            <span className="page-count">{currentIndex + 1} / {viewerList.length}</span>
            <button onClick={() => setCurrentIndex((index) => Math.min(viewerList.length - 1, index + 1))} disabled={currentIndex === viewerList.length - 1}>다음</button>
          </div>
        </div>

        <div className="viewer-content">
          {currentItem?.type === 'text' ? (
            <div className="paper-view text-mode">
              {currentItem.content.split('\n').map((line, index) => (
                <p key={index}>{line}</p>
              ))}
            </div>
          ) : (
            <div className="paper-view file-mode">
              <iframe src={currentItem?.url} title="document-viewer" className="document-frame" />
            </div>
          )}
        </div>
      </div>

      <div className="analysis-side law-explorer-side">
        <div className="law-explorer">
          <div className="law-explorer-header">
            <h2>관련 법령 검색 결과</h2>
            {normalizedKeywords.list.length > 0 && (
              <div className="law-keyword-inline">검색 키워드: {normalizedKeywords.list.join(', ')}</div>
            )}
          </div>

          {isLawLoading ? (
            <div className="law-loading">법령 검색 중...</div>
          ) : lawError ? (
            <div className="law-error">{lawError}</div>
          ) : lawResults.length === 0 ? (
            <div className="law-empty">관련 법령 검색 결과가 없습니다.</div>
          ) : (
            <div className="law-explorer-body">
              <div className="law-list-panel">
                <div className="law-list-scroll">
                  {lawResults.map((law, index) => (
                    <button
                      key={law.statute_id || index}
                      type="button"
                      className={`law-list-item ${selectedLawIndex === index ? 'active' : ''}`}
                      onClick={() => setSelectedLawIndex(index)}
                    >
                      <div className="law-list-title">{law.law_title || '법령명 없음'}</div>
                      <div className="law-list-domain">{law.domain}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="law-detail-panel">
                {selectedLaw ? (
                  <>
                    <div className="law-detail-title">{selectedLaw.law_title || '법령명 없음'}</div>
                    <div className="law-detail-meta">{selectedLaw.domain}</div>
                    <div className="law-detail-content">{selectedLaw.content || '상세 내용이 없습니다.'}</div>
                  </>
                ) : (
                  <div className="law-empty">법령을 선택하면 상세 내용이 표시됩니다.</div>
                )}
              </div>
            </div>
          )}

          <button className="go-to-case-btn" onClick={handleGoToCase} disabled={isCaseLoading}>
            {isCaseLoading ? '판례를 찾는 중...' : '유사 판례 보기'}
          </button>
        </div>
      </div>

      <button className="back-to-main" onClick={() => navigate(-1)}>←</button>
    </div>
  );
}

export default ResultPage;