import type { DashboardSnapshot } from "@/lib/dashboard/types";

const DEFAULT_API_BASE = "http://localhost:8787";

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
      this.lastGood = snapshot;
      return snapshot;
    } catch (error) {
      if (this.lastGood) {
        return {
          ...this.lastGood,
          controlsHint: `${this.lastGood.controlsHint} | stale (backend unreachable)`,
        };
      }
      throw error;
    }
  }
}
