import {
  KIND_COLORS,
  STATUS_COLORS,
  type AgentHoverDetails,
  type AgentNode,
} from "@/lib/dashboard/types";

type Point = {
  x: number;
  y: number;
};

type TreeRow = {
  node: AgentNode;
  key: string;
  branch: string;
};

type AgentTreeProps = {
  title: string;
  nodes: AgentNode[];
  onNodeHover?: (node: AgentHoverDetails, point: Point) => void;
  onNodeLeave?: () => void;
};

function toRows(nodes: AgentNode[]): TreeRow[] {
  const rows: TreeRow[] = [];

  const walk = (list: AgentNode[], depth: number, prefix: string, lineage: string) => {
    list.forEach((node, index) => {
      const isLast = index === list.length - 1;
      const branch = `${prefix}${depth === 0 ? "" : isLast ? "└─ " : "├─ "}`;
      const rowKey = lineage ? `${lineage}.${index}` : `${index}`;
      rows.push({ node, key: `${rowKey}-${node.id}`, branch });

      const nextPrefix = `${prefix}${depth === 0 ? "" : isLast ? "   " : "│  "}`;
      if (node.children.length > 0) {
        walk(node.children, depth + 1, nextPrefix, rowKey);
      }
    });
  };

  walk(nodes, 0, "", "");
  return rows;
}

function kindGlyph(kind: AgentNode["kind"]): string {
  if (kind === "fix") return "▲";
  if (kind === "builder") return "⬤";
  return "●";
}

export function AgentTree({ title, nodes, onNodeHover, onNodeLeave }: AgentTreeProps) {
  const rows = toRows(nodes);

  return (
    <section className="panel panel-green agent-tree-panel">
      <h3 className="panel-title">{title}</h3>
      <div className="agent-tree-scroll">
        {rows.map(({ node, branch, key }) => {
          const statusColor = STATUS_COLORS[node.status];
          return (
            <div
              className="agent-row"
              key={key}
              onMouseEnter={(event) =>
                onNodeHover?.(node, { x: event.clientX, y: event.clientY })
              }
              onMouseMove={(event) =>
                onNodeHover?.(node, { x: event.clientX, y: event.clientY })
              }
              onMouseLeave={onNodeLeave}
              title={`${node.id} • ${node.task}`}
            >
              <span className="branch">{branch}</span>
              <span style={{ color: statusColor }}>■■■</span>
              <span className="agent-id"> {node.id}</span>
              <span className="agent-role"> ({node.role})</span>
              <span style={{ color: statusColor }}> {node.status}</span>
              <span className="agent-meta"> {node.progress}%</span>
              <span className="agent-meta"> • </span>
              <span style={{ color: KIND_COLORS[node.kind] }}>
                {kindGlyph(node.kind)} {node.kind}
              </span>
            </div>
          );
        })}
        {rows.length === 0 ? <div className="agent-empty">No agents</div> : null}
      </div>
    </section>
  );
}
