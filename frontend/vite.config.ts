import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// VITE_BASE lets the GitHub Pages build live under /mapay/; everything else (dev, Vercel, iOS) uses /.
export default defineConfig({
  base: process.env.VITE_BASE || '/',
  plugins: [react()],
})
