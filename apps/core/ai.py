"""
Shared Gemini AI service for the in-app Bonus AI feature.

Uses the official `google-genai` (>= 3.5.0) Interactions API with Pydantic structured
output and graceful timeout/error handling so missing API keys or transient failures
never crash judging.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from django.conf import settings
from google import genai
from google.genai import types
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_GEMINI_MODEL = "gemini-4-hydrogen"


class DispatchBriefing(BaseModel):
    """Reference structured-output contract for the Theme 4 AI Dispatch Co-Pilot."""

    executive_summary: str
    recommended_actions: list[str]
    safety_flags: list[str]
    estimated_impact_note: str


def is_ai_configured() -> bool:
    """Return True when a Gemini API key is configured in Django settings."""
    return bool(getattr(settings, "GEMINI_API_KEY", "").strip())


def _strip_markdown_fences(text: str) -> str:
    """Strip optional surrounding markdown code fences (e.g. ```json ... ```)."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _extract_output_text(interaction: object) -> str:
    """Extract generated text from an Interactions API response."""
    output_text = (getattr(interaction, "output_text", None) or "").strip()
    if output_text:
        return _strip_markdown_fences(output_text)

    chunks: list[str] = []
    for step in getattr(interaction, "steps", None) or ():
        if getattr(step, "type", None) != "model_output":
            continue
        for content in getattr(step, "content", None) or ():
            if getattr(content, "type", None) == "text":
                text = getattr(content, "text", None)
                if text:
                    chunks.append(text)
    return _strip_markdown_fences("".join(chunks))


def generate_structured(
    prompt: str,
    response_schema: type[T],
    system_instruction: str = "",
    timeout_seconds: float = 20.0,
    thinking_level: str = "medium",
    previous_interaction_id: str | None = None,
) -> tuple[T | None, str | None]:
    """
    Call Gemini Interactions API with structured JSON output validated into `response_schema`.

    Returns `(parsed_model, None)` on success or `(None, human_readable_error)` on
    missing configuration, timeout, or API error.
    """
    api_key = getattr(settings, "GEMINI_API_KEY", "").strip()
    if not api_key:
        return None, "GEMINI_API_KEY is not configured; using deterministic fallback."

    model_name = (
        getattr(settings, "GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
        or DEFAULT_GEMINI_MODEL
    )
    timeout_sec = max(1.0, float(timeout_seconds))
    timeout_ms = int(timeout_sec * 1000)

    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_ms),
        )
        request_kwargs: dict[str, object] = {
            "model": model_name,
            "input": prompt,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": response_schema.model_json_schema(),
            },
            "generation_config": {
                "thinking_level": thinking_level,
            },
            "timeout": timeout_sec,
        }
        if system_instruction:
            request_kwargs["system_instruction"] = system_instruction
        if previous_interaction_id:
            request_kwargs["previous_interaction_id"] = previous_interaction_id

        interaction = client.interactions.create(**request_kwargs)
        raw_text = _extract_output_text(interaction)
        if not raw_text:
            return None, "Gemini returned an empty response."
        return response_schema.model_validate_json(raw_text), None
    except Exception as exc:
        logger.warning("Gemini structured generation failed: %s", exc)
        return None, f"Gemini request failed: {exc.__class__.__name__}"
