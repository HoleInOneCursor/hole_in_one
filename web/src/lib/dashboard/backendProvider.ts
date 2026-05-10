import type { DashboardSnapshot } from "@/lib/dashboard/types";

const DEFAULT_API_BASE = "http://localhost:8787";
const OUTAGE_LOG_INTERVAL_MS = 30_000;

function normalizedApiBase(raw: string | undefined): string {
  const base = (raw ?? DEFAULT_API_BASE).trim();
  return base.replace(/\/+$/, "");
}

function assertSnapshotShape(value: unknown): DashboardSnapshot {
  if (!value || typeof value !== "object") {
    throw new Error("dashboard snapshot payload is not an object");
  }
  const candidate = value as Partial<DashboardSnapshot>;
  if (!candidate.projectName || !candidate.metrics || !candidate.mergeQueue) {
    throw new Error("dashboard snapshot payload is missing required fields");
  }
  return candidate as DashboardSnapshot;
}

export class BackendDashboardProvider {
  private readonly apiBase: string;
  private lastGood: DashboardSnapshot | null = null;
  private backendReachable = true;
  private lastOutageLogAt = 0;

  constructor(apiBase: string = normalizedApiBase(process.env.NEXT_PUBLIC_DASHBOARD_API_BASE)) {
    this.apiBase = normalizedApiBase(apiBase);
  }

  async snapshot(): Promise<DashboardSnapshot> {
    try {
      const response = await fetch(`${this.apiBase}/api/dashboard/snapshot`, {
        method: "GET",
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`snapshot endpoint returned ${response.status}`);
      }
      const payload = (await response.json()) as unknown;
      const snapshot = assertSnapshotShape(payload);
      if (!this.backendReachable) {
        console.info(`[dashboard] Live backend recovered at ${this.apiBase}.`);
      }
      this.backendReachable = true;
      this.lastGood = snapshot;
      return snapshot;
    } catch (error) {
      this.noteBackendUnreachable(error);
      if (this.lastGood) {
        return {
          ...this.lastGood,
          controlsHint: `${this.lastGood.controlsHint} | stale (backend unreachable)`,
        };
      }
      return this.unavailableSnapshot();
    }
  }

  private noteBackendUnreachable(error: unknown): void {
    const now = Date.now();
    const shouldLog = this.backendReachable || now - this.lastOutageLogAt >= OUTAGE_LOG_INTERVAL_MS;
    this.backendReachable = false;
    if (!shouldLog) {
      return;
    }
    this.lastOutageLogAt = now;
    const reason =
      error instanceof Error && error.message ? error.message : "unable to reach dashboard backend";
    console.info(`[dashboard] Backend unavailable (${reason}); continuing to poll ${this.apiBase}.`);
  }

  private unavailableSnapshot(): DashboardSnapshot {
    const stamp = new Date().toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    return {
      projectName: "HOLE IN GOLF",
      uptime: "0:00:00",
      totalParallelAgents: 0,
      commitsPerHour: 0,
      metrics: {
        iteration: 0,
        commitsPerHour: 0,
        agentsDone: 0,
        agentsTotal: 100,
        failed: 0,
        pending: 0,
        mergeRate: 0,
        tokensK: 0,
        estCostUsd: 0,
        implementationAgents: 0,
        fixAgents: 0,
      },
      mergeQueue: {
        successRate: 0,
        merged: 0,
        conflicts: 0,
        failed: 0,
      },
      inProgress: [],
      completed: [],
      activityLines: [
        `${stamp}  sync      live backend unreachable, retrying`,
      ],
      featureProgress: {
        label: "FEATURES",
        done: 0,
        total: 100,
      },
      controlsHint: `live mode | backend unreachable (${this.apiBase}) | retrying`,
    };
  }
}
