export type AgentStatus = "running" | "complete" | "failed" | "pending";
export type AgentKind = "builder" | "implementation" | "fix";

export type AgentNode = {
  id: string;
  role: string;
  kind: AgentKind;
  status: AgentStatus;
  progress: number;
  children: AgentNode[];
};

export type MetricsSnapshot = {
  iteration: number;
  commitsPerHour: number;
  agentsDone: number;
  agentsTotal: number;
  failed: number;
  pending: number;
  mergeRate: number;
  tokensK: number;
  estCostUsd: number;
  implementationAgents: number;
  fixAgents: number;
};

export type MergeQueueSnapshot = {
  successRate: number;
  merged: number;
  conflicts: number;
  failed: number;
};

export type FeatureProgressSnapshot = {
  label: string;
  done: number;
  total: number;
};

export type DashboardSnapshot = {
  projectName: string;
  uptime: string;
  totalParallelAgents: number;
  commitsPerHour: number;
  metrics: MetricsSnapshot;
  mergeQueue: MergeQueueSnapshot;
  inProgress: AgentNode[];
  completed: AgentNode[];
  activityLines: string[];
  featureProgress: FeatureProgressSnapshot;
  controlsHint: string;
};

export const STATUS_COLORS: Record<AgentStatus, string> = {
  running: "#4da3ff",
  complete: "#5be26c",
  failed: "#ff4545",
  pending: "#f2d14f",
};

export const KIND_COLORS: Record<AgentKind, string> = {
  builder: "#8db4ff",
  implementation: "#6ace43",
  fix: "#ffbf4a",
};
