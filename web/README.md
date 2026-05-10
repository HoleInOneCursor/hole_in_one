# Hole In Golf Web Dashboard

Next.js frontend visualizer for Hole In Golf.

## Run locally

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:3000`.

## Live backend mode (FastAPI)

```bash
NEXT_PUBLIC_DASHBOARD_MODE=live \
NEXT_PUBLIC_DASHBOARD_API_BASE=http://localhost:8787 \
npm run dev
```

Expected backend endpoints:
- `GET /api/dashboard/snapshot`
- `GET /api/dashboard/health`

## What is implemented

- Same dashboard format as the terminal version:
  - top status strip
  - metrics + merge queue sidebar
  - tabs: `Agent Grid`, `Activity`, `Graph`
  - features progress + controls footer
- Graph is rendered as animated SVG force layout (web-native, not terminal glyphs).
- Data is mock/simulated only right now (backend is intentionally not connected yet).

## Build and lint

```bash
cd web
npm run lint
npm run build
```
