import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Header from './components/Header';
import SidePanel from './components/SidePanel';
import HomePage from './pages/HomePage';
import DisclaimerPage from './pages/DisclaimerPage';
import MainPage from './pages/MainPage';
import ResultPage from './pages/ResultPage';
import CasePage from './pages/CasePage';
import CctvPage from './pages/CctvPage';
import RecordPage from './pages/RecordPage';


import './App.css';
import './styles/sidePanel.css';

function App() {
  // 헤더의 "목록" 버튼으로 열고 닫는 사이드 패널 상태.
  const [isSidePanelOpen, setIsSidePanelOpen] = useState(false);

  // 현재 상태를 반전해 사이드 패널 토글.
  const toggleSidePanel = () => {
    setIsSidePanelOpen(!isSidePanelOpen);
  };

  // 사이드 패널 메뉴 항목 정의.
  const sampleItems = [
    { label: '나의 기록', path: '/record' },
    { label: 'CCTV 조회', path: '/cctv' },
  ];

  return (
    // 앱 전체 라우팅 컨텍스트.
    <Router>
      {/* 공통 헤더: 목록 버튼 클릭 이벤트를 상위에서 전달 */}
      <Header onListClick={toggleSidePanel} />
      {/* 페이지별 라우트 매핑 */}
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/disclaimer" element={<DisclaimerPage />} />
        <Route path="/main" element={<MainPage />} />
        <Route path="/record" element={<RecordPage />} />
        <Route path="/result" element={<ResultPage />} />
        <Route path="/case" element={<CasePage />} />
        <Route path="/cctv" element={<CctvPage />} />
      </Routes>
      {/* 모든 페이지에서 공통으로 사용할 사이드 패널 */}
      <SidePanel isOpen={isSidePanelOpen} onClose={toggleSidePanel} items={sampleItems} />
    </Router>
  );
}

export default App;
