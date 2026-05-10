from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from random import Random

from rich.text import Text
from textual.widgets import Static

from hole_in_one.ui.models import AgentKind, AgentNode, AgentStatus


@dataclass(slots=True)
class _NodeFrame:
    id: str
    kind: AgentKind
    status: AgentStatus
    child_count: int


@dataclass(slots=True)
class _SimNode:
    id: str
    kind: AgentKind
    status: AgentStatus
    child_count: int
    x: float
    y: float
    vx: float
    vy: float
    scale: float


class AgentGraphWidget(Static):
    """Animated force-layout graph for working agents."""

    def __init__(self, *, tick_s: float = 0.12, **kwargs) -> None:
        super().__init__(**kwargs)
        self.tick_s = tick_s
        self._rng = Random(17)
        self._sim_nodes: dict[str, _SimNode] = {}
        self._edges: set[tuple[str, str]] = set()
        self._repel = 90.0
        self._spring = 0.03
        self._damping = 0.86
        self._center_pull = 0.008

    def on_mount(self) -> None:
        self.set_interval(self.tick_s, self._tick_graph)
        self.update("[#6b7d8a]Waiting for agent data...[/]")

    def sync_agents(self, roots: list[AgentNode]) -> None:
        frames, edges, parents = self._flatten(roots)
        width, height = self._current_bounds()

        for node_id, frame in frames.items():
            existing = self._sim_nodes.get(node_id)
            if existing:
                existing.kind = frame.kind
                existing.status = frame.status
                existing.child_count = frame.child_count
                existing.scale = self._node_scale(frame.kind, frame.child_count)
                continue

            parent = parents.get(node_id)
            if parent and parent in self._sim_nodes:
                anchor = self._sim_nodes[parent]
                x = max(2.0, min(width - 3.0, anchor.x + self._rng.uniform(-6, 6)))
                y = max(2.0, min(height - 3.0, anchor.y + self._rng.uniform(-4, 4)))
            else:
                x = self._rng.uniform(3, max(4, width - 4))
                y = self._rng.uniform(2, max(3, height - 3))
            self._sim_nodes[node_id] = _SimNode(
                id=node_id,
                kind=frame.kind,
                status=frame.status,
                child_count=frame.child_count,
                x=x,
                y=y,
                vx=self._rng.uniform(-0.25, 0.25),
                vy=self._rng.uniform(-0.20, 0.20),
                scale=self._node_scale(frame.kind, frame.child_count),
            )

        for node_id in list(self._sim_nodes):
            if node_id not in frames:
                self._sim_nodes.pop(node_id, None)

        self._edges = {(src, dst) for (src, dst) in edges if src in self._sim_nodes and dst in self._sim_nodes}

    def _flatten(
        self,
        roots: list[AgentNode],
    ) -> tuple[dict[str, _NodeFrame], set[tuple[str, str]], dict[str, str]]:
        frames: dict[str, _NodeFrame] = {}
        edges: set[tuple[str, str]] = set()
        parents: dict[str, str] = {}

        def walk(node: AgentNode, parent_id: str | None = None) -> None:
            frames[node.id] = _NodeFrame(
                id=node.id,
                kind=node.kind,
                status=node.status,
                child_count=len(node.children),
            )
            if parent_id:
                edges.add((parent_id, node.id))
                parents[node.id] = parent_id
            for child in node.children:
                walk(child, node.id)

        for root in roots:
            walk(root)

        return frames, edges, parents

    def _node_scale(self, kind: AgentKind, child_count: int) -> float:
        if kind == AgentKind.BUILDER:
            base = 2.3
        elif kind == AgentKind.FIX:
            base = 1.3
        else:
            base = 1.2
        if child_count > 0:
            base += min(1.3, 0.3 * child_count)
        return base

    def _tick_graph(self) -> None:
        if not self._sim_nodes:
            self.update("[#6b7d8a]No in-progress agents yet.[/]", layout=False)
            return
        width, height = self._current_bounds()
        self._step_physics(width, height)
        self.update(self._render_canvas(width, height), layout=False)

    def _current_bounds(self) -> tuple[int, int]:
        width = max(24, self.content_size.width)
        height = max(10, self.content_size.height)
        return width, height

    def _step_physics(self, width: int, height: int) -> None:
        nodes = list(self._sim_nodes.values())
        forces: dict[str, list[float]] = {node.id: [0.0, 0.0] for node in nodes}

        for idx, left in enumerate(nodes):
            for right in nodes[idx + 1 :]:
                dx = right.x - left.x
                dy = right.y - left.y
                dist_sq = dx * dx + dy * dy + 0.15
                dist = sqrt(dist_sq)
                repel = self._repel / dist_sq
                fx = (dx / dist) * repel
                fy = (dy / dist) * repel
                forces[left.id][0] -= fx
                forces[left.id][1] -= fy
                forces[right.id][0] += fx
                forces[right.id][1] += fy

        for src, dst in self._edges:
            left = self._sim_nodes[src]
            right = self._sim_nodes[dst]
            dx = right.x - left.x
            dy = right.y - left.y
            dist = sqrt(dx * dx + dy * dy) + 0.001
            target = 4.0 + left.scale + right.scale
            stretch = dist - target
            pull = self._spring * stretch
            fx = (dx / dist) * pull
            fy = (dy / dist) * pull
            forces[left.id][0] += fx
            forces[left.id][1] += fy
            forces[right.id][0] -= fx
            forces[right.id][1] -= fy

        cx = width / 2
        cy = height / 2
        for node in nodes:
            forces[node.id][0] += (cx - node.x) * self._center_pull
            forces[node.id][1] += (cy - node.y) * self._center_pull

        min_x = 2.0
        max_x = width - 3.0
        min_y = 1.5
        max_y = height - 2.0
        for node in nodes:
            fx, fy = forces[node.id]
            node.vx = (node.vx + fx) * self._damping
            node.vy = (node.vy + fy) * self._damping
            node.x += node.vx
            node.y += node.vy

            if node.x < min_x:
                node.x = min_x
                node.vx = abs(node.vx) * 0.55
            elif node.x > max_x:
                node.x = max_x
                node.vx = -abs(node.vx) * 0.55

            if node.y < min_y:
                node.y = min_y
                node.vy = abs(node.vy) * 0.55
            elif node.y > max_y:
                node.y = max_y
                node.vy = -abs(node.vy) * 0.55

    def _render_canvas(self, width: int, height: int) -> Text:
        chars = [[" "] * width for _ in range(height)]
        styles: list[list[str | None]] = [[None] * width for _ in range(height)]

        def put(x: int, y: int, ch: str, style: str, *, overwrite: bool = True) -> None:
            if x < 0 or x >= width or y < 0 or y >= height:
                return
            if not overwrite and chars[y][x] != " ":
                return
            chars[y][x] = ch
            styles[y][x] = style

        for src, dst in self._edges:
            start = self._sim_nodes[src]
            end = self._sim_nodes[dst]
            self._draw_line(
                int(round(start.x)),
                int(round(start.y)),
                int(round(end.x)),
                int(round(end.y)),
                put=put,
            )

        for node in self._sim_nodes.values():
            x = int(round(node.x))
            y = int(round(node.y))
            color = self._status_color(node.status)
            symbol = self._node_symbol(node.kind, node.scale)
            if node.scale >= 2.1:
                for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    put(x + ox, y + oy, "•", self._soft_color(color), overwrite=False)
            put(x, y, symbol, f"bold {color}")

            if node.child_count > 0 or node.kind == AgentKind.BUILDER:
                label = node.id[:14]
                for idx, char in enumerate(label):
                    put(x + 2 + idx, y, char, "#98aebd", overwrite=False)

        out = Text()
        for row_idx, row in enumerate(chars):
            last_style: str | None = None
            for col_idx, ch in enumerate(row):
                style = styles[row_idx][col_idx]
                if style != last_style:
                    out.append(ch, style=style)
                    last_style = style
                else:
                    out.append(ch)
            if row_idx != height - 1:
                out.append("\n")
        return out

    def _draw_line(self, x0: int, y0: int, x1: int, y1: int, *, put) -> None:
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        glyph = self._line_glyph(x1 - x0, y1 - y0)

        while True:
            put(x0, y0, glyph, "#4c5863", overwrite=False)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def _line_glyph(self, dx: int, dy: int) -> str:
        adx = abs(dx)
        ady = abs(dy)
        if adx > ady * 2:
            return "─"
        if ady > adx * 2:
            return "│"
        return "╲" if dx * dy >= 0 else "╱"

    def _node_symbol(self, kind: AgentKind, scale: float) -> str:
        if kind == AgentKind.FIX:
            return "▲"
        if kind == AgentKind.BUILDER or scale >= 2.1:
            return "⬤"
        return "●"

    def _status_color(self, status: AgentStatus) -> str:
        return {
            AgentStatus.RUNNING: "#4da3ff",
            AgentStatus.COMPLETE: "#5be26c",
            AgentStatus.FAILED: "#ff4545",
            AgentStatus.PENDING: "#f2d14f",
        }[status]

    def _soft_color(self, base: str) -> str:
        return {
            "#4da3ff": "#2a5f99",
            "#5be26c": "#2e7f3a",
            "#ff4545": "#8e2d2d",
            "#f2d14f": "#8b7a2d",
        }.get(base, "#4c5863")
