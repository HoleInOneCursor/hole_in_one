# Hole In Golf

**Theme:** *Build Something Agents Want* — a minimal loop where **Cursor cloud agents** ship a PR, **Greptile** reviews it, and agents apply follow-up commits.

Stack: **Python**, **httpx**, **Next.js**, and the [Cursor Cloud Agents HTTP API](https://cursor.com/docs/cloud-agent/api/endpoints.md) (no TypeScript SDK). Scope is intentionally small: one PR loop you can extend; the web UI demos agent activity visually.

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

## What the backend CLI does

1. A **builder** cloud agent opens a PR on `GITHUB_REPO` (`POST /v1/agents` with `autoCreatePR`).
2. The builder is **stopped** (`CURSOR_STOP_AGENT`, default `archive`) once the PR is resolved.
3. Greptile reviews the PR; this CLI polls GitHub for checks/comments.
4. Each fix round starts a **new** cloud agent scoped to that PR (`repos[0].prUrl`), then stops it when the run finishes. Use `MAX_PARALLEL_FIXERS=2` only if you accept possible branch contention.
5. **Continuous mode** (`CONTINUOUS_BUILDS=1` or `orchestrate --continuous`): after Greptile + fix rounds, wait until the PR **merges**, then start another builder on the same default branch so the repo keeps gaining small improvements.

Set **`GITHUB_AUTO_MERGE=merge`** (or `squash` / `rebase`) so each new PR **queues GitHub auto-merge** as soon as the CLI knows the PR number (merging still waits on your checks and branch protection). On GitHub: **Settings → General → Pull Requests → Allow auto-merge**. The PAT needs **Pull requests: Read and write** (fine-grained). When queueing **succeeds**, **`GITHUB_MERGE_ON_GREPTILE_CLEAN`** is skipped for that PR so GitHub merges alone—no redundant REST merge. If GraphQL queueing **fails** (common with insufficient PAT scopes) but Greptile looks **clean**, the CLI **REST-merges** using the same **`GITHUB_AUTO_MERGE`** method (`squash` / `merge` / `rebase`) so **`CONTINUOUS_BUILDS`** is not stuck waiting. If you see “Resource not accessible by personal access token”, expand PAT permissions, authorize SSO, or use **`GITHUB_MERGE_IMMEDIATE`** / **`GITHUB_MERGE_ON_GREPTILE_CLEAN`** instead.

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

# Builder task (overrides BUILDER_PROMPT in .env):
orchestrate --prompt "Add a README section on agent ergonomics."
orchestrate -i   # type the task when prompted

# Keep shipping after each merge (set in .env or use flag):
# CONTINUOUS_BUILDS=1
# GITHUB_MERGE_IMMEDIATE=squash   # or GITHUB_AUTO_MERGE=squash if Allow auto-merge is on
orchestrate --continuous

python -m hole_in_one.orchestrate --help
```

Prerequisites: Greptile GitHub app on the repo; Cursor Cloud connected to that repo; optional `triggerOnUpdates` in `greptile.json` so re-review runs after pushes. **`GITHUB_TOKEN`** needs **Checks: Read** on fine-grained PATs (for `/commits/.../check-runs`); without it the CLI falls back to PR comments/reviews only.

If **`GITHUB_DEFAULT_BRANCH`** is unset, the CLI loads the repo’s **GitHub default branch** via the API (not hard-coded `main`). **`CURSOR_STARTING_REF_REFS_FIRST`** / **`CURSOR_TRY_COMMIT_SHA_FOR_STARTING_REF`** retry Cursor `startingRef` when branch validation flakes.

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
