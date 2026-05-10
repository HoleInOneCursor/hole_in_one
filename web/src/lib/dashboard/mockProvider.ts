import {
  AgentKind,
  type AgentNode,
  type AgentStatus,
  type DashboardSnapshot,
  type FeatureProgressSnapshot,
  type MergeQueueSnapshot,
  type MetricsSnapshot,
} from "@/lib/dashboard/types";

class SeededRandom {
  private state: number;

  constructor(seed: number) {
    this.state = seed >>> 0;
  }

  next(): number {
    this.state += 0x6d2b79f5;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  int(min: number, maxInclusive: number): number {
    return Math.floor(this.next() * (maxInclusive - min + 1)) + min;
  }

  float(min: number, max: number): number {
    return min + this.next() * (max - min);
  }

  choice<T>(items: readonly T[]): T {
    return items[this.int(0, items.length - 1)] as T;
  }
}

function cloneNode(node: AgentNode): AgentNode {
  return {
    ...node,
    children: node.children.map(cloneNode),
  };
}

function nowTime(): string {
  const now = new Date();
  return now.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatUptime(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export class MockDashboardProvider {
  private rng = new SeededRandom(7);
  private startedAt = Date.now();
  private iteration = 0;
  private activity: string[] = [];
  private completed = this.seedCompletedAgents();
  private inProgress = this.seedInProgressAgents();
  private mergeConflicts = 2;
  private mergeFailed = 0;
  private merged = 36;
  private tokensK = 367.4;
  private costUsd = 0.37;
  private agentsTotal = 100;

  constructor() {
    this.emit("boot", "dashboard initialized");
    this.emit("sync", "mock provider online; backend disconnected");
  }

  snapshot(): DashboardSnapshot {
    this.tick();

    const [doneCount, failedCount, pendingCount] = this.summarizeCounts();
    const implementationAgents = this.countKind("implementation");
    const fixAgents = this.countKind("fix");
    const mergeRate =
      Math.round(
        (this.merged / Math.max(1, this.merged + this.mergeConflicts + this.mergeFailed)) *
          1000,
      ) / 10;

    const metrics: MetricsSnapshot = {
      iteration: this.iteration,
      commitsPerHour: 11349 + this.rng.int(-120, 90),
      agentsDone: doneCount,
      agentsTotal: this.agentsTotal,
      failed: failedCount,
      pending: pendingCount,
      mergeRate,
      tokensK: Math.round(this.tokensK * 10) / 10,
      estCostUsd: Math.round(this.costUsd * 100) / 100,
      implementationAgents,
      fixAgents,
    };

    const mergeQueue: MergeQueueSnapshot = {
      successRate: mergeRate,
      merged: this.merged,
      conflicts: this.mergeConflicts,
      failed: this.mergeFailed,
    };

    const featureProgress: FeatureProgressSnapshot = {
      label: "FEATURES",
      done: doneCount,
      total: this.agentsTotal,
    };

    return {
      projectName: "HOLE IN GOLF",
      uptime: formatUptime(Date.now() - this.startedAt),
      totalParallelAgents: this.inProgress.length,
      commitsPerHour: metrics.commitsPerHour,
      metrics,
      mergeQueue,
      inProgress: this.inProgress.map(cloneNode),
      completed: this.completed.map(cloneNode),
      activityLines: [...this.activity],
      featureProgress,
      controlsHint: "mock mode | tab=agent-grid/activity/graph",
    };
  }

  private tick(): void {
    this.iteration += 1;
    this.tokensK += this.rng.float(0.5, 2.2);
    this.costUsd += this.rng.float(0.002, 0.011);

    const runningNodes = this.iterNodes(this.inProgress).filter((node) => node.status === "running");
    if (runningNodes.length > 0) {
      const node = this.rng.choice(runningNodes);
      node.progress = Math.min(100, node.progress + this.rng.int(7, 24));
      if (node.progress >= 100 && this.rng.next() > 0.08) {
        node.status = "complete";
        this.emit("complete", `${node.id} finished by ${node.role}`);
      } else if (node.progress >= 95) {
        node.status = "failed";
        this.emit("failed", `${node.id} failed lint checks`);
      }
    }

    this.rollCompletedRoots();
    if (this.iteration % 5 === 0) {
      this.emit("merge", `merged worker/${String(this.rng.int(1, 44)).padStart(3, "0")}`);
      this.merged += 1;
    }
  }

  private rollCompletedRoots(): void {
    const moved: AgentNode[] = [];
    const stillActive: AgentNode[] = [];

    for (const root of this.inProgress) {
      if (root.status === "complete" || root.status === "failed") {
        moved.push(root);
      } else {
        stillActive.push(root);
      }
    }

    this.inProgress = stillActive;
    if (moved.length > 0) {
      this.completed.push(...moved);
    }

    while (this.inProgress.length < 12) {
      this.inProgress.push(this.newRootAgent());
    }
  }

  private newRootAgent(): AgentNode {
    const base = this.rng.int(50, 99);
    const kind = this.rng.choice<AgentKind>(["implementation", "fix"]);

    return {
      id: `agent-${String(base).padStart(3, "0")}`,
      role: "planner",
      kind,
      status: "running",
      progress: this.rng.int(3, 42),
      children: [],
    };
  }

  private summarizeCounts(): [number, number, number] {
    const allNodes = [...this.iterNodes(this.inProgress), ...this.iterNodes(this.completed)];
    let done = 0;
    let failed = 0;
    let pending = 0;

    for (const node of allNodes) {
      if (node.status === "complete") done += 1;
      if (node.status === "failed") failed += 1;
      if (node.status === "pending") pending += 1;
    }

    return [done, failed, pending];
  }

  private countKind(kind: AgentKind): number {
    const allNodes = [...this.iterNodes(this.inProgress), ...this.iterNodes(this.completed)];
    return allNodes.filter((node) => node.kind === kind).length;
  }

  private iterNodes(roots: AgentNode[]): AgentNode[] {
    const nodes: AgentNode[] = [];
    const stack = [...roots];

    while (stack.length > 0) {
      const current = stack.pop();
      if (!current) continue;
      nodes.push(current);
      for (const child of current.children) {
        stack.push(child);
      }
    }

    return nodes;
  }

  private emit(prefix: string, message: string): void {
    this.activity.push(`${nowTime()}  ${prefix.padEnd(8, " ")}  ${message}`);
    if (this.activity.length > 120) {
      this.activity = this.activity.slice(-120);
    }
  }

  private seedInProgressAgents(): AgentNode[] {
    return [
      {
        id: "agent-001",
        role: "planner",
        kind: "builder",
        status: "running",
        progress: 38,
        children: [
          {
            id: "agent-001-sub-1",
            role: "subplanner",
            kind: "implementation",
            status: "running",
            progress: 22,
            children: [
              {
                id: "agent-001-sub-1-sub-1",
                role: "worker",
                kind: "implementation",
                status: "running",
                progress: 13,
                children: [],
              },
            ],
          },
        ],
      },
      {
        id: "agent-004",
        role: "planner",
        kind: "implementation",
        status: "running",
        progress: 61,
        children: [],
      },
      {
        id: "agent-007",
        role: "planner",
        kind: "fix",
        status: "running",
        progress: 48,
        children: [],
      },
      {
        id: "agent-012",
        role: "planner",
        kind: "implementation",
        status: "running",
        progress: 74,
        children: [],
      },
      {
        id: "agent-019",
        role: "planner",
        kind: "fix",
        status: "pending",
        progress: 0,
        children: [],
      },
      {
        id: "agent-024",
        role: "planner",
        kind: "implementation",
        status: "running",
        progress: 52,
        children: [
          {
            id: "agent-024-sub-1",
            role: "subplanner",
            kind: "implementation",
            status: "running",
            progress: 36,
            children: [],
          },
        ],
      },
      {
        id: "agent-029",
        role: "planner",
        kind: "fix",
        status: "running",
        progress: 29,
        children: [],
      },
      {
        id: "agent-030",
        role: "planner",
        kind: "implementation",
        status: "running",
        progress: 44,
        children: [],
      },
      {
        id: "agent-034",
        role: "planner",
        kind: "fix",
        status: "failed",
        progress: 100,
        children: [],
      },
      {
        id: "agent-036",
        role: "planner",
        kind: "implementation",
        status: "running",
        progress: 82,
        children: [],
      },
      {
        id: "agent-038",
        role: "planner",
        kind: "implementation",
        status: "running",
        progress: 46,
        children: [],
      },
      {
        id: "agent-049",
        role: "planner",
        kind: "fix",
        status: "running",
        progress: 60,
        children: [],
      },
    ];
  }

  private seedCompletedAgents(): AgentNode[] {
    const completed: AgentNode[] = [];

    for (const idx of [5, 8, 10, 11, 14, 17, 18, 22, 26, 27]) {
      completed.push({
        id: `agent-${String(idx).padStart(3, "0")}`,
        role: "planner",
        kind: "implementation",
        status: "complete",
        progress: 100,
        children: [],
      });
    }

    for (const idx of [30, 34]) {
      const status: AgentStatus = idx === 34 ? "failed" : "complete";
      completed.push({
        id: `agent-${String(idx).padStart(3, "0")}`,
        role: "planner",
        kind: "fix",
        status,
        progress: 100,
        children: [],
      });
    }

    return completed;
  }
}
