# Hole In Golf

**Theme:** *Build Something Agents Want* — a minimal loop where **Cursor cloud agents** ship a PR, **Greptile** reviews it, and agents apply follow-up commits.

Stack: **Python**, **httpx**, and **Next.js**.

This repo now has a frontend-first **web dashboard**:
- Next.js app in `web/`
- Tabs: `Agent Grid`, `Activity`, `Graph`
- Graph is a browser-native animated node/edge visualization
- Current web dashboard is intentionally mock-data driven (no backend wiring yet)

A legacy Textual terminal dashboard still exists in the Python package, but the web UI is now the primary frontend.

## Quick start (web dashboard)

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:3000`.

## Quick start (backend loop)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# fill CURSOR_API_KEY, GITHUB_TOKEN, GITHUB_REPO

# run backend orchestration loop
orchestrate backend
# or: orchestrate-loop
```

Prerequisites: Greptile GitHub app on the repo; Cursor Cloud connected to that repo; optional `triggerOnUpdates` in `greptile.json` so re-review runs after pushes.

Tune `GREPTILE_BOT_SUBSTRINGS` / `GREPTILE_CHECK_SUBSTRINGS` if your Greptile app uses different logins or check titles.

## Layout

| Module | Role |
| --- | --- |
| `src/hole_in_one/orchestrate.py` | Backend orchestration loop |
| `web/src/lib/dashboard/mockProvider.ts` | Mock dashboard provider + simulation |
| `web/src/lib/dashboard/types.ts` | Dashboard view models/types |
| `web/src/components/dashboard/Dashboard.tsx` | Main web dashboard layout |
| `web/src/components/dashboard/ForceGraph.tsx` | Animated graph tab visualization |
| `web/src/components/dashboard/AgentTree.tsx` | In-progress/completed tree panels |
