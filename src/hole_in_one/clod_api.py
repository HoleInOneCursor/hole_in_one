"""Optional CLōD (https://clod.io/) chat completions — OpenAI-compatible API."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

import httpx

DEFAULT_CLOD_BASE_URL = "https://api.clod.io/v1"
DEFAULT_CLOD_MODEL = "Claude Opus 4.6"

_VERDICT_RE = re.compile(r"(?im)^\s*VERDICT\s*:\s*(PASS|FAIL)\s*$")


def _chat_completion(
    *,
    messages: list[dict[str, str]],
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: float,
    max_completion_tokens: int,
    temperature: float,
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_completion_tokens,
    }
    with httpx.Client(timeout=timeout_s) as client:
        r = client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        r.raise_for_status()
        body = r.json()

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("CLōD response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("CLōD response malformed choices[0]")
    msg = first.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("CLōD returned empty content")
    return content.strip()


def plan_builder_tasks(
    goal: str,
    *,
    api_key: str,
    base_url: str = DEFAULT_CLOD_BASE_URL,
    model: str = DEFAULT_CLOD_MODEL,
    max_tasks: int = 6,
    timeout_s: float = 120.0,
    max_completion_tokens: int = 2048,
) -> list[str]:
    """
    Split one high-level product goal into ordered builder prompts (e.g. backend → frontend).
    Each task is intended to become its own Cursor builder run / PR in sequence.
    """
    g = goal.strip()
    if not g:
        return []

    system = (
        "You break down one software goal into a **sequential** list of Cursor cloud-agent tasks.\n"
        "Rules:\n"
        "- Output **only** a JSON array of strings — no markdown fences, no commentary.\n"
        "- Each string is a complete, actionable prompt for one repository PR.\n"
        "- Order matters: earlier tasks should not depend on later ones (e.g. API/schema before UI).\n"
        "- Prefer 2–5 tasks for full-stack work (backend / shared contracts / frontend / docs).\n"
        "- Keep tasks scoped so parallel conflicts are unlikely when run sequentially on default branch.\n"
        f"- At most {max_tasks} tasks."
    )
    user_msg = f"Goal to decompose:\n\n{g}"

    raw = _chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_s=timeout_s,
        max_completion_tokens=max_completion_tokens,
        temperature=0.2,
    )

    blob = raw.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```\s*$", blob)
    if fence:
        blob = fence.group(1).strip()

    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        arr_match = re.search(r"\[[\s\S]*\]", blob)
        if not arr_match:
            raise RuntimeError(f"Planner returned non-JSON: {blob[:400]}") from None
        data = json.loads(arr_match.group(0))

    if not isinstance(data, list):
        raise RuntimeError("Planner JSON must be an array of strings")

    tasks: list[str] = []
    for item in data[:max_tasks]:
        if isinstance(item, str) and item.strip():
            tasks.append(item.strip())
        elif isinstance(item, dict) and "task" in item:
            t = str(item.get("task", "")).strip()
            if t:
                tasks.append(t)

    return tasks if tasks else [g]


def plan_pr_workstreams(
    task_prompt: str,
    *,
    api_key: str,
    base_url: str = DEFAULT_CLOD_BASE_URL,
    model: str = DEFAULT_CLOD_MODEL,
    max_workstreams: int = 4,
    timeout_s: float = 90.0,
    max_completion_tokens: int = 1536,
) -> list[str]:
    """
    Split one builder task into independent workstreams for subagents on the same PR branch.
    """
    p = task_prompt.strip()
    if not p:
        return []

    system = (
        "You break one coding task into independent, parallelizable implementation workstreams.\n"
        "Rules:\n"
        "- Output only a JSON array of strings.\n"
        "- Each item is a concise workstream instruction for a subagent working on the same PR branch.\n"
        "- Do NOT tell subagents to open a new PR, create release notes, or repeat all tests in every item.\n"
        "- Prefer file/module boundaries and minimal overlap to reduce merge conflicts.\n"
        "- Return 2 to 4 workstreams when possible.\n"
        f"- Return at most {max_workstreams} items."
    )
    user_msg = f"Task to decompose into workstreams:\n\n{p}"

    raw = _chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_s=timeout_s,
        max_completion_tokens=max_completion_tokens,
        temperature=0.2,
    )

    blob = raw.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```\s*$", blob)
    if fence:
        blob = fence.group(1).strip()

    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        arr_match = re.search(r"\[[\s\S]*\]", blob)
        if not arr_match:
            raise RuntimeError(f"Workstream planner returned non-JSON: {blob[:400]}") from None
        data = json.loads(arr_match.group(0))

    if not isinstance(data, list):
        raise RuntimeError("Workstream planner JSON must be an array of strings")

    out: list[str] = []
    for item in data[:max_workstreams]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict) and "task" in item:
            t = str(item.get("task", "")).strip()
            if t:
                out.append(t)
    return out


def compress_greptile_feedback_for_fix(
    raw: str,
    *,
    api_key: str,
    base_url: str = DEFAULT_CLOD_BASE_URL,
    model: str = DEFAULT_CLOD_MODEL,
    timeout_s: float = 60.0,
    max_input_chars: int = 24000,
    max_completion_tokens: int = 2048,
) -> str:
    """Rewrite noisy Greptile/HTML feedback into concise fix instructions via CLōD."""
    raw_stripped = raw.strip()
    if not raw_stripped:
        return raw

    clipped = raw_stripped[:max_input_chars]
    if len(raw_stripped) > max_input_chars:
        clipped += "\n\n[truncated for CLōD input cap]"

    system = (
        "You rewrite noisy pull-request review feedback (HTML/Markdown, often from Greptile) "
        "into concise instructions for a coding agent editing the repository.\n"
        "Rules:\n"
        "- Output Markdown bullet lists; include file paths and concrete changes when known.\n"
        "- Preserve severity markers (P0/P1/P2) when present.\n"
        "- Omit boilerplate, praise-only lines, and duplicate points.\n"
        "- Keep every actionable requirement; drop purely informational fluff."
    )
    user_msg = "Review feedback to address:\n\n" + clipped

    return _chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_s=timeout_s,
        max_completion_tokens=max_completion_tokens,
        temperature=0.2,
    )


def clod_second_validator(
    *,
    greptile_summary: str,
    patch_bundle: str,
    api_key: str,
    base_url: str = DEFAULT_CLOD_BASE_URL,
    model: str = DEFAULT_CLOD_MODEL,
    timeout_s: float = 120.0,
    max_completion_tokens: int = 1536,
    max_greptile_chars: int = 12000,
    max_patch_chars: int = 28000,
) -> tuple[Literal["PASS", "FAIL", "UNKNOWN"], str]:
    """Independent LLM pass: correlate Greptile summary with diffs; first line must be VERDICT: PASS|FAIL."""
    g = greptile_summary.strip() or "(No Greptile summary.)"
    g = g[:max_greptile_chars]
    if len(greptile_summary.strip()) > max_greptile_chars:
        g += "\n\n[Greptile summary truncated for validator.]"

    p = patch_bundle.strip() or "(No unified diffs.)"
    p = p[:max_patch_chars]
    if len(patch_bundle.strip()) > max_patch_chars:
        p += "\n\n[Patch bundle truncated for validator.]"

    system = (
        "You are a secondary reviewer for a GitHub pull request.\n"
        "Greptile (automated review) produced the first block below; the second block "
        "contains unified diffs from the PR.\n"
        "Decide if there are any **blocking** issues for merging (logic bugs, security, "
        "incorrect behavior, missing critical tests when required, contradicting the review).\n"
        "Documentation-only nits and stylistic preferences are **not** blocking unless Greptile "
        "marks them critical.\n"
        "Respond EXACTLY in this format:\n"
        "First line: VERDICT: PASS\n"
        "or\n"
        "First line: VERDICT: FAIL\n"
        "Then a short Markdown bullet rationale (omit if PASS)."
    )
    user_msg = (
        "### Greptile summary\n\n"
        + g
        + "\n\n### Unified diffs (truncated)\n\n"
        + p
    )

    raw = _chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_s=timeout_s,
        max_completion_tokens=max_completion_tokens,
        temperature=0.1,
    )

    m = _VERDICT_RE.search(raw)
    if not m:
        return "UNKNOWN", raw
    v = m.group(1).upper()
    if v == "PASS":
        return "PASS", raw
    if v == "FAIL":
        return "FAIL", raw
    return "UNKNOWN", raw
