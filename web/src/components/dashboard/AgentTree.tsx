import { KIND_COLORS, STATUS_COLORS, type AgentNode } from "@/lib/dashboard/types";

type TreeRow = {
  node: AgentNode;
  depth: number;
  branch: string;
};

function toRows(nodes: AgentNode[]): TreeRow[] {
  const rows: TreeRow[] = [];

  const walk = (list: AgentNode[], depth: number, prefix: string) => {
    list.forEach((node, index) => {
      const isLast = index === list.length - 1;
      const branch = `${prefix}${depth === 0 ? "" : isLast ? "└─ " : "├─ "}`;
      rows.push({ node, depth, branch });
      const nextPrefix = `${prefix}${depth === 0 ? "" : isLast ? "   " : "│  "}`;
      if (node.children.length > 0) {
        walk(node.children, depth + 1, nextPrefix);
      }
    });
  };

  walk(nodes, 0, "");
  return rows;
}

function kindGlyph(kind: AgentNode["kind"]): string {
  if (kind === "fix") return "▲";
  if (kind === "builder") return "⬤";
  return "●";
}

export function AgentTree({ title, nodes }: { title: string; nodes: AgentNode[] }) {
  const rows = toRows(nodes);

  return (
    <section className="panel panel-green agent-tree-panel">
      <h3 className="panel-title">{title}</h3>
      <div className="agent-tree-scroll">
        {rows.map(({ node, branch }) => {
          const statusColor = STATUS_COLORS[node.status];
          return (
            <div className="agent-row" key={node.id}>
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
