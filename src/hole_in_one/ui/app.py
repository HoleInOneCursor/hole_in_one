from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, RichLog, Static, TabbedContent, TabPane, Tree

from hole_in_one.ui.models import AgentKind, AgentNode, AgentStatus, DashboardSnapshot
from hole_in_one.ui.provider import DashboardDataProvider, MockDashboardProvider


def _status_style(status: AgentStatus) -> str:
    return {
        AgentStatus.RUNNING: "#6ace43",
        AgentStatus.COMPLETE: "#58c33e",
        AgentStatus.FAILED: "#e34b57",
        AgentStatus.PENDING: "#8e9aa0",
    }[status]


def _kind_style(kind: AgentKind) -> str:
    return {
        AgentKind.BUILDER: "#8db4ff",
        AgentKind.IMPLEMENTATION: "#6ace43",
        AgentKind.FIX: "#ffbf4a",
    }[kind]


def _agent_label(node: AgentNode) -> Text:
    text = Text()
    text.append("■■■ ", style=_status_style(node.status))
    text.append(f"{node.id} ", style="#c7d4d8")
    text.append(f"({node.role}) ", style="#8e9aa0")
    text.append(node.status.value, style=_status_style(node.status))
    text.append(f" {node.progress}%", style="#8e9aa0")
    text.append(" • ", style="#5f6b72")
    text.append(node.kind.value, style=_kind_style(node.kind))
    return text


class HoleInGolfDashboard(App[None]):
    CSS = """
    Screen {
        background: #06090f;
        color: #d2dde2;
    }

    #top-strip {
        border: round #1f5a73;
        color: #b8d2dd;
        margin: 0 1;
        padding: 0 1;
        height: 3;
    }

    #main-row {
        height: 1fr;
        margin: 0 1;
    }

    #sidebar {
        width: 30;
        margin-right: 1;
    }

    #workspace {
        width: 1fr;
    }

    .panel {
        border: round #325ecb;
        padding: 0 1;
    }

    #metrics-panel {
        height: 1fr;
        margin-bottom: 1;
    }

    #merge-panel {
        height: 14;
        border: round #9e2fc7;
    }

    #workspace-tabs {
        height: 1fr;
        margin-bottom: 1;
    }

    #tree-row {
        height: 1fr;
    }

    .tree-panel {
        border: round #6ea333;
        margin-right: 1;
    }

    #completed-tree {
        margin-right: 0;
    }

    .log-panel {
        border: round #6ea333;
        height: 12;
        margin-top: 1;
    }

    #bottom-row {
        height: 3;
        margin: 0 1 1 1;
    }

    #features-bar {
        width: 1fr;
        border: round #2a8ca2;
        margin-right: 1;
    }

    #controls-bar {
        width: 56;
        border: round #2a8ca2;
    }

    Footer {
        background: #07111b;
    }
    """

    BINDINGS = [("q", "quit", "Quit"), ("tab", "focus_next", "Next panel"), ("shift+tab", "focus_previous", "Prev panel")]

    def __init__(
        self,
        provider: DashboardDataProvider | None = None,
        *,
        refresh_interval: float = 1.0,
    ) -> None:
        super().__init__()
        self.provider = provider or MockDashboardProvider()
        self.refresh_interval = refresh_interval
        self._last_activity_count = 0

    def compose(self) -> ComposeResult:
        yield Static(id="top-strip")
        with Horizontal(id="main-row"):
            with Vertical(id="sidebar"):
                metrics = Static(id="metrics-panel", classes="panel")
                metrics.border_title = "METRICS"
                yield metrics
                merge_panel = Static(id="merge-panel", classes="panel")
                merge_panel.border_title = "MERGE QUEUE"
                yield merge_panel

            with Vertical(id="workspace"):
                with TabbedContent(id="workspace-tabs"):
                    with TabPane("Agent Grid", id="agent-grid-tab"):
                        with Horizontal(id="tree-row"):
                            in_progress = Tree("in-progress", id="in-progress-tree", classes="tree-panel")
                            in_progress.border_title = "In Progress"
                            yield in_progress
                            completed = Tree("completed", id="completed-tree", classes="tree-panel")
                            completed.border_title = "Completed"
                            yield completed
                        agent_log = RichLog(id="agent-log", classes="log-panel", highlight=False, wrap=False)
                        agent_log.border_title = "Activity"
                        yield agent_log

                    with TabPane("Activity", id="activity-tab"):
                        timeline = RichLog(id="activity-log", classes="panel", highlight=False, wrap=False)
                        timeline.border_title = "Timeline"
                        yield timeline

        with Horizontal(id="bottom-row"):
            yield Static(id="features-bar", classes="panel")
            yield Static(id="controls-bar", classes="panel")

        yield Footer()

    def on_mount(self) -> None:
        for tree in (self.query_one("#in-progress-tree", Tree), self.query_one("#completed-tree", Tree)):
            tree.show_root = False
            tree.root.expand()
        self.set_interval(self.refresh_interval, self._refresh_dashboard)
        self._refresh_dashboard()

    def _refresh_dashboard(self) -> None:
        snapshot = self.provider.snapshot()
        self._render_header(snapshot)
        self._render_metrics(snapshot)
        self._render_merge_queue(snapshot)
        self._render_tree("#in-progress-tree", snapshot.in_progress)
        self._render_tree("#completed-tree", snapshot.completed)
        self._render_activity(snapshot.activity_lines)
        self._render_bottom(snapshot)

    def _render_header(self, snapshot: DashboardSnapshot) -> None:
        head = Text()
        head.append(f"{snapshot.project_name}  ", style="#8ac5d8")
        head.append(snapshot.uptime, style="#6b9bb2")
        head.append(" " * 6)
        head.append(f"{snapshot.total_parallel_agents} agents in parallel", style="#9dc4cf")
        head.append(" " * 6)
        head.append(f"{snapshot.commits_per_hour:,} commits/hr", style="#63c956")
        self.query_one("#top-strip", Static).update(head)

    def _render_metrics(self, snapshot: DashboardSnapshot) -> None:
        metrics = snapshot.metrics
        table = Table.grid(expand=True)
        table.add_column(style="#8e9aa0")
        table.add_column(justify="right")
        table.add_row("Iteration", str(metrics.iteration))
        table.add_row("Commits/hr", f"{metrics.commits_per_hour:,}")
        table.add_row("Agents done", f"{metrics.agents_done}/{metrics.agents_total}")
        table.add_row("Failed", f"[#e34b57]{metrics.failed}[/]")
        table.add_row("Pending", f"[#8e9aa0]{metrics.pending}[/]")
        table.add_row("Merge rate", f"[#63c956]{metrics.merge_rate:.1f}%[/]")
        table.add_row("Tokens", f"{metrics.tokens_k:.1f}K")
        table.add_row("Est. cost", f"${metrics.est_cost_usd:.2f}")
        table.add_row("Impl agents", f"[#6ace43]{metrics.implementation_agents}[/]")
        table.add_row("Fix agents", f"[#ffbf4a]{metrics.fix_agents}[/]")
        self.query_one("#metrics-panel", Static).update(table)

    def _render_merge_queue(self, snapshot: DashboardSnapshot) -> None:
        queue = snapshot.merge_queue
        table = Table.grid(expand=True)
        table.add_column(style="#8e9aa0")
        table.add_column(justify="right")
        table.add_row("Success", f"[#63c956]{queue.success_rate:.0f}%[/]")
        table.add_row("Merged", f"[#63c956]{queue.merged}[/]")
        table.add_row("Conflicts", f"[#ffbf4a]{queue.conflicts}[/]")
        table.add_row("Failed", f"[#e34b57]{queue.failed}[/]")
        self.query_one("#merge-panel", Static).update(table)

    def _render_tree(self, selector: str, nodes: list[AgentNode]) -> None:
        tree = self.query_one(selector, Tree)
        tree.clear()
        tree.root.expand()
        for node in nodes:
            self._append_tree_node(tree.root, node)

    def _append_tree_node(self, parent, node: AgentNode) -> None:
        branch = parent.add(_agent_label(node), expand=True)
        for child in node.children:
            self._append_tree_node(branch, child)

    def _render_activity(self, lines: list[str]) -> None:
        delta = lines[self._last_activity_count :]
        if not delta:
            return
        agent_log = self.query_one("#agent-log", RichLog)
        activity_log = self.query_one("#activity-log", RichLog)
        for line in delta:
            styled = self._style_activity_line(line)
            agent_log.write(styled)
            activity_log.write(styled)
        self._last_activity_count = len(lines)

    def _style_activity_line(self, line: str) -> Text:
        text = Text(line, style="#89a5b0")
        lowered = line.lower()
        if "failed" in lowered:
            text.stylize("#e34b57")
        elif "merge" in lowered:
            text.stylize("#63c956")
        elif "complete" in lowered:
            text.stylize("#6ace43")
        return text

    def _render_bottom(self, snapshot: DashboardSnapshot) -> None:
        done = snapshot.feature_progress.done
        total = max(1, snapshot.feature_progress.total)
        percent = int((done / total) * 100)
        bar_width = 34
        fill = int((done / total) * bar_width)
        progress_bar = f"[#63c956]{'█' * fill}[/][#2d3640]{'█' * (bar_width - fill)}[/]"
        features = (
            f"[#8dc2d1]{snapshot.feature_progress.label}[/]  "
            f"{progress_bar}  "
            f"[#9fb4bd]{done}/{total} {percent}%[/]"
        )
        self.query_one("#features-bar", Static).update(features)
        self.query_one("#controls-bar", Static).update(f"[#9fb4bd]{snapshot.controls_hint}[/]")


def run_dashboard(provider: DashboardDataProvider | None = None, *, refresh_interval: float = 1.0) -> None:
    app = HoleInGolfDashboard(provider=provider, refresh_interval=refresh_interval)
    app.run()
