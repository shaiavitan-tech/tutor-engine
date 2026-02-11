from __future__ import annotations

import base64
from typing import Optional

from openai import OpenAI

from app.core.config import logger

VISION_MODEL = "gpt-4.1-mini"  # או gpt-4o אם זמין


async def ocr_image_to_text(image_bytes: bytes) -> str:
    """
    OCR אמיתי באמצעות OpenAI Vision:
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

        # קריאה ל-Vision בפורמט הנכון
        response = client.responses.create(
            model=VISION_MODEL,
            input=[
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
                            "type": "input_image",
                            "image_url": data_url,
                        },
                    ],
                }
            ],
        )

        # ניסיון ראשון: להשתמש ב-helper אם קיים
        raw_text = getattr(response, "output_text", "") or ""
        logger.debug(
            "ocr_image_to_text | output_text_length=%s value_preview=%r",
            len(raw_text),
            raw_text[:200],
        )

        # Fallback: אם output_text ריק, לנסות לאסוף טקסט מה-output הגולמי (אם יש)
        if not raw_text and getattr(response, "output", None):
            parts: list[str] = []
            try:
                for item in response.output:
                    content = getattr(item, "content", None)
                    if not content:
                        continue
                    for c in content:
                        c_type = getattr(c, "type", None)
                        # בגרסאות שונות זה יכול להיקרא "output_text" או "text"
                        if c_type in ("output_text", "text"):
                            text_val = getattr(c, "text", "") or ""
                            if text_val:
                                parts.append(text_val)
                raw_text = " ".join(parts)
                logger.debug(
                    "ocr_image_to_text | fallback_output_text_length=%s value_preview=%r",
                    len(raw_text),
                    raw_text[:200],
                )
            except Exception as parse_exc:
                logger.error(
                    "ocr_image_to_text | error parsing response.output | error=%s",
                    parse_exc,
                )

        if not raw_text:
            logger.warning("ocr_image_to_text | empty OCR result from Vision")
            return ""

        # נרמול בסיסי – הפיכת רווחים מרובים לרווח אחד, הסרת רווחים בקצוות
        normalized = " ".join(raw_text.split())
        logger.debug(
            "ocr_image_to_text | normalized_text_length=%s value_preview=%r",
            len(normalized),
            normalized[:200],
        )
        return normalized.strip()

    except Exception as exc:
        logger.error("ocr_image_to_text | error=%s", exc)
        # עדיף להחזיר מחרוזת ריקה ולא להפיל את הזרימה
        return ""
