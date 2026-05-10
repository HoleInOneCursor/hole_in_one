from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AgentStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    PENDING = "pending"


class AgentKind(str, Enum):
    BUILDER = "builder"
    IMPLEMENTATION = "implementation"
    FIX = "fix"


@dataclass(slots=True)
class AgentNode:
    id: str
    role: str
    kind: AgentKind
    status: AgentStatus
    progress: int = 0
    children: list["AgentNode"] = field(default_factory=list)


@dataclass(slots=True)
class MetricsSnapshot:
    iteration: int
    commits_per_hour: int
    agents_done: int
    agents_total: int
    failed: int
    pending: int
    merge_rate: float
    tokens_k: float
    est_cost_usd: float
    implementation_agents: int
    fix_agents: int


@dataclass(slots=True)
class MergeQueueSnapshot:
    success_rate: float
    merged: int
    conflicts: int
    failed: int


@dataclass(slots=True)
class FeatureProgressSnapshot:
    label: str
    done: int
    total: int


@dataclass(slots=True)
class DashboardSnapshot:
    project_name: str
    uptime: str
    total_parallel_agents: int
    commits_per_hour: int
    metrics: MetricsSnapshot
    merge_queue: MergeQueueSnapshot
    in_progress: list[AgentNode]
    completed: list[AgentNode]
    activity_lines: list[str]
    feature_progress: FeatureProgressSnapshot
    controls_hint: str
