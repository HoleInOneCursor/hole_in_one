from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

GITHUB_API = "https://api.github.com"

_check_runs_permission_warned = False


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


def _repo_access_failure_message(repo: Repo, status_code: int) -> str:
    full = f"{repo.owner}/{repo.name}"
    base = (
        f'Cannot read repository "{full}" from GitHub (HTTP {status_code}). '
        "Verify GITHUB_REPO is exactly owner/name (no URL). "
        "If the repo is private, GITHUB_TOKEN must belong to a user or bot that can access it "
        "(classic PAT: repo scope; fine-grained: Repository access to this repo)."
    )
    if status_code == 404:
        return base + " Note: GitHub often returns 404 for private repos when the token has no access."
    return base


def get_default_branch(client: httpx.Client, repo: Repo) -> str:
    """GitHub `default_branch` for the repo (requires repo scope on the token)."""
    r = client.get(f"/repos/{repo.owner}/{repo.name}")
    if r.status_code in (403, 404):
        raise SystemExit(_repo_access_failure_message(repo, r.status_code))
    r.raise_for_status()
    return str(r.json()["default_branch"])


def branch_exists(client: httpx.Client, repo: Repo, branch: str) -> bool:
    enc = quote(branch, safe="")
    r = client.get(f"/repos/{repo.owner}/{repo.name}/branches/{enc}")
    return r.status_code == 200


def get_branch_tip_sha(client: httpx.Client, repo: Repo, branch: str) -> str:
    """SHA of the branch tip commit (for Cursor startingRef when branch-name checks flake)."""
    enc = quote(branch, safe="")
    r = client.get(f"/repos/{repo.owner}/{repo.name}/branches/{enc}")
    r.raise_for_status()
    data = r.json()
    commit = (data.get("commit") or {}) if isinstance(data, dict) else {}
    sha = commit.get("sha")
    if not sha:
        raise RuntimeError(f"GitHub returned no commit.sha for branch {branch!r}")
    return str(sha)


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


def user_repo_full_names(client: httpx.Client, *, max_pages: int = 10) -> list[str]:
    """Repos visible to this token (owner, collaborator, or org member)."""
    names: list[str] = []
    for page in range(1, max_pages + 1):
        r = client.get(
            "/user/repos",
            params={
                "per_page": 100,
                "page": page,
                "affiliation": "owner,collaborator,organization_member",
                "sort": "full_name",
            },
        )
        r.raise_for_status()
        batch: list[Any] = r.json()
        if not batch:
            break
        for item in batch:
            fn = item.get("full_name")
            if isinstance(fn, str):
                names.append(fn)
        if len(batch) < 100:
            break
    return names


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


def find_latest_open_pr_head_ref_prefix(
    client: httpx.Client,
    repo: Repo,
    *,
    ref_prefix: str = "cursor/",
    per_page: int = 40,
) -> dict[str, Any] | None:
    """Newest-updated open PR whose head ref starts with ``ref_prefix`` (Cursor often uses ``cursor/…``)."""
    r = client.get(
        f"/repos/{repo.owner}/{repo.name}/pulls",
        params={
            "state": "open",
            "sort": "updated",
            "direction": "desc",
            "per_page": min(100, max(1, per_page)),
        },
    )
    r.raise_for_status()
    pulls: list[dict[str, Any]] = r.json()
    for pr in pulls:
        head = pr.get("head") or {}
        ref = str(head.get("ref") or "")
        if ref.startswith(ref_prefix):
            return pr
    return None


def get_pr_head(client: httpx.Client, repo: Repo, pull_number: int) -> tuple[str, str]:
    r = client.get(f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}")
    r.raise_for_status()
    data = r.json()
    return data["head"]["sha"], data["head"]["ref"]


def _parse_github_iso(ts: str) -> datetime:
    """Parse GitHub API timestamps (…Z or …+00:00) for comparison."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _record_updated_since(ts: str | None, since_iso: str | None) -> bool:
    """If since_iso is set, include only records whose timestamp is >= since."""
    if since_iso is None:
        return True
    if not ts:
        return False
    try:
        return _parse_github_iso(ts) >= _parse_github_iso(since_iso)
    except ValueError:
        return True


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
    comments_since_iso: str | None = None,
) -> GreptileSignal:
    global _check_runs_permission_warned

    summary_parts: list[str] = []
    check_conclusion: str | None = None
    greptile_check_completed = False

    cr = client.get(f"/repos/{repo.owner}/{repo.name}/commits/{head_sha}/check-runs")
    if cr.status_code == 200:
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
    elif cr.status_code in (401, 403):
        if not _check_runs_permission_warned:
            _check_runs_permission_warned = True
            print(
                "GITHUB_TOKEN cannot read commit check runs (HTTP "
                f"{cr.status_code}); skipping Checks API. "
                "Fine-grained PAT: add repository permission **Checks: Read**. "
                "Classic PAT: ensure **repo** scope. Continuing with PR reviews/comments only.",
                file=sys.stderr,
            )
    else:
        cr.raise_for_status()

    rev = client.get(f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}/reviews")
    rev.raise_for_status()
    for item in rev.json():
        if not _record_updated_since(item.get("submitted_at"), comments_since_iso):
            continue
        if _login_matches(item.get("user", {}).get("login"), bot_substrings) and item.get("body"):
            summary_parts.append(f"[review {item.get('state')}] {item['body']}")

    ic_params: dict[str, str] = {}
    if comments_since_iso:
        ic_params["since"] = comments_since_iso
    ic = client.get(
        f"/repos/{repo.owner}/{repo.name}/issues/{pull_number}/comments",
        params=ic_params or None,
    )
    ic.raise_for_status()
    for item in ic.json():
        if not _record_updated_since(item.get("updated_at"), comments_since_iso):
            continue
        if _login_matches(item.get("user", {}).get("login"), bot_substrings) and item.get("body"):
            summary_parts.append(f"[issue comment] {item['body']}")

    rc = client.get(f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}/comments")
    rc.raise_for_status()
    for item in rc.json():
        if not _record_updated_since(item.get("updated_at"), comments_since_iso):
            continue
        if _login_matches(item.get("user", {}).get("login"), bot_substrings) and item.get("body"):
            summary_parts.append(f"[review comment] {item['body']}")

    done = greptile_check_completed or len(summary_parts) > 0
    return GreptileSignal(done=done, summary_parts=summary_parts, check_conclusion=check_conclusion)


def fetch_latest_greptile_issue_comment_body(
    client: httpx.Client,
    repo: Repo,
    pull_number: int,
    *,
    bot_substrings: list[str],
    max_pages: int = 5,
) -> str | None:
    """Newest issue-comment body from a Greptile bot (by ``updated_at``).

    GitHub in-place edits bump ``updated_at``, but polling with ``comments_since_iso`` can still
    miss pairing that edit with the post-fix window — fall back to this to read the live summary.
    """
    best_dt: datetime | None = None
    best_body: str | None = None
    page = 1
    while page <= max_pages:
        r = client.get(
            f"/repos/{repo.owner}/{repo.name}/issues/{pull_number}/comments",
            params={"per_page": 100, "page": page},
        )
        r.raise_for_status()
        batch: list[Any] = r.json()
        if not batch:
            break
        for item in batch:
            login = (item.get("user") or {}).get("login")
            body = item.get("body")
            if not isinstance(body, str) or not body.strip():
                continue
            if not _login_matches(login, bot_substrings):
                continue
            ts = item.get("updated_at") or item.get("created_at")
            if not isinstance(ts, str):
                continue
            try:
                cand = _parse_github_iso(ts)
            except ValueError:
                continue
            if best_dt is None or cand >= best_dt:
                best_dt = cand
                best_body = body.strip()
        if len(batch) < 100:
            break
        page += 1
    return best_body


_MERGE_METHOD_GRAPHQL = {"merge": "MERGE", "squash": "SQUASH", "rebase": "REBASE"}


def parse_github_auto_merge_method(raw: str) -> str:
    """Return GraphQL PullRequestMergeMethod (MERGE | SQUASH | REBASE)."""
    key = raw.strip().lower()
    if key not in _MERGE_METHOD_GRAPHQL:
        raise ValueError(f"merge method must be merge|squash|rebase, not {raw!r}")
    return _MERGE_METHOD_GRAPHQL[key]


def enable_pull_request_auto_merge(
    client: httpx.Client,
    repo: Repo,
    pull_number: int,
    merge_method: str,
) -> None:
    """Queue GitHub auto-merge (merges when checks/branch rules allow).

    Fine-grained PAT: repository **Pull requests: Read and write** (GraphQL); classic: **repo** scope.
    """
    gql_method = parse_github_auto_merge_method(merge_method)
    pr = client.get(f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}")
    pr.raise_for_status()
    node_id = pr.json().get("node_id")
    if not isinstance(node_id, str) or not node_id:
        raise RuntimeError("GitHub PR JSON missing node_id (needed for GraphQL auto-merge).")

    query = """
mutation EnableAutoMerge($id: ID!, $method: PullRequestMergeMethod!) {
  enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: $method}) {
    pullRequest {
      id
      autoMergeRequest { enabledAt }
    }
  }
}
"""
    r = client.post(
        "/graphql",
        json={"query": query, "variables": {"id": node_id, "method": gql_method}},
    )
    r.raise_for_status()
    body = r.json()
    errors = body.get("errors")
    if errors:
        msgs = "; ".join(str(e.get("message", e)) for e in errors)
        raise RuntimeError(f"enablePullRequestAutoMerge failed: {msgs}")


def pull_request_merged(client: httpx.Client, repo: Repo, pull_number: int) -> bool:
    r = client.get(f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}")
    r.raise_for_status()
    return bool(r.json().get("merged"))


def fetch_pull_request_patch_bundle(
    client: httpx.Client,
    repo: Repo,
    pull_number: int,
    *,
    max_total_chars: int = 28000,
    per_page: int = 100,
) -> str:
    """Concatenate unified diffs from GET pulls/{n}/files for CLōD / tooling (truncated)."""
    parts: list[str] = []
    total = 0
    page = 1
    while True:
        r = client.get(
            f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}/files",
            params={"per_page": per_page, "page": page},
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            break
        for item in data:
            if not isinstance(item, dict):
                continue
            fn = item.get("filename") or "?"
            status = item.get("status") or ""
            patch = item.get("patch")
            chunk_header = f"\n--- {fn} ({status}) ---\n"
            chunk_body = (
                patch if isinstance(patch, str) else "(no unified diff; binary or large file)\n"
            )
            chunk = chunk_header + chunk_body
            if total + len(chunk) > max_total_chars:
                parts.append("\n--- [truncated: remaining files omitted] ---\n")
                return "".join(parts).strip()
            parts.append(chunk)
            total += len(chunk)
        if len(data) < per_page:
            break
        page += 1
    return "".join(parts).strip()


def wait_pull_merged(
    client: httpx.Client,
    repo: Repo,
    pull_number: int,
    *,
    poll_interval_s: float,
    budget_s: float,
) -> bool:
    try:
        deadline = time.monotonic() + budget_s
        while time.monotonic() < deadline:
            if pull_request_merged(client, repo, pull_number):
                return True
            time.sleep(poll_interval_s)
        return False
    except KeyboardInterrupt:
        print("\nInterrupted while waiting for PR merge.", file=sys.stderr)
        raise SystemExit(130) from None


def fetch_pull_merge_snapshot(client: httpx.Client, repo: Repo, pull_number: int) -> dict[str, Any]:
    """Subset of GET pull JSON fields relevant to merging."""
    r = client.get(f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}")
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else {}


_CLOD_VALIDATOR_SECTION_RE = re.compile(
    r"<!--\s*hole-in-one:clod-validator\s*-->.*?<!--\s*/hole-in-one:clod-validator\s*-->",
    re.DOTALL | re.IGNORECASE,
)


def get_pull_request_body(client: httpx.Client, repo: Repo, pull_number: int) -> str:
    data = fetch_pull_merge_snapshot(client, repo, pull_number)
    b = data.get("body")
    return b if isinstance(b, str) else ""


def merge_clod_validator_pr_section(existing_body: str | None, section_inner_md: str) -> str:
    """Insert or replace a marked CLōD validator section in the PR description."""
    inner = section_inner_md.strip()
    block = (
        "<!-- hole-in-one:clod-validator -->\n"
        f"{inner}\n"
        "<!-- /hole-in-one:clod-validator -->"
    )
    eb = existing_body or ""
    if _CLOD_VALIDATOR_SECTION_RE.search(eb):
        return _CLOD_VALIDATOR_SECTION_RE.sub(block, eb, count=1).strip()
    sep = "\n\n" if eb.strip() else ""
    return (eb.rstrip() + sep + block).strip()


def update_pull_request_body(client: httpx.Client, repo: Repo, pull_number: int, body: str) -> None:
    r = client.patch(
        f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}",
        json={"body": body},
    )
    r.raise_for_status()


def create_pull_issue_comment(
    client: httpx.Client,
    repo: Repo,
    pull_number: int,
    body: str,
) -> None:
    """PRs use the Issues comments endpoint (pull_number equals issue number)."""
    r = client.post(
        f"/repos/{repo.owner}/{repo.name}/issues/{pull_number}/comments",
        json={"body": body},
    )
    r.raise_for_status()


def wait_pull_mergeable_clean(
    client: httpx.Client,
    repo: Repo,
    pull_number: int,
    *,
    poll_interval_s: float,
    budget_s: float,
) -> bool:
    """
    Poll until GitHub reports mergeable=true and mergeable_state=clean.
    Returns False on timeout or if merge conflicts (dirty).
    """
    try:
        deadline = time.monotonic() + budget_s
        while time.monotonic() < deadline:
            data = fetch_pull_merge_snapshot(client, repo, pull_number)
            if data.get("merged"):
                return True
            mergeable = data.get("mergeable")
            state = str(data.get("mergeable_state") or "").lower()
            if mergeable is False and state == "dirty":
                print(
                    "GitHub reports merge conflicts (mergeable_state=dirty); cannot REST-merge.",
                    file=sys.stderr,
                )
                return False
            if mergeable is True and state == "clean":
                return True
            time.sleep(poll_interval_s)
        return False
    except KeyboardInterrupt:
        print("\nInterrupted while waiting for mergeable PR.", file=sys.stderr)
        raise SystemExit(130) from None


_MERGE_METHOD_REST = frozenset({"merge", "squash", "rebase"})


def merge_pull_request_rest(
    client: httpx.Client,
    repo: Repo,
    pull_number: int,
    merge_method: str,
) -> None:
    """Merge immediately via REST PUT .../merge (not GraphQL auto-merge)."""
    key = merge_method.strip().lower()
    if key not in _MERGE_METHOD_REST:
        raise ValueError(f"merge_method must be merge|squash|rebase, not {merge_method!r}")
    r = client.put(
        f"/repos/{repo.owner}/{repo.name}/pulls/{pull_number}/merge",
        json={"merge_method": key},
    )
    if r.status_code == 200:
        return
    detail = (r.text or "").strip()
    if len(detail) > 800:
        detail = detail[:800] + "…"
    raise RuntimeError(f"merge pull failed HTTP {r.status_code}: {detail or r.reason_phrase}")
