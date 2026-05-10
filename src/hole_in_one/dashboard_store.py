from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta

from hole_in_one.ui.models import (
    AgentKind,
    AgentNode,
    AgentStatus,
    DashboardSnapshot,
    FeatureProgressSnapshot,
    MergeQueueSnapshot,
    MetricsSnapshot,
)


class DashboardStore:
    """Thread-safe in-memory dashboard state used by FastAPI + orchestrator."""

    def __init__(
        self,
        *,
        project_name: str = "HOLE IN GOLF",
        agents_total: int = 100,
        activity_limit: int = 240,
    ) -> None:
        self._lock = threading.RLock()
        self._project_name = project_name
        self._agents_total = max(1, agents_total)
        self._started_at = time.monotonic()
        self._controls_hint = "live mode | tab=agent-grid/activity/graph"

        self._iteration = 0
        self._tokens_k = 0.0
        self._est_cost_usd = 0.0

        self._merged = 0
        self._conflicts = 0
        self._merge_failed = 0
        self._merged_pull_numbers: set[int] = set()

        self._activity: deque[str] = deque(maxlen=max(40, activity_limit))
        self._in_progress: list[AgentNode] = []
        self._completed: list[AgentNode] = []
        self._planner_tasks: tuple[str, ...] = ()
        self._planner_task_index: int = -1

        self.record_activity("boot", "live dashboard store initialized")

    def record_activity(self, prefix: str, message: str) -> None:
        now = time.strftime("%H:%M:%S")
        line = f"{now}  {prefix:<8}  {message}"
        with self._lock:
            self._activity.append(line)

    def set_controls_hint(self, hint: str) -> None:
        with self._lock:
            self._controls_hint = hint

    def set_iteration(self, iteration: int) -> None:
        with self._lock:
            self._iteration = max(0, iteration)

    def bump_iteration(self) -> None:
        with self._lock:
            self._iteration += 1

    def set_tokens_cost(self, *, tokens_k: float | None = None, est_cost_usd: float | None = None) -> None:
        with self._lock:
            if tokens_k is not None:
                self._tokens_k = max(0.0, tokens_k)
            if est_cost_usd is not None:
                self._est_cost_usd = max(0.0, est_cost_usd)

    def set_agents_total(self, total: int) -> None:
        with self._lock:
            self._agents_total = max(1, total)

    def set_planner_tasks(self, tasks: Sequence[str], *, current_index: int = 0) -> None:
        """Expose CLōD split builder prompts and which step is running (for web dashboard)."""
        with self._lock:
            self._planner_tasks = tuple(str(t) for t in tasks)
            if not self._planner_tasks:
                self._planner_task_index = -1
            else:
                self._planner_task_index = max(0, min(current_index, len(self._planner_tasks) - 1))

    def add_or_update_root_agent(
        self,
        *,
        agent_id: str,
        role: str,
        task: str,
        kind: AgentKind,
        status: AgentStatus,
        progress: int,
    ) -> None:
        with self._lock:
            idx = self._find_root_index(self._in_progress, agent_id)
            if idx is not None:
                node = self._in_progress[idx]
                self._in_progress[idx] = replace(
                    node,
                    role=role,
                    task=task,
                    kind=kind,
                    status=status,
                    progress=max(0, min(100, progress)),
                )
                return

            done_idx = self._find_root_index(self._completed, agent_id)
            if done_idx is not None:
                node = self._completed.pop(done_idx)
                self._in_progress.append(
                    replace(
                        node,
                        role=role,
                        task=task,
                        kind=kind,
                        status=status,
                        progress=max(0, min(100, progress)),
                    )
                )
                return

            self._in_progress.append(
                AgentNode(
                    id=agent_id,
                    role=role,
                    task=task,
                    kind=kind,
                    status=status,
                    progress=max(0, min(100, progress)),
                )
            )

    def finish_agent(self, agent_id: str, *, success: bool, note: str | None = None) -> None:
        with self._lock:
            idx = self._find_root_index(self._in_progress, agent_id)
            if idx is None:
                return
            node = self._in_progress.pop(idx)
            finished = replace(
                node,
                status=AgentStatus.COMPLETE if success else AgentStatus.FAILED,
                progress=100 if success else max(1, node.progress),
            )
            self._completed.append(finished)
            if note:
                self._activity.append(f"{time.strftime('%H:%M:%S')}  complete   {note}")

    def add_or_update_child_agent(
        self,
        *,
        parent_id: str,
        agent_id: str,
        role: str,
        task: str,
        kind: AgentKind,
        status: AgentStatus,
        progress: int,
    ) -> bool:
        with self._lock:
            parent = self._find_node(self._in_progress, parent_id) or self._find_node(
                self._completed,
                parent_id,
            )
            if parent is None:
                return False

            child = self._find_node(parent.children, agent_id)
            if child is not None:
                child.role = role
                child.task = task
                child.kind = kind
                child.status = status
                child.progress = max(0, min(100, progress))
                return True

            parent.children.append(
                AgentNode(
                    id=agent_id,
                    role=role,
                    task=task,
                    kind=kind,
                    status=status,
                    progress=max(0, min(100, progress)),
                )
            )
            return True

    def finish_child_agent(
        self,
        *,
        parent_id: str,
        agent_id: str,
        success: bool,
        note: str | None = None,
    ) -> bool:
        with self._lock:
            parent = self._find_node(self._in_progress, parent_id) or self._find_node(
                self._completed,
                parent_id,
            )
            if parent is None:
                return False

            child = self._find_node(parent.children, agent_id)
            if child is None:
                return False

            child.status = AgentStatus.COMPLETE if success else AgentStatus.FAILED
            child.progress = 100 if success else max(1, child.progress)

            if note:
                self._activity.append(f"{time.strftime('%H:%M:%S')}  complete   {note}")
            return True

    def mark_merge_queued(self, pull_number: int, method: str) -> None:
        self.record_activity("merge", f"queued auto-merge ({method}) for PR #{pull_number}")

    def mark_merge_conflict(self, pull_number: int, detail: str) -> None:
        with self._lock:
            self._conflicts += 1
        self.record_activity("merge", f"PR #{pull_number} conflict/block: {detail}")

    def mark_merge_failure(self, pull_number: int, detail: str) -> None:
        with self._lock:
            self._merge_failed += 1
        self.record_activity("failed", f"merge failed for PR #{pull_number}: {detail}")

    def mark_pr_merged(self, pull_number: int) -> None:
        with self._lock:
            if pull_number in self._merged_pull_numbers:
                return
            self._merged_pull_numbers.add(pull_number)
            self._merged += 1
        self.record_activity("merge", f"PR #{pull_number} merged")

    def snapshot(self) -> DashboardSnapshot:
        with self._lock:
            in_progress = [self._clone_node(node) for node in self._in_progress]
            completed = [self._clone_node(node) for node in self._completed]
            activity_lines = list(self._activity)
            uptime = str(timedelta(seconds=int(time.monotonic() - self._started_at)))

            all_nodes = [*self._flatten(in_progress), *self._flatten(completed)]
            done_count = sum(1 for n in all_nodes if n.status == AgentStatus.COMPLETE)
            failed_count = sum(1 for n in all_nodes if n.status == AgentStatus.FAILED)
            pending_count = sum(1 for n in all_nodes if n.status == AgentStatus.PENDING)
            running_count = sum(1 for n in all_nodes if n.status == AgentStatus.RUNNING)
            implementation_agents = sum(1 for n in all_nodes if n.kind == AgentKind.IMPLEMENTATION)
            fix_agents = sum(1 for n in all_nodes if n.kind == AgentKind.FIX)

            merge_total = self._merged + self._conflicts + self._merge_failed
            merge_rate = round((self._merged / max(1, merge_total)) * 100, 1)

            elapsed_hours = max(1e-6, (time.monotonic() - self._started_at) / 3600.0)
            commits_per_hour = int(round(self._merged / elapsed_hours)) if self._merged > 0 else 0

            metrics = MetricsSnapshot(
                iteration=self._iteration,
                commits_per_hour=commits_per_hour,
                agents_done=done_count,
                agents_total=self._agents_total,
                failed=failed_count,
                pending=pending_count,
                merge_rate=merge_rate,
                tokens_k=round(self._tokens_k, 1),
                est_cost_usd=round(self._est_cost_usd, 2),
                implementation_agents=implementation_agents,
                fix_agents=fix_agents,
            )
            merge_queue = MergeQueueSnapshot(
                success_rate=merge_rate,
                merged=self._merged,
                conflicts=self._conflicts,
                failed=self._merge_failed,
            )
            feature_progress = FeatureProgressSnapshot(
                label="FEATURES",
                done=done_count,
                total=self._agents_total,
            )

            return DashboardSnapshot(
                project_name=self._project_name,
                uptime=uptime,
                total_parallel_agents=running_count,
                commits_per_hour=commits_per_hour,
                metrics=metrics,
                merge_queue=merge_queue,
                in_progress=in_progress,
                completed=completed,
                activity_lines=activity_lines,
                feature_progress=feature_progress,
                controls_hint=self._controls_hint,
                planner_tasks=self._planner_tasks,
                planner_task_index=self._planner_task_index,
            )

    def _find_root_index(self, roots: list[AgentNode], agent_id: str) -> int | None:
        for idx, node in enumerate(roots):
            if node.id == agent_id:
                return idx
        return None

    def _find_node(self, roots: list[AgentNode], agent_id: str) -> AgentNode | None:
        stack = list(roots)
        while stack:
            node = stack.pop()
            if node.id == agent_id:
                return node
            stack.extend(node.children)
        return None

    def _clone_node(self, node: AgentNode) -> AgentNode:
        return replace(node, children=[self._clone_node(c) for c in node.children])

    def _flatten(self, roots: list[AgentNode]) -> list[AgentNode]:
        out: list[AgentNode] = []
        stack = list(roots)
        while stack:
            node = stack.pop()
            out.append(node)
            stack.extend(node.children)
        return out
