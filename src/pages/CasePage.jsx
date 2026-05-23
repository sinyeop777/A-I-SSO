import React, { useState, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import styled from 'styled-components';

const SplitContainer = styled.div`
  display: flex;
  width: 100%;
  max-width: 100%;
  height: calc(100vh - 72px);
  background: #0d1526;
  overflow: hidden;
`;

const ListSide = styled.div`
  flex: 0 0 40%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(201, 168, 76, 0.3);
  background: rgba(17, 27, 48, 0.5);
  overflow: hidden;
`;

const ListHeader = styled.div`
  padding: 14px 16px;
  border-bottom: 1px solid rgba(201, 168, 76, 0.2);
  background: #111b30;
`;

const ListHeaderTitle = styled.h2`
  margin: 0;
  color: #f0d080;
  font-size: 18px;
`;

const ListScroll = styled.div`
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
`;

const CaseListItem = styled.button`
  width: 100%;
  text-align: left;
  border: 1px solid rgba(201, 168, 76, 0.28);
  background: rgba(20, 31, 53, 0.8);
  color: #f0d080;
  border-radius: 9px;
  padding: 10px 11px;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease;

  &:hover {
    background: rgba(201, 168, 76, 0.14);
  }

  &.active {
    background: rgba(201, 168, 76, 0.22);
    border-color: rgba(201, 168, 76, 0.75);
  }
`;

const CaseItemNumber = styled.div`
  font-weight: 700;
  font-size: 14px;
  color: #ffe9a0;
  margin-bottom: 4px;
  line-height: 1.35;
`;

const CaseItemVerdict = styled.div`
  font-size: 12px;
  color: #c9a84c;
`;

const DetailSide = styled.div`
  flex: 0 0 60%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #0d1526;
  padding: 16px;
  overflow: hidden;
`;

const DetailHeader = styled.div`
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(201, 168, 76, 0.2);
  margin-bottom: 16px;
`;

const DetailTitle = styled.h2`
  margin: 0;
  color: #f0d080;
  font-size: 20px;
  margin-bottom: 8px;
`;

const DetailMeta = styled.div`
  color: #c9a84c;
  font-size: 13px;
`;

const DetailContent = styled.div`
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  color: #e5e9f2;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
`;

const EmptyContent = styled.div`
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: rgba(201, 168, 76, 0.4);
  font-size: 15px;
`;

const BackButton = styled.button`
  position: fixed;
  bottom: 30px;
  left: 30px;
  width: 62px;
  height: 62px;
  border-radius: 14px;
  background: linear-gradient(135deg, #c9a84c, #f0d080);
  color: #0d1526;
  border: 1px solid rgba(255, 255, 255, 0.18);
  font-size: 20px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.32);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s ease, box-shadow 0.2s ease, filter 0.2s ease;

  &:hover {
    transform: translateY(-2px);
    filter: brightness(1.04);
    box-shadow: 0 12px 24px rgba(0, 0, 0, 0.36);
  }
`;

const CctvButton = styled.button`
  position: fixed;
  bottom: 30px;
  right: 30px;
  width: 72px;
  height: 62px;
  border-radius: 14px;
  background: linear-gradient(135deg, #1a73e8, #4c8dff);
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.18);
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.32);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: 0.02em;
  transition: transform 0.2s ease, box-shadow 0.2s ease, filter 0.2s ease;

  &:hover {
    transform: translateY(-2px);
    filter: brightness(1.05);
    box-shadow: 0 12px 24px rgba(0, 0, 0, 0.36);
  }
`;

const getCaseOriginalText = (caseItem) => {
  if (!caseItem) {
    return '';
  }

  return caseItem.originalText || caseItem.rawText || caseItem.description || caseItem.output_text || '';
};

const CasePage = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { cases = [], recordId = null, recordOwnerGoogleSub = null, locationCase = '', caseType = 'civil' } = location.state || {};

  const [selectedIndex, setSelectedIndex] = useState(0);

  const selectedCase = useMemo(() => {
    return cases && cases.length > 0 ? cases[selectedIndex] : null;
  }, [cases, selectedIndex]);

  const selectedCaseMeta = useMemo(() => {
    if (!selectedCase) {
      return '';
    }

    return [
      selectedCase.caseNumber && `사건번호: ${selectedCase.caseNumber}`,
      selectedCase.precedId && `일련번호: ${selectedCase.precedId}`,
      selectedCase.verdict && `판결: ${selectedCase.verdict}`,
      selectedCase.similarity && `유사도: ${selectedCase.similarity}%`,
      selectedCase.source && `출처: ${selectedCase.source}`,
    ].filter(Boolean).join(' · ');
  }, [selectedCase]);

  if (!cases || cases.length === 0) {
    return (
      <SplitContainer>
        <EmptyContent>유사 판례가 없습니다.</EmptyContent>
        <BackButton onClick={() => navigate(-1)}>←</BackButton>
      </SplitContainer>
    );
  }

  return (
    <SplitContainer>
      <ListSide>
        <ListHeader>
          <ListHeaderTitle>유사 판례 목록</ListHeaderTitle>
        </ListHeader>
        <ListScroll>
          {cases.map((caseItem, index) => (
            <CaseListItem
              key={caseItem.precedId || caseItem.caseNumber || index}
              className={selectedIndex === index ? 'active' : ''}
              onClick={() => setSelectedIndex(index)}
            >
              <CaseItemNumber>
                {caseItem.caseNumber || caseItem.precedId || `판례 ${index + 1}`}
              </CaseItemNumber>
              <CaseItemVerdict>
                {caseItem.verdict || caseItem.case_name}
              </CaseItemVerdict>
            </CaseListItem>
          ))}
        </ListScroll>
      </ListSide>

      <DetailSide>
        {selectedCase ? (
          <>
            <DetailHeader>
              <DetailTitle>{selectedCase.case_name || selectedCase.caseNumber || '판례 정보'}</DetailTitle>
              <DetailMeta>{selectedCaseMeta || '원문 메타데이터 없음'}</DetailMeta>
            </DetailHeader>
            <DetailContent>
              {getCaseOriginalText(selectedCase) || '원문 정보 없음'}
            </DetailContent>
          </>
        ) : (
          <EmptyContent>판례를 선택하면 상세 내용이 표시됩니다.</EmptyContent>
        )}
      </DetailSide>

      <BackButton onClick={() => navigate(-1)}>←</BackButton>
      <CctvButton
        onClick={() => navigate('/cctv', {
          state: {
            recordId,
            recordOwnerGoogleSub,
            initialAddress: locationCase ?? '',
            caseType,
          },
        })}
      >
        CCTV
      </CctvButton>
    </SplitContainer>
  );
};

export default CasePage;