# Hole In Golf

**Theme:** *Build Something Agents Want* — a minimal loop where **Cursor cloud agents** ship a PR, **Greptile** reviews it, and agents apply follow-up commits.

Stack: **Python**, **httpx**, **Textual**, and the [Cursor Cloud Agents HTTP API](https://cursor.com/docs/cloud-agent/api/endpoints.md) (no TypeScript SDK).

This repo now has a frontend-first terminal dashboard entrypoint:
- Default CLI mode opens the TUI visualizer (`orchestrate` or `hole-in-golf`).
- Backend orchestration loop is still available via explicit `backend` mode.
- TUI tabs: `Agent Grid`, `Activity`, and live `Graph`.
- Current dashboard is intentionally mock-data driven (no backend wiring yet) so integration is straightforward when APIs stabilize.

## What you demo

1. A **builder** cloud agent opens a PR on `GITHUB_REPO` (`POST /v1/agents` with `autoCreatePR`).
2. The builder is **stopped** (`CURSOR_STOP_AGENT`, default `archive`) once the PR is resolved.
3. Greptile reviews the PR; this CLI polls GitHub for checks/comments.
4. Each fix round starts a **new** cloud agent scoped to that PR (`repos[0].prUrl`), then stops it when the run finishes. Use `MAX_PARALLEL_FIXERS=2` only if you accept possible branch contention.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e .

cp .env.example .env
# fill CURSOR_API_KEY, GITHUB_TOKEN, GITHUB_REPO

# open terminal dashboard (default mode)
orchestrate
# or: hole-in-golf

# run legacy backend loop
orchestrate backend
# or: orchestrate-loop
```

Prerequisites: Greptile GitHub app on the repo; Cursor Cloud connected to that repo; optional `triggerOnUpdates` in `greptile.json` so re-review runs after pushes.

Tune `GREPTILE_BOT_SUBSTRINGS` / `GREPTILE_CHECK_SUBSTRINGS` if your Greptile app uses different logins or check titles.

## Layout

| Module | Role |
| --- | --- |
| `hole_in_one/cursor_api.py` | Cursor REST: create agent, runs, wait |
| `hole_in_one/github_api.py` | Greptile heuristics via GitHub REST |
| `hole_in_one/feedback.py` | Chunk markdown for parallel mode |
| `hole_in_one/orchestrate.py` | Backend orchestration loop |
| `hole_in_one/cli.py` | CLI entrypoint (`ui` default, `backend` optional) |
| `hole_in_one/ui/models.py` | Dashboard view models |
| `hole_in_one/ui/provider.py` | Provider interface + mock provider |
| `hole_in_one/ui/app.py` | Textual terminal dashboard |
