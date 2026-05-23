// ESLint 기본 규칙과 React 관련 규칙을 프로젝트 전역에 적용한다.
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // 빌드 산출물/가상환경은 린트 대상에서 제외한다.
  globalIgnores(['dist', '.venv', '.venv/**']),
  {
    // JS/JSX 파일에 대해서만 규칙을 적용한다.
    files: ['**/*.{js,jsx}'],
    extends: [
      // ESLint 기본 추천 규칙.
      js.configs.recommended,
      // React Hooks 규칙.
      reactHooks.configs.flat.recommended,
      // Vite 환경의 React Fast Refresh 규칙.
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      // 파싱 대상 스펙과 전역 객체(browser)를 정의한다.
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      // 대문자/언더스코어 패턴은 의도적 미사용 값으로 허용한다.
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }],
    },
  },
])
