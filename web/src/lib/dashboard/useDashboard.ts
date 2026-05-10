"use client";

import { useEffect, useRef, useState } from "react";

import { MockDashboardProvider } from "@/lib/dashboard/mockProvider";
import type { DashboardSnapshot } from "@/lib/dashboard/types";

const DEFAULT_INTERVAL_MS = 1000;

export function useDashboard(intervalMs: number = DEFAULT_INTERVAL_MS): DashboardSnapshot | null {
  const providerRef = useRef<MockDashboardProvider | null>(null);
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);

  if (providerRef.current == null) {
    providerRef.current = new MockDashboardProvider();
  }

  useEffect(() => {
    const provider = providerRef.current;
    if (!provider) return;

    setSnapshot(provider.snapshot());
    const handle = window.setInterval(() => {
      setSnapshot(provider.snapshot());
    }, intervalMs);

    return () => window.clearInterval(handle);
  }, [intervalMs]);

  return snapshot;
}
