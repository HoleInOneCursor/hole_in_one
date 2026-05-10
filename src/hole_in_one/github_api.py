from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class Repo:
    owner: str
    name: str


def parse_repo(full: str) -> Repo:
    m = re.match(r"^([^/]+)/([^/]+)$", full.strip())
    if not m:
        raise ValueError(f'Invalid GITHUB_REPO "{full}" (want owner/name)')
    return Repo(owner=m.group(1), name=m.group(2))


def repo_https_url(r: Repo) -> str:
    return f"https://github.com/{r.owner}/{r.name}"


def github_client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=GITHUB_API,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=60.0,
    )


def pull_number_from_pr_url(pr_url: str | None) -> int | None:
    if not pr_url:
        return None
    m = re.search(r"/pull/(\d+)(?:$|[/?#])", pr_url)
    return int(m.group(1)) if m else None


def find_open_pr_for_branch(client: httpx.Client, repo: Repo, branch: str) -> dict[str, Any] | None:
    head = f"{repo.owner}:{branch}"
    r = client.get(
        f"/repos/{repo.owner}/{repo.name}/pulls",
        params={"state": "open", "head": head, "per_page": 10},
    )
    r.raise_for_status()
    pulls: list[dict[str, Any]] = r.json()
    return pulls[0] if pulls else None


def get_pr_head(client: httpx.Client, repo: Repo, pull_number: int) -> tuple[str, str]:
    r = client.get(f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}")
    r.raise_for_status()
    data = r.json()
    return data["head"]["sha"], data["head"]["ref"]


def _login_matches(login: str | None, needles: list[str]) -> bool:
    if not login:
        return False
    lower = login.lower()
    return any(n.lower() in lower for n in needles)


@dataclass
class GreptileSignal:
    done: bool
    summary_parts: list[str]
    check_conclusion: str | None


def poll_greptile_signal(
    client: httpx.Client,
    repo: Repo,
    pull_number: int,
    head_sha: str,
    *,
    bot_substrings: list[str],
    check_name_substrings: list[str],
) -> GreptileSignal:
    summary_parts: list[str] = []
    check_conclusion: str | None = None
    greptile_check_completed = False

    cr = client.get(f"/repos/{repo.owner}/{repo.name}/commits/{head_sha}/check-runs")
    cr.raise_for_status()
    for run in cr.json().get("check_runs", []):
        name = (run.get("name") or "").lower()
        if not any(s.lower() in name for s in check_name_substrings):
            continue
        if run.get("status") == "completed":
            greptile_check_completed = True
            check_conclusion = run.get("conclusion")
            out = run.get("output") or {}
            if out.get("summary"):
                summary_parts.append(out["summary"])
            if out.get("text"):
                summary_parts.append(out["text"])

    rev = client.get(f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}/reviews")
    rev.raise_for_status()
    for item in rev.json():
        if _login_matches(item.get("user", {}).get("login"), bot_substrings) and item.get("body"):
            summary_parts.append(f"[review {item.get('state')}] {item['body']}")

    ic = client.get(f"/repos/{repo.owner}/{repo.name}/issues/{pull_number}/comments")
    ic.raise_for_status()
    for item in ic.json():
        if _login_matches(item.get("user", {}).get("login"), bot_substrings) and item.get("body"):
            summary_parts.append(f"[issue comment] {item['body']}")

    rc = client.get(f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}/comments")
    rc.raise_for_status()
    for item in rc.json():
        if _login_matches(item.get("user", {}).get("login"), bot_substrings) and item.get("body"):
            summary_parts.append(f"[review comment] {item['body']}")

    done = greptile_check_completed or len(summary_parts) > 0
    return GreptileSignal(done=done, summary_parts=summary_parts, check_conclusion=check_conclusion)
