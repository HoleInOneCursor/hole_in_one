from __future__ import annotations

import time
from typing import Any

import httpx

CURSOR_API_BASE = "https://api.cursor.com"


class CursorCloudError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _auth(api_key: str) -> tuple[str, str]:
    return (api_key, "")


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
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "prompt": {"text": prompt_text},
        "repos": [{"prUrl": pr_url}],
        "autoCreatePR": auto_create_pr,
        "autoGenerateBranch": auto_generate_branch,
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
