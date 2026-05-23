import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { createUserRecord, extractKeywords } from '../api/apiService';
import '../styles/MainPage.css';

function MainPage() {
  // 사건 본문 입력 상태.
  const [story, setStory] = useState('');
  // 제출/저장 진행 상태.
  const [loading, setLoading] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false); // 모달리스 상태
  const [uploadedFiles, setUploadedFiles] = useState([]); // 파일 목록
  const [caseType, setCaseType] = useState('civil'); // 민사='civil', 형사='criminal'
  const [user] = useState(() => {
    // 초기 로드 시 sessionStorage에서 로그인 사용자 읽어오기
    const saved = sessionStorage.getItem('user');
    if (!saved) return null;
    try {
      const parsed = JSON.parse(saved);
      return parsed?.id ? parsed : null;
    } catch {
      return null;
    }
  });
  const fileInputRef = useRef(null);
  const navigate = useNavigate();

  // 파일 업로드 처리
  const handleFileChange = (e) => {
    const files = Array.from(e.target.files);
    setUploadedFiles((prev) => [...prev, ...files]);
  };

  // 파일 삭제
  const removeFile = (index) => {
    setUploadedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async () => {
    // 텍스트와 파일이 모두 비어 있으면 제출을 막는다.
    if (!story.trim() && uploadedFiles.length === 0) {
      alert('사연을 입력하거나 파일을 업로드해주세요.');
      return;
    }

    // 파일 원본명 목록을 저장 payload에 포함한다.
    const filePaths = uploadedFiles.map((file) => file.name);

    const moveToResultPage = (created = null, keywordResult = null) => {
      // 분석 결과 페이지로 이동하면서 현재 입력 상태를 함께 전달한다.
      // (ResultPage에서 키워드 추출을 처리함)
      navigate('/result', {
        state: {
          polishedStory: story,
          files: uploadedFiles, // 첨부 파일 객체 배열 전달
          savedFilePaths: filePaths,
          relatedLaws: [],
          storyId: null,
          recordId: created?.record_id ?? null,
          recordOwnerGoogleSub: user?.id ?? null,
          generatedTitle: created?.title,
          locationCase: '',
          extractedKeywords: keywordResult,
          caseType: caseType,
        },
      });
    };

    setLoading(true);

    try {
      if (!user) {
        // 비로그인 사용자는 기록 저장 없이 결과 페이지로만 이동한다.
        console.log('[MainPage] 비로그인 사용자 - 결과 페이지로 이동');
        moveToResultPage(null);
        return;
      }

      // 로그인 사용자는 기록 저장 전에 키워드/문서 요약을 생성한다.
      let keywordResult = null;
      try {
        keywordResult = await extractKeywords(story || '첨부 문서를 분석해 핵심을 추출해주세요.', uploadedFiles);
      } catch (extractError) {
        console.warn('[MainPage] 키워드/요약 사전 추출 실패:', extractError);
      }

      // 로그인 사용자는 백엔드에 기록을 생성한다.
      console.log('[MainPage] 기록 생성 시작...');
      const created = await createUserRecord({
        googleSub: user.id,
        caseType,
        payloadCase: {
          story,
          file_paths: filePaths,
          extracted_keywords: keywordResult?.keywords ?? [],
          file_summaries: keywordResult?.file_summaries ?? [],
        },
        locationCase: '',
      });

      console.log('[MainPage] ✅ 기록 생성 성공:', created.record_id);
      moveToResultPage(created, keywordResult);
    } catch (error) {
      console.error('[MainPage] 오류 발생:', error);
      alert('처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="main-page">
      <div className="main-content">
        <div className="lamp-wrap">
          <div className="lamp-wire" />
          <div className="lamp-bulb" />
          <div className="lamp-glow" />
        </div>

        {/* ── 새 파일 업로드 버튼 ── */}
        <button 
          className="new-file-btn" 
          // 파일 목록 패널 토글.
          onClick={() => setIsModalOpen(!isModalOpen)}
        >
          {isModalOpen ? '목록 닫기' : '+ 새 파일 업로드'}
        </button>

        <textarea
          className="story-textarea"
          value={story}
          onChange={(e) => setStory(e.target.value)}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !loading) {
              handleSubmit();
            }
          }}
          placeholder="사연을 입력하세요..."
          disabled={loading}
        />

        <div className="case-type-selector">
          <label>판례 유형 선택:</label>
          <div className="case-type-options">
            <label className="radio-wrapper">
              <input
                type="radio"
                name="caseType"
                value="civil"
                checked={caseType === 'civil'}
                onChange={(e) => setCaseType(e.target.value)}
              />
              <span>민사</span>
            </label>
            <label className="radio-wrapper">
              <input
                type="radio"
                name="caseType"
                value="criminal"
                checked={caseType === 'criminal'}
                onChange={(e) => setCaseType(e.target.value)}
              />
              <span>형사</span>
            </label>
          </div>
        </div>

        {loading ? (
          <div className="loading-spinner" />
        ) : (
          <button
            className="submit-btn"
            onClick={handleSubmit}
            disabled={!story.trim() && uploadedFiles.length === 0}
          >
            제출
          </button>
        )}

        <p className="welcome-msg">
          <span>{user?.name || '회원'}</span>님 어서오세요!
        </p>

        {/* ── 모달리스 파일 업로드 창 ── */}
        {isModalOpen && (
          <div className="modaless-upload-box">
            <div className="modal-header">
              <h4>첨부 파일 목록</h4>
              <button className="close-mini-btn" onClick={() => setIsModalOpen(false)}>×</button>
            </div>
            
            <div className="file-controls">
              <input 
                type="file" 
                multiple 
                style={{ display: 'none' }} 
                ref={fileInputRef}
                onChange={handleFileChange}
              />
              {/* 숨겨진 input을 버튼으로 트리거한다. */}
              <button className="add-file-trigger" onClick={() => fileInputRef.current.click()}>
                파일 선택
              </button>
            </div>

            <ul className="uploaded-file-list">
              {uploadedFiles.length === 0 ? (
                <li className="empty-msg">첨부된 파일이 없습니다.</li>
              ) : (
                uploadedFiles.map((file, i) => (
                  <li key={i} className="file-item">
                    <span className="file-name">{file.name}</span>
                    <button className="file-remove-btn" onClick={() => removeFile(i)}>삭제</button>
                  </li>
                ))
              )}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

export default MainPage;