from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional, TypedDict

from openai import OpenAI

from app.core.config import logger

VISION_MODEL = "gpt-4.1-mini"  # או gpt-4o / gpt-4o-mini


class OcrExercise(TypedDict, total=False):
    id: int
    text: str
    section_label: Optional[str]
    topic: str              # "algebra" | "geometry" | "english" | "other"
    has_diagram: bool


class OcrResult(TypedDict):
    instructions: str
    exercises: List[OcrExercise]


async def ocr_image_to_text(image_bytes: bytes) -> OcrResult:
    """
    OCR אמיתי באמצעות OpenAI Vision:
    - מחזיר אובייקט:
      {
        "instructions": str,
        "exercises": [
            {
              "id": int,
              "text": str,
              "section_label": Optional[str],
              "topic": "algebra"|"geometry"|"english"|"other",
              "has_diagram": bool
            }, ...
        ]
      }
    """
    if not image_bytes:
        logger.warning("ocr_image_to_text | empty image_bytes")
        return {"instructions": "", "exercises": []}

    try:
        logger.info(
            "ocr_image_to_text | calling OpenAI Vision | model=%s",
            VISION_MODEL,
        )

        client = OpenAI()

        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64_image}"

        prompt = (
            "You are an OCR and worksheet parser for K-12 math, geometry, and English.\n\n"
            "GOAL:\n"
            "- Analyze the entire image (including tables, multi-column layouts, and diagrams).\n"
            "- Extract a structured representation of the page as JSON.\n\n"
            "REQUIREMENTS:\n"
            "1. Identify any general instructions on the page (e.g. "
            "\"Solve the following equations\", \"Read the text and answer the questions\"). "
            "Return them as a single string in 'instructions'. If none, use an empty string.\n"
            "2. Identify each exercise separately. An exercise can be:\n"
            "   - An equation or system of equations (e.g. 'x^2 + 5 = 14', '3x + 2y = 7, x - y = 1').\n"
            "   - A geometry problem, possibly referring to a drawn figure.\n"
            "   - A reading comprehension question in English.\n"
            "   - Any other stand-alone question or task.\n"
            "3. For each exercise, extract:\n"
            "   - 'id': a running integer starting from 1.\n"
            "   - 'text': the full exercise text as a single line, WITHOUT section letters or numbering.\n"
            "   - 'section_label': the section label if it exists (e.g. 'א', 'ב', 'a', 'b', '1)', '2)'), "
            "     otherwise null.\n"
            "   - 'topic': one of 'algebra', 'geometry', 'english', or 'other'.\n"
            "   - 'has_diagram': true if the exercise clearly refers to a diagram/figure on the page, "
            "     otherwise false.\n"
            "4. When removing section labels, do NOT lose any part of the actual exercise text.\n"
            "5. If the page contains an English reading passage followed by questions, keep the questions "
            "   as separate exercises.\n"
            "6. Return a SINGLE JSON object with this EXACT structure:\n"
            "{\n"
            '  \"instructions\": \"string (may be empty)\",\n'
            '  \"exercises\": [\n'
            '    {\n'
            '      \"id\": 1,\n'
            '      \"text\": \"exercise 1 text without section label\",\n'
            '      \"section_label\": null,\n'
            '      \"topic\": \"algebra\",\n'
            '      \"has_diagram\": false\n'
            '    }\n'
            '  ]\n'
            "}\n"
            "Do NOT include any extra keys or commentary. Do NOT solve the exercises.\n"
        )

        resp = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            max_tokens=800,
        )

        raw_text = ""
        try:
            choice = resp.choices[0]
            msg = choice.message
            if isinstance(msg.content, str):
                raw_text = msg.content
            elif isinstance(msg.content, list):
                parts: List[str] = []
                for c in msg.content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        parts.append(c.get("text", ""))
                raw_text = " ".join(parts)
        except Exception as parse_exc:
            logger.error(
                "ocr_image_to_text | error parsing chat.completions response | error=%s",
                parse_exc,
            )
            return {"instructions": "", "exercises": []}

        logger.debug(
            "ocr_image_to_text | raw_text_length=%s preview=%r",
            len(raw_text),
            raw_text[:300],
        )

        if not raw_text:
            logger.warning("ocr_image_to_text | empty OCR result from Vision")
            return {"instructions": "", "exercises": []}

        # ניסיון לפענח כ‑JSON (כולל strip של ```json ``` אם צריך)
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].lstrip()
            try:
                data = json.loads(cleaned)
            except Exception as exc:
                logger.error(
                    "ocr_image_to_text | response is not valid JSON | error=%s preview=%r",
                    exc,
                    raw_text[:300],
                )
                return {"instructions": "", "exercises": []}

        instructions = (data.get("instructions") or "").strip()
        exercises_raw = data.get("exercises") or []
        if not isinstance(exercises_raw, list):
            exercises_raw = []

        exercises: List[OcrExercise] = []
        for idx, ex in enumerate(exercises_raw, start=1):
            if not isinstance(ex, dict):
                continue

            text = (ex.get("text") or "").strip()
            if not text:
                continue

            section_label = ex.get("section_label")
            if isinstance(section_label, str):
                section_label = section_label.strip() or None
            else:
                section_label = None

            topic = (ex.get("topic") or "other").strip().lower()
            if topic not in ("algebra", "geometry", "english", "other"):
                topic = "other"

            has_diagram = bool(ex.get("has_diagram"))

            exercises.append(
                OcrExercise(
                    id=ex.get("id") or idx,
                    text=text,
                    section_label=section_label,
                    topic=topic,
                    has_diagram=has_diagram,
                )
            )

        logger.debug(
            "ocr_image_to_text | instructions_len=%s exercises_count=%s first_ex_preview=%r",
            len(instructions),
            len(exercises),
            exercises[0]["text"][:120] if exercises else "",
        )

        return {
            "instructions": instructions,
            "exercises": exercises,
        }


    except Exception as exc:
        logger.error("ocr_image_to_text | error=%s", exc)
        return {"instructions": "", "exercises": []}
