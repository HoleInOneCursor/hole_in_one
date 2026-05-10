"use client";

import { useMemo, useState } from "react";

import { AgentTree } from "@/components/dashboard/AgentTree";
import { ForceGraph } from "@/components/dashboard/ForceGraph";
import { useDashboard } from "@/lib/dashboard/useDashboard";
import {
  STATUS_COLORS,
  type AgentHoverDetails,
  type AgentNode,
} from "@/lib/dashboard/types";

type TabKey = "agent-grid" | "activity" | "graph";

type HoverCard = {
  node: AgentHoverDetails;
  x: number;
  y: number;
};

function flattenNodes(roots: AgentNode[]): AgentNode[] {
  const out: AgentNode[] = [];
  const stack = [...roots];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current) continue;
    out.push(current);
    for (const child of current.children) stack.push(child);
  }
  return out;
}

function statusTone(line: string): string {
  const lower = line.toLowerCase();
  if (lower.includes("failed")) return "var(--status-failed)";
  if (lower.includes("merge")) return "var(--status-complete)";
  if (lower.includes("complete")) return "var(--status-complete)";
  return "var(--text-dim)";
}

export function Dashboard() {
  const snapshot = useDashboard(1000);
  const [tab, setTab] = useState<TabKey>("agent-grid");
  const [hoverCard, setHoverCard] = useState<HoverCard | null>(null);

  const featurePercent = useMemo(() => {
    if (!snapshot) return 0;
    return Math.round((snapshot.featureProgress.done / Math.max(1, snapshot.featureProgress.total)) * 100);
  }, [snapshot]);

  const tooltipPosition = useMemo(() => {
    if (!hoverCard) return null;

    const width = 280;
    const height = 134;
    if (typeof window === "undefined") {
      return { left: hoverCard.x + 14, top: hoverCard.y + 14 };
    }

    return {
      left: Math.max(8, Math.min(window.innerWidth - width - 8, hoverCard.x + 14)),
      top: Math.max(8, Math.min(window.innerHeight - height - 8, hoverCard.y + 14)),
    };
  }, [hoverCard]);

  if (!snapshot) {
    return <div className="dashboard-loading">Loading dashboard…</div>;
  }

  const allWorking = flattenNodes(snapshot.inProgress);

  return (
    <main className="dashboard-shell">
      <header className="panel panel-cyan top-strip">
        <span className="brand">{snapshot.projectName}</span>
        <span className="muted">{snapshot.uptime}</span>
        <span className="muted">{snapshot.totalParallelAgents} agents in parallel</span>
        <span className="bright-green">{snapshot.commitsPerHour.toLocaleString()} commits/hr</span>
      </header>

      <section className="main-grid">
        <aside className="left-column">
          <section className="panel panel-magenta merge-panel">
            <h3 className="panel-title">MERGE QUEUE</h3>
            <div className="kv-grid">
              <div>Success</div>
              <div style={{ color: STATUS_COLORS.complete }}>{Math.round(snapshot.mergeQueue.successRate)}%</div>
              <div>Merged</div>
              <div style={{ color: STATUS_COLORS.complete }}>{snapshot.mergeQueue.merged}</div>
              <div>Conflicts</div>
              <div style={{ color: "var(--status-fix)" }}>{snapshot.mergeQueue.conflicts}</div>
              <div>Failed</div>
              <div style={{ color: STATUS_COLORS.failed }}>{snapshot.mergeQueue.failed}</div>
            </div>
          </section>

          <section className="panel panel-blue">
            <h3 className="panel-title">METRICS</h3>
            <div className="kv-grid">
              <div>Commits/hr</div>
              <div>{snapshot.metrics.commitsPerHour.toLocaleString()}</div>
              <div>Agents done</div>
              <div>
                {snapshot.metrics.agentsDone}/{snapshot.metrics.agentsTotal}
              </div>
              <div>Failed</div>
              <div style={{ color: STATUS_COLORS.failed }}>{snapshot.metrics.failed}</div>
              <div>Pending</div>
              <div style={{ color: STATUS_COLORS.pending }}>{snapshot.metrics.pending}</div>
              <div>Merge rate</div>
              <div style={{ color: STATUS_COLORS.complete }}>{snapshot.metrics.mergeRate.toFixed(1)}%</div>
              <div>Tokens</div>
              <div>{snapshot.metrics.tokensK.toFixed(1)}K</div>
              <div>Est. cost</div>
              <div>${snapshot.metrics.estCostUsd.toFixed(2)}</div>
              <div>Impl agents</div>
              <div style={{ color: "var(--status-impl)" }}>{snapshot.metrics.implementationAgents}</div>
              <div>Fix agents</div>
              <div style={{ color: "var(--status-fix)" }}>{snapshot.metrics.fixAgents}</div>
            </div>
          </section>
        </aside>

        <section className="right-column">
          <div className="tabs-row">
            <button
              className={`tab-btn ${tab === "agent-grid" ? "active" : ""}`}
              onClick={() => {
                setHoverCard(null);
                setTab("agent-grid");
              }}
            >
              Agent Grid
            </button>
            <button
              className={`tab-btn ${tab === "activity" ? "active" : ""}`}
              onClick={() => {
                setHoverCard(null);
                setTab("activity");
              }}
            >
              Activity
            </button>
            <button
              className={`tab-btn ${tab === "graph" ? "active" : ""}`}
              onClick={() => {
                setHoverCard(null);
                setTab("graph");
              }}
            >
              Graph
            </button>
          </div>

          {tab === "agent-grid" ? (
            <>
              <div className="tree-columns">
                <AgentTree
                  title="In Progress"
                  nodes={snapshot.inProgress}
                  onNodeHover={(node, point) => setHoverCard({ node, x: point.x, y: point.y })}
                  onNodeLeave={() => setHoverCard(null)}
                />
                <AgentTree
                  title="Completed"
                  nodes={snapshot.completed}
                  onNodeHover={(node, point) => setHoverCard({ node, x: point.x, y: point.y })}
                  onNodeLeave={() => setHoverCard(null)}
                />
              </div>
              <section className="panel panel-green activity-slice">
                <h3 className="panel-title">Activity</h3>
                <div className="activity-scroll">
                  {snapshot.activityLines.slice(-18).map((line, idx) => (
                    <div className="activity-line" key={`${line}-${idx}`} style={{ color: statusTone(line) }}>
                      {line}
                    </div>
                  ))}
                </div>
              </section>
            </>
          ) : null}

          {tab === "activity" ? (
            <section className="panel panel-green full-activity">
              <h3 className="panel-title">Timeline</h3>
              <div className="activity-scroll">
                {snapshot.activityLines.map((line, idx) => (
                  <div className="activity-line" key={`${line}-${idx}`} style={{ color: statusTone(line) }}>
                    {line}
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {tab === "graph" ? (
            <section className="panel panel-green graph-panel">
              <h3 className="panel-title">Agent Flow Graph</h3>
              <ForceGraph
                roots={snapshot.inProgress}
                onNodeHover={(node, point) => setHoverCard({ node, x: point.x, y: point.y })}
                onNodeLeave={() => setHoverCard(null)}
              />
              <div className="graph-legend">
                <span>
                  <strong>Shapes:</strong> builder circle, implementation circle, fix triangle
                </span>
                <span>
                  <strong>Status:</strong> blue=running, green=complete, red=failed, yellow=pending
                </span>
                <span>{allWorking.length} working agents visualized</span>
              </div>
            </section>
          ) : null}
        </section>
      </section>

      <footer className="bottom-row">
        <section className="panel panel-cyan features">
          <h3 className="panel-title">{snapshot.featureProgress.label}</h3>
          <div className="feature-progress">
            <div className="feature-track">
              <div className="feature-fill" style={{ width: `${featurePercent}%` }} />
            </div>
            <div className="feature-meta">
              {snapshot.featureProgress.done}/{snapshot.featureProgress.total} {featurePercent}%
            </div>
          </div>
        </section>
        <section className="panel panel-cyan controls">{snapshot.controlsHint}</section>
      </footer>

      {hoverCard && tooltipPosition ? (
        <aside className="agent-hover-card" style={tooltipPosition}>
          <div className="hover-id">{hoverCard.node.id}</div>
          <div className="hover-line">
            <span>{hoverCard.node.role}</span>
            <span>{hoverCard.node.kind}</span>
          </div>
          <div className="hover-task">{hoverCard.node.task}</div>
          <div className="hover-line">
            <span style={{ color: STATUS_COLORS[hoverCard.node.status] }}>{hoverCard.node.status}</span>
            <span>{hoverCard.node.progress}%</span>
          </div>
        </aside>
      ) : null}
    </main>
  );
}
