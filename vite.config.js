import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  // JSX 변환/React Fast Refresh를 위한 공식 플러그인.
  plugins: [react()],
})
