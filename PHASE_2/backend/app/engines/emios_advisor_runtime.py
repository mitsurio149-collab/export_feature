"""Runtime helpers for upgrading EMIOS advisor output with live AI output."""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any

from app.ai.cache import InMemoryNarrativeCache, cache_key
from app.ai.client import BoschClient
from app.ai.config import AISettings
from app.engines.emios_advisor import EMIOSAdvisor
from app.engines.emios_advisor_input_builder import build_emios_advisor_input

logger = logging.getLogger(__name__)

_advisor_cache = InMemoryNarrativeCache()


async def upgrade_advisor_with_ai(result: Any) -> None:
    """
    Replace result.advisor_output with a live Bosch LLM Farm response.
    Mutates result in-place. Never raises — falls back to the existing
    deterministic output on any failure.
    """
    try:
        # Resolve .env relative to the backend root (parent of app/)
        _backend_root = Path(__file__).resolve().parents[1]
        _env_path = _backend_root / ".env"

        settings = AISettings(_env_file=str(_env_path))
        if not settings.ai_advisor_enabled:
            logger.info("AI advisor disabled via AI_ADVISOR_ENABLED flag — using template")
            return

        client = BoschClient(settings)
        try:
            advisor_input = build_emios_advisor_input(result)
            if settings.ai_cache_enabled:
                cache_key_value = cache_key(advisor_input, "emios-bosch")
                cached = _advisor_cache.get(cache_key_value)
                if inspect.isawaitable(cached):
                    cached = await cached
                if cached is not None:
                    result.advisor_output = cached
                    logger.info("EMIOSAdvisor: using cached advisor output")
                    return

            ai_output = await EMIOSAdvisor().run_with_ai(
                inp=advisor_input,
                client=client,
                ai_advisor_enabled=True,
            )
            result.advisor_output = ai_output
            if settings.ai_cache_enabled:
                stored = _advisor_cache.set(cache_key_value, ai_output)
                if inspect.isawaitable(stored):
                    await stored
            logger.info("EMIOSAdvisor: Bosch LLM Farm response applied to advisor_output")
        finally:
            await client.aclose()

    except Exception as exc:
        logger.warning(
            "EMIOSAdvisor AI upgrade failed (%s) — keeping deterministic fallback",
            exc,
        )


async def _upgrade_advisor_with_ai(result: Any) -> None:
    await upgrade_advisor_with_ai(result)
