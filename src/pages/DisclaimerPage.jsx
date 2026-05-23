import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import '../styles/DisclaimerPage.css';

function DisclaimerPage() {
  const navigate = useNavigate();
  // 면책 조항 체크 여부.
  const [agreed, setAgreed] = useState(false);

  const handleAgreeChange = (e) => {
    const isChecked = e.target.checked;
    setAgreed(isChecked);

    // 동의 즉시 메인 입력 페이지로 이동한다.
    if (isChecked) {
      navigate('/main');
    }
  };

  return (
    <div className="disclaimer-page">
      <div className="disclaimer-glow disclaimer-glow--top" />
      <div className="disclaimer-glow disclaimer-glow--bottom" />

      <section className="disclaimer-card" aria-labelledby="disclaimer-title">
        <p className="disclaimer-chip">AI 법률 안내</p>
        <h1 id="disclaimer-title" className="disclaimer-heading">
          서비스 이용 전
          <br />
          면책 조항을 확인해 주세요
        </h1>

        <p className="disclaimer-body">
          본 서비스는 AI 기반 법률 정보 제공 서비스로, 법률 조언이나 법적 효력을 갖지
          않습니다. 제공되는 정보는 참고용으로만 활용하시기 바라며, 실제 법적 문제는
          반드시 전문 변호사와 상담하시기 바랍니다. 본 서비스의 분석 결과로 인한 손해에
          대해 책임을 지지 않습니다.
        </p>

        <label className="disclaimer-check" htmlFor="agree-disclaimer">
          <input
            id="agree-disclaimer"
            type="checkbox"
            checked={agreed}
            onChange={handleAgreeChange}
          />
          <span>위 면책 조항을 읽었으며 동의합니다.</span>
        </label>

        <p className="disclaimer-helper">체크하면 Main 페이지로 자동 이동합니다.</p>
      </section>
    </div>
  );
}

export default DisclaimerPage;
