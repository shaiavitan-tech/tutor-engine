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

        # שימוש ב-responses / chat עם vision – תבנית מומלצת בדוק. [web:163][web:170]
        response = client.responses.create(
            model=VISION_MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
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

        raw_text = response.output_text or ""
        logger.debug(
            "ocr_image_to_text | raw_text_length=%s",
            len(raw_text),
        )

        # נרמול בסיסי – אפשר להשאיר עם שורות או להפוך לשורה אחת
        normalized = " ".join(raw_text.split())
        return normalized.strip()

    except Exception as exc:
        logger.error("ocr_image_to_text | error=%s", exc)
        # עדיף להחזיר מחרוזת ריקה ולא להפיל את הזרימה
        return ""
