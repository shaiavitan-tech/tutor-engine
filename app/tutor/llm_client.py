# app/tutor/llm_client.py

from __future__ import annotations

from typing import List, Dict, AsyncGenerator

import os
from openai import OpenAI

from app.core.config import logger

_client: OpenAI | None = None


def get_llm_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        logger.info("Initializing OpenAI client")
        _client = OpenAI(api_key=api_key)
    return _client


def chat_completion(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 512,
) -> str:
    """
    קריאה סינכרונית ל-chat.completions.
    במודלים החדשים משתמשים ב-max_completion_tokens במקום max_tokens.
    """
    logger.debug(
        "LLM chat_completion | model=%s temperature=%.2f max_tokens=%s",
        model,
        temperature,
        max_tokens,
    )
    client = get_llm_client()
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_completion_tokens=max_tokens,  # חשוב: לא max_tokens
    )
    content = resp.choices[0].message.content or ""
    logger.debug("LLM chat_completion success | length=%s", len(content))
    return content


async def chat_completion_stream(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 512,
) -> AsyncGenerator[str, None]:
    """
    סטרימינג של תשובה – מחזיר טקסט חלקי בכל צעד.
    גם כאן משתמשים ב-max_completion_tokens.
    """
    logger.debug(
        "LLM chat_completion_stream | model=%s temperature=%.2f max_tokens=%s",
        model,
        temperature,
        max_tokens,
    )
    client = get_llm_client()
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_completion_tokens=max_tokens,  # במקום max_tokens
        stream=True,
    )

    # openai-python מחזיר iterator סינכרוני; נעטוף ל-async
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta
