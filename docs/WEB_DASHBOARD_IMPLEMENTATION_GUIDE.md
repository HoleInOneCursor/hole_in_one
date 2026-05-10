# Hole In Golf Web Dashboard: Implementation + Backend Integration Guide

This guide explains:
- what each current web dashboard component does,
- how data flows today,
- how to replace mock data with real backend data when ready.

The goal is to keep the UI structure exactly as-is while making backend wiring clean and low-risk.

## 1. Current architecture (today)

## Frontend entry points
- `web/src/app/page.tsx`: renders the dashboard page.
- `web/src/components/dashboard/Dashboard.tsx`: top-level dashboard layout and tab logic.

## Data layer
- `web/src/lib/dashboard/types.ts`: shared frontend view models (`DashboardSnapshot`, `AgentNode`, etc.).
- `web/src/lib/dashboard/useDashboard.ts`: polling hook used by `Dashboard`.
- `web/src/lib/dashboard/mockProvider.ts`: in-memory simulated provider (current source of truth).

## Visualization components
- `web/src/components/dashboard/AgentTree.tsx`: recursive tree-like rows for In Progress + Completed tabs.
- `web/src/components/dashboard/ForceGraph.tsx`: SVG force simulation for graph tab.
- Hover context card is rendered in `Dashboard.tsx` and fed by hover events from both AgentTree and ForceGraph.

## Backend loop (existing Python side)
- `src/hole_in_one/orchestrate.py`: orchestration loop (builder agent + Greptile feedback + fix rounds).
- `src/hole_in_one/cursor_api.py`: Cursor cloud API client.
- `src/hole_in_one/github_api.py`: GitHub/Greptile polling helpers.

---

## 2. Integration strategy (recommended)

Use an **adapter pattern**:
1. Keep UI components unchanged.
2. Keep `DashboardSnapshot` as the frontend contract.
3. Add a real backend provider that returns that exact shape.
4. Switch `useDashboard` from mock provider to backend provider with a feature flag.

This avoids rewriting `Dashboard`, `AgentTree`, and `ForceGraph`.

---

## 3. Canonical payload contract

Match this structure from backend -> frontend (same semantics as `types.ts`):

```json
{
  "projectName": "HOLE IN GOLF",
  "uptime": "0:03:41",
  "totalParallelAgents": 12,
  "commitsPerHour": 11412,
  "metrics": {
    "iteration": 23,
    "commitsPerHour": 11412,
    "agentsDone": 19,
    "agentsTotal": 100,
    "failed": 2,
    "pending": 1,
    "mergeRate": 95.2,
    "tokensK": 412.8,
    "estCostUsd": 0.58,
    "implementationAgents": 28,
    "fixAgents": 9
  },
  "mergeQueue": {
    "successRate": 95.2,
    "merged": 41,
    "conflicts": 3,
    "failed": 1
  },
  "inProgress": [
    {
      "id": "agent-001",
      "role": "planner",
      "task": "physics agent coordinator",
      "kind": "builder",
      "status": "running",
      "progress": 42,
      "children": []
    }
  ],
  "completed": [],
  "activityLines": [
    "17:17:48  complete   agent-001 finished physics agent coordinator"
  ],
  "featureProgress": {
    "label": "FEATURES",
    "done": 19,
    "total": 100
  },
  "controlsHint": "live mode | tab=agent-grid/activity/graph"
}
```

## Important constraints
- `AgentNode.id` must be globally unique across active/completed nodes.
- `kind` must be one of: `builder | implementation | fix`.
- `status` must be one of: `running | complete | failed | pending`.
- `task` should always be populated (used by hover context cards).
- `children` defines graph/tree edges.

---

## 4. Backend API shape

Start with polling; add streaming later.

## Minimum endpoints
- `GET /api/dashboard/snapshot`
  - Returns a full `DashboardSnapshot`.
- `GET /api/dashboard/health`
  - Returns backend connection state (optional but useful).

## Optional streaming endpoint (later)
- `GET /api/dashboard/stream` (SSE) or `WS /api/dashboard/ws`
  - Pushes snapshot deltas/events to reduce polling lag.

---

## 5. Backend implementation plan (Python)

Create a thin web API layer near your orchestration loop.

## Step A: Introduce backend-side snapshot models
- Reuse/extend existing dataclasses in `src/hole_in_one/ui/models.py`.
- Add `task: str` to Python `AgentNode` to match frontend contract.
- Keep status/kind enums aligned with frontend literal strings.

## Step B: Build a live snapshot store
- Create an in-memory store (thread-safe) that always holds latest snapshot.
- Update store during orchestrator lifecycle events:
  - builder started/finished,
  - fix agents started/finished,
  - failures,
  - merge/conflict counters,
  - activity log lines.

## Step C: Expose HTTP snapshot endpoint
- Add a small FastAPI/Starlette app that serializes the snapshot store.
- Return camelCase JSON fields to match frontend `DashboardSnapshot`.

## Step D: Start API with orchestrator
- Option 1: same process (shared memory, easiest).
- Option 2: separate process + Redis/pubsub (better scalability).

For your current stage, Option 1 is faster.

---

## 6. Frontend integration plan (Next.js)

## Step A: Add a real provider
Create `web/src/lib/dashboard/backendProvider.ts`:
- `snapshot()` should call `fetch("/api/dashboard/snapshot")`.
- Parse/validate payload to `DashboardSnapshot`.
- Return cached last-good snapshot on transient failure.

## Step B: make `useDashboard` provider-driven
Replace hardcoded `MockDashboardProvider` with:
- `MockDashboardProvider` when `NEXT_PUBLIC_DASHBOARD_MODE=mock`
- `BackendDashboardProvider` when `NEXT_PUBLIC_DASHBOARD_MODE=live`

## Step C: add runtime fallback
If live fetch fails:
- show non-blocking warning in `controlsHint` or header,
- keep rendering last-good snapshot,
- optionally fall back to mock only in local/dev.

## Step D: keep component APIs unchanged
No changes needed in:
- `Dashboard.tsx`
- `AgentTree.tsx`
- `ForceGraph.tsx`

They already consume `DashboardSnapshot` cleanly.

---

## 7. Suggested file additions/changes

## Backend (Python)
- Add: `src/hole_in_one/dashboard_store.py`
- Add: `src/hole_in_one/dashboard_api.py`
- Update: `src/hole_in_one/ui/models.py` (`task` on `AgentNode`)
- Update: `src/hole_in_one/orchestrate.py` (emit lifecycle events into store)

## Frontend (Next.js)
- Add: `web/src/lib/dashboard/backendProvider.ts`
- Update: `web/src/lib/dashboard/useDashboard.ts` (provider selection + fallback)
- Optional: add a small status badge in `Dashboard.tsx` for `mock/live` mode

---

## 8. Event mapping from orchestrator -> UI

Map these orchestrator phases to dashboard updates:

1. Builder created
- Add builder node in `inProgress`.
- Activity: `boot` / `builder-start`.

2. Builder run finished
- Mark builder `complete` or `failed`.
- Move to `completed` if terminal.

3. Greptile feedback received
- Spawn fix nodes (kind=`fix`, status=`running` or `pending`).
- Increment `fixAgents` metric.

4. Fix agent completed
- Mark status `complete`/`failed`.
- Update merge/failed/conflict counters.

5. New child/sub-agent relationships
- Populate `children` under parent planner/builder nodes.
- Graph tab will auto-render edges from this tree.

---

## 9. Validation checklist before go-live

- No duplicate `AgentNode.id` values.
- All nodes include `task` and `progress`.
- `inProgress` + `completed` together reflect true state transitions.
- Metrics are internally consistent (`agentsDone <= agentsTotal`, etc.).
- Graph tab shows nodes immediately (non-empty `inProgress`).
- Hover cards show meaningful `task` text in both Tree and Graph.
- Frontend handles temporary backend outage without blanking the whole dashboard.

---

## 10. Practical rollout sequence

1. Add backend snapshot store + endpoint returning static fixture.
2. Point frontend live provider at fixture endpoint.
3. Replace fixture with real orchestrator events.
4. Keep polling at 1s initially.
5. Add SSE/WebSocket only if needed for latency/scale.

This sequence keeps risk low and lets you verify UI correctness early.

---

## 11. Quick local run modes

## Mock mode (current)
```bash
cd web
NEXT_PUBLIC_DASHBOARD_MODE=mock npm run dev
```

## Live mode (after backend endpoint exists)
```bash
cd web
NEXT_PUBLIC_DASHBOARD_MODE=live npm run dev
```

If Next.js and Python run on different origins locally, configure CORS and either:
- a Next.js rewrite proxy, or
- direct fetch with `NEXT_PUBLIC_DASHBOARD_API_BASE`.

---

## 12. Common pitfalls

- Missing `task` field: hover cards become low-value.
- Non-unique node IDs: React key warnings + graph node collapsing.
- Status enum mismatch (`FINISHED` vs `complete`): map backend state explicitly.
- Partial snapshots with missing required fields: validate before render.
- Tight coupling of UI to raw backend payloads: always adapt through `DashboardSnapshot`.
