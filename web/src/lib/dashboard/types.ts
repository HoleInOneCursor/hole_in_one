export type AgentStatus = "running" | "complete" | "failed" | "pending";
export type AgentKind = "builder" | "implementation" | "fix";

export type AgentNode = {
  id: string;
  role: string;
  task: string;
  kind: AgentKind;
  status: AgentStatus;
  progress: number;
  children: AgentNode[];
};

export type AgentHoverDetails = {
  id: string;
  role: string;
  task: string;
  kind: AgentKind;
  status: AgentStatus;
  progress: number;
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
  /** CLōD split builder steps; empty when not used. */
  plannerTasks: string[];
  /** Index into `plannerTasks` for the step in progress, or -1. */
  plannerTaskIndex: number;
};

export const STATUS_COLORS: Record<AgentStatus, string> = {
  running: "#38bdf8",
  complete: "#d8b4fe",
  failed: "#f87171",
  pending: "#fbbf24",
};

export const KIND_COLORS: Record<AgentKind, string> = {
  builder: "#c084fc",
  implementation: "#67e8f9",
  fix: "#fb923c",
};
