"""Groq = fast structured agents. Gemini = planning / explanation agents.

If a provider is missing or rate-limited, the other is used, then heuristics.
"""

from __future__ import annotations

import logging
from typing import Any

from moodos.config import settings
from moodos.jsonutil import parse_json_object

log = logging.getLogger("moodos.llm")

EXTRACT_SYSTEM = (
    "You extract structured slots for MoodOS, an experience orchestrator. "
    "Return ONLY valid JSON. No markdown. Unknown fields use null or empty lists. "
    "Never invent live showtimes, prices, or availability."
)


# Hard per-request HTTP timeout for every LLM call. The planner gives the LLM
# 35s (see orchestrator._plan_with_budget) and then abandons the thread on a
# timeout; without these bounds Groq would retry for ~180s per leg and Gemini
# has NO default HTTP timeout at all, so abandoned threads could burn quota
# for minutes after the request already returned.
LLM_TIMEOUT_S = 25.0


class LLMRouter:
    def __init__(self) -> None:
        self._groq = None
        self._gemini = None
        if settings.groq_api_key:
            try:
                from groq import Groq

                self._groq = Groq(
                    api_key=settings.groq_api_key,
                    timeout=LLM_TIMEOUT_S,
                    max_retries=0,
                )
            except Exception as exc:
                log.warning("Groq init failed: %s", exc)
        if settings.gemini_api_key:
            try:
                from google import genai

                self._gemini = genai.Client(
                    api_key=settings.gemini_api_key,
                    http_options={"timeout": int(LLM_TIMEOUT_S * 1000)},
                )
            except Exception as exc:
                log.warning("Gemini init failed: %s", exc)

    @property
    def groq_ready(self) -> bool:
        return self._groq is not None

    @property
    def gemini_ready(self) -> bool:
        return self._gemini is not None

    def extract_json(self, user_prompt: str) -> dict[str, Any]:
        """Groq-first: intent, mood, constraints — low latency JSON."""
        if self._groq:
            data = self._groq_json(user_prompt, settings.groq_fast_model)
            if data:
                data["_agent"] = "groq"
                data["_model"] = settings.groq_fast_model
                return data
        if self._gemini:
            data = self._gemini_json(user_prompt)
            if data:
                data["_agent"] = "gemini"
                return data
        return {}

    def plan_json(self, user_prompt: str) -> dict[str, Any]:
        """Gemini-first: experience bundle + explanation — longer reasoning."""
        if self._gemini:
            data = self._gemini_json(user_prompt)
            if data:
                data["_agent"] = "gemini"
                return data
        if self._groq:
            data = self._groq_json(user_prompt, settings.groq_reason_model) or self._groq_json(
                user_prompt, settings.groq_fast_model
            )
            if data:
                data["_agent"] = "groq"
                return data
        return {}

    def _groq_json(self, user_prompt: str, model: str) -> dict[str, Any]:
        try:
            resp = self._groq.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            content = (resp.choices[0].message.content or "") if resp.choices else ""
            return parse_json_object(content)
        except Exception as exc:
            log.warning("Groq %s failed: %s", model, exc)
            return {}

    def _gemini_json(self, user_prompt: str) -> dict[str, Any]:
        models = [settings.gemini_plan_model, *settings.gemini_fallback_models.split(",")]
        prompt = EXTRACT_SYSTEM + "\n\n" + user_prompt
        for model in [m.strip() for m in models if m.strip()]:
            try:
                resp = self._gemini.models.generate_content(model=model, contents=prompt)
                text = getattr(resp, "text", None) or ""
                data = parse_json_object(text)
                if data:
                    data["_model"] = model
                    return data
            except Exception as exc:
                log.warning("Gemini %s failed: %s", model, exc)
                continue
        return {}


router = LLMRouter()
