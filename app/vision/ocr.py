from __future__ import annotations

import base64
from typing import Optional

from openai import OpenAI

from app.core.config import logger

VISION_MODEL = "gpt-4-vision-preview"  # או gpt-4o / gpt-4.1-mini אם מוגדר אצלך


async def ocr_image_to_text(image_bytes: bytes) -> str:
    """
    OCR אמיתי באמצעות OpenAI Vision (פורמט chat.completions):
    - מקודד את התמונה ל-base64.
    - שולח ל-API עם הנחיה ברורה: "חלץ רק את הטקסט של התרגיל".
    - מחזיר את הטקסט שחולץ, מנורמל לשורה אחת.
    """
    if not image_bytes:
        logger.warning("ocr_image_to_text | empty image_bytes")
        return ""

    try:
        logger.info(
            "ocr_image_to_text | calling OpenAI Vision | model=%s",
            VISION_MODEL,
        )

        client = OpenAI()

        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64_image}"

        # שימוש ב-chat.completions עם תוכן תמונה + טקסט
        resp = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Please extract only the text of the exercise from this image. "
                                "If there are multiple lines, keep them in order. "
                                "Do not add explanations, just the raw exercise text."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ],
            max_tokens=300,
        )

        # שליפת הטקסט מהתשובה
        raw_text = ""
        try:
            choice = resp.choices[0]
            msg = choice.message
            # בחלק מהגרסאות זה פשוט msg.content (string), בחלק – רשימת חלקים
            if isinstance(msg.content, str):
                raw_text = msg.content
            elif isinstance(msg.content, list):
                parts: list[str] = []
                for c in msg.content:
                    if c.get("type") == "text":
                        parts.append(c.get("text", ""))
                raw_text = " ".join(parts)
        except Exception as parse_exc:
            logger.error(
                "ocr_image_to_text | error parsing chat.completions response | error=%s",
                parse_exc,
            )

        logger.debug(
            "ocr_image_to_text | raw_text_length=%s value_preview=%r",
            len(raw_text),
            raw_text[:200],
        )

        if not raw_text:
            logger.warning("ocr_image_to_text | empty OCR result from Vision")
            return ""

        # נרמול בסיסי
        normalized = " ".join(raw_text.split())
        logger.debug(
            "ocr_image_to_text | normalized_text_length=%s value_preview=%r",
            len(normalized),
            normalized[:200],
        )
        return normalized.strip()

    except Exception as exc:
        logger.error("ocr_image_to_text | error=%s", exc)
        return ""
