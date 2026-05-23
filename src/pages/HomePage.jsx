import { useNavigate } from 'react-router-dom';
import { useState } from 'react';
import '../styles/Homepage.css';

function Homepage() {
  const navigate = useNavigate();
  // 법제처 배지 hover 시 툴팁 표시 제어 상태.
  const [lawHovered, setLawHovered] = useState(false);

  return (
    <div className="homepage">
      <div className="bg-grid" />
      <div className="bg-glow bg-glow--tl" />
      <div className="bg-glow bg-glow--br" />

      <main className="hp-hero">
        <div className="hero-left">
          <p className="hero-tag">교통사고 · 법률 분쟁 · 복잡한 사건</p>

          <h1 className="hero-title">
            변호사의 검토 시간은 줄이고,<br />
            <span className="hero-title--accent">변론의 깊이는 더합니다.</span>
          </h1>

          <p className="hero-desc">
            사건을 입력하면 AI가 관련 법령을 분석하고
            유사 판례와 유사률을 찾아드립니다.
          </p>

          <div className="feature-badges">
            <div className="badge">
              <span className="badge-icon">📝</span>
              <span>사건 분석</span>
            </div>
            <div className="badge">
              <span className="badge-icon">⚖️</span>
              <span>관련 법령 검색</span>
            </div>
            <div className="badge">
              <span className="badge-icon">🔍</span>
              <span>유사 판례 제시</span>
            </div>
          </div>

          <button className="cta-btn" onClick={() => navigate('/disclaimer')}>
            {/* 면책 동의 단계로 이동 */}
            <span>사건을 입력하세요</span>
          </button>
        </div>

        <div className="hero-right">
          <div className="hero-img-glow" />
          <img
            src="/images/leftIcon.png"
            alt="이의 있음! 이미지"
            className="hero-img"
          />
        </div>
      </main>

      {/* ── 법제처 배지 ── */}
      <div
        className={`legislation-wrap ${lawHovered ? 'law-hover' : ''}`}
        onMouseEnter={() => setLawHovered(true)}
        onMouseLeave={() => setLawHovered(false)}
      >
        <div className={`tooltip law-tooltip ${lawHovered ? 'tooltip--show' : ''}`}>
          <p className="tt-title">대한민국 공식 법령 데이터 기반</p>
          <p className="tt-body">
            분석에 사용되는 모든 판례 및 법률 자료는
            법제처 국가법령정보센터 API를 통해
            실시간 수신하는 공식 데이터입니다.
          </p>
          <p className="tt-promise">
            정확하고 신뢰할 수 있는 정보만으로 분석함을 약속드립니다.
          </p>
        </div>
        <img src="/images/LegislationIcon.png" alt="법제처" className="law-img" />
      </div>

    </div>
  );
}

export default Homepage;