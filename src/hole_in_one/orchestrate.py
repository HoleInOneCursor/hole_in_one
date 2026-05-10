from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from dotenv import load_dotenv

from hole_in_one.cursor_api import (
    create_agent,
    create_agent_on_pr,
    get_agent,
    stop_agent,
    wait_for_terminal_run,
)
from hole_in_one.feedback import split_feedback
from hole_in_one.github_api import (
    Repo,
    find_open_pr_for_branch,
    get_pr_head,
    github_client,
    parse_repo,
    poll_greptile_signal,
    pull_number_from_pr_url,
    repo_https_url,
)

load_dotenv()


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None or v == "":
        raise SystemExit(f"Missing env {name}")
    return v


def _comma_list(name: str, default: str) -> list[str]:
    return [s.strip() for s in os.environ.get(name, default).split(",") if s.strip()]


def _wait_greptile(
    gh: httpx.Client,
    repo: Repo,
    pull_number: int,
    *,
    bot_substrings: list[str],
    check_substrings: list[str],
    poll_interval_s: float,
    poll_budget_s: float,
) -> str:
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
                break
            if signal.check_conclusion == "success":
                print("Greptile check completed with success and no captured text; nothing to fix.")
                sys.exit(0)
            if signal.check_conclusion and signal.check_conclusion != "success":
                feedback_text = (
                    f"Greptile check completed with conclusion: {signal.check_conclusion}.\n"
                    "The GitHub PR checks UI may contain details not exposed via API.\n"
                    "Address any reported issues until the Greptile check is green."
                )
                break
        elapsed = int(time.monotonic() - started)
        print(
            f"[wait] No Greptile signal yet ({elapsed}s / {int(poll_budget_s)}s)",
        )
        time.sleep(poll_interval_s)
    return feedback_text


def _run_single_fix_agent(
    api_key: str,
    *,
    pr_url: str,
    pull_number: int,
    feedback_text: str,
    model_id: str | None,
    stop_mode: str,
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
    )
    fix_agent_id = created["agent"]["id"]
    run_id = created["run"]["id"]
    print(f"Greptile fix agent: {fix_agent_id}")
    run = wait_for_terminal_run(api_key, fix_agent_id, run_id)
    if run.get("status") != "FINISHED":
        print("Fix run failed:", run, file=sys.stderr)
        sys.exit(2)
    print("Fix run finished.")
    stop_agent(api_key, fix_agent_id, stop_mode)
    print(f"Stopped fix agent ({stop_mode}): {fix_agent_id}")


def _parallel_fix_agents(
    api_key: str,
    *,
    pr_url: str,
    pull_number: int,
    chunks: list[str],
    max_workers: int,
    model_id: str | None,
    stop_mode: str,
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
        )
        agent_id = created["agent"]["id"]
        run_id = created["run"]["id"]
        print(f"Greptile fix agent (slice {idx + 1}): {agent_id}")
        run = wait_for_terminal_run(api_key, agent_id, run_id)
        if run.get("status") != "FINISHED":
            raise RuntimeError(f"Fix slice {idx} failed: {run}")
        stop_agent(api_key, agent_id, stop_mode)
        print(f"Stopped fix agent ({stop_mode}): {agent_id}")

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(one, i, c) for i, c in enumerate(chunks)]
        for f in as_completed(futures):
            f.result()
    print("Parallel fix runs finished (inspect PR for conflicts).")


def main() -> None:
    api_key = _env("CURSOR_API_KEY")
    gh_token = _env("GITHUB_TOKEN")
    repo_full = _env("GITHUB_REPO")
    repo = parse_repo(repo_full)
    repo_url = repo_https_url(repo)

    builder_prompt = os.environ.get(
        "BUILDER_PROMPT",
        'Make a small, self-contained improvement that fits the theme "Build Something Agents Want"\n'
        "(for example: a helper script, a concise doc, or a tiny devtool that makes agent workflows nicer).\n"
        "Keep the change reviewable in under 15 minutes.",
    )

    poll_interval_s = float(os.environ.get("GREPTILE_POLL_INTERVAL_S", "20"))
    poll_budget_s = float(os.environ.get("GREPTILE_POLL_BUDGET_S", "900"))
    max_fix_rounds = int(os.environ.get("MAX_FIX_ROUNDS", "3"))
    max_parallel_fixers = min(2, max(1, int(os.environ.get("MAX_PARALLEL_FIXERS", "1"))))
    max_feedback_chunks = int(os.environ.get("MAX_FEEDBACK_CHUNKS", "6"))
    fix_round_cooldown_s = float(os.environ.get("FIX_ROUND_COOLDOWN_S", "45"))
    stop_mode = os.environ.get("CURSOR_STOP_AGENT", "archive").strip()

    bot_substrings = _comma_list("GREPTILE_BOT_SUBSTRINGS", "greptile")
    check_substrings = _comma_list("GREPTILE_CHECK_SUBSTRINGS", "greptile")
    default_branch = os.environ.get("GITHUB_DEFAULT_BRANCH", "main")
    model_id = os.environ.get("CURSOR_MODEL") or None

    print(
        f"Repo {repo_full} | new agent per Greptile fix | "
        f"max_parallel_fixers={max_parallel_fixers} | stop={stop_mode}",
    )

    with github_client(gh_token) as gh:
        created = create_agent(
            api_key,
            prompt_text=builder_prompt + "\n\nOpen a normal (non-draft) PR with a clear title and description.",
            repo_url=repo_url,
            starting_ref=default_branch,
            auto_create_pr=True,
            skip_reviewer_request=True,
            model_id=model_id,
        )
        builder_id = created["agent"]["id"]
        run_id = created["run"]["id"]
        print(f"Builder agent: {builder_id}")

        initial = wait_for_terminal_run(api_key, builder_id, run_id)
        if initial.get("status") != "FINISHED":
            print("Builder run failed:", initial, file=sys.stderr)
            try:
                stop_agent(api_key, builder_id, stop_mode)
            except Exception as exc:
                print(f"Warning: could not stop builder agent: {exc}", file=sys.stderr)
            sys.exit(2)

        pr_url: str | None = None
        pull_number: int | None = None
        try:
            agent_meta = get_agent(api_key, builder_id)
            branch_name = agent_meta.get("branchName")
            if not branch_name:
                print("Agent has no branchName after run; cannot resolve PR.", file=sys.stderr)
                sys.exit(2)

            pr_data = find_open_pr_for_branch(gh, repo, branch_name)
            if not pr_data:
                print(
                    f"No open PR found for head {repo.owner}:{branch_name}. Open GitHub or widen search.",
                    file=sys.stderr,
                )
                sys.exit(2)

            pr_url = pr_data.get("html_url")
            pull_number = pr_data.get("number") or pull_number_from_pr_url(pr_url)
            if not pull_number:
                print("Could not determine PR number.", file=sys.stderr)
                sys.exit(2)

            print("PR:", pr_url)
        finally:
            try:
                stop_agent(api_key, builder_id, stop_mode)
                print(f"Stopped builder agent ({stop_mode}): {builder_id}")
            except Exception as exc:
                print(f"Warning: could not stop builder agent: {exc}", file=sys.stderr)

        assert pr_url is not None and pull_number is not None

        feedback_text = _wait_greptile(
            gh,
            repo,
            pull_number,
            bot_substrings=bot_substrings,
            check_substrings=check_substrings,
            poll_interval_s=poll_interval_s,
            poll_budget_s=poll_budget_s,
        )

        if not feedback_text:
            print(
                "No Greptile feedback collected before timeout. "
                "Tune GREPTILE_* or comment @greptileai on the PR.",
            )
            print("PR:", pr_url)
            sys.exit(0)

        print("--- Greptile feedback (truncated) ---\n", feedback_text[:4000])

        for round_i in range(1, max_fix_rounds + 1):
            print(f"\n=== Fix round {round_i}/{max_fix_rounds} (new cloud agent) ===")

            if max_parallel_fixers <= 1:
                _run_single_fix_agent(
                    api_key,
                    pr_url=pr_url,
                    pull_number=pull_number,
                    feedback_text=feedback_text,
                    model_id=model_id,
                    stop_mode=stop_mode,
                )
            else:
                chunks = split_feedback(feedback_text, max_feedback_chunks)
                _parallel_fix_agents(
                    api_key,
                    pr_url=pr_url,
                    pull_number=pull_number,
                    chunks=chunks,
                    max_workers=max_parallel_fixers,
                    model_id=model_id,
                    stop_mode=stop_mode,
                )

            print(f"Cooling down {fix_round_cooldown_s}s for Greptile to re-run…")
            time.sleep(fix_round_cooldown_s)

            head_sha, _ = get_pr_head(gh, repo, pull_number)
            after = poll_greptile_signal(
                gh,
                repo,
                pull_number,
                head_sha,
                bot_substrings=bot_substrings,
                check_name_substrings=check_substrings,
            )
            joined = "\n".join(after.summary_parts).strip()
            if not joined:
                print("No Greptile text after fix; stopping fix loop.")
                break
            feedback_text = joined

        print("\nDone. PR:", pr_url)


if __name__ == "__main__":
    main()
