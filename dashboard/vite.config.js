import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, '')
  return {
    root: import.meta.dirname,
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      host: true,
      proxy: {
        '/api': {
          target: 'https://cslogixdispatch.com',
          changeOrigin: true,
          secure: true,
          headers: {
            'X-Dev-Key': env.CSL_DEV_KEY || '',
          },
        },
      },
    },
  }
})
