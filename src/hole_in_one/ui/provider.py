from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import replace
from datetime import timedelta
from typing import Protocol

from hole_in_one.ui.models import (
    AgentKind,
    AgentNode,
    AgentStatus,
    DashboardSnapshot,
    FeatureProgressSnapshot,
    MergeQueueSnapshot,
    MetricsSnapshot,
)


class DashboardDataProvider(Protocol):
    def snapshot(self) -> DashboardSnapshot:
        """Return the latest dashboard view model."""


class MockDashboardProvider:
    """Frontend-only simulation provider.

    Replace this with a real provider that polls backend APIs when ready.
    """

    def __init__(self) -> None:
        self._rng = random.Random(7)
        self._started_at = time.monotonic()
        self._iteration = 0
        self._activity: deque[str] = deque(maxlen=120)
        self._completed = self._seed_completed_agents()
        self._in_progress = self._seed_in_progress_agents()
        self._merge_conflicts = 2
        self._merge_failed = 0
        self._merged = 36
        self._tokens_k = 367.4
        self._cost_usd = 0.37
        self._agents_total = 100
        self._emit("boot", "dashboard initialized")
        self._emit("sync", "mock provider online; backend disconnected")

    def snapshot(self) -> DashboardSnapshot:
        self._tick()

        done_count, failed_count, pending_count = self._summarize_counts()
        implementation_agents = self._count_kind(AgentKind.IMPLEMENTATION)
        fix_agents = self._count_kind(AgentKind.FIX)
        merge_rate = round((self._merged / max(1, self._merged + self._merge_conflicts + self._merge_failed)) * 100, 1)

        metrics = MetricsSnapshot(
            iteration=self._iteration,
            commits_per_hour=11349 + self._rng.randint(-120, 90),
            agents_done=done_count,
            agents_total=self._agents_total,
            failed=failed_count,
            pending=pending_count,
            merge_rate=merge_rate,
            tokens_k=round(self._tokens_k, 1),
            est_cost_usd=round(self._cost_usd, 2),
            implementation_agents=implementation_agents,
            fix_agents=fix_agents,
        )
        merge_queue = MergeQueueSnapshot(
            success_rate=merge_rate,
            merged=self._merged,
            conflicts=self._merge_conflicts,
            failed=self._merge_failed,
        )
        feature = FeatureProgressSnapshot(label="FEATURES", done=done_count, total=self._agents_total)
        uptime = str(timedelta(seconds=int(time.monotonic() - self._started_at)))

        return DashboardSnapshot(
            project_name="HOLE IN GOLF",
            uptime=uptime,
            total_parallel_agents=len(self._in_progress),
            commits_per_hour=metrics.commits_per_hour,
            metrics=metrics,
            merge_queue=merge_queue,
            in_progress=[self._clone_node(node) for node in self._in_progress],
            completed=[self._clone_node(node) for node in self._completed],
            activity_lines=list(self._activity),
            feature_progress=feature,
            controls_hint="mock mode | tab=agent-grid/activity/graph | q=quit",
            planner_tasks=(),
            planner_task_index=-1,
        )

    def _tick(self) -> None:
        self._iteration += 1
        self._tokens_k += self._rng.uniform(0.5, 2.2)
        self._cost_usd += self._rng.uniform(0.002, 0.011)

        running_nodes = [node for node in self._iter_nodes(self._in_progress) if node.status == AgentStatus.RUNNING]
        if running_nodes:
            node = self._rng.choice(running_nodes)
            node.progress = min(100, node.progress + self._rng.randint(7, 24))
            if node.progress >= 100 and self._rng.random() > 0.08:
                node.status = AgentStatus.COMPLETE
                self._emit("complete", f"{node.id} finished by {node.role}")
            elif node.progress >= 95:
                node.status = AgentStatus.FAILED
                self._emit("failed", f"{node.id} failed lint checks")

        self._roll_completed_roots()
        if self._iteration % 5 == 0:
            self._emit("merge", f"merged worker/{self._rng.randint(1, 44):03d}")
            self._merged += 1

    def _roll_completed_roots(self) -> None:
        moved: list[AgentNode] = []
        still_active: list[AgentNode] = []
        for root in self._in_progress:
            if root.status in {AgentStatus.COMPLETE, AgentStatus.FAILED}:
                moved.append(root)
            else:
                still_active.append(root)
        self._in_progress = still_active
        if moved:
            self._completed.extend(moved)
        while len(self._in_progress) < 12:
            self._in_progress.append(self._new_root_agent())

    def _seed_in_progress_agents(self) -> list[AgentNode]:
        return [
            AgentNode(
                id="agent-001",
                role="planner",
                task="physics system coordinator",
                kind=AgentKind.BUILDER,
                status=AgentStatus.RUNNING,
                progress=38,
                children=[
                    AgentNode(
                        id="agent-001-sub-1",
                        role="subplanner",
                        task="worker decomposition",
                        kind=AgentKind.IMPLEMENTATION,
                        status=AgentStatus.RUNNING,
                        progress=22,
                        children=[
                            AgentNode(
                                id="agent-001-sub-1-sub-1",
                                role="worker",
                                task="entity collision resolution",
                                kind=AgentKind.IMPLEMENTATION,
                                status=AgentStatus.RUNNING,
                                progress=13,
                            ),
                        ],
                    ),
                ],
            ),
            AgentNode(
                id="agent-004",
                role="planner",
                task="render pipeline orchestrator",
                kind=AgentKind.IMPLEMENTATION,
                status=AgentStatus.RUNNING,
                progress=61,
            ),
            AgentNode(
                id="agent-007",
                role="planner",
                task="repair PR conflict from Greptile",
                kind=AgentKind.FIX,
                status=AgentStatus.RUNNING,
                progress=48,
            ),
            AgentNode(
                id="agent-012",
                role="planner",
                task="world streaming planner",
                kind=AgentKind.IMPLEMENTATION,
                status=AgentStatus.RUNNING,
                progress=74,
            ),
            AgentNode(
                id="agent-019",
                role="planner",
                task="resolve flaky test failures",
                kind=AgentKind.FIX,
                status=AgentStatus.PENDING,
                progress=0,
            ),
            AgentNode(
                id="agent-024",
                role="planner",
                task="terrain noise generation",
                kind=AgentKind.IMPLEMENTATION,
                status=AgentStatus.RUNNING,
                progress=52,
                children=[
                    AgentNode(
                        id="agent-024-sub-1",
                        role="subplanner",
                        task="camera follow smoothing",
                        kind=AgentKind.IMPLEMENTATION,
                        status=AgentStatus.RUNNING,
                        progress=36,
                    )
                ],
            ),
            AgentNode(
                id="agent-029",
                role="planner",
                task="patch merge regression",
                kind=AgentKind.FIX,
                status=AgentStatus.RUNNING,
                progress=29,
            ),
            AgentNode(
                id="agent-030",
                role="planner",
                task="input buffer handling",
                kind=AgentKind.IMPLEMENTATION,
                status=AgentStatus.RUNNING,
                progress=44,
            ),
            AgentNode(
                id="agent-034",
                role="planner",
                task="repair lint/type guard breaks",
                kind=AgentKind.FIX,
                status=AgentStatus.FAILED,
                progress=100,
            ),
            AgentNode(
                id="agent-036",
                role="planner",
                task="animation state transitions",
                kind=AgentKind.IMPLEMENTATION,
                status=AgentStatus.RUNNING,
                progress=82,
            ),
            AgentNode(
                id="agent-038",
                role="planner",
                task="occlusion culling pass",
                kind=AgentKind.IMPLEMENTATION,
                status=AgentStatus.RUNNING,
                progress=46,
            ),
            AgentNode(
                id="agent-049",
                role="planner",
                task="fix serialization edge case",
                kind=AgentKind.FIX,
                status=AgentStatus.RUNNING,
                progress=60,
            ),
        ]

    def _seed_completed_agents(self) -> list[AgentNode]:
        completed: list[AgentNode] = []
        for idx in (5, 8, 10, 11, 14, 17, 18, 22, 26, 27):
            completed.append(
                AgentNode(
                    id=f"agent-{idx:03d}",
                    role="planner",
                    task="implementation complete",
                    kind=AgentKind.IMPLEMENTATION,
                    status=AgentStatus.COMPLETE,
                    progress=100,
                )
            )
        for idx in (30, 34):
            completed.append(
                AgentNode(
                    id=f"agent-{idx:03d}",
                    role="planner",
                    task="fix round complete",
                    kind=AgentKind.FIX,
                    status=AgentStatus.FAILED if idx == 34 else AgentStatus.COMPLETE,
                    progress=100,
                )
            )
        return completed

    def _new_root_agent(self) -> AgentNode:
        base = self._rng.randint(50, 99)
        kind = self._rng.choice([AgentKind.IMPLEMENTATION, AgentKind.FIX])
        return AgentNode(
            id=f"agent-{base:03d}",
            role="planner",
            task="repair PR conflict from Greptile"
            if kind == AgentKind.FIX
            else "iterative implementation task",
            kind=kind,
            status=AgentStatus.RUNNING,
            progress=self._rng.randint(3, 42),
        )

    def _summarize_counts(self) -> tuple[int, int, int]:
        all_nodes = [*self._iter_nodes(self._in_progress), *self._iter_nodes(self._completed)]
        done = sum(1 for node in all_nodes if node.status == AgentStatus.COMPLETE)
        failed = sum(1 for node in all_nodes if node.status == AgentStatus.FAILED)
        pending = sum(1 for node in all_nodes if node.status == AgentStatus.PENDING)
        return done, failed, pending

    def _count_kind(self, kind: AgentKind) -> int:
        return sum(
            1
            for node in [*self._iter_nodes(self._in_progress), *self._iter_nodes(self._completed)]
            if node.kind == kind
        )

    def _iter_nodes(self, roots: list[AgentNode]) -> list[AgentNode]:
        nodes: list[AgentNode] = []
        stack = list(roots)
        while stack:
            current = stack.pop()
            nodes.append(current)
            stack.extend(current.children)
        return nodes

    def _clone_node(self, node: AgentNode) -> AgentNode:
        return replace(
            node,
            children=[self._clone_node(child) for child in node.children],
        )

    def _emit(self, prefix: str, message: str) -> None:
        now = time.strftime("%H:%M:%S")
        self._activity.append(f"{now}  {prefix:<8}  {message}")
