# Hole In Golf

**Theme:** *Build Something Agents Want* — a minimal loop where **Cursor cloud agents** ship a PR, **Greptile** reviews it, and agents apply follow-up commits.

Stack: **Python**, **httpx**, **Next.js**, and the [Cursor Cloud Agents HTTP API](https://cursor.com/docs/cloud-agent/api/endpoints.md) (no TypeScript SDK). Scope is intentionally small: one PR loop you can extend; the web UI demos agent activity visually.

## Summary

**Hole In Golf** ships **`hole_in_one`**, a Python CLI that drives **Cursor cloud agents** on a GitHub repo: builders open PRs, **Greptile** reviews them, optional **fix rounds** spawn more agents on the same PR, and optional **[CLōD](https://clod.io/)** can summarize Greptile for fixes and run a **second validator** (PR body / comment). The **CLōD planner** (`--plan` or `CLOD_PLANNER=1`) turns one high-level goal into **ordered sequential builder tasks**. Merge behavior prefers GitHub **auto-merge** when it works; when GraphQL queueing fails (e.g. “clean status”), the CLI can **REST-merge** after Greptile + fixes + validator. Multi-task planner runs wait for each PR to merge before the next step by default (`CLOD_PLANNER_WAIT_MERGE_BETWEEN_TASKS`).

The **Next.js** app in `web/` is the primary dashboard: **Agent Grid**, **Activity**, **Graph**, plus **Builder Plan** (live steps from the orchestrator). Point it at `orchestrate`’s FastAPI bridge (`GET /api/dashboard/snapshot`) or use mock mode for UI-only demos. Styling is **Cursor-inspired** (dark zinc, violet accents, Inter + JetBrains Mono).

**Web dashboard** (`web/`):

- Tabs: **Agent Grid**, **Activity**, **Graph**; sidebar **Builder Plan** when the planner is active
- **Live**: `NEXT_PUBLIC_DASHBOARD_MODE=live` + FastAPI snapshot API from `orchestrate` (defaults `http://127.0.0.1:8787`)
- **Mock**: default mode for UI demos without the Python backend

A legacy **Textual** terminal UI remains in the Python package.

## Quick start (web dashboard)

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:3000`.

Live mode (real backend snapshots):

```bash
cd web
NEXT_PUBLIC_DASHBOARD_MODE=live \
NEXT_PUBLIC_DASHBOARD_API_BASE=http://localhost:8787 \
npm run dev
```

## What the backend CLI does

1. A **builder** cloud agent opens a PR on `GITHUB_REPO` (`POST /v1/agents` with `autoCreatePR`).
2. The builder is **stopped** (`CURSOR_STOP_AGENT`, default `archive`) once the PR is resolved.
3. Greptile reviews the PR; this CLI polls GitHub for checks/comments.
4. Each fix round starts a **new** cloud agent scoped to that PR (`repos[0].prUrl`), then stops it when the run finishes. Use `MAX_PARALLEL_FIXERS>1` only if you accept possible branch contention (cap is 5).
5. **Continuous mode** (`CONTINUOUS_BUILDS=1` or `orchestrate --continuous`): after Greptile + fix rounds, wait until the PR **merges**, then start another builder on the same default branch so the repo keeps gaining small improvements.
6. Exposes a FastAPI dashboard bridge at `GET /api/dashboard/snapshot` and `GET /api/dashboard/health` (default `http://127.0.0.1:8787`) so the Next.js dashboard can poll live orchestration state.

Set **`GITHUB_AUTO_MERGE=merge`** (or `squash` / `rebase`) so each new PR **queues GitHub auto-merge** as soon as the CLI knows the PR number (merging still waits on your checks and branch protection). On GitHub: **Settings → General → Pull Requests → Allow auto-merge**. The PAT needs **Pull requests: Read and write** (fine-grained). When queueing **succeeds**, **`GITHUB_MERGE_ON_GREPTILE_CLEAN`** is skipped for that PR so GitHub merges alone—no redundant REST merge. If GraphQL queueing **fails** (PAT issues, or GitHub’s *“Pull request is in clean status”* when there are no **required** checks to wait on), the CLI still **REST-merges** after Greptile + fix rounds + CLōD validator using the same **`GITHUB_AUTO_MERGE`** method—polls until **`mergeable_state=clean`**, so you are not stuck with only `GITHUB_MERGE_ON_GREPTILE_CLEAN` or a Greptile “skip fix loop” path. If you see “Resource not accessible by personal access token”, expand PAT permissions, authorize SSO, or use **`GITHUB_MERGE_IMMEDIATE`** / **`GITHUB_MERGE_ON_GREPTILE_CLEAN`** instead.

If you cannot use GraphQL auto-merge, set **`GITHUB_MERGE_IMMEDIATE=squash`** (or `merge` / `rebase`): after Greptile + fix rounds, the CLI **polls until `mergeable_state=clean`**, then **`PUT .../pulls/{id}/merge`**. If **`GITHUB_AUTO_MERGE`** and **`GITHUB_MERGE_IMMEDIATE`** are both set, REST wins (GraphQL is skipped).

For **continuous** runs where Greptile is often clean but GraphQL queueing **failed**, **`GITHUB_MERGE_ON_GREPTILE_CLEAN=squash`** REST-merges only on that clean-skip path. **`GITHUB_MERGE_IMMEDIATE`** merges after **every** cycle when set.

## Quick start (backend loop)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# fill CURSOR_API_KEY, GITHUB_TOKEN, GITHUB_REPO

orchestrate
# or: python -m hole_in_one.orchestrate
# or: orchestrate-loop  (same entrypoint as orchestrate)
# Textual dashboard only: hole-in-golf   # default mode is ui (not the Cursor/Greptile CLI flags)

# Builder task (overrides BUILDER_PROMPT in .env):
orchestrate --prompt "Add a README section on agent ergonomics."
orchestrate -i   # type the task when prompted

# One high-level goal → CLōD splits into sequential builders (backend → frontend, etc.):
# CLOD_API_KEY=…   CLOD_PLANNER=1   orchestrate --prompt "Build a minimal full-stack …"
# Or: orchestrate --prompt "…" --plan
# Not compatible with --continuous / CONTINUOUS_BUILDS when multiple tasks are planned.
# By default the CLI waits for each PR to merge before the next task (CLOD_PLANNER_WAIT_MERGE_BETWEEN_TASKS=1)
# so the next builder runs on an updated default branch.

# Keep shipping after each merge (set in .env or use flag):
# CONTINUOUS_BUILDS=1
# GITHUB_MERGE_IMMEDIATE=squash   # or GITHUB_AUTO_MERGE=squash if Allow auto-merge is on
orchestrate --continuous

python -m hole_in_one.orchestrate --help
```

Prerequisites: Greptile GitHub app on the repo; Cursor Cloud connected to that repo; optional `triggerOnUpdates` in `greptile.json` so re-review runs after pushes. **`GITHUB_TOKEN`** needs **Checks: Read** on fine-grained PATs (for `/commits/.../check-runs`); without it the CLI falls back to PR comments/reviews only.

Optional **[CLōD](https://clod.io/)** ([API docs](https://clod.io/docs)): set **`CLOD_API_KEY`** for **`POST .../chat/completions`**. With **`CLOD_COMPRESS_FOR_FIX=1`** (default), Greptile feedback is summarized before each Cursor **fix** agent; clean/skip heuristics still use **raw** Greptile text. With **`CLOD_VALIDATOR=1`**, a **second pass** sends Greptile summary plus PR **unified diffs** to CLōD and expects **`VERDICT: PASS`** or **`FAIL`**; **`CLOD_VALIDATOR_APPEND_PR_BODY=1`** updates the PR description inside a marked HTML block (plain-text title **CLōD second validator**, then **Automated (UTC)** / **Verdict:** lines and model output—replaced on re-run), and **`CLOD_VALIDATOR_COMMENT_PR=1`** posts the same blurb as a timeline comment (**`GITHUB_TOKEN`** needs permission to edit the PR / create issue comments). **`CLOD_VALIDATOR_STRICT=1`** aborts before REST merge on **`FAIL`** (**`UNKNOWN`** never blocks). GraphQL auto-merge may already be queued earlier—see `.env.example`.

If **`GITHUB_DEFAULT_BRANCH`** is unset, the CLI loads the repo’s **GitHub default branch** via the API (not hard-coded `main`). **`CURSOR_STARTING_REF_REFS_FIRST`** / **`CURSOR_TRY_COMMIT_SHA_FOR_STARTING_REF`** retry Cursor `startingRef` when branch validation flakes.

Tune `GREPTILE_BOT_SUBSTRINGS` / `GREPTILE_CHECK_SUBSTRINGS` if your Greptile app uses different logins or check titles.

## Layout

| Module | Role |
| --- | --- |
| `src/hole_in_one/orchestrate.py` | Backend orchestration loop |
| `src/hole_in_one/clod_api.py` | Optional CLōD chat summarization for fix prompts |
| `web/src/lib/dashboard/mockProvider.ts` | Mock dashboard provider + simulation |
| `web/src/lib/dashboard/types.ts` | Dashboard view models/types |
| `web/src/components/dashboard/Dashboard.tsx` | Main web dashboard layout |
| `web/src/components/dashboard/ForceGraph.tsx` | Animated graph tab visualization |
| `web/src/components/dashboard/AgentTree.tsx` | In-progress/completed tree panels |
