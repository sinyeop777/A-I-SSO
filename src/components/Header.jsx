import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import '../styles/header.css';


const Header = ({ onListClick }) => {
  const navigate = useNavigate();
  // sessionStorage의 사용자 정보를 초기값으로 복원한다.
  const [user, setUser] = useState(() => {
    const saved = sessionStorage.getItem('user');
    if (!saved) return null;

    try {
      const parsed = JSON.parse(saved);
      const now = Math.floor(Date.now() / 1000);

      if (parsed?.expires_at && now > parsed.expires_at) {
        sessionStorage.removeItem('user');
        return null;
      }

      return parsed;
    } catch {
      sessionStorage.removeItem('user');
      return null;
    }
  });
  const [showExpiry, setShowExpiry] = useState(false); // 만료 경고 모달
  const timerRef = useRef(null); // 만료 타이머

  // ── 토큰 만료 처리 ──
  const handleTokenExpired = useCallback(() => {
    sessionStorage.removeItem('user');
    setUser(null);
    setShowExpiry(false);
    if (window.google) {
      window.google.accounts.id.disableAutoSelect();
    }
    alert('로그인이 만료되었습니다. 다시 로그인해주세요.');
  }, []);

  // ── 저장된 사용자 기준으로 만료/타이머 동기화 ──
  useEffect(() => {
    // 로그인 만료 시각이 없으면 타이머를 설정하지 않는다.
    if (!user?.expires_at) return;

    if (timerRef.current) clearTimeout(timerRef.current);

    const now = Math.floor(Date.now() / 1000);
    const remaining = (user.expires_at - now) * 1000;
    let warningTimer = null;

    if (remaining > 0) {
      const warningTime = remaining - 5 * 60 * 1000;
      if (warningTime > 0) {
        warningTimer = setTimeout(() => setShowExpiry(true), warningTime);
      }

      timerRef.current = setTimeout(() => {
        handleTokenExpired();
      }, remaining);
    } else {
      timerRef.current = setTimeout(() => {
        handleTokenExpired();
      }, 0);
    }

    return () => {
      // effect 재실행/언마운트 시 기존 타이머를 정리한다.
      if (warningTimer) clearTimeout(warningTimer);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [handleTokenExpired, user]);

  // ── Google 초기화 ──
  useEffect(() => {
    // Google 로그인 콜백을 window에 등록해 외부 스크립트가 호출하도록 한다.
    window.handleCredentialResponse = async (response) => {
      try {
        const res = await axios.post(
          'http://localhost:8000/api/auth/google',
          { token: response.credential }
        );

        const userData = res.data.user;

        // 로그인 성공 시 사용자 정보를 저장해 새로고침 후에도 유지한다.
        sessionStorage.setItem('user', JSON.stringify(userData));

        setUser(userData);

      } catch (err) {
        const detail = err.response?.data?.detail;

        if (detail === 'TOKEN_EXPIRED') {
          alert('로그인 토큰이 만료되었습니다. 다시 로그인해주세요.');
        } else {
          console.error('로그인 실패:', err);
          alert('로그인 중 오류가 발생했습니다.');
        }
      }
    };

    const initGoogle = () => {
      // Google SDK가 로드된 경우 버튼을 렌더링한다.
      if (window.google) {
        window.google.accounts.id.initialize({
          client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID,
          callback:  window.handleCredentialResponse,
        });

        window.google.accounts.id.renderButton(
          document.getElementById('google-btn'),
          {
            type:           'standard',
            shape:          'pill',
            theme:          'outline',
            text:           'signin_with',
            size:           'large',
            logo_alignment: 'left',
          }
        );
      }
    };

    if (window.google) {
      // SDK가 이미 로드되어 있으면 즉시 초기화.
      initGoogle();
    } else {
      // 아직 로드 전이면 window.onload 시점에 초기화.
      window.onload = initGoogle;
    }

    // 컴포넌트 언마운트 시 타이머 정리
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  // ── 로그아웃 ──
  const handleLogout = () => {
    // 로컬 세션/타이머를 정리하고 UI를 비로그인 상태로 전환한다.
    if (timerRef.current) clearTimeout(timerRef.current);
    sessionStorage.removeItem('user');
    setUser(null);
    setShowExpiry(false);
    if (window.google) {
      window.google.accounts.id.disableAutoSelect();
    }
  };

  return (
    <>
      <header className="hp-header">
        {/* 로고 클릭 시 홈 이동 */}
        <div className="header-logo" onClick={() => navigate('/')} role="button" style={{ cursor: 'pointer' }}>
          <img src="/images/logoIcon.png" alt="로고" />
          <span>A(I)SSO</span>
        </div>

        <div className="header-btn-group">
          {/* Google SDK가 버튼을 그릴 대상 컨테이너 */}
          <div id="google-btn" className={user ? 'google-btn-hidden' : ''} />

          {user ? (
            <div className="user-profile">
              <img src={user.picture} alt="프로필" className="profile-img" />
              <span className="user-name">{user.name}</span>
              <button className="logout-btn" onClick={handleLogout}>로그아웃</button>
              <button className="header-btn" onClick={onListClick}>목록</button>
            </div>
          ) : (
            <button className="header-btn" onClick={onListClick}>목록</button>
          )}
        </div>
      </header>

      {/* ── 만료 경고 모달 ── */}
      {showExpiry && (
        <div className="expiry-overlay">
          <div className="expiry-modal">
            <p className="expiry-title">⚠️ 로그인 만료 예정</p>
            <p className="expiry-desc">
              5분 후 로그인이 만료됩니다.<br />
              계속 이용하려면 다시 로그인해주세요.
            </p>
            <div className="expiry-btns">
              <button
                className="expiry-btn expiry-btn--dismiss"
                onClick={() => setShowExpiry(false)}
              >
                나중에
              </button>
              <button
                className="expiry-btn expiry-btn--relogin"
                onClick={() => {
                  handleLogout();
                  setShowExpiry(false);
                }}
              >
                다시 로그인
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default Header;