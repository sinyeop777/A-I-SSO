import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import '../styles/sidePanel.css';

const SidePanel = ({ isOpen, onClose, items = [] }) => {
  const navigate = useNavigate();
  // 마지막으로 선택한 항목 인덱스(활성 스타일 표시용).
  const [selectedIndex, setSelectedIndex] = useState(null);

  return (
    <div className={`side-panel ${isOpen ? 'is-open' : ''}`}>
      <button className="side-panel-close" onClick={onClose} aria-label="사이드 패널 닫기">×</button>
      <h3 className="side-panel-title">목록</h3>
      <ul className="side-panel-list">
        {items.length > 0 ? (
          items.map((item, index) => (
            <li
              key={item?.path ?? index}
              className={`side-panel-item ${selectedIndex === index ? 'is-active' : ''}`}
              onClick={() => {
                // 항목 선택 상태를 업데이트하고 경로가 있으면 이동한다.
                setSelectedIndex(index);
                if (item?.path) {
                  navigate(item.path);
                  onClose?.();
                }
              }}
            >
              {item?.label ?? item}
            </li>
          ))
        ) : (
          <li className="side-panel-item side-panel-empty">항목이 없습니다.</li>
        )}
      </ul>
    </div>
  );
};

export default SidePanel;