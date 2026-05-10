"""Optional CLōD (https://clod.io/) chat completions — OpenAI-compatible API."""

from __future__ import annotations

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
