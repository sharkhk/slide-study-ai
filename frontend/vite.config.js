import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve(__dirname, '../backend/dist'),
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    proxy: { '/api': 'http://localhost:5000' }
  }
})
