# Hole in One

**Theme:** *Build Something Agents Want* — a minimal loop where **Cursor cloud agents** ship a PR, **Greptile** reviews it, and agents apply follow-up commits.

Stack: **Python**, **httpx**, and the [Cursor Cloud Agents HTTP API](https://cursor.com/docs/cloud-agent/api/endpoints.md) (no TypeScript SDK). Scope is intentionally small: one PR loop you can extend.

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

orchestrate
# or: python -m hole_in_one.orchestrate
```

Prerequisites: Greptile GitHub app on the repo; Cursor Cloud connected to that repo; optional `triggerOnUpdates` in `greptile.json` so re-review runs after pushes.

Tune `GREPTILE_BOT_SUBSTRINGS` / `GREPTILE_CHECK_SUBSTRINGS` if your Greptile app uses different logins or check titles.

## Layout

| Module | Role |
| --- | --- |
| `hole_in_one/cursor_api.py` | Cursor REST: create agent, runs, wait |
| `hole_in_one/github_api.py` | Greptile heuristics via GitHub REST |
| `hole_in_one/feedback.py` | Chunk markdown for parallel mode |
| `hole_in_one/orchestrate.py` | CLI |
