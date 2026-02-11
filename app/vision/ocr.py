from __future__ import annotations

import base64
from typing import Optional

from openai import OpenAI

from app.core.config import logger

# מודל vision פעיל בחשבון שלך
VISION_MODEL = "gpt-4.1-mini"  # אפשר להחליף ל-gpt-4o / gpt-4o-mini אם תרצה


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
                                "Please extract only the text of the exercises from this image. "
                                "Return each separate exercise on its own line. "
                                "Do not add numbering or explanations, just the raw exercise text lines."
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
            # בחלק מהגרסאות msg.content הוא string, בחלק list של חלקים
            if isinstance(msg.content, str):
                raw_text = msg.content
            elif isinstance(msg.content, list):
                parts: list[str] = []
                for c in msg.content:
                    if isinstance(c, dict) and c.get("type") == "text":
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

        logger.debug(
            "ocr_image_to_text | raw_text_length=%s value_preview=%r",
            len(raw_text),
            raw_text[:200],
        )

        if not raw_text:
            logger.warning("ocr_image_to_text | empty OCR result from Vision")
            return ""

        # נרמול: שומרים תרגיל אחד בכל שורה
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        normalized = "\n".join(lines)

        logger.debug(
            "ocr_image_to_text | normalized_lines=%s value_preview=%r",
            len(lines),
            normalized[:200],
        )

        return normalized


    except Exception as exc:
        logger.error("ocr_image_to_text | error=%s", exc)
        return ""
