import {
  type AgentKind,
  type AgentNode,
  type AgentStatus,
  type DashboardSnapshot,
  type FeatureProgressSnapshot,
  type MergeQueueSnapshot,
  type MetricsSnapshot,
} from "@/lib/dashboard/types";

type WorkstreamSeed = {
  slug: string;
  role: string;
  task: string;
  kind: AgentKind;
  children?: WorkstreamSeed[];
};

type RuntimeMeta = {
  parentId: string | null;
  spawnPlan: WorkstreamSeed[];
  spawnedChildren: number;
  maxProgressBeforeChildren: number;
  depth: number;
  spawnedFix: boolean;
};

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

function slugify(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 44);
}

const COD_GOAL_PROMPT =
  "Build a production-grade Call of Duty style online FPS: authoritative multiplayer, " +
  "responsive combat, identity/auth, progression, live services, and CI quality gates.";

const COD_WORKSTREAMS: WorkstreamSeed[] = [
  {
    slug: "gameplay",
    role: "planner/gameplay",
    task: "Own gameplay workstream: combat loop, movement fidelity, sandbox interactions.",
    kind: "builder",
    children: [
      {
        slug: "engine-runtime",
        role: "subplanner/engine",
        task: "Split engine runtime into deterministic tick phases and frame pipeline boundaries.",
        kind: "builder",
        children: [
          {
            slug: "ecs-scheduler",
            role: "worker/engine",
            task: "Implement ECS scheduler with strict phase ordering for simulation determinism.",
            kind: "implementation",
          },
          {
            slug: "physics-bridge",
            role: "worker/physics",
            task: "Integrate physics bridge for collision, rigid body updates, and trace queries.",
            kind: "implementation",
          },
          {
            slug: "render-framegraph",
            role: "worker/render",
            task: "Ship render framegraph staging hooks used by gameplay and world streaming.",
            kind: "implementation",
          },
        ],
      },
      {
        slug: "movement",
        role: "subplanner/movement",
        task: "Deliver sprint, slide, jump, and mantle traversal with predictable replication.",
        kind: "builder",
        children: [
          {
            slug: "traversal-state-machine",
            role: "worker/movement",
            task: "Build traversal state machine for sprint, crouch, slide, jump, and mantle.",
            kind: "implementation",
          },
          {
            slug: "camera-recoil-coupling",
            role: "worker/movement",
            task: "Wire camera motion and recoil coupling so feel remains stable under latency.",
            kind: "implementation",
          },
        ],
      },
      {
        slug: "meshes-animation",
        role: "subplanner/meshes",
        task: "Stand up skeletal mesh, animation retargeting, and LOD streaming workflow.",
        kind: "builder",
        children: [
          {
            slug: "skeletal-import",
            role: "worker/meshes",
            task: "Create skeletal import pipeline with validation for naming and rig compatibility.",
            kind: "implementation",
          },
          {
            slug: "ik-retarget",
            role: "worker/animation",
            task: "Implement IK retargeting and weapon stance pose blending for FPS hands.",
            kind: "implementation",
          },
          {
            slug: "lod-streaming",
            role: "worker/meshes",
            task: "Add LOD streaming budget logic for near/far transitions without frame spikes.",
            kind: "implementation",
          },
        ],
      },
      {
        slug: "sandbox-tools",
        role: "subplanner/sandbox",
        task: "Expose gameplay sandbox scripting, trigger volumes, and command tooling.",
        kind: "builder",
        children: [
          {
            slug: "trigger-volumes",
            role: "worker/sandbox",
            task: "Implement trigger volume system with event payloads and replay safety.",
            kind: "implementation",
          },
          {
            slug: "mission-scripting",
            role: "worker/sandbox",
            task: "Ship mission scripting bindings for objectives, spawn waves, and fail conditions.",
            kind: "implementation",
          },
        ],
      },
    ],
  },
  {
    slug: "networking",
    role: "planner/networking",
    task: "Own network stack workstream: replication, matchmaking, dedicated servers, anti-cheat telemetry.",
    kind: "builder",
    children: [
      {
        slug: "replication",
        role: "subplanner/replication",
        task: "Decompose replication into channels, prediction, and reconciliation pipelines.",
        kind: "builder",
        children: [
          {
            slug: "entity-replication",
            role: "worker/netcode",
            task: "Implement entity replication channels and bandwidth budgets per actor class.",
            kind: "implementation",
          },
          {
            slug: "client-prediction",
            role: "worker/netcode",
            task: "Add client prediction + server reconciliation for movement and aiming states.",
            kind: "implementation",
          },
          {
            slug: "lag-compensation",
            role: "worker/netcode",
            task: "Integrate server rewind for lag compensated hit validation.",
            kind: "implementation",
          },
        ],
      },
      {
        slug: "matchmaking",
        role: "subplanner/matchmaking",
        task: "Implement party queueing, MMR ranking, and region-aware session allocation.",
        kind: "builder",
        children: [
          {
            slug: "party-queue",
            role: "worker/matchmaking",
            task: "Ship party queue domain model with MMR buckets and timeout fallbacks.",
            kind: "implementation",
          },
          {
            slug: "region-routing",
            role: "worker/matchmaking",
            task: "Implement region routing policy using ping, capacity, and fairness constraints.",
            kind: "implementation",
          },
        ],
      },
      {
        slug: "server-fleet",
        role: "subplanner/fleet",
        task: "Manage dedicated server image, autoscaling, and drain behavior for match lifecycle.",
        kind: "builder",
        children: [
          {
            slug: "server-image",
            role: "worker/fleet",
            task: "Harden dedicated server image and startup contract for fast cold boot.",
            kind: "implementation",
          },
          {
            slug: "autoscaling",
            role: "worker/fleet",
            task: "Add autoscaling rules for match burst loads with queue pressure signals.",
            kind: "implementation",
          },
        ],
      },
      {
        slug: "anti-cheat-ingest",
        role: "subplanner/anticheat",
        task: "Implement anti-cheat telemetry ingest and suspicious session scoring.",
        kind: "builder",
        children: [
          {
            slug: "telemetry-schema",
            role: "worker/anticheat",
            task: "Define anti-cheat telemetry schema and ingestion validation contracts.",
            kind: "implementation",
          },
          {
            slug: "session-scoring",
            role: "worker/anticheat",
            task: "Ship suspicious session scoring pipeline and reviewer queue integration.",
            kind: "implementation",
          },
        ],
      },
    ],
  },
  {
    slug: "auth",
    role: "planner/auth",
    task: "Own identity workstream: account login, token lifecycle, entitlement checks, RBAC.",
    kind: "builder",
    children: [
      {
        slug: "device-oauth",
        role: "subplanner/auth",
        task: "Build device + OAuth login entry points for console and web clients.",
        kind: "builder",
        children: [
          {
            slug: "device-login-flow",
            role: "worker/auth",
            task: "Implement device login flow with proof code exchange and polling constraints.",
            kind: "implementation",
          },
          {
            slug: "oauth-callbacks",
            role: "worker/auth",
            task: "Add OAuth callback validation, nonce replay prevention, and provider mapping.",
            kind: "implementation",
          },
        ],
      },
      {
        slug: "account-linking",
        role: "subplanner/auth",
        task: "Support platform account linking, unlink safety, and entitlement merges.",
        kind: "builder",
        children: [
          {
            slug: "linking-service",
            role: "worker/auth",
            task: "Implement account linking service with conflict resolution and audit records.",
            kind: "implementation",
          },
          {
            slug: "entitlement-merge",
            role: "worker/auth",
            task: "Merge cross-platform entitlements and preserve purchased inventory state.",
            kind: "implementation",
          },
        ],
      },
      {
        slug: "session-security",
        role: "subplanner/security",
        task: "Handle token rotation, session revocation, and role-based authorization controls.",
        kind: "builder",
        children: [
          {
            slug: "token-rotation",
            role: "worker/security",
            task: "Implement rotating access tokens with revocation propagation and replay guards.",
            kind: "implementation",
          },
          {
            slug: "rbac-enforcement",
            role: "worker/security",
            task: "Add RBAC policy checks for admin routes and sensitive account operations.",
            kind: "implementation",
          },
        ],
      },
    ],
  },
  {
    slug: "progression-liveops",
    role: "planner/liveops",
    task: "Own progression and liveops workstream: stats, battle pass, economy, store.",
    kind: "builder",
    children: [
      {
        slug: "stats-ingest",
        role: "worker/liveops",
        task: "Ship post-match stats ingest and aggregate leaderboard snapshot jobs.",
        kind: "implementation",
      },
      {
        slug: "inventory-service",
        role: "worker/liveops",
        task: "Implement inventory service with transactional grants, spends, and rollbacks.",
        kind: "implementation",
      },
      {
        slug: "battle-pass",
        role: "worker/liveops",
        task: "Deliver battle pass progression rules and season rollover migrations.",
        kind: "implementation",
      },
      {
        slug: "storefront",
        role: "worker/liveops",
        task: "Integrate storefront catalog sync, price validation, and checkout hooks.",
        kind: "implementation",
      },
    ],
  },
  {
    slug: "qa-observability",
    role: "planner/quality",
    task: "Own QA workstream: test harnesses, CI checks, perf budgets, runtime observability.",
    kind: "builder",
    children: [
      {
        slug: "integration-harness",
        role: "worker/qa",
        task: "Build integration harness covering auth, matchmaking, and gameplay start flow.",
        kind: "implementation",
      },
      {
        slug: "perf-budgets",
        role: "worker/perf",
        task: "Add frame-time, tick-time, and memory regression thresholds in CI.",
        kind: "implementation",
      },
      {
        slug: "crash-telemetry",
        role: "worker/obs",
        task: "Ship crash telemetry and structured runtime tracing across services.",
        kind: "implementation",
      },
      {
        slug: "release-gates",
        role: "worker/qa",
        task: "Define release gates with smoke tests and merge blocking policy checks.",
        kind: "implementation",
      },
    ],
  },
];

export class MockDashboardProvider {
  private readonly rng = new SeededRandom(17);
  private readonly startedAt = Date.now();
  private readonly maxParallelRunning = 24;
  private readonly activityLimit = 220;
  private readonly runtime = new Map<string, RuntimeMeta>();
  private readonly plannerTasks = COD_WORKSTREAMS.map(
    (item, idx) => `Step ${idx + 1}: ${item.role} -> ${item.task}`,
  );

  private iteration = 0;
  private inProgress: AgentNode[] = [];
  private completed: AgentNode[] = [];
  private activity: string[] = [];
  private topLevelSpawned = 0;

  private merged = 0;
  private mergeConflicts = 0;
  private mergeFailed = 0;
  private tokensK = 0;
  private costUsd = 0;
  private agentsTotal = 1;

  constructor() {
    const orchestratorId = "cod-orch";
    const orchestrator: AgentNode = {
      id: orchestratorId,
      role: "orchestrator",
      task: COD_GOAL_PROMPT,
      kind: "builder",
      status: "running",
      progress: 4,
      children: [],
    };
    this.inProgress = [orchestrator];
    this.runtime.set(orchestratorId, {
      parentId: null,
      spawnPlan: COD_WORKSTREAMS,
      spawnedChildren: 0,
      maxProgressBeforeChildren: 64,
      depth: 0,
      spawnedFix: false,
    });

    this.emit("boot", "mock orchestration simulation initialized");
    this.emit("prompt", COD_GOAL_PROMPT);
    this.emit("plan", "starting with 1 orchestrator; workstreams will fan out recursively");
  }

  snapshot(): DashboardSnapshot {
    this.tick();

    const [doneCount, failedCount, pendingCount] = this.summarizeCounts();
    const implementationAgents = this.countKind("implementation");
    const fixAgents = this.countKind("fix");
    const mergeTotal = this.merged + this.mergeConflicts + this.mergeFailed;
    const mergeRate = Math.round((this.merged / Math.max(1, mergeTotal)) * 1000) / 10;
    const elapsedHours = Math.max(1e-6, (Date.now() - this.startedAt) / 3_600_000);
    const commitsPerHour = this.merged > 0 ? Math.round(this.merged / elapsedHours) : 0;

    const metrics: MetricsSnapshot = {
      iteration: this.iteration,
      commitsPerHour,
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
      label: "WORKSTREAM COVERAGE",
      done: doneCount,
      total: this.agentsTotal,
    };

    const plannerTaskIndex =
      this.topLevelSpawned > 0
        ? Math.min(this.plannerTasks.length - 1, this.topLevelSpawned - 1)
        : -1;

    return {
      projectName: "HOLE IN GOLF",
      uptime: formatUptime(Date.now() - this.startedAt),
      totalParallelAgents: this.countStatus("running"),
      commitsPerHour: metrics.commitsPerHour,
      metrics,
      mergeQueue,
      inProgress: this.inProgress.map(cloneNode),
      completed: this.completed.map(cloneNode),
      activityLines: [...this.activity],
      featureProgress,
      controlsHint:
        "mock mode | prompt=build COD | recursive planners + workers + fixers simulation",
      plannerTasks: [...this.plannerTasks],
      plannerTaskIndex,
    };
  }

  private tick(): void {
    this.iteration += 1;
    this.tokensK += this.rng.float(0.9, 3.8);
    this.costUsd += this.rng.float(0.004, 0.019);

    this.spawnFromReadyParents();
    this.promotePendingAgents();
    this.advanceRunningAgents();
    this.archiveFinishedRoots();
    this.emitHeartbeat();
  }

  private spawnFromReadyParents(): void {
    // Slow orchestration fanout to feel closer to long-running real execution.
    if (this.iteration % 2 !== 0) return;
    let spawnBudget = this.iteration < 24 ? 2 : 3;

    const candidates = [...this.runtime.entries()]
      .map(([id, meta]) => {
        const node = this.findNode(id);
        return { id, meta, node };
      })
      .filter(
        (item) =>
          item.node != null &&
          item.node.status === "running" &&
          item.meta.spawnedChildren < item.meta.spawnPlan.length,
      )
      .sort((a, b) => a.meta.depth - b.meta.depth);

    for (const candidate of candidates) {
      if (spawnBudget <= 0) break;
      if (!candidate.node) continue;

      const trigger = 10 + candidate.meta.spawnedChildren * 9 + candidate.meta.depth * 4;
      if (candidate.node.progress < trigger) continue;

      const spawnChance = candidate.meta.depth === 0 ? 0.95 : candidate.meta.depth === 1 ? 0.82 : 0.7;
      if (this.rng.next() > spawnChance) continue;

      const seed = candidate.meta.spawnPlan[candidate.meta.spawnedChildren];
      if (!seed) continue;

      this.spawnChild(candidate.id, seed, candidate.meta.depth + 1);
      candidate.meta.spawnedChildren += 1;
      spawnBudget -= 1;

      if (candidate.meta.parentId === null) {
        this.topLevelSpawned = candidate.meta.spawnedChildren;
        this.emit(
          "plan",
          `primary workstream ${this.topLevelSpawned}/${COD_WORKSTREAMS.length} dispatched`,
        );
      }
    }
  }

  private spawnChild(parentId: string, seed: WorkstreamSeed, depth: number): void {
    const parent = this.findNode(parentId);
    if (!parent) return;

    const prefix = seed.kind === "fix" ? "fix" : seed.kind === "builder" ? "plan" : "work";
    const descriptor = seed.slug || seed.role || seed.task;
    const id = this.allocateNamedId(prefix, descriptor);

    const startRunning = this.countStatus("running") < this.maxParallelRunning;
    const status: AgentStatus = startRunning ? "running" : "pending";
    const progress = status === "running" ? this.rng.int(1, 8) : 0;

    const node: AgentNode = {
      id,
      role: seed.role,
      task: seed.task,
      kind: seed.kind,
      status,
      progress,
      children: [],
    };

    parent.children.push(node);
    this.agentsTotal += 1;
    this.runtime.set(id, {
      parentId,
      spawnPlan: seed.children ?? [],
      spawnedChildren: 0,
      maxProgressBeforeChildren: seed.children && seed.children.length > 0 ? 62 : 100,
      depth,
      spawnedFix: false,
    });

    this.emit(
      "spawn",
      `${id} (${seed.role}) spawned under ${parent.id} -> ${seed.slug.replaceAll("-", "_")}`,
    );
  }

  private promotePendingAgents(): void {
    const openSlots = this.maxParallelRunning - this.countStatus("running");
    if (openSlots <= 0) return;

    const pending = this.iterNodes(this.inProgress).filter((node) => node.status === "pending");
    const wakeCount = Math.min(openSlots, pending.length, 3);
    for (let idx = 0; idx < wakeCount; idx += 1) {
      const node = pending[idx];
      if (!node) continue;
      node.status = "running";
      node.progress = Math.max(1, this.rng.int(1, 4));
      this.emit("dispatch", `${node.id} picked up by runner pool (${node.role})`);
    }
  }

  private advanceRunningAgents(): void {
    const runningNodes = this.iterNodes(this.inProgress)
      .filter((node) => node.status === "running")
      .sort((a, b) => this.depthFor(b.id) - this.depthFor(a.id));

    for (const node of runningNodes) {
      const meta = this.runtime.get(node.id);
      const hasUnspawnedChildren = meta ? meta.spawnedChildren < meta.spawnPlan.length : false;
      const hasActiveChildren = this.nodeHasActiveChildren(node);

      // Roughly 50% slower completion cadence.
      const baseStep =
        node.kind === "builder" ? this.rng.int(2, 4) : node.kind === "fix" ? this.rng.int(3, 7) : this.rng.int(2, 6);

      if (hasUnspawnedChildren && meta) {
        node.progress = Math.min(meta.maxProgressBeforeChildren, node.progress + baseStep);
        continue;
      }

      if (hasActiveChildren) {
        const cap = node.kind === "builder" ? 93 : 88;
        node.progress = Math.min(cap, node.progress + Math.max(1, Math.floor(baseStep / 3)));
        continue;
      }

      node.progress = Math.min(100, node.progress + baseStep);
      if (node.progress >= 100) {
        this.finalizeNode(node);
      }
    }
  }

  private finalizeNode(node: AgentNode): void {
    if (node.status !== "running") return;

    if (this.shouldFail(node)) {
      node.status = "failed";
      this.mergeConflicts += 1;
      if (this.rng.next() < 0.35) {
        this.mergeFailed += 1;
      }
      this.emit("failed", `${node.id} failed: ${node.task}`);
      this.spawnFixerFor(node);
      return;
    }

    node.status = "complete";
    this.emit("complete", `${node.id} completed: ${node.task}`);

    if (node.kind === "implementation") {
      this.merged += 1;
      if (this.rng.next() < 0.55) {
        this.emit(
          "merge",
          `merged ${node.id} (${this.merged} total)`,
        );
      }
    }

    if (node.kind === "fix") {
      this.merged += 1;
      this.emit("merge", `fix merged from ${node.id}`);
      this.resolveParentFailureFromFix(node);
    }
  }

  private shouldFail(node: AgentNode): boolean {
    if (node.kind !== "implementation") return false;
    if (node.children.length > 0) return false;
    let failChance = 0.22;
    const fingerprint = `${node.role} ${node.task}`.toLowerCase();
    if (
      fingerprint.includes("netcode") ||
      fingerprint.includes("replication") ||
      fingerprint.includes("physics") ||
      fingerprint.includes("security") ||
      fingerprint.includes("auth")
    ) {
      failChance += 0.08;
    }
    if (
      fingerprint.includes("anticheat") ||
      fingerprint.includes("lag") ||
      fingerprint.includes("token")
    ) {
      failChance += 0.05;
    }
    return this.rng.next() < Math.min(0.42, failChance);
  }

  private spawnFixerFor(failedNode: AgentNode): void {
    const meta = this.runtime.get(failedNode.id);
    if (meta && meta.spawnedFix) return;
    if (meta) {
      meta.spawnedFix = true;
    }
    const issueSlugs = this.issueSlugsForFailure(failedNode);
    const fixCount = Math.min(issueSlugs.length, this.rng.next() < 0.62 ? 2 : 1);
    for (let i = 0; i < fixCount; i += 1) {
      const issue = issueSlugs[i];
      if (!issue) continue;
      const fixerSeed: WorkstreamSeed = {
        slug: issue,
        role: "fixer/greptile",
        task: `Fix ${issue.replaceAll("-", " ")} in ${failedNode.id} and rerun focused checks.`,
        kind: "fix",
      };
      this.spawnChild(failedNode.id, fixerSeed, this.depthFor(failedNode.id) + 1);
      this.emit("fix", `spawned ${fixerSeed.slug} fixer for ${failedNode.id}`);
    }
  }

  private issueSlugsForFailure(node: AgentNode): string[] {
    const text = `${node.role} ${node.task}`.toLowerCase();
    if (text.includes("movement")) {
      return ["invalid-ammo-usage", "movement-state-desync", "slide-cancel-regression"];
    }
    if (text.includes("physics")) {
      return ["collision-penetration-bug", "projectile-trace-mismatch", "rigid-body-jitter"];
    }
    if (text.includes("netcode") || text.includes("replication") || text.includes("lag")) {
      return ["snapshot-ordering-race", "hit-reg-desync", "rollback-window-overflow"];
    }
    if (text.includes("auth") || text.includes("security") || text.includes("token")) {
      return ["token-refresh-race", "session-revocation-gap", "rbac-guard-miss"];
    }
    if (text.includes("anticheat")) {
      return ["telemetry-schema-mismatch", "scoring-threshold-drift", "review-queue-backpressure"];
    }
    if (text.includes("mesh") || text.includes("animation")) {
      return ["ik-pose-breakage", "lod-pop-regression", "asset-rig-compat-bug"];
    }
    return ["invalid-ammo-usage", "null-state-guard-miss", "integration-contract-break"];
  }

  private resolveParentFailureFromFix(fixNode: AgentNode): void {
    const meta = this.runtime.get(fixNode.id);
    const parentId = meta?.parentId;
    if (!parentId) return;
    const parent = this.findNode(parentId);
    if (!parent || parent.status !== "failed") return;

    const unresolvedFixers = parent.children.some(
      (child) => child.kind === "fix" && (child.status === "running" || child.status === "pending"),
    );
    if (unresolvedFixers) return;

    parent.status = "complete";
    parent.progress = 100;
    this.emit("recover", `${parent.id} marked resolved after fixer merge (${fixNode.id})`);
  }

  private archiveFinishedRoots(): void {
    const stillActive: AgentNode[] = [];
    const doneRoots: AgentNode[] = [];

    for (const root of this.inProgress) {
      if (
        (root.status === "complete" || root.status === "failed") &&
        !this.nodeHasActiveChildren(root)
      ) {
        doneRoots.push(root);
      } else {
        stillActive.push(root);
      }
    }

    this.inProgress = stillActive;
    if (doneRoots.length > 0) {
      this.completed.push(...doneRoots);
    }
  }

  private emitHeartbeat(): void {
    if (this.iteration % 18 !== 0) return;
    this.emit(
      "telemetry",
      `running=${this.countStatus("running")} pending=${this.countStatus("pending")} merged=${this.merged}`,
    );
  }

  private depthFor(id: string): number {
    return this.runtime.get(id)?.depth ?? 0;
  }

  private nodeHasActiveChildren(node: AgentNode): boolean {
    const stack = [...node.children];
    while (stack.length > 0) {
      const current = stack.pop();
      if (!current) continue;
      if (current.status === "running" || current.status === "pending") {
        return true;
      }
      if (current.children.length > 0) {
        stack.push(...current.children);
      }
    }
    return false;
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

  private countStatus(status: AgentStatus): number {
    return this.iterNodes(this.inProgress).filter((node) => node.status === status).length;
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
      if (current.children.length > 0) {
        stack.push(...current.children);
      }
    }
    return nodes;
  }

  private findNode(id: string): AgentNode | null {
    const stack = [...this.inProgress, ...this.completed];
    while (stack.length > 0) {
      const current = stack.pop();
      if (!current) continue;
      if (current.id === id) return current;
      if (current.children.length > 0) {
        stack.push(...current.children);
      }
    }
    return null;
  }

  private allocateNamedId(prefix: string, descriptor: string): string {
    const baseSlug = slugify(descriptor) || "agent";
    const root = `${prefix}-${baseSlug}`;
    if (!this.findNode(root)) {
      return root;
    }
    let suffix = 2;
    while (true) {
      const candidate = `${root}-${suffix}`;
      if (!this.findNode(candidate)) {
        return candidate;
      }
      suffix += 1;
    }
  }

  private emit(prefix: string, message: string): void {
    this.activity.push(`${nowTime()}  ${prefix.padEnd(8, " ")}  ${message}`);
    if (this.activity.length > this.activityLimit) {
      this.activity = this.activity.slice(-this.activityLimit);
    }
  }
}
