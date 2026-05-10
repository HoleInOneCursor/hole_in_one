"use client";

import { useEffect, useRef, useState } from "react";

import {
  STATUS_COLORS,
  type AgentHoverDetails,
  type AgentKind,
  type AgentNode,
  type AgentStatus,
} from "@/lib/dashboard/types";

type Point = {
  x: number;
  y: number;
};

type ForceGraphProps = {
  roots: AgentNode[];
  onNodeHover?: (node: AgentHoverDetails, point: Point) => void;
  onNodeLeave?: () => void;
};

type FrameNode = {
  id: string;
  role: string;
  task: string;
  kind: AgentKind;
  status: AgentStatus;
  progress: number;
  childCount: number;
};

type SimNode = FrameNode & {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
};

type Edge = {
  source: string;
  target: string;
};

type RenderEdge = {
  id: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
};

type RenderData = {
  nodes: SimNode[];
  edges: RenderEdge[];
};

type SimulationState = {
  nodes: Map<string, SimNode>;
  edges: Edge[];
};

const REPEL = 6500;
const SPRING = 0.016;
const DAMPING = 0.9;
const CENTER_PULL = 0.005;

function nodeRadius(kind: AgentKind, childCount: number): number {
  const base = kind === "builder" ? 18 : 10;
  const hierarchyBoost = Math.min(9, childCount * 2);
  return base + hierarchyBoost;
}

function flatten(roots: AgentNode[]): {
  nodes: Map<string, FrameNode>;
  edges: Edge[];
  parents: Map<string, string>;
} {
  const nodes = new Map<string, FrameNode>();
  const edges: Edge[] = [];
  const parents = new Map<string, string>();

  const walk = (node: AgentNode, parentId?: string) => {
    nodes.set(node.id, {
      id: node.id,
      role: node.role,
      task: node.task,
      kind: node.kind,
      status: node.status,
      progress: node.progress,
      childCount: node.children.length,
    });

    if (parentId) {
      edges.push({ source: parentId, target: node.id });
      parents.set(node.id, parentId);
    }

    for (const child of node.children) {
      walk(child, node.id);
    }
  };

  for (const root of roots) walk(root);

  return { nodes, edges, parents };
}

function trianglePoints(x: number, y: number, r: number): string {
  const top = `${x},${y - r}`;
  const left = `${x - r * 0.9},${y + r * 0.8}`;
  const right = `${x + r * 0.9},${y + r * 0.8}`;
  return `${top} ${left} ${right}`;
}

function edgeColor(sourceStatus: AgentStatus): string {
  if (sourceStatus === "failed") return "rgba(248, 113, 113, 0.5)";
  if (sourceStatus === "complete") return "rgba(216, 180, 254, 0.45)";
  if (sourceStatus === "pending") return "rgba(251, 191, 36, 0.45)";
  return "rgba(56, 189, 248, 0.46)";
}

function buildRenderData(sim: SimulationState): RenderData {
  const nodes = [...sim.nodes.values()];
  const edges: RenderEdge[] = [];

  for (const edge of sim.edges) {
    const source = sim.nodes.get(edge.source);
    const target = sim.nodes.get(edge.target);
    if (!source || !target) continue;

    edges.push({
      id: `${edge.source}->${edge.target}`,
      x1: source.x,
      y1: source.y,
      x2: target.x,
      y2: target.y,
      color: edgeColor(source.status),
    });
  }

  return { nodes, edges };
}

export function ForceGraph({ roots, onNodeHover, onNodeLeave }: ForceGraphProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const simRef = useRef<SimulationState>({ nodes: new Map(), edges: [] });
  const [size, setSize] = useState({ width: 800, height: 440 });
  const [renderData, setRenderData] = useState<RenderData>({ nodes: [], edges: [] });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const resize = () => {
      const rect = el.getBoundingClientRect();
      setSize({
        width: Math.max(420, Math.floor(rect.width)),
        height: Math.max(280, Math.floor(rect.height)),
      });
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(el);

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const { nodes: frameNodes, edges, parents } = flatten(roots);
    const sim = simRef.current;

    for (const [id, node] of frameNodes) {
      const existing = sim.nodes.get(id);
      if (existing) {
        existing.role = node.role;
        existing.task = node.task;
        existing.kind = node.kind;
        existing.status = node.status;
        existing.progress = node.progress;
        existing.childCount = node.childCount;
        existing.radius = nodeRadius(node.kind, node.childCount);
        continue;
      }

      const parentId = parents.get(id);
      const parent = parentId ? sim.nodes.get(parentId) : undefined;
      const x = parent
        ? parent.x + (Math.random() * 2 - 1) * 50
        : 32 + Math.random() * Math.max(40, size.width - 64);
      const y = parent
        ? parent.y + (Math.random() * 2 - 1) * 34
        : 24 + Math.random() * Math.max(40, size.height - 48);

      sim.nodes.set(id, {
        ...node,
        x,
        y,
        vx: (Math.random() * 2 - 1) * 0.5,
        vy: (Math.random() * 2 - 1) * 0.5,
        radius: nodeRadius(node.kind, node.childCount),
      });
    }

    for (const id of [...sim.nodes.keys()]) {
      if (!frameNodes.has(id)) {
        sim.nodes.delete(id);
      }
    }

    sim.edges = edges.filter((edge) => sim.nodes.has(edge.source) && sim.nodes.has(edge.target));
  }, [roots, size.width, size.height]);

  useEffect(() => {
    let raf = 0;
    let lastPaint = 0;

    const loop = (ts: number) => {
      const sim = simRef.current;
      const nodes = [...sim.nodes.values()];

      if (nodes.length > 0) {
        const fx = new Map<string, number>();
        const fy = new Map<string, number>();
        for (const node of nodes) {
          fx.set(node.id, 0);
          fy.set(node.id, 0);
        }

        for (let i = 0; i < nodes.length; i += 1) {
          for (let j = i + 1; j < nodes.length; j += 1) {
            const a = nodes[i] as SimNode;
            const b = nodes[j] as SimNode;
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const distSq = dx * dx + dy * dy + 0.4;
            const dist = Math.sqrt(distSq);
            const force = REPEL / distSq;
            const dirX = dx / dist;
            const dirY = dy / dist;

            fx.set(a.id, (fx.get(a.id) ?? 0) - dirX * force);
            fy.set(a.id, (fy.get(a.id) ?? 0) - dirY * force);
            fx.set(b.id, (fx.get(b.id) ?? 0) + dirX * force);
            fy.set(b.id, (fy.get(b.id) ?? 0) + dirY * force);
          }
        }

        for (const edge of sim.edges) {
          const a = sim.nodes.get(edge.source);
          const b = sim.nodes.get(edge.target);
          if (!a || !b) continue;

          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) + 0.01;
          const target = a.radius + b.radius + 44;
          const stretch = dist - target;
          const pull = SPRING * stretch;
          const dirX = dx / dist;
          const dirY = dy / dist;

          fx.set(a.id, (fx.get(a.id) ?? 0) + dirX * pull);
          fy.set(a.id, (fy.get(a.id) ?? 0) + dirY * pull);
          fx.set(b.id, (fx.get(b.id) ?? 0) - dirX * pull);
          fy.set(b.id, (fy.get(b.id) ?? 0) - dirY * pull);
        }

        const cx = size.width / 2;
        const cy = size.height / 2;
        const minX = 20;
        const maxX = size.width - 20;
        const minY = 18;
        const maxY = size.height - 20;

        for (const node of nodes) {
          const centerX = (cx - node.x) * CENTER_PULL;
          const centerY = (cy - node.y) * CENTER_PULL;
          const forceX = (fx.get(node.id) ?? 0) + centerX;
          const forceY = (fy.get(node.id) ?? 0) + centerY;

          node.vx = (node.vx + forceX * 0.016) * DAMPING;
          node.vy = (node.vy + forceY * 0.016) * DAMPING;
          node.x += node.vx;
          node.y += node.vy;

          const r = node.radius;
          if (node.x < minX + r) {
            node.x = minX + r;
            node.vx = Math.abs(node.vx) * 0.48;
          }
          if (node.x > maxX - r) {
            node.x = maxX - r;
            node.vx = -Math.abs(node.vx) * 0.48;
          }
          if (node.y < minY + r) {
            node.y = minY + r;
            node.vy = Math.abs(node.vy) * 0.48;
          }
          if (node.y > maxY - r) {
            node.y = maxY - r;
            node.vy = -Math.abs(node.vy) * 0.48;
          }
        }
      }

      if (ts - lastPaint > 40) {
        setRenderData(buildRenderData(sim));
        lastPaint = ts;
      }
      raf = window.requestAnimationFrame(loop);
    };

    raf = window.requestAnimationFrame(loop);
    return () => window.cancelAnimationFrame(raf);
  }, [size.width, size.height]);

  return (
    <div className="graph-shell" ref={containerRef}>
      <svg className="graph-svg" viewBox={`0 0 ${size.width} ${size.height}`}>
        <defs>
          <filter id="nodeGlow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {renderData.edges.map((edge) => (
          <line
            key={edge.id}
            x1={edge.x1}
            y1={edge.y1}
            x2={edge.x2}
            y2={edge.y2}
            stroke={edge.color}
            strokeWidth={1.6}
            strokeLinecap="round"
          />
        ))}

        {renderData.nodes.map((node) => {
          const color = STATUS_COLORS[node.status];
          const labelVisible = node.kind === "builder" || node.childCount > 0;
          const hoverPayload: AgentHoverDetails = {
            id: node.id,
            role: node.role,
            task: node.task,
            kind: node.kind,
            status: node.status,
            progress: node.progress,
          };

          return (
            <g
              key={node.id}
              onMouseEnter={(event) =>
                onNodeHover?.(hoverPayload, { x: event.clientX, y: event.clientY })
              }
              onMouseMove={(event) =>
                onNodeHover?.(hoverPayload, { x: event.clientX, y: event.clientY })
              }
              onMouseLeave={onNodeLeave}
              style={{ cursor: "crosshair" }}
            >
              {node.kind === "fix" ? (
                <polygon
                  points={trianglePoints(node.x, node.y, node.radius)}
                  fill={color}
                  fillOpacity={0.92}
                  stroke={color}
                  strokeWidth={1.5}
                  filter="url(#nodeGlow)"
                />
              ) : (
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={node.radius}
                  fill={color}
                  fillOpacity={node.kind === "builder" ? 0.9 : 0.85}
                  stroke={color}
                  strokeWidth={1.4}
                  filter="url(#nodeGlow)"
                />
              )}

              {labelVisible ? (
                <text x={node.x + node.radius + 7} y={node.y + 4} className="graph-label">
                  {node.id}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
