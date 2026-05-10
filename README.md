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
5. **Continuous mode** (`CONTINUOUS_BUILDS=1` or `orchestrate --continuous`): after Greptile + fix rounds, wait until the PR **merges**, then start another builder on the same default branch so the repo keeps gaining small improvements.

Set **`GITHUB_AUTO_MERGE=merge`** (or `squash` / `rebase`) so each new PR **queues GitHub auto-merge** as soon as the CLI knows the PR number (merging still waits on your checks and branch protection). Repo setting **Allow auto-merge** must be on; the PAT needs **Pull requests: write** for the GraphQL call.

## Quick start (backend loop)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# fill CURSOR_API_KEY, GITHUB_TOKEN, GITHUB_REPO

orchestrate
# or: python -m hole_in_one.orchestrate
```

Prerequisites: Greptile GitHub app on the repo; Cursor Cloud connected to that repo; optional `triggerOnUpdates` in `greptile.json` so re-review runs after pushes. **`GITHUB_TOKEN`** needs **Checks: Read** on fine-grained PATs (for `/commits/.../check-runs`); without it the CLI falls back to PR comments/reviews only.

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
