from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hole_in_one.dashboard_store import DashboardStore
from hole_in_one.ui.models import AgentNode, DashboardSnapshot


@dataclass(slots=True)
class DashboardApiRuntime:
    host: str
    port: int
    thread: threading.Thread
    server: Any

    def stop(self) -> None:
        self.server.should_exit = True


def _serialize_agent(node: AgentNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "role": node.role,
        "task": node.task,
        "kind": node.kind.value,
        "status": node.status.value,
        "progress": node.progress,
        "children": [_serialize_agent(child) for child in node.children],
    }


def _serialize_snapshot(snapshot: DashboardSnapshot) -> dict[str, Any]:
    return {
        "projectName": snapshot.project_name,
        "uptime": snapshot.uptime,
        "totalParallelAgents": snapshot.total_parallel_agents,
        "commitsPerHour": snapshot.commits_per_hour,
        "metrics": {
            "iteration": snapshot.metrics.iteration,
            "commitsPerHour": snapshot.metrics.commits_per_hour,
            "agentsDone": snapshot.metrics.agents_done,
            "agentsTotal": snapshot.metrics.agents_total,
            "failed": snapshot.metrics.failed,
            "pending": snapshot.metrics.pending,
            "mergeRate": snapshot.metrics.merge_rate,
            "tokensK": snapshot.metrics.tokens_k,
            "estCostUsd": snapshot.metrics.est_cost_usd,
            "implementationAgents": snapshot.metrics.implementation_agents,
            "fixAgents": snapshot.metrics.fix_agents,
        },
        "mergeQueue": {
            "successRate": snapshot.merge_queue.success_rate,
            "merged": snapshot.merge_queue.merged,
            "conflicts": snapshot.merge_queue.conflicts,
            "failed": snapshot.merge_queue.failed,
        },
        "inProgress": [_serialize_agent(node) for node in snapshot.in_progress],
        "completed": [_serialize_agent(node) for node in snapshot.completed],
        "activityLines": snapshot.activity_lines,
        "featureProgress": {
            "label": snapshot.feature_progress.label,
            "done": snapshot.feature_progress.done,
            "total": snapshot.feature_progress.total,
        },
        "controlsHint": snapshot.controls_hint,
        "plannerTasks": list(snapshot.planner_tasks),
        "plannerTaskIndex": snapshot.planner_task_index,
    }


def create_dashboard_api(
    store: DashboardStore,
    *,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    app = FastAPI(title="Hole In Golf Dashboard API", version="0.1.0")

    allow_origins = cors_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/dashboard/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "uptime": store.snapshot().uptime,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    @app.get("/api/dashboard/snapshot")
    def snapshot() -> dict[str, Any]:
        return _serialize_snapshot(store.snapshot())

    return app


def start_dashboard_api_server(
    store: DashboardStore,
    *,
    host: str,
    port: int,
    cors_origins: list[str] | None = None,
    log_level: str = "warning",
) -> DashboardApiRuntime:
    import uvicorn

    app = create_dashboard_api(store, cors_origins=cors_origins)
    config = uvicorn.Config(app=app, host=host, port=port, log_level=log_level)
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True, name="dashboard-api")
    thread.start()

    deadline = time.monotonic() + 8.0
    while not getattr(server, "started", False) and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)

    return DashboardApiRuntime(host=host, port=port, thread=thread, server=server)
