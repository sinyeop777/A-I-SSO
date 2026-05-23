import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// React 앱을 root DOM에 마운트한다.
createRoot(document.getElementById('root')).render(
  // 개발 중 잠재적 부작용을 빠르게 발견하기 위한 StrictMode.
  <StrictMode>
    <App />
  </StrictMode>,
)
