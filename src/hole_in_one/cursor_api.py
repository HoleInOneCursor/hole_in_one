from __future__ import annotations

import re
import time
from typing import Any

import httpx

CURSOR_API_BASE = "https://api.cursor.com"


class CursorCloudError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body

    def __str__(self) -> str:
        base = super().__str__()
        if not (self.body and self.body.strip()):
            return base
        detail = self.body.strip()
        if len(detail) > 1200:
            detail = detail[:1200] + "…"
        return f"{base}\n{detail}"


def _auth(api_key: str) -> tuple[str, str]:
    return (api_key, "")


def _repo_https_from_github_pr_url(pr_url: str) -> str | None:
    m = re.match(
        r"^https://github\.com/([^/]+)/([^/]+)/pull/\d+",
        pr_url.strip(),
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    return f"https://github.com/{m.group(1)}/{m.group(2)}"


def list_cloud_agent_github_repos(api_key: str) -> list[str]:
    """
    Repositories the Cursor Cloud Agents GitHub App can access for this API key.
    Same visibility surface create_agent uses for branch verification.
    Rate limits are strict (see Cursor API docs); call sparingly.
    """
    with httpx.Client(base_url=CURSOR_API_BASE, timeout=120.0) as client:
        r = client.get("/v1/repositories", auth=_auth(api_key))
        if r.status_code >= 400:
            raise CursorCloudError(
                f"list_repositories failed: {r.status_code}",
                status_code=r.status_code,
                body=r.text,
            )
        data = r.json()
        items = data.get("items") or []
        urls: list[str] = []
        for item in items:
            if isinstance(item, dict) and item.get("url"):
                urls.append(str(item["url"]))
        return urls


def create_agent(
    api_key: str,
    *,
    prompt_text: str,
    repo_url: str,
    starting_ref: str,
    auto_create_pr: bool = True,
    skip_reviewer_request: bool = True,
    model_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "prompt": {"text": prompt_text},
        "repos": [{"url": repo_url, "startingRef": starting_ref}],
        "autoCreatePR": auto_create_pr,
        "skipReviewerRequest": skip_reviewer_request,
    }
    if model_id:
        body["model"] = {"id": model_id}

    with httpx.Client(base_url=CURSOR_API_BASE, timeout=120.0) as client:
        r = client.post("/v1/agents", auth=_auth(api_key), json=body)
        if r.status_code >= 400:
            raise CursorCloudError(
                f"create_agent failed: {r.status_code}",
                status_code=r.status_code,
                body=r.text,
            )
        return r.json()


def get_agent(api_key: str, agent_id: str) -> dict[str, Any]:
    with httpx.Client(base_url=CURSOR_API_BASE, timeout=60.0) as client:
        r = client.get(f"/v1/agents/{agent_id}", auth=_auth(api_key))
        if r.status_code >= 400:
            raise CursorCloudError(
                f"get_agent failed: {r.status_code}",
                status_code=r.status_code,
                body=r.text,
            )
        return r.json()


def get_run(api_key: str, agent_id: str, run_id: str) -> dict[str, Any]:
    with httpx.Client(base_url=CURSOR_API_BASE, timeout=60.0) as client:
        r = client.get(f"/v1/agents/{agent_id}/runs/{run_id}", auth=_auth(api_key))
        if r.status_code >= 400:
            raise CursorCloudError(
                f"get_run failed: {r.status_code}",
                status_code=r.status_code,
                body=r.text,
            )
        return r.json()


def create_run(api_key: str, agent_id: str, prompt_text: str) -> dict[str, Any]:
    body = {"prompt": {"text": prompt_text}}
    with httpx.Client(base_url=CURSOR_API_BASE, timeout=120.0) as client:
        r = client.post(f"/v1/agents/{agent_id}/runs", auth=_auth(api_key), json=body)
        if r.status_code == 409:
            raise CursorCloudError("agent_busy", status_code=409, body=r.text)
        if r.status_code >= 400:
            raise CursorCloudError(
                f"create_run failed: {r.status_code}",
                status_code=r.status_code,
                body=r.text,
            )
        return r.json()


def wait_for_terminal_run(
    api_key: str,
    agent_id: str,
    run_id: str,
    *,
    poll_s: float = 4.0,
) -> dict[str, Any]:
    terminal = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}
    while True:
        run = get_run(api_key, agent_id, run_id)
        if run.get("status") in terminal:
            return run
        time.sleep(poll_s)


def archive_agent(api_key: str, agent_id: str) -> None:
    with httpx.Client(base_url=CURSOR_API_BASE, timeout=60.0) as client:
        r = client.post(f"/v1/agents/{agent_id}/archive", auth=_auth(api_key))
        if r.status_code >= 400:
            raise CursorCloudError(
                f"archive_agent failed: {r.status_code}",
                status_code=r.status_code,
                body=r.text,
            )


def delete_agent(api_key: str, agent_id: str) -> None:
    with httpx.Client(base_url=CURSOR_API_BASE, timeout=60.0) as client:
        r = client.delete(f"/v1/agents/{agent_id}", auth=_auth(api_key))
        if r.status_code >= 400:
            raise CursorCloudError(
                f"delete_agent failed: {r.status_code}",
                status_code=r.status_code,
                body=r.text,
            )


def stop_agent(api_key: str, agent_id: str, mode: str) -> None:
    """Tear down a cloud agent after its run. mode: archive | delete | none."""
    m = mode.lower().strip()
    if m in ("", "none", "off", "false", "0"):
        return
    if m == "archive":
        archive_agent(api_key, agent_id)
        return
    if m == "delete":
        delete_agent(api_key, agent_id)
        return
    raise ValueError(f"Invalid CURSOR_STOP_AGENT mode: {mode!r} (use archive, delete, or none)")


def create_agent_on_pr(
    api_key: str,
    *,
    prompt_text: str,
    pr_url: str,
    auto_create_pr: bool = False,
    auto_generate_branch: bool = False,
    model_id: str | None = None,
    pr_head_ref: str | None = None,
) -> dict[str, Any]:
    # Cursor rejects root-level autoCreatePR / autoGenerateBranch when repos[0].prUrl is set.
    _ = (auto_create_pr, auto_generate_branch)

    repo_cfg: dict[str, Any] = {"prUrl": pr_url}
    base_url = _repo_https_from_github_pr_url(pr_url)
    if base_url:
        repo_cfg["url"] = base_url
    if pr_head_ref:
        repo_cfg["startingRef"] = pr_head_ref

    body: dict[str, Any] = {
        "prompt": {"text": prompt_text},
        "repos": [repo_cfg],
        "skipReviewerRequest": True,
    }
    if model_id:
        body["model"] = {"id": model_id}

    with httpx.Client(base_url=CURSOR_API_BASE, timeout=120.0) as client:
        r = client.post("/v1/agents", auth=_auth(api_key), json=body)
        if r.status_code >= 400:
            raise CursorCloudError(
                f"create_agent_on_pr failed: {r.status_code}",
                status_code=r.status_code,
                body=r.text,
            )
        return r.json()
