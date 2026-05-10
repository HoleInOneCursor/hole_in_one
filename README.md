# Hole in One

**Theme:** *Build Something Agents Want* — a minimal loop where **Cursor cloud agents** ship a PR, **Greptile** reviews it, and agents apply follow-up commits.

Stack: **Python**, **httpx**, and the [Cursor Cloud Agents HTTP API](https://cursor.com/docs/cloud-agent/api/endpoints.md) (no TypeScript SDK). Scope is intentionally small: one PR loop you can extend.

## What you demo

1. A **builder** cloud agent opens a PR on `GITHUB_REPO` (`POST /v1/agents` with `autoCreatePR`).
2. The builder is **stopped** (`CURSOR_STOP_AGENT`, default `archive`) once the PR is resolved.
3. Greptile reviews the PR; this CLI polls GitHub for checks/comments.
4. Each fix round starts a **new** cloud agent scoped to that PR (`repos[0].prUrl`), then stops it when the run finishes. Use `MAX_PARALLEL_FIXERS=2` only if you accept possible branch contention.
5. **Continuous mode** (`CONTINUOUS_BUILDS=1` or `orchestrate --continuous`): after Greptile + fix rounds, wait until the PR **merges**, then start another builder on the same default branch so the repo keeps gaining small improvements.

Set **`GITHUB_AUTO_MERGE=merge`** (or `squash` / `rebase`) so each new PR **queues GitHub auto-merge** as soon as the CLI knows the PR number (merging still waits on your checks and branch protection). Repo setting **Allow auto-merge** must be on; the PAT needs **Pull requests: write** for the GraphQL call.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e .

cp .env.example .env
# fill CURSOR_API_KEY, GITHUB_TOKEN, GITHUB_REPO

orchestrate
# or: python -m hole_in_one.orchestrate

# Keep shipping after each merge (set in .env or use flag):
# CONTINUOUS_BUILDS=1
# GITHUB_AUTO_MERGE=squash
orchestrate --continuous

python -m hole_in_one.orchestrate --help
```

Prerequisites: Greptile GitHub app on the repo; Cursor Cloud connected to that repo; optional `triggerOnUpdates` in `greptile.json` so re-review runs after pushes. **`GITHUB_TOKEN`** needs **Checks: Read** on fine-grained PATs (for `/commits/.../check-runs`); without it the CLI falls back to PR comments/reviews only.

Tune `GREPTILE_BOT_SUBSTRINGS` / `GREPTILE_CHECK_SUBSTRINGS` if your Greptile app uses different logins or check titles.

## Layout

| Module | Role |
| --- | --- |
| `hole_in_one/cursor_api.py` | Cursor REST: create agent, runs, wait |
| `hole_in_one/github_api.py` | Greptile heuristics via GitHub REST |
| `hole_in_one/feedback.py` | Chunk markdown for parallel mode |
| `hole_in_one/orchestrate.py` | CLI |
