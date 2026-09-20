import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The FastAPI app serves the data; Vite proxies so the browser sees one
// origin and we avoid CORS config on the Python side entirely.
const API = process.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Every FastAPI router prefix must appear here or its requests fall
    // through to Vite and the view shows "the API isn't responding".
    // Keep in step with app.include_router(...) in src/api/main.py.
    proxy: Object.fromEntries(
      ['/dashboard', '/exposure', '/risk', '/income', '/portfolios', '/prices', '/reports',
       '/scenarios', '/benchmarks', '/groups', '/trades', '/agents',
       '/summaries', '/production', '/trading-graph', '/health']
        .map((p) => [p, { target: API, changeOrigin: true }]),
    ),
  },
})
