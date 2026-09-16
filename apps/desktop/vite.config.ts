import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// Tauri expects a fixed, predictable dev server port (see src-tauri/tauri.conf.json's devUrl).
// https://v2.tauri.app/start/frontend/vite/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      // don't watch the Rust/Python sidecar sources, they have their own build loops
      ignored: ['**/src-tauri/**', '**/backend/**'],
    },
  },
})
