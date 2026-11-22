import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The Worker serves whatever lands in dist/, so the build output path here and
// wrangler.jsonc's assets.directory are one setting in two files. Change both.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // The old site was a single 147KB file with every image inlined as base64.
    // Never again: anything over 2KB becomes a real file the browser can cache.
    assetsInlineLimit: 2048,
  },
  server: {
    // 5174, not Vite's default 5173. The Personal Website project runs on
    // 5173, and a Playwright run here once silently attached to it and
    // compared Comprsly against someone else's homepage. strictPort makes a
    // clash fail loudly instead of sliding to the next free port.
    port: 5174,
    strictPort: true,
    // Hand the API, redirect and stats routes to `wrangler dev` so local dev
    // exercises the real Worker instead of a mock.
    proxy: {
      '/api': 'http://localhost:8787',
      '/go': 'http://localhost:8787',
      '/stats': 'http://localhost:8787',
    },
  },
})
