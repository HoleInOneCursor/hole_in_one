from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

from hole_in_one.clod_api import (
    DEFAULT_CLOD_BASE_URL,
    DEFAULT_CLOD_MODEL,
    clod_second_validator,
    compress_greptile_feedback_for_fix,
    plan_builder_tasks,
    plan_pr_workstreams,
)
from hole_in_one.dashboard_api import DashboardApiRuntime, start_dashboard_api_server
from hole_in_one.dashboard_store import DashboardStore
from hole_in_one.cursor_api import (
    CursorCloudError,
    create_agent,
    create_agent_on_pr,
    get_agent,
    stop_agent,
    wait_for_terminal_run,
)
from hole_in_one.feedback import split_feedback
from hole_in_one.github_api import (
    Repo,
    branch_exists,
    create_pull_issue_comment,
    enable_pull_request_auto_merge,
    fetch_latest_greptile_issue_comment_body,
    fetch_pull_request_patch_bundle,
    find_latest_open_pr_head_ref_prefix,
    find_open_pr_for_branch,
    get_branch_tip_sha,
    get_default_branch,
    get_pr_head,
    get_pull_request_body,
    github_client,
    merge_clod_validator_pr_section,
    merge_pull_request_rest,
    parse_repo,
    poll_greptile_signal,
    pull_number_from_pr_url,
    pull_request_merged,
    repo_https_url,
    update_pull_request_body,
    wait_pull_mergeable_clean,
    wait_pull_merged,
)
from hole_in_one.ui.models import AgentKind, AgentStatus

load_dotenv()

DEFAULT_BUILDER_PROMPT = (
    'Make a small, self-contained improvement that fits the theme "Build Something Agents Want"\n'
    "(for example: a helper script, a concise doc, or a tiny devtool that makes agent workflows nicer).\n"
    "Keep the change reviewable in under 15 minutes."
)


def _utc_iso_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _greptile_plain_excerpt(raw: str, *, max_len: int = 6000) -> str:
    """Strip HTML-ish noise for PR comments; keep Greptile context readable."""
    if not raw.strip():
        return "(No Greptile text was captured for this run.)"
    t = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    t = re.sub(r"</p\s*>", "\n\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if len(t) > max_len:
        return t[:max_len].rstrip() + "\n\n_(Greptile excerpt truncated.)_"
    return t


def _patch_bundle_stats(patch_bundle: str) -> str:
    if not patch_bundle.strip():
        return "No unified diff text from GitHub for this PR (empty or binary-only files)."
    chunks = [p for p in patch_bundle.split("\n--- ") if p.strip()]
    n = len(chunks)
    chars = len(patch_bundle)
    return f"~{n} file section(s) in the patch bundle, {chars} characters (subject to CLI truncation caps)."


def _clod_validator_pr_blurb(
    *,
    stamp: str,
    verdict: str,
    vbody: str,
    validator_exc: BaseException | None,
    pr_url: str,
    pull_number: int,
    clod_model: str,
    greptile_raw: str,
    patch_bundle: str,
) -> str:
    """Rich Markdown for PR description and timeline comment."""
    title = "CLōD second validator"
    head = f"{title}\n\nAutomated ({stamp}) via hole_in_one orchestrate.\n\n"
    intro = (
        "This is an extra review step from **CLōD** (via **hole_in_one**): it receives "
        "Greptile’s feedback and the PR’s **unified diffs**, then decides if anything "
        "**merge-blocking** still stands out compared with what Greptile reported.\n\n"
        f"- **Model:** `{clod_model}`\n"
        f"- **Pull request:** #{pull_number} — {pr_url}\n\n"
    )
    greptile_plain = _greptile_plain_excerpt(greptile_raw)
    context = (
        "### What CLōD saw\n\n"
        f"- {_patch_bundle_stats(patch_bundle)}\n"
        "- Greptile summary excerpt (HTML stripped):\n\n"
        "<details>\n<summary>Greptile excerpt</summary>\n\n"
        f"{greptile_plain}\n\n"
        "</details>\n\n"
    )
    if validator_exc is not None:
        return (
            head
            + intro
            + context
            + "### Result\n\n"
            + "Verdict: UNKNOWN\n\n"
            + f"The validator request failed before a model verdict:\n\n```\n{validator_exc}\n```"
        )
    tail = vbody.strip()
    verdict_block = (
        "### Verdict\n\n"
        f"Verdict: {verdict}\n\n"
        + ("### Model response\n\n" + tail if tail else f"VERDICT: {verdict}")
    )
    return head + intro + context + verdict_block


def _greptile_indicates_no_action_needed(text: str, *, extra_substrings: list[str]) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    lower = stripped.lower()
    for s in extra_substrings:
        if s and s.lower() in lower:
            return True
    # Avoid matching "Not safe to merge" (Greptile often uses both phrases).
    if re.search(r"\bsafe\s+to\s+merge\b", stripped, re.I) and not re.search(
        r"\bnot\s+safe\s+to\s+merge\b",
        stripped,
        re.I,
    ):
        return True
    if re.search(r"\bno\s+(critical\s+)?issues\s+(were\s+)?found\b", stripped, re.I):
        return True
    if "no files require special attention" in lower and re.search(r"\b5\s*/\s*5\b", stripped):
        return True
    return False


def _branch_name_from_cursor_agent(agent: dict[str, object]) -> str | None:
    v = agent.get("branchName")
    if isinstance(v, str) and v.strip():
        return v.strip()
    repos = agent.get("repos")
    if isinstance(repos, list):
        for entry in repos:
            if isinstance(entry, dict):
                bn = entry.get("branchName")
                if isinstance(bn, str) and bn.strip():
                    return bn.strip()
    return None


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None or v == "":
        raise SystemExit(f"Missing env {name}")
    return v


def _comma_list(name: str, default: str) -> list[str]:
    return [s.strip() for s in os.environ.get(name, default).split(",") if s.strip()]


@dataclass(frozen=True)
class ClodCompressConfig:
    api_key: str
    base_url: str
    model: str
    timeout_s: float
    max_input_chars: int
    max_completion_tokens: int


def _maybe_clod_compress(raw: str, cfg: ClodCompressConfig | None) -> str:
    """Optional CLōD rewrite for fix-agent prompts; Greptile skip heuristics use raw text only."""
    if cfg is None or not raw.strip():
        return raw
    try:
        out = compress_greptile_feedback_for_fix(
            raw,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model=cfg.model,
            timeout_s=cfg.timeout_s,
            max_input_chars=cfg.max_input_chars,
            max_completion_tokens=cfg.max_completion_tokens,
        )
    except Exception as exc:
        print(
            f"Warning: CLōD feedback compression failed; using raw Greptile text. ({exc})",
            file=sys.stderr,
        )
        return raw
    print(
        f"CLōD: summarized Greptile feedback for fix prompt ({len(raw)} → {len(out)} chars).",
        file=sys.stderr,
    )
    return out


@dataclass(frozen=True)
class GreptileWaitResult:
    text: str
    timed_out: bool
    clean_success_no_text: bool


def _wait_greptile(
    gh: httpx.Client,
    repo: Repo,
    pull_number: int,
    *,
    bot_substrings: list[str],
    check_substrings: list[str],
    poll_interval_s: float,
    poll_budget_s: float,
    continuous: bool = False,
) -> GreptileWaitResult:
    started = time.monotonic()
    feedback_text = ""
    while time.monotonic() - started < poll_budget_s:
        head_sha, _ = get_pr_head(gh, repo, pull_number)
        signal = poll_greptile_signal(
            gh,
            repo,
            pull_number,
            head_sha,
            bot_substrings=bot_substrings,
            check_name_substrings=check_substrings,
        )
        if signal.done:
            if signal.summary_parts:
                feedback_text = "\n\n---\n\n".join(signal.summary_parts)
                return GreptileWaitResult(
                    text=feedback_text,
                    timed_out=False,
                    clean_success_no_text=False,
                )
            if signal.check_conclusion == "success":
                print("Greptile check completed with success and no captured text; nothing to fix.")
                if continuous:
                    return GreptileWaitResult(text="", timed_out=False, clean_success_no_text=True)
                sys.exit(0)
            if signal.check_conclusion and signal.check_conclusion != "success":
                feedback_text = (
                    f"Greptile check completed with conclusion: {signal.check_conclusion}.\n"
                    "The GitHub PR checks UI may contain details not exposed via API.\n"
                    "Address any reported issues until the Greptile check is green."
                )
                return GreptileWaitResult(
                    text=feedback_text,
                    timed_out=False,
                    clean_success_no_text=False,
                )
        elapsed = int(time.monotonic() - started)
        print(
            f"[wait] No Greptile signal yet ({elapsed}s / {int(poll_budget_s)}s)",
        )
        time.sleep(poll_interval_s)
    return GreptileWaitResult(
        text=feedback_text,
        timed_out=True,
        clean_success_no_text=False,
    )


def _normalize_workstreams(items: list[str], *, max_items: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = re.sub(r"\s+", " ", raw).strip(" -\t\r\n")
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def _heuristic_workstream_plan(task_prompt: str, *, max_items: int) -> list[str]:
    cleaned = re.sub(r"\s+", " ", task_prompt).strip()
    if len(cleaned) > 220:
        cleaned = cleaned[:220].rstrip() + "…"
    candidates = [
        (
            f"Implement core logic and data flow for: {cleaned}. Keep the scope in backend/core "
            "modules and add focused tests when available."
        ),
        (
            f"Integrate UI/API wiring for: {cleaned}. Reuse existing interfaces and keep contracts "
            "compatible with the core logic changes."
        ),
        (
            f"Harden and document: {cleaned}. Run lint/tests where available, fix edge-case regressions, "
            "and update README or usage docs."
        ),
    ]
    return _normalize_workstreams(candidates, max_items=max_items)


def _plan_subagent_workstreams(
    task_prompt: str,
    *,
    max_items: int,
    clod_key: str,
    clod_base_url: str,
    clod_model: str,
    clod_timeout_s: float,
    clod_max_completion_tokens: int,
    use_clod: bool,
) -> list[str]:
    if max_items <= 0:
        return []

    if use_clod and clod_key:
        try:
            planned = plan_pr_workstreams(
                task_prompt,
                api_key=clod_key,
                base_url=clod_base_url,
                model=clod_model,
                max_workstreams=max_items,
                timeout_s=clod_timeout_s,
                max_completion_tokens=clod_max_completion_tokens,
            )
            normalized = _normalize_workstreams(planned, max_items=max_items)
            if len(normalized) >= 2:
                return normalized
            print(
                "CLōD workstream planner returned fewer than 2 items; using heuristic fallback.",
                file=sys.stderr,
            )
        except Exception as exc:
            print(
                f"Warning: CLōD workstream planner failed ({exc}); using heuristic fallback.",
                file=sys.stderr,
            )

    return _heuristic_workstream_plan(task_prompt, max_items=max_items)


def _run_workstream_subagents(
    api_key: str,
    *,
    parent_agent_id: str,
    pr_url: str,
    pull_number: int,
    pr_head_ref: str | None,
    workstreams: list[str],
    max_workers: int,
    model_id: str | None,
    stop_mode: str,
    dashboard: DashboardStore | None = None,
) -> None:
    total = len(workstreams)
    if total <= 0:
        return

    def _mark_started(agent_id: str, idx: int, item: str) -> None:
        if dashboard is None:
            return
        attached = dashboard.add_or_update_child_agent(
            parent_id=parent_agent_id,
            agent_id=agent_id,
            role=f"workstream-{idx + 1}",
            task=item,
            kind=AgentKind.IMPLEMENTATION,
            status=AgentStatus.RUNNING,
            progress=8,
        )
        if not attached:
            dashboard.add_or_update_root_agent(
                agent_id=agent_id,
                role=f"workstream-{idx + 1}",
                task=item,
                kind=AgentKind.IMPLEMENTATION,
                status=AgentStatus.RUNNING,
                progress=8,
            )
        dashboard.record_activity(
            "impl",
            f"{agent_id} started workstream {idx + 1}/{total} on PR #{pull_number}",
        )

    def _mark_finished(agent_id: str, idx: int, *, success: bool, note: str) -> None:
        if dashboard is None:
            return
        attached = dashboard.finish_child_agent(
            parent_id=parent_agent_id,
            agent_id=agent_id,
            success=success,
            note=note,
        )
        if not attached:
            dashboard.finish_agent(
                agent_id,
                success=success,
                note=note,
            )
        dashboard.record_activity(
            "impl",
            f"{agent_id} {'completed' if success else 'failed'} workstream {idx + 1}/{total}",
        )

    def one(idx: int, workstream_task: str) -> None:
        prompt = "\n".join(
            [
                f"You are subagent {idx + 1}/{total} on PR #{pull_number} ({pr_url}).",
                "Only execute your assigned workstream; avoid unrelated refactors.",
                "Push commits to the existing PR branch; do not open another PR.",
                "Leave clear commit messages describing the slice you changed.",
                "",
                "Assigned workstream:",
                workstream_task,
            ]
        )
        created = create_agent_on_pr(
            api_key,
            prompt_text=prompt,
            pr_url=pr_url,
            auto_create_pr=False,
            auto_generate_branch=False,
            model_id=model_id,
            pr_head_ref=pr_head_ref,
        )
        agent_id = created["agent"]["id"]
        run_id = created["run"]["id"]
        print(f"Workstream subagent ({idx + 1}/{total}): {agent_id}")
        _mark_started(agent_id, idx, workstream_task)

        try:
            run = wait_for_terminal_run(api_key, agent_id, run_id)
            if str(run.get("status") or "") != "FINISHED":
                _mark_finished(
                    agent_id,
                    idx,
                    success=False,
                    note=f"{agent_id} failed workstream {idx + 1}/{total}",
                )
                raise RuntimeError(
                    f"Workstream {idx + 1}/{total} failed for agent {agent_id}: {run}",
                )
            _mark_finished(
                agent_id,
                idx,
                success=True,
                note=f"{agent_id} completed workstream {idx + 1}/{total}",
            )
        finally:
            try:
                stop_agent(api_key, agent_id, stop_mode)
                print(f"Stopped workstream subagent ({stop_mode}): {agent_id}")
            except Exception as exc:
                print(
                    f"Warning: could not stop workstream subagent {agent_id}: {exc}",
                    file=sys.stderr,
                )

    if max_workers <= 1 or total <= 1:
        for i, item in enumerate(workstreams):
            one(i, item)
        return

    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, total)) as ex:
        futures = [ex.submit(one, i, item) for i, item in enumerate(workstreams)]
        for fut in as_completed(futures):
            try:
                fut.result()
            except BaseException as exc:
                errors.append(exc)
    if errors:
        raise RuntimeError(
            f"{len(errors)} workstream subagent(s) failed; first error: {errors[0]}",
        )


def _run_single_fix_agent(
    api_key: str,
    *,
    pr_url: str,
    pull_number: int,
    pr_head_ref: str | None,
    feedback_text: str,
    model_id: str | None,
    stop_mode: str,
    dashboard: DashboardStore | None = None,
) -> None:
    fix_prompt = "\n".join(
        [
            "You are fixing this open PR based on third-party code review (Greptile).",
            "Apply minimal, correct changes. Run tests or linters if the repo has them.",
            "Push commits to the existing PR branch; do not open a second PR unless absolutely necessary.",
            "",
            "Review feedback:",
            feedback_text,
        ]
    )
    created = create_agent_on_pr(
        api_key,
        prompt_text=fix_prompt,
        pr_url=pr_url,
        auto_create_pr=False,
        auto_generate_branch=False,
        model_id=model_id,
        pr_head_ref=pr_head_ref,
    )
    fix_agent_id = created["agent"]["id"]
    run_id = created["run"]["id"]
    print(f"Greptile fix agent: {fix_agent_id}")
    if dashboard is not None:
        dashboard.add_or_update_root_agent(
            agent_id=fix_agent_id,
            role="fixer",
            task=f"Resolve Greptile feedback for PR #{pull_number}",
            kind=AgentKind.FIX,
            status=AgentStatus.RUNNING,
            progress=5,
        )
        dashboard.record_activity("fix-start", f"{fix_agent_id} started for PR #{pull_number}")
    run = wait_for_terminal_run(api_key, fix_agent_id, run_id)
    if run.get("status") != "FINISHED":
        print("Fix run failed:", run, file=sys.stderr)
        if dashboard is not None:
            dashboard.finish_agent(
                fix_agent_id,
                success=False,
                note=f"{fix_agent_id} failed during fix run",
            )
        sys.exit(2)
    print("Fix run finished.")
    if dashboard is not None:
        dashboard.finish_agent(
            fix_agent_id,
            success=True,
            note=f"{fix_agent_id} completed fix run",
        )
    stop_agent(api_key, fix_agent_id, stop_mode)
    print(f"Stopped fix agent ({stop_mode}): {fix_agent_id}")
    if dashboard is not None:
        dashboard.record_activity("fix-stop", f"{fix_agent_id} stopped ({stop_mode})")


def _parallel_fix_agents(
    api_key: str,
    *,
    pr_url: str,
    pull_number: int,
    pr_head_ref: str | None,
    chunks: list[str],
    max_workers: int,
    model_id: str | None,
    stop_mode: str,
    dashboard: DashboardStore | None = None,
) -> None:
    def one(idx: int, chunk: str) -> None:
        prompt = "\n".join(
            [
                f"Fix slice {idx + 1}/{len(chunks)} for open PR #{pull_number} ({pr_url}).",
                "Only address this slice; keep changes small.",
                "",
                chunk,
            ]
        )
        created = create_agent_on_pr(
            api_key,
            prompt_text=prompt,
            pr_url=pr_url,
            auto_create_pr=False,
            auto_generate_branch=False,
            model_id=model_id,
            pr_head_ref=pr_head_ref,
        )
        agent_id = created["agent"]["id"]
        run_id = created["run"]["id"]
        print(f"Greptile fix agent (slice {idx + 1}): {agent_id}")
        if dashboard is not None:
            dashboard.add_or_update_root_agent(
                agent_id=agent_id,
                role="fixer",
                task=f"Fix slice {idx + 1}/{len(chunks)} for PR #{pull_number}",
                kind=AgentKind.FIX,
                status=AgentStatus.RUNNING,
                progress=5,
            )
            dashboard.record_activity(
                "fix-start",
                f"{agent_id} started slice {idx + 1}/{len(chunks)}",
            )
        run = wait_for_terminal_run(api_key, agent_id, run_id)
        if run.get("status") != "FINISHED":
            if dashboard is not None:
                dashboard.finish_agent(
                    agent_id,
                    success=False,
                    note=f"{agent_id} failed fix slice {idx + 1}",
                )
            raise RuntimeError(f"Fix slice {idx} failed: {run}")
        if dashboard is not None:
            dashboard.finish_agent(
                agent_id,
                success=True,
                note=f"{agent_id} completed fix slice {idx + 1}",
            )
        stop_agent(api_key, agent_id, stop_mode)
        print(f"Stopped fix agent ({stop_mode}): {agent_id}")
        if dashboard is not None:
            dashboard.record_activity("fix-stop", f"{agent_id} stopped ({stop_mode})")

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(one, i, c) for i, c in enumerate(chunks)]
        for f in as_completed(futures):
            f.result()
    print("Parallel fix runs finished (inspect PR for conflicts).")


def _rest_merge_when_mergeable(
    gh: httpx.Client,
    repo: Repo,
    pull_number: int,
    *,
    merge_method: str,
    merge_poll_budget_s: float,
    merge_poll_interval_s: float,
    env_label: str,
) -> bool:
    """REST-merge when GitHub reports mergeable. Returns False if merge failed or timed out."""
    print(
        f"{env_label}={merge_method}: polling until mergeable_state=clean "
        "(or already merged), then REST merge…",
    )
    try:
        merged_ok = wait_pull_mergeable_clean(
            gh,
            repo,
            pull_number,
            poll_interval_s=merge_poll_interval_s,
            budget_s=merge_poll_budget_s,
        )
        if merged_ok:
            if pull_request_merged(gh, repo, pull_number):
                print("PR already merged.")
                return True
            try:
                merge_pull_request_rest(gh, repo, pull_number, merge_method)
                print("Merged PR via GitHub REST API.")
                return True
            except Exception as exc:
                print(f"REST merge failed: {exc}", file=sys.stderr)
                return False

        print(
            "PR did not become mergeable in time, or has conflicts / is blocked. "
            "Fix checks, reviews, or conflicts and merge manually.",
            file=sys.stderr,
        )
        return False
    except KeyboardInterrupt:
        print("\norchestrate: interrupted during REST merge wait.", file=sys.stderr)
        raise SystemExit(130) from None


def main() -> None:
    prs = argparse.ArgumentParser(
        description="Hole in One: Cursor builder + Greptile + optional fix rounds + continuous mode. "
        "Use --plan (and CLOD_API_KEY) to split one goal into sequential builder tasks via CLōD.",
    )
    mx = prs.add_mutually_exclusive_group()
    mx.add_argument(
        "-p",
        "--prompt",
        metavar="TEXT",
        help="Instructions for the builder cloud agent (overrides BUILDER_PROMPT in .env)",
    )
    mx.add_argument(
        "-i",
        "--interactive-prompt",
        action="store_true",
        help="Prompt on the terminal for the builder task (overrides BUILDER_PROMPT)",
    )
    prs.add_argument(
        "--plan",
        action="store_true",
        help="Use CLōD (CLOD_API_KEY) to split --prompt / BUILDER_PROMPT into ordered builder tasks "
        "(sequential PRs). Also enable with CLOD_PLANNER=1. Not with --continuous.",
    )
    prs.add_argument(
        "--continuous",
        action="store_true",
        help="After each PR run, wait for merge then start another builder (env CONTINUOUS_BUILDS=1)",
    )
    args = prs.parse_args()

    if args.interactive_prompt:
        print("Task for the builder cloud agent (one line; Ctrl+C to cancel):")
        try:
            base_goal = input("> ").strip()
        except EOFError:
            raise SystemExit("No prompt entered.") from None
        if not base_goal:
            raise SystemExit("Empty prompt.")
    elif args.prompt is not None:
        base_goal = args.prompt.strip()
        if not base_goal:
            raise SystemExit("Empty --prompt.")
    else:
        base_goal = os.environ.get("BUILDER_PROMPT", DEFAULT_BUILDER_PROMPT)

    api_key = _env("CURSOR_API_KEY")
    gh_token = _env("GITHUB_TOKEN")
    repo_full = _env("GITHUB_REPO")
    repo = parse_repo(repo_full)
    repo_url = repo_https_url(repo)

    poll_interval_s = float(os.environ.get("GREPTILE_POLL_INTERVAL_S", "20"))
    poll_budget_s = float(os.environ.get("GREPTILE_POLL_BUDGET_S", "900"))
    max_fix_rounds = int(os.environ.get("MAX_FIX_ROUNDS", "3"))
    max_parallel_fixers = min(5, max(1, int(os.environ.get("MAX_PARALLEL_FIXERS", "1"))))
    max_feedback_chunks = int(os.environ.get("MAX_FEEDBACK_CHUNKS", "6"))
    fix_round_cooldown_s = float(os.environ.get("FIX_ROUND_COOLDOWN_S", "45"))
    stop_mode = os.environ.get("CURSOR_STOP_AGENT", "archive").strip()

    bot_substrings = _comma_list("GREPTILE_BOT_SUBSTRINGS", "greptile")
    check_substrings = _comma_list("GREPTILE_CHECK_SUBSTRINGS", "greptile")
    greptile_clean_substrings = _comma_list("GREPTILE_CLEAN_SUBSTRINGS", "")
    explicit_branch = os.environ.get("GITHUB_DEFAULT_BRANCH", "").strip()
    model_id = os.environ.get("CURSOR_MODEL") or None

    refs_first = os.environ.get("CURSOR_STARTING_REF_REFS_FIRST", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    try_commit_sha = os.environ.get(
        "CURSOR_TRY_COMMIT_SHA_FOR_STARTING_REF",
        "",
    ).strip().lower() in ("1", "true", "yes")

    continuous = args.continuous or os.environ.get("CONTINUOUS_BUILDS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    continuous_merge_wait_s = float(os.environ.get("CONTINUOUS_MERGE_WAIT_S", "7200"))
    continuous_poll_s = float(os.environ.get("CONTINUOUS_POLL_INTERVAL_S", "15"))
    continuous_sleep_s = float(os.environ.get("CONTINUOUS_SLEEP_BETWEEN_S", "5"))

    github_auto_merge_raw = os.environ.get("GITHUB_AUTO_MERGE", "").strip().lower()
    github_auto_merge: str | None = github_auto_merge_raw or None
    if github_auto_merge and github_auto_merge not in ("merge", "squash", "rebase"):
        raise SystemExit(
            "GITHUB_AUTO_MERGE must be merge, squash, or rebase (or unset).",
        )

    github_merge_immediate_raw = os.environ.get("GITHUB_MERGE_IMMEDIATE", "").strip().lower()
    github_merge_immediate: str | None = github_merge_immediate_raw or None
    if github_merge_immediate and github_merge_immediate not in ("merge", "squash", "rebase"):
        raise SystemExit(
            "GITHUB_MERGE_IMMEDIATE must be merge, squash, or rebase (or unset).",
        )

    github_merge_on_clean_raw = os.environ.get(
        "GITHUB_MERGE_ON_GREPTILE_CLEAN",
        "",
    ).strip().lower()
    github_merge_on_clean: str | None = github_merge_on_clean_raw or None
    if github_merge_on_clean and github_merge_on_clean not in ("merge", "squash", "rebase"):
        raise SystemExit(
            "GITHUB_MERGE_ON_GREPTILE_CLEAN must be merge, squash, or rebase (or unset).",
        )

    merge_poll_budget_s = float(os.environ.get("GITHUB_MERGE_POLL_BUDGET_S", "7200"))
    merge_poll_interval_s = float(os.environ.get("GITHUB_MERGE_POLL_INTERVAL_S", "15"))

    def _env_truthy(name: str) -> bool:
        return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")

    dashboard_enabled = os.environ.get("DASHBOARD_API_ENABLED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    dashboard_host = os.environ.get("DASHBOARD_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    dashboard_port = int(os.environ.get("DASHBOARD_API_PORT", "8787"))
    dashboard_cors_origins = [
        s.strip()
        for s in os.environ.get("DASHBOARD_API_CORS_ORIGINS", "*").split(",")
        if s.strip()
    ]

    clod_key = os.environ.get("CLOD_API_KEY", "").strip()
    _clod_base_raw = os.environ.get("CLOD_BASE_URL", "").strip().rstrip("/")
    clod_shared_base = _clod_base_raw or DEFAULT_CLOD_BASE_URL
    _clod_model_raw = os.environ.get("CLOD_MODEL", "").strip()
    clod_shared_model = _clod_model_raw or DEFAULT_CLOD_MODEL

    _compress_raw = os.environ.get("CLOD_COMPRESS_FOR_FIX", "1").strip().lower()
    clod_compress_for_fix = _compress_raw not in ("0", "false", "no")

    workstream_subagents_enabled = os.environ.get(
        "WORKSTREAM_SUBAGENTS_ENABLED",
        "1",
    ).strip().lower() not in ("0", "false", "no")
    max_workstream_subagents = (
        min(8, max(1, int(os.environ.get("MAX_WORKSTREAM_SUBAGENTS", "3"))))
        if workstream_subagents_enabled
        else 0
    )
    max_parallel_workstreams = min(5, max(1, int(os.environ.get("MAX_PARALLEL_WORKSTREAMS", "2"))))
    workstream_subagents_strict = _env_truthy("WORKSTREAM_SUBAGENTS_STRICT")
    workstream_use_clod_planner = os.environ.get(
        "CLOD_WORKSTREAM_PLANNER",
        "1",
    ).strip().lower() not in ("0", "false", "no")
    workstream_clod_timeout_s = float(os.environ.get("CLOD_WORKSTREAM_TIMEOUT_S", "90"))
    workstream_clod_max_completion_tokens = int(
        os.environ.get("CLOD_WORKSTREAM_MAX_COMPLETION_TOKENS", "1536"),
    )

    clod_cfg: ClodCompressConfig | None = None
    if clod_key and clod_compress_for_fix:
        clod_cfg = ClodCompressConfig(
            api_key=clod_key,
            base_url=clod_shared_base,
            model=clod_shared_model,
            timeout_s=float(os.environ.get("CLOD_TIMEOUT_S", "60")),
            max_input_chars=int(os.environ.get("CLOD_MAX_INPUT_CHARS", "24000")),
            max_completion_tokens=int(os.environ.get("CLOD_MAX_COMPLETION_TOKENS", "2048")),
        )

    clod_validator_enabled = _env_truthy("CLOD_VALIDATOR")
    clod_validator_strict = _env_truthy("CLOD_VALIDATOR_STRICT")
    clod_validator_max_patch_chars = int(os.environ.get("CLOD_VALIDATOR_MAX_PATCH_CHARS", "28000"))
    clod_validator_max_greptile_chars = int(
        os.environ.get("CLOD_VALIDATOR_MAX_GREPTILE_CHARS", "12000"),
    )
    clod_validator_timeout_s = float(os.environ.get("CLOD_VALIDATOR_TIMEOUT_S", "120"))
    clod_validator_max_completion_tokens = int(
        os.environ.get("CLOD_VALIDATOR_MAX_COMPLETION_TOKENS", "1536"),
    )
    clod_validator_append_pr = _env_truthy("CLOD_VALIDATOR_APPEND_PR_BODY")
    clod_validator_comment_pr = _env_truthy("CLOD_VALIDATOR_COMMENT_PR")

    if clod_validator_enabled and not clod_key:
        raise SystemExit("CLOD_VALIDATOR=1 requires CLOD_API_KEY.")

    planner_enabled = args.plan or (
        os.environ.get("CLOD_PLANNER", "").strip().lower() in ("1", "true", "yes")
    )
    if planner_enabled:
        if not clod_key:
            raise SystemExit("CLOD_PLANNER/--plan requires CLOD_API_KEY.")
        planner_max = max(1, min(12, int(os.environ.get("CLOD_PLANNER_MAX_TASKS", "6"))))
        planner_timeout_s = float(os.environ.get("CLOD_PLANNER_TIMEOUT_S", "120"))
        planner_tokens = int(os.environ.get("CLOD_PLANNER_MAX_COMPLETION_TOKENS", "2048"))
        print("\n=== CLōD planner (split goal into sequential builders) ===", flush=True)
        try:
            builder_prompts = plan_builder_tasks(
                base_goal,
                api_key=clod_key,
                base_url=clod_shared_base,
                model=clod_shared_model,
                max_tasks=planner_max,
                timeout_s=planner_timeout_s,
                max_completion_tokens=planner_tokens,
            )
            print(f"Planner produced {len(builder_prompts)} task(s).", flush=True)
            for i, t in enumerate(builder_prompts):
                preview = t.replace("\n", " ").strip()
                if len(preview) > 200:
                    preview = preview[:200] + "…"
                print(f"  {i + 1}. {preview}", flush=True)
        except Exception as exc:
            print(
                f"Warning: CLōD planner failed ({exc}); using single builder prompt.",
                file=sys.stderr,
            )
            builder_prompts = [base_goal]
    else:
        builder_prompts = [base_goal]

    if len(builder_prompts) > 1 and continuous:
        raise SystemExit(
            "Multiple planner tasks cannot be combined with --continuous or CONTINUOUS_BUILDS=1. "
            "Disable CLOD_PLANNER/--plan for continuous mode, or use a single-task goal.",
        )

    queue_auto_merge = bool(github_auto_merge) and not github_merge_immediate
    if github_auto_merge and github_merge_immediate:
        print(
            "Both GITHUB_AUTO_MERGE and GITHUB_MERGE_IMMEDIATE are set; "
            "using immediate REST merge only (skipping GraphQL auto-merge).",
            file=sys.stderr,
        )

    extra_banner = []
    if queue_auto_merge:
        extra_banner.append(f"auto-merge={github_auto_merge}")
    if github_merge_immediate:
        extra_banner.append(f"merge-immediate={github_merge_immediate}")
    if github_merge_on_clean:
        extra_banner.append(f"merge-on-greptile-clean={github_merge_on_clean}")
    if clod_cfg:
        extra_banner.append(f"clod=model:{clod_cfg.model}")
    if clod_validator_enabled:
        extra_banner.append(f"clod-validator={'strict' if clod_validator_strict else 'warn'}")
        if clod_validator_append_pr:
            extra_banner.append("clod-pr-append")
        if clod_validator_comment_pr:
            extra_banner.append("clod-pr-comment")
    if planner_enabled:
        extra_banner.append("clod-planner")
    if workstream_subagents_enabled and max_workstream_subagents > 0:
        extra_banner.append(
            f"workstreams={max_workstream_subagents} (parallel={max_parallel_workstreams})",
        )
        if workstream_use_clod_planner and clod_key:
            extra_banner.append("workstream-planner=clod")
        else:
            extra_banner.append("workstream-planner=heuristic")
        if workstream_subagents_strict:
            extra_banner.append("workstream-strict")
    else:
        extra_banner.append("workstreams=off")

    dashboard_store: DashboardStore | None = None
    dashboard_api: DashboardApiRuntime | None = None
    if dashboard_enabled:
        dashboard_store = DashboardStore(project_name="HOLE IN GOLF")
        dashboard_store.set_controls_hint(
            f"live mode | backend={dashboard_host}:{dashboard_port} | tab=agent-grid/activity/graph",
        )
        dashboard_store.record_activity(
            "config",
            f"repo={repo_full} continuous={continuous} max_fix_rounds={max_fix_rounds}",
        )
        try:
            dashboard_api = start_dashboard_api_server(
                dashboard_store,
                host=dashboard_host,
                port=dashboard_port,
                cors_origins=dashboard_cors_origins,
            )
            extra_banner.append(f"dashboard-api=http://{dashboard_host}:{dashboard_port}")
        except Exception as exc:
            dashboard_api = None
            dashboard_store.record_activity("failed", f"dashboard API start failed: {exc}")
            print(f"Warning: could not start dashboard API: {exc}", file=sys.stderr)

    print(
        f"Repo {repo_full} | builder_tasks={len(builder_prompts)} | new agent per Greptile fix | "
        f"max_parallel_fixers={max_parallel_fixers} | stop={stop_mode}"
        f" | continuous={continuous}"
        + (f" | {' | '.join(extra_banner)}" if extra_banner else ""),
    )

    def _starting_ref_retryable(exc: CursorCloudError) -> bool:
        if not exc.body:
            return False
        b = exc.body.lower()
        if exc.status_code == 400:
            return (
                "verify existence" in b
                or "failed to verify" in b
                or "does not exist in repository" in b
            )
        if exc.status_code == 404:
            return (
                "failed to fetch branch" in b
                or "get-a-reference" in b
                or ("failed to fetch" in b and "ref" in b)
            )
        return False

    try:
        with github_client(gh_token) as gh:
            if explicit_branch:
                if not branch_exists(gh, repo, explicit_branch):
                    actual = get_default_branch(gh, repo)
                    raise SystemExit(
                        f"GITHUB_DEFAULT_BRANCH={explicit_branch!r} does not exist on {repo_full}. "
                        f"GitHub default branch is {actual!r}. Update .env or remove GITHUB_DEFAULT_BRANCH "
                        "to use the repo default automatically.",
                    )
                default_branch = explicit_branch
            else:
                default_branch = get_default_branch(gh, repo)
                print(f"Starting ref (GitHub default branch): {default_branch}")

            if not branch_exists(gh, repo, default_branch):
                raise SystemExit(
                    f"Branch {default_branch!r} has no commits on {repo_full} yet (or the ref does not exist). "
                    "Push at least one commit, or set GITHUB_DEFAULT_BRANCH to an existing branch.",
                )

            for _task_i, builder_prompt in enumerate(builder_prompts):
                if len(builder_prompts) > 1:
                    print(f"\n=== Builder task {_task_i + 1}/{len(builder_prompts)} ===", flush=True)
                full_builder_prompt = (
                    builder_prompt + "\n\nOpen a normal (non-draft) PR with a clear title and description."
                )
                cycle = 0
                while True:
                    cycle += 1
                    if continuous:
                        print(f"\n=== Continuous build cycle {cycle} ===")
    
                    if continuous and cycle > 1 and not explicit_branch:
                        default_branch = get_default_branch(gh, repo)
                    if dashboard_store is not None:
                        dashboard_store.set_iteration(cycle)
                        dashboard_store.record_activity(
                            "cycle",
                            f"cycle {cycle} started on {default_branch}",
                        )
    
                    refs_heads = f"refs/heads/{default_branch}"
                    pair = [("refs_heads", refs_heads), ("branch_name", default_branch)]
                    starting_attempts: list[tuple[str, str]] = pair if refs_first else [pair[1], pair[0]]
                    if refs_first and cycle == 1:
                        print(
                            "CURSOR_STARTING_REF_REFS_FIRST=1 — trying refs/heads before plain branch name.",
                        )
                    if try_commit_sha:
                        starting_attempts.append(
                            ("commit_sha", get_branch_tip_sha(gh, repo, default_branch)),
                        )
    
                    seen_refs: set[str] = set()
                    created: dict | None = None
                    last_exc: CursorCloudError | None = None
                    for label, start_ref in starting_attempts:
                        if start_ref in seen_refs:
                            continue
                        seen_refs.add(start_ref)
                        preview = (
                            f"{start_ref[:12]}…{start_ref[-6:]}" if len(start_ref) > 44 else start_ref
                        )
                        print(f"create_agent startingRef ({label}): {preview}")
                        try:
                            created = create_agent(
                                api_key,
                                prompt_text=full_builder_prompt,
                                repo_url=repo_url,
                                starting_ref=start_ref,
                                auto_create_pr=True,
                                skip_reviewer_request=True,
                                model_id=model_id,
                            )
                            break
                        except CursorCloudError as exc:
                            last_exc = exc
                            if not _starting_ref_retryable(exc):
                                raise
                            snippet = (exc.body or "")[:280].replace("\n", " ")
                            print(
                                f"  → Cursor rejected this startingRef; retrying. ({snippet})",
                                file=sys.stderr,
                            )
        
                    if created is None:
                        print(
                            "\nAll startingRef attempts failed. "
                            "If Cursor lists your repo under Integrations, contact Cursor support.\n",
                            file=sys.stderr,
                        )
                        if last_exc:
                            raise last_exc
                        raise RuntimeError("create_agent failed without exception")
        
                    builder_id = created["agent"]["id"]
                    run_id = created["run"]["id"]
                    print(f"Builder agent: {builder_id}")
                    if dashboard_store is not None:
                        dashboard_store.add_or_update_root_agent(
                            agent_id=builder_id,
                            role="builder",
                            task="Open PR from builder task",
                            kind=AgentKind.BUILDER,
                            status=AgentStatus.RUNNING,
                            progress=8,
                        )
                        dashboard_store.record_activity(
                            "builder",
                            f"{builder_id} started on {default_branch}",
                        )
    
                    initial = wait_for_terminal_run(api_key, builder_id, run_id)
                    if initial.get("status") != "FINISHED":
                        print("Builder run failed:", initial, file=sys.stderr)
                        if dashboard_store is not None:
                            dashboard_store.finish_agent(
                                builder_id,
                                success=False,
                                note=f"{builder_id} failed builder run",
                            )
                        try:
                            stop_agent(api_key, builder_id, stop_mode)
                        except Exception as exc:
                            print(f"Warning: could not stop builder agent: {exc}", file=sys.stderr)
                        sys.exit(2)
                    if dashboard_store is not None:
                        dashboard_store.finish_agent(
                            builder_id,
                            success=True,
                            note=f"{builder_id} finished builder run",
                        )
        
                    pr_url: str | None = None
                    pull_number: int | None = None
                    try:
                        agent_meta = get_agent(api_key, builder_id)
                        branch_name = _branch_name_from_cursor_agent(agent_meta)
                        if not branch_name:
                            for attempt in range(10):
                                time.sleep(3.0)
                                agent_meta = get_agent(api_key, builder_id)
                                branch_name = _branch_name_from_cursor_agent(agent_meta)
                                if branch_name:
                                    print(f"Resolved branchName from Cursor API (poll {attempt + 2}).")
                                    break
        
                        pr_data = None
                        if branch_name:
                            pr_data = find_open_pr_for_branch(gh, repo, branch_name)
        
                        if not pr_data:
                            ref_prefix = os.environ.get("CURSOR_PR_HEAD_PREFIX", "cursor/").strip() or "cursor/"
                            guess = find_latest_open_pr_head_ref_prefix(gh, repo, ref_prefix=ref_prefix)
                            if guess:
                                pr_data = guess
                                head = guess.get("head") or {}
                                branch_name = str(head.get("ref") or branch_name or "")
                                print(
                                    "No usable branchName on agent; using newest open PR whose head ref starts with "
                                    f"{ref_prefix!r} → #{guess.get('number')} ({branch_name}). "
                                    "Confirm this is the builder PR if several exist.",
                                    file=sys.stderr,
                                )
        
                        if not pr_data:
                            print(
                                "Could not resolve builder PR: Cursor agent has no usable branchName "
                                "and no matching open PR.",
                                file=sys.stderr,
                            )
                            print(
                                f"Agent JSON (truncated):\n{json.dumps(agent_meta, indent=2)[:3500]}",
                                file=sys.stderr,
                            )
                            sys.exit(2)
        
                        pr_url = pr_data.get("html_url")
                        pull_number = pr_data.get("number") or pull_number_from_pr_url(pr_url)
                        if not pull_number:
                            print("Could not determine PR number.", file=sys.stderr)
                            sys.exit(2)
    
                        print("PR:", pr_url)
                        if dashboard_store is not None:
                            dashboard_store.record_activity("pr", f"opened PR #{pull_number}: {pr_url}")
                    finally:
                        try:
                            stop_agent(api_key, builder_id, stop_mode)
                            print(f"Stopped builder agent ({stop_mode}): {builder_id}")
                            if dashboard_store is not None:
                                dashboard_store.record_activity(
                                    "builder",
                                    f"{builder_id} stopped ({stop_mode})",
                                )
                        except Exception as exc:
                            print(f"Warning: could not stop builder agent: {exc}", file=sys.stderr)
        
                    assert pr_url is not None and pull_number is not None
                    _, pr_head_ref_for_fix = get_pr_head(gh, repo, pull_number)

                    if workstream_subagents_enabled and max_workstream_subagents > 0:
                        workstreams = _plan_subagent_workstreams(
                            builder_prompt,
                            max_items=max_workstream_subagents,
                            clod_key=clod_key,
                            clod_base_url=clod_shared_base,
                            clod_model=clod_shared_model,
                            clod_timeout_s=workstream_clod_timeout_s,
                            clod_max_completion_tokens=workstream_clod_max_completion_tokens,
                            use_clod=workstream_use_clod_planner,
                        )
                        if workstreams:
                            print(
                                f"Planned {len(workstreams)} workstream subagent task(s) for PR #{pull_number}:",
                            )
                            for i, ws in enumerate(workstreams):
                                print(f"  {i + 1}. {ws}")
                            if dashboard_store is not None:
                                dashboard_store.record_activity(
                                    "plan",
                                    f"{len(workstreams)} workstreams for PR #{pull_number}",
                                )
                            try:
                                _run_workstream_subagents(
                                    api_key,
                                    parent_agent_id=builder_id,
                                    pr_url=pr_url,
                                    pull_number=pull_number,
                                    pr_head_ref=pr_head_ref_for_fix,
                                    workstreams=workstreams,
                                    max_workers=max_parallel_workstreams,
                                    model_id=model_id,
                                    stop_mode=stop_mode,
                                    dashboard=dashboard_store,
                                )
                                _, pr_head_ref_for_fix = get_pr_head(gh, repo, pull_number)
                                print(
                                    f"Finished workstream subagents for PR #{pull_number}.",
                                )
                                if dashboard_store is not None:
                                    dashboard_store.record_activity(
                                        "plan",
                                        f"completed workstreams for PR #{pull_number}",
                                    )
                            except Exception as exc:
                                print(
                                    f"Warning: workstream subagents failed on PR #{pull_number}: {exc}",
                                    file=sys.stderr,
                                )
                                if dashboard_store is not None:
                                    dashboard_store.record_activity(
                                        "failed",
                                        f"workstream subagents failed on PR #{pull_number}",
                                    )
                                if workstream_subagents_strict:
                                    if continuous:
                                        break
                                    raise SystemExit(2) from exc
        
                    graphql_auto_merge_enabled = False
                    graphql_auto_merge_failed = False
                    if queue_auto_merge and github_auto_merge:
                        try:
                            enable_pull_request_auto_merge(gh, repo, pull_number, github_auto_merge)
                            graphql_auto_merge_enabled = True
                            print(
                                f"Queued GitHub auto-merge ({github_auto_merge}); "
                                "merges when required checks and branch rules pass.",
                            )
                            if dashboard_store is not None:
                                dashboard_store.mark_merge_queued(pull_number, github_auto_merge)
                        except Exception as exc:
                            graphql_auto_merge_failed = True
                            print(f"Warning: could not enable auto-merge: {exc}", file=sys.stderr)
                            if dashboard_store is not None:
                                dashboard_store.record_activity(
                                    "failed",
                                    f"auto-merge queue failed for PR #{pull_number}",
                                )
                            raw = str(exc)
                            gql_prefix = "enablePullRequestAutoMerge failed: "
                            msg_body = raw[len(gql_prefix) :] if raw.startswith(gql_prefix) else raw
                            low = msg_body.lower()
                            if (
                                "personal access token" in low
                                or "resource not accessible" in low
                                or "forbidden" in low
                            ):
                                print(
                                    "Hint: GraphQL auto-merge needs a PAT allowed to update PR merge settings — "
                                    "fine-grained: Repository permissions → Pull requests: Read and write "
                                    "(add this repo; authorize SSO if org-required). "
                                    "Repo → Settings → Pull Requests → Allow auto-merge must be on. "
                                    "If Greptile looks clean, this CLI will attempt a REST merge using "
                                    "the same method as GITHUB_AUTO_MERGE. Or fix the PAT and rely on "
                                    "GraphQL queue-only auto-merge.",
                                    file=sys.stderr,
                                )
                            elif "clean status" in low:
                                print(
                                    "Hint: GitHub sometimes rejects queueing auto-merge when the PR is already "
                                    "mergeable (mergeable_state=clean), e.g. branch protection has no **required** "
                                    "status checks — auto-merge is for waiting on checks. Use a direct merge "
                                    "(this CLI’s REST fallback after Greptile, or merge in the UI). "
                                    "Add required checks on the base branch if you want true auto-merge queueing.",
                                    file=sys.stderr,
                                )
                            elif (
                                "auto merge" in low
                                or "automerge" in low
                                or "workflow" in low
                                or "merge queue" in low
                                or "branch protection" in low
                            ):
                                print(
                                    "Hint: Confirm the repository has **Allow auto-merge** enabled "
                                    "(Settings → General → Pull Requests), branch protection allows "
                                    "the merge method you chose, and required checks/reviews match what "
                                    "you expect.",
                                    file=sys.stderr,
                                )
        
                    if dashboard_store is not None:
                        dashboard_store.record_activity(
                            "greptile",
                            f"waiting for review signal on PR #{pull_number}",
                        )
                    gr = _wait_greptile(
                        gh,
                        repo,
                        pull_number,
                        bot_substrings=bot_substrings,
                        check_substrings=check_substrings,
                        poll_interval_s=poll_interval_s,
                        poll_budget_s=poll_budget_s,
                        continuous=continuous,
                    )
        
                    if gr.clean_success_no_text:
                        feedback_text = ""
                        if dashboard_store is not None:
                            dashboard_store.record_activity(
                                "greptile",
                                f"PR #{pull_number} check passed with no text",
                            )
                    elif gr.timed_out:
                        print(
                            "No Greptile feedback collected before timeout. "
                            "Tune GREPTILE_* or comment @greptileai on the PR.",
                        )
                        print("PR:", pr_url)
                        if dashboard_store is not None:
                            dashboard_store.record_activity(
                                "failed",
                                f"Greptile timed out for PR #{pull_number}",
                            )
                        if continuous:
                            break
                        sys.exit(0)
                    else:
                        feedback_text = gr.text
                        if dashboard_store is not None:
                            dashboard_store.record_activity(
                                "greptile",
                                f"captured feedback for PR #{pull_number}",
                            )
        
                    if feedback_text:
                        print("--- Greptile feedback (truncated) ---\n", feedback_text[:4000])
        
                    skipped_fix_loop_for_clean_greptile = False
        
                    if max_fix_rounds <= 0:
                        print("MAX_FIX_ROUNDS=0 — skipping fix loop.")
                        if dashboard_store is not None:
                            dashboard_store.record_activity("fix", "MAX_FIX_ROUNDS=0; skipped")
                    elif not feedback_text:
                        print("Skipping Greptile fix rounds (no feedback text).")
                        if dashboard_store is not None:
                            dashboard_store.record_activity("fix", "no feedback text; skipped")
                    elif _greptile_indicates_no_action_needed(
                        feedback_text,
                        extra_substrings=greptile_clean_substrings,
                    ):
                        print("Greptile feedback looks clean — skipping fix loop.")
                        skipped_fix_loop_for_clean_greptile = True
                        if dashboard_store is not None:
                            dashboard_store.record_activity(
                                "fix",
                                f"Greptile clean for PR #{pull_number}; skipped",
                            )
                    else:
                        for round_i in range(1, max_fix_rounds + 1):
                            print(f"\n=== Fix round {round_i}/{max_fix_rounds} (new cloud agent) ===")
                            if dashboard_store is not None:
                                dashboard_store.record_activity(
                                    "fix",
                                    f"round {round_i}/{max_fix_rounds} started on PR #{pull_number}",
                                )
                            head_sha_before_fix, _ = get_pr_head(gh, repo, pull_number)
                            round_started_iso = _utc_iso_z()
        
                            fix_prompt_feedback = _maybe_clod_compress(feedback_text, clod_cfg)
        
                            if max_parallel_fixers <= 1:
                                _run_single_fix_agent(
                                    api_key,
                                    pr_url=pr_url,
                                    pull_number=pull_number,
                                    pr_head_ref=pr_head_ref_for_fix,
                                    feedback_text=fix_prompt_feedback,
                                    model_id=model_id,
                                    stop_mode=stop_mode,
                                    dashboard=dashboard_store,
                                )
                            else:
                                chunks = split_feedback(fix_prompt_feedback, max_feedback_chunks)
                                _parallel_fix_agents(
                                    api_key,
                                    pr_url=pr_url,
                                    pull_number=pull_number,
                                    pr_head_ref=pr_head_ref_for_fix,
                                    chunks=chunks,
                                    max_workers=max_parallel_fixers,
                                    model_id=model_id,
                                    stop_mode=stop_mode,
                                    dashboard=dashboard_store,
                                )
        
                            print(f"Cooling down {fix_round_cooldown_s}s for Greptile to re-run…")
                            time.sleep(fix_round_cooldown_s)
        
                            head_sha, pr_head_ref_for_fix = get_pr_head(gh, repo, pull_number)
                            if head_sha == head_sha_before_fix:
                                print("PR head SHA unchanged after fix round — stopping (no new commits).")
                                if dashboard_store is not None:
                                    dashboard_store.record_activity(
                                        "fix",
                                        "no commit change after fix round; stopping",
                                    )
                                break
        
                            after = poll_greptile_signal(
                                gh,
                                repo,
                                pull_number,
                                head_sha,
                                bot_substrings=bot_substrings,
                                check_name_substrings=check_substrings,
                                comments_since_iso=round_started_iso,
                            )
                            joined = "\n".join(after.summary_parts).strip()
                            if not joined:
                                latest_issue = fetch_latest_greptile_issue_comment_body(
                                    gh,
                                    repo,
                                    pull_number,
                                    bot_substrings=bot_substrings,
                                )
                                if latest_issue:
                                    joined = latest_issue
                                    print(
                                        "Recovered Greptile summary from latest issue comment "
                                        "(post-fix poll had no new-comment window match).",
                                        file=sys.stderr,
                                    )
                                    if dashboard_store is not None:
                                        dashboard_store.record_activity(
                                            "greptile",
                                            "recovered summary from latest issue comment",
                                        )
    
                                    mirror_raw = os.environ.get(
                                        "GREPTILE_MIRROR_FALLBACK_COMMENT",
                                        "1",
                                    ).strip().lower()
                                    mirror_fallback = mirror_raw not in ("0", "false", "no")
                                    if mirror_fallback:
                                        cap = 62000
                                        snap = (
                                            joined if len(joined) <= cap else joined[:cap] + "\n\n_(truncated)_"
                                        )
                                        mirror_body = (
                                            "**Greptile summary (orchestrate snapshot)** — posted because "
                                            "Greptile often *edits* its summary in place; fresh timeline "
                                            "comments surface the current text for bots and humans.\n\n"
                                            + snap
                                        )
                                        try:
                                            create_pull_issue_comment(
                                                gh,
                                                repo,
                                                pull_number,
                                                mirror_body,
                                            )
                                            print(
                                                "Posted Greptile snapshot as a new PR issue comment.",
                                                file=sys.stderr,
                                            )
                                        except Exception as exc:
                                            print(
                                                f"Warning: could not post Greptile snapshot comment ({exc}).",
                                                file=sys.stderr,
                                            )
    
                            if _greptile_indicates_no_action_needed(
                                joined,
                                extra_substrings=greptile_clean_substrings,
                            ):
                                print("Greptile indicates no remaining issues; stopping fix loop.")
                                skipped_fix_loop_for_clean_greptile = True
                                if dashboard_store is not None:
                                    dashboard_store.record_activity(
                                        "fix",
                                        "Greptile indicates no remaining issues",
                                    )
                                break
                            if not joined:
                                if after.check_conclusion == "success":
                                    print(
                                        "Greptile check succeeded with no captured text after fix; "
                                        "stopping fix loop.",
                                    )
                                    if dashboard_store is not None:
                                        dashboard_store.record_activity(
                                            "fix",
                                            "Greptile success after fix round",
                                        )
                                    break
                                print("No Greptile text after fix; stopping fix loop.")
                                if dashboard_store is not None:
                                    dashboard_store.record_activity(
                                        "fix",
                                        "no Greptile text after fix round; stopping",
                                    )
                                break
                            feedback_text = joined
        
                    print("\nDone. PR:", pr_url)
                    if dashboard_store is not None:
                        dashboard_store.record_activity("pr", f"cycle done for PR #{pull_number}")
        
                    if clod_validator_enabled:
                        print("\n=== CLōD second validator ===")
                        verdict = "UNKNOWN"
                        vbody = ""
                        patch_bundle = ""
                        validator_exc: BaseException | None = None
                        try:
                            patch_bundle = fetch_pull_request_patch_bundle(
                                gh,
                                repo,
                                pull_number,
                                max_total_chars=clod_validator_max_patch_chars,
                            )
                            verdict, vbody = clod_second_validator(
                                greptile_summary=feedback_text,
                                patch_bundle=patch_bundle,
                                api_key=clod_key,
                                base_url=clod_shared_base,
                                model=clod_shared_model,
                                timeout_s=clod_validator_timeout_s,
                                max_completion_tokens=clod_validator_max_completion_tokens,
                                max_greptile_chars=clod_validator_max_greptile_chars,
                                max_patch_chars=clod_validator_max_patch_chars,
                            )
                        except Exception as exc:
                            validator_exc = exc
                            print(
                                f"Warning: CLōD validator failed ({exc}); verdict UNKNOWN (non-blocking).",
                                file=sys.stderr,
                            )
        
                        print(f"CLōD validator verdict: {verdict}")
                        if vbody.strip():
                            print(vbody[:8000])
        
                        if clod_validator_append_pr or clod_validator_comment_pr:
                            stamp = _utc_iso_z()
                            inner = _clod_validator_pr_blurb(
                                stamp=stamp,
                                verdict=verdict,
                                vbody=vbody,
                                validator_exc=validator_exc,
                                pr_url=pr_url,
                                pull_number=pull_number,
                                clod_model=clod_shared_model,
                                greptile_raw=feedback_text,
                                patch_bundle=patch_bundle,
                            )
                            append_cap = int(os.environ.get("CLOD_VALIDATOR_PR_MAX_CHARS", "45000"))
                            if len(inner) > append_cap:
                                inner = inner[:append_cap] + "\n\n_(truncated)_"
                            try:
                                if clod_validator_append_pr:
                                    cur_body = get_pull_request_body(gh, repo, pull_number)
                                    merged = merge_clod_validator_pr_section(cur_body, inner)
                                    update_pull_request_body(gh, repo, pull_number, merged)
                                    print(
                                        "Updated PR description with CLōD validator section.",
                                        file=sys.stderr,
                                    )
                                if clod_validator_comment_pr:
                                    comment_body = _clod_validator_pr_blurb(
                                        stamp=stamp,
                                        verdict=verdict,
                                        vbody=vbody,
                                        validator_exc=validator_exc,
                                        pr_url=pr_url,
                                        pull_number=pull_number,
                                        clod_model=clod_shared_model,
                                        greptile_raw=feedback_text,
                                        patch_bundle=patch_bundle,
                                    )
                                    comment_cap = 65000
                                    if len(comment_body) > comment_cap:
                                        comment_body = comment_body[:comment_cap] + "\n\n_(truncated)_"
                                    create_pull_issue_comment(gh, repo, pull_number, comment_body)
                                    print(
                                        "Posted CLōD validator as a PR comment.",
                                        file=sys.stderr,
                                    )
                            except Exception as exc:
                                print(
                                    f"Warning: could not publish CLōD validator to GitHub ({exc}).",
                                    file=sys.stderr,
                                )
        
                        if clod_validator_strict and verdict == "FAIL":
                            print(
                                "CLōD validator STRICT: FAIL — stopping before REST merge / merge wait. "
                                "Note: GraphQL auto-merge may already be queued (GITHUB_AUTO_MERGE).",
                                file=sys.stderr,
                            )
                            if continuous:
                                break
                            sys.exit(1)
        
                    rest_merge_method: str | None = github_merge_immediate
                    rest_merge_label = "GITHUB_MERGE_IMMEDIATE"
                    if (
                        not rest_merge_method
                        and github_merge_on_clean
                        and skipped_fix_loop_for_clean_greptile
                        and not graphql_auto_merge_enabled
                    ):
                        rest_merge_method = github_merge_on_clean
                        rest_merge_label = "GITHUB_MERGE_ON_GREPTILE_CLEAN"
                    elif (
                        github_merge_on_clean
                        and skipped_fix_loop_for_clean_greptile
                        and graphql_auto_merge_enabled
                        and not github_merge_immediate
                    ):
                        print(
                            "Skipping GITHUB_MERGE_ON_GREPTILE_CLEAN — GitHub auto-merge already queued "
                            "(GITHUB_AUTO_MERGE).",
                        )
                    elif (
                        not rest_merge_method
                        and skipped_fix_loop_for_clean_greptile
                        and graphql_auto_merge_failed
                        and github_auto_merge
                        and not github_merge_immediate
                    ):
                        rest_merge_method = github_auto_merge
                        rest_merge_label = "GITHUB_AUTO_MERGE (REST fallback)"
                        print(
                            "GraphQL auto-merge failed — merging via REST API using "
                            f"{github_auto_merge!r} (same as GITHUB_AUTO_MERGE).",
                            file=sys.stderr,
                        )
        
                    if rest_merge_method:
                        merge_ok = _rest_merge_when_mergeable(
                            gh,
                            repo,
                            pull_number,
                            merge_method=rest_merge_method,
                            merge_poll_budget_s=merge_poll_budget_s,
                            merge_poll_interval_s=merge_poll_interval_s,
                            env_label=rest_merge_label,
                        )
                        if not merge_ok:
                            if dashboard_store is not None:
                                dashboard_store.mark_merge_failure(
                                    pull_number,
                                    f"{rest_merge_label} {rest_merge_method} failed",
                                )
                            if continuous:
                                break
                            sys.exit(1)
                        if dashboard_store is not None:
                            dashboard_store.mark_pr_merged(pull_number)
    
                    if not continuous:
                        break
        
                    print(
                        f"Waiting up to {continuous_merge_wait_s:.0f}s for PR #{pull_number} to merge…",
                    )
                    if dashboard_store is not None:
                        dashboard_store.record_activity(
                            "merge",
                            f"waiting for PR #{pull_number} merge",
                        )
                    try:
                        merged_in_wait = wait_pull_merged(
                            gh,
                            repo,
                            pull_number,
                            poll_interval_s=continuous_poll_s,
                            budget_s=continuous_merge_wait_s,
                        )
                    except KeyboardInterrupt:
                        print("\norchestrate: interrupted during merge wait.", file=sys.stderr)
                        raise SystemExit(130) from None
        
                    if not merged_in_wait:
                        print(
                            "Timed out waiting for merge; stopping continuous loop "
                            "(fix GITHUB_AUTO_MERGE PAT, use REST merge envs, or merge manually).",
                            file=sys.stderr,
                        )
                        if dashboard_store is not None:
                            dashboard_store.mark_merge_conflict(
                                pull_number,
                                "timed out waiting for merge",
                            )
                        break
    
                    print("PR merged; cooling down before next builder.")
                    if dashboard_store is not None:
                        dashboard_store.mark_pr_merged(pull_number)
                    time.sleep(continuous_sleep_s)
    finally:
        if dashboard_api is not None:
            dashboard_api.stop()


if __name__ == "__main__":
    main()
