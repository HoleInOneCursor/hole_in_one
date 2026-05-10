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

Next.js **does not** load the repo-root `.env`. Put `NEXT_PUBLIC_*` in **`web/.env.local`** (see `.env.example` in repo root for values), or export them in the shell:

```bash
NEXT_PUBLIC_DASHBOARD_MODE=live \
NEXT_PUBLIC_DASHBOARD_API_BASE=http://localhost:8787 \
npm run dev
```

Restart `npm run dev` after changing env files.

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
- **Mock** when `NEXT_PUBLIC_DASHBOARD_MODE` is unset or not `live`; **live** polls the FastAPI URLs above (run `orchestrate` so `:8787` is up).

## Build and lint

```bash
cd web
npm run lint
npm run build
```
