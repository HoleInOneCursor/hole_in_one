"use client";

import { useEffect, useRef, useState } from "react";

import { BackendDashboardProvider } from "@/lib/dashboard/backendProvider";
import { MockDashboardProvider } from "@/lib/dashboard/mockProvider";
import type { DashboardSnapshot } from "@/lib/dashboard/types";

const DEFAULT_INTERVAL_MS = 1000;
const DASHBOARD_MODE = (process.env.NEXT_PUBLIC_DASHBOARD_MODE ?? "mock").toLowerCase();

export function useDashboard(intervalMs: number = DEFAULT_INTERVAL_MS): DashboardSnapshot | null {
  const providerRef = useRef<MockDashboardProvider | BackendDashboardProvider | null>(null);
  const localFallbackRef = useRef<MockDashboardProvider | null>(null);
  const gotLiveSnapshotRef = useRef(false);
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);

  if (providerRef.current == null) {
    providerRef.current =
      DASHBOARD_MODE === "live" ? new BackendDashboardProvider() : new MockDashboardProvider();
  }

  useEffect(() => {
    const provider = providerRef.current;
    if (!provider) return;
    let cancelled = false;

    const pull = async () => {
      try {
        const nextSnapshot = await provider.snapshot();
        if (DASHBOARD_MODE === "live") {
          gotLiveSnapshotRef.current = true;
        }
        if (!cancelled) {
          setSnapshot(nextSnapshot);
        }
      } catch (error) {
        if (!cancelled) {
          const reason = error instanceof Error ? error.message : String(error);
          console.info(`Dashboard snapshot fetch issue: ${reason}`);
          if (DASHBOARD_MODE === "live" && !gotLiveSnapshotRef.current) {
            if (localFallbackRef.current == null) {
              localFallbackRef.current = new MockDashboardProvider();
            }
            const fallbackSnapshot = localFallbackRef.current.snapshot();
            setSnapshot({
              ...fallbackSnapshot,
              controlsHint: "live mode unreachable; showing local mock fallback",
            });
          }
        }
      }
    };

    void pull();
    const handle = window.setInterval(() => {
      void pull();
    }, intervalMs);

    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [intervalMs]);

  return snapshot;
}
