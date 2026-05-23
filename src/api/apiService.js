import axios from 'axios';

// 분석 API(프론트 프록시/별도 서버) 기본 주소.
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:3000';
// 인증/기록 관리 백엔드 주소.
const AUTH_API_BASE_URL = import.meta.env.VITE_AUTH_API_URL || 'http://localhost:8000';

// 공통 axios 인스턴스.
const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 요청 인터셉터: 인증 토큰 추가 (필요 시)
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('authToken');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// 응답 인터셉터: 에러 처리
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

/**
 * 사연 분석 API
 * @param {string} text - 원본 사연 텍스트
 * @returns {Promise<{polishedStory: string, relatedLaws: string[]}>}
 */
export const analyzeStory = async (text) => {
  try {
    const response = await api.post('/api/analyze', { text });
    return response.data;
  } catch {
    throw new Error('사연 분석에 실패했습니다.');
  }
};

/**
 * 유사 판례 조회 API
 * @param {string} storyId - 사연 ID
 * @returns {Promise<Array<{verdict: string, caseNumber: string, similarity: number, description: string}>>}
 */
export const getSimilarCases = async (storyId) => {
  try {
    const response = await api.post('/api/cases', { storyId });
    return response.data;
  } catch {
    throw new Error('유사 판례 조회에 실패했습니다.');
  }
};

/**
 * 사용자 기록 조회 API
 * @returns {Promise<Array<{id: string, story: string, date: string, status: string}>>}
 */
export const getUserRecords = async () => {
  try {
    const response = await api.get('/api/records');
    return response.data;
  } catch {
    throw new Error('사용자 기록 조회에 실패했습니다.');
  }
};

/**
 * 법령 통합 검색 API (lawFind 기반)
 * @param {string} query - 검색할 질문/키워드
 * @param {string} caseType - civil | criminal | all
 * @param {number} nResults - 반환할 결과 개수 (기본 20)
 * @returns {Promise<{results: Array}>}
 */
export const searchLaws = async (query, caseType = 'all', nResults = 20) => {
  try {
    const response = await axios.post(`${AUTH_API_BASE_URL}/api/law-search`, {
      query,
      case_type: caseType,
      n_results: nResults,
    });
    return response.data;
  } catch (error) {
    console.error('법령 검색 실패:', error);
    throw new Error('법령 검색에 실패했습니다.');
  }
};

/**
 * 판례 검색 API
 * @param {string} query - 검색 키워드
 * @param {string} caseType - civil | criminal
 * @param {number} nResults - 반환할 결과 개수
 * @returns {Promise<{cases: Array}>}
 */
export const searchCases = async (query, caseType = 'civil', nResults = 20) => {
  try {
    const response = await axios.post(`${AUTH_API_BASE_URL}/api/case-search`, {
      query,
      case_type: caseType,
      n_results: nResults,
    });
    return response.data;
  } catch (error) {
    console.error('판례 검색 실패:', error);
    throw new Error('판례 검색에 실패했습니다.');
  }
};

export const createUserRecord = async ({ googleSub, payloadCase, locationCase = '', recordCase = 'traffic_case', caseType = 'civil' }) => {
  // 사용자 사건 기록을 생성하고 생성된 record_id를 돌려받는다.
  const response = await axios.post(`${AUTH_API_BASE_URL}/api/records`, {
    google_sub: googleSub,
    record_case: recordCase,
    case_type: caseType,
    payload_case: payloadCase,
    location_case: locationCase,
  });

  return response.data;
};

export const fetchUserRecords = async ({ googleSub, query = '' }) => {
  // 검색어(query)와 함께 사용자 기록 목록을 가져온다.
  const response = await axios.get(`${AUTH_API_BASE_URL}/api/records`, {
    params: {
      google_sub: googleSub,
      q: query,
    },
  });

  return response.data.records ?? [];
};

export const rerunRecordAnalysis = async ({ recordId, googleSub }) => {
  // 저장된 기록을 다시 분석해 결과 payload를 가져온다.
  const response = await axios.post(`${AUTH_API_BASE_URL}/api/records/${recordId}/rerun`, {
    google_sub: googleSub,
  });

  return response.data;
};

export const updateRecordLocation = async ({ recordId, googleSub, locationCase }) => {
  // CCTV 페이지에서 누적 사건 장소를 기록의 location_case에 반영한다.
  const response = await axios.patch(`${AUTH_API_BASE_URL}/api/records/${recordId}/location`, {
    google_sub: googleSub,
    location_case: locationCase,
  });

  return response.data;
};

export const deleteUserRecord = async ({ recordId, googleSub }) => {
  // 특정 기록을 사용자 소유권(google_sub)으로 검증하며 삭제한다.
  const response = await axios.delete(`${AUTH_API_BASE_URL}/api/records/${recordId}`, {
    params: { google_sub: googleSub },
  });

  return response.data;
};

/**
 * 핵심 키워드 추출 API (Gemini 사용)
 * @param {string} prompt - 사용자가 입력한 사건 프롬프트
 * @param {File} file - 첨부 문서 (선택사항)
 * @returns {Promise<{success: boolean, keywords: object, message: string, file_text_preview: string}>}
 */
export const extractKeywords = async (prompt, files = []) => {
  try {
    const formData = new FormData();
    
    // JSON 필드는 application/json이 아닌 multipart로 전송하므로 문자열로 추가
    formData.append('prompt', prompt);

    const normalizedFiles = Array.isArray(files)
      ? files
      : files
        ? [files]
        : [];

    normalizedFiles.forEach((file) => {
      if (file) {
        formData.append('files', file);
      }
    });

    const response = await axios.post(`${AUTH_API_BASE_URL}/api/extract-keywords`, formData);

    return response.data;
  } catch (error) {
    console.error('키워드 추출 실패:', error);
    throw new Error('핵심 키워드 추출에 실패했습니다.');
  }
};

export default api;