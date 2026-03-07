# frontend

React HMI dashboard for the scada-sim water treatment plant simulation.

Built with Vite + TypeScript + Tailwind CSS + Recharts. Served by nginx in
production, proxied behind the OWASP WAF.

## Development

```bash
npm install
npm run dev   # starts on http://localhost:5173, proxies /api to localhost:8000
```

The backend needs to be running for the HMI to show live data. You can start
it in mock mode without Factory.io:

```bash
cd ../backend && MOCK_MODE=true uvicorn app.main:app --reload
```

## Production build

The Dockerfile handles this — multi-stage build compiles the React app then
copies the static files into an nginx:alpine image.
