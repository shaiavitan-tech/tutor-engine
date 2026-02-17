from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, status
from pydantic import BaseModel

from app.core.config import logger
from app.domain.filters import ensure_allowed_subject, build_off_topic_response
from app.domain.model import QuestionClassification, Subject
from app.tutor import tutor_engine          # ← זה הייבוא הנכון
from app.vision.ocr import ocr_image_to_text

router = APIRouter(prefix="/exercises", tags=["exercises"])


# ========= מודלים =========

class StartFromTextRequest(BaseModel):
    student_name: str = "Shira"
    question_text: str


class StartFromTextResponse(BaseModel):
    allowed: bool
    session_id: Optional[int] = None
    question_text: Optional[str] = None
    subject: Optional[str] = None
    skills: Optional[list[str]] = None
    hint_text: Optional[str] = None
    hint_level: Optional[int] = None
    message: Optional[str] = None


class StartFromImageResponse(BaseModel):
    """
    הפעלה מתמונה יכולה לייצר:
    - עבור חשבון/גאומטריה: תרגיל אחד או סט תרגילים (exercises).
    - עבור אנגלית: tasks_summary + tasks טקסטואליים.
    - בנוסף: אם בחרנו תרגיל ראשון והתחלנו session, נחזיר גם רמז ראשון כרגיל.
    """
    allowed: bool
    # אם התחיל session עבור תרגיל ראשון
    session_id: Optional[int] = None
    question_text: Optional[str] = None
    subject: Optional[str] = None
    skills: Optional[list[str]] = None
    hint_text: Optional[str] = None
    hint_level: Optional[int] = None

    # מידע כללי לסט תרגילים (חשבון / גאומטריה)
    exercises: Optional[list[str]] = None

    # מידע לדפי אנגלית
    tasks_summary: Optional[str] = None
    tasks: Optional[list[str]] = None

    message: Optional[str] = None


# ========= עזר פנימי =========

def _split_ocr_to_math_exercises(text: str) -> list[str]:
    """
    פיצול גס של OCR לחשבון/גאומטריה:
    לוקח שורות שיש בהן לפחות ספרה או סימן מתמטי.
    """
    text = text.replace("\r", "")
    lines = [ln.strip() for ln in text.split("\n")]
    exercises: list[str] = []

    for ln in lines:
        if not ln:
            continue
        has_digit = any(ch.isdigit() for ch in ln)
        has_math_sym = any(ch in "+-*/=%" for ch in ln)
        if has_digit or has_math_sym:
            exercises.append(ln)

    if not exercises and text.strip():
        exercises = [text.strip()]

    return exercises


# ========= טקסט =========

@router.post("/start_from_text", response_model=StartFromTextResponse)
async def start_from_text(payload: StartFromTextRequest):
    logger.info(
        "API /exercises/start_from_text | student=%s",
        payload.student_name,
    )

    classification: QuestionClassification | None = ensure_allowed_subject(
        payload.question_text
    )
    if classification is None:
        logger.info("start_from_text | off-topic question")
        return StartFromTextResponse(
            allowed=False,
            message=build_off_topic_response(),
        )

    result = tutor_engine.generate_hint_for_new_exercise(
        student_name=payload.student_name,
        question=classification,
        raw_text=payload.question_text,
        source_type="text",
        image_path=None,
    )

    if not result.get("allowed", True):
        return StartFromTextResponse(
            allowed=False,
            message=build_off_topic_response(),
        )

    return StartFromTextResponse(
        allowed=True,
        session_id=result["session_id"],
        question_text=result["question_text"],
        subject=result["subject"],
        skills=result["skills"],
        hint_text=result["hint_text"],
        hint_level=result["hint_level"],
    )


# ========= תמונה – סט תרגילים / משימות =========

@router.post("/start_from_image", response_model=StartFromImageResponse)
async def start_from_image(
    student_name: str = "Shira",
    file: UploadFile = File(...),
):
    """
    OCR לתמונה + התחלת תרגיל:
    - חשבון/גאומטריה (subject=MATH): מפיק רשימת תרגילים מתוך ה-OCR,
      מתחיל תרגיל ראשון (session + hint) ומחזיר גם את כל הרשימה ב-exercises.
    - אנגלית (subject=ENGLISH): מחזיר tasks_summary + tasks (ללא session),
      כדי שה-frontend יעבוד איתן כמו עם "תרגיל טקסט" רגיל.
    """
    logger.info(
        "API /exercises/start_from_image | student=%s filename=%s",
        student_name,
        file.filename,
    )

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty image",
        )

    # --- OCR חדש: מחזיר אובייקט מובנה ---
    ocr_result = await ocr_image_to_text(image_bytes)
    instructions = ocr_result.get("instructions", "") or ""
    ocr_exercises = ocr_result.get("exercises", []) or []

    if not ocr_exercises:
        logger.info("start_from_image | empty OCR result (no exercises)")
        return StartFromImageResponse(
            allowed=False,
            message="לא הצלחתי לקרוא את הטקסט מהתמונה. נסי שוב עם תמונה ברורה יותר.",
        )

    # מחברים הוראות + כל התרגילים לצורך סיווג נושא
    combined_text_parts: list[str] = []
    if instructions.strip():
        combined_text_parts.append(instructions.strip())
    combined_text_parts.extend(
        ex.get("text", "") for ex in ocr_exercises if ex.get("text")
    )
    combined_text = "\n".join(p for p in combined_text_parts if p.strip())

    logger.debug(
        "start_from_image | OCR combined_text length=%s",
        len(combined_text),
    )

    classification: QuestionClassification | None = ensure_allowed_subject(combined_text)
    if classification is None:
        logger.info("start_from_image | off-topic question after OCR")
        return StartFromImageResponse(
            allowed=False,
            message=build_off_topic_response(),
        )

    subject = classification.subject
    logger.info(
        "start_from_image | classified subject=%s",
        subject.value,
    )

    # --- 1. חשבון / גאומטריה (Subject.MATH) ---
    if subject == Subject.MATH:
        # טקסטי התרגילים כפי שחולצו מה-OCR (כבר בלי סעיפים)
        exercises_text = [ex["text"] for ex in ocr_exercises if ex.get("text")]
        logger.debug(
            "start_from_image | math/geometry raw_exercises_count=%s",
            len(exercises_text),
        )

        if not exercises_text:
            return StartFromImageResponse(
                allowed=False,
                message="לא הצלחתי לזהות תרגילי חשבון/גאומטריה בתמונה.",
            )

        # שמירה על ההתנהגות הקיימת: עדיין משתמשים ב-_split_ocr_to_math_exercises על טקסט שורות
        raw_for_split = "\n".join(exercises_text)
        exercises = _split_ocr_to_math_exercises(raw_for_split)
        logger.debug(
            "start_from_image | math/geometry exercises_count_after_split=%s",
            len(exercises),
        )

        if not exercises:
            # fallback: אם הפונקציה לא חילקה כלום, משתמשים ברשימה שכבר יש לנו
            exercises = exercises_text

        # נתחיל session ורמז רק לתרגיל הראשון; השאר יטופלו בצד ה-frontend
        first_question_text = exercises[0]

        result = tutor_engine.generate_hint_for_new_exercise(
            student_name=student_name,
            question=classification,
            raw_text=first_question_text,
            source_type="image",
            image_path=None,  # אם תשמור לדיסק – תעדכן כאן
        )

        if not result.get("allowed", True):
            return StartFromImageResponse(
                allowed=False,
                message=build_off_topic_response(),
            )

        return StartFromImageResponse(
            allowed=True,
            session_id=result["session_id"],
            question_text=result["question_text"],
            subject=result["subject"],
            skills=result["skills"],
            hint_text=result["hint_text"],
            hint_level=result["hint_level"],
            exercises=exercises,
        )

    # --- 2. אנגלית ---
    if subject == Subject.ENGLISH:
        # בשלב ראשון: כל הטקסט המאוחד כמשימה אחת; אפשר לשדרג אחר כך לפירוק לפי exercises
        normalized = classification.normalized_question or combined_text.strip()

        summary = (
            "זיהיתי דף תרגול באנגלית. "
            "נעבור יחד על המשימה/המשימות ונבין מה צריך לעשות, ואז נפתור אותן ביחד."
        )

        tasks = [normalized]

        return StartFromImageResponse(
            allowed=True,
            subject=subject.value,
            tasks_summary=summary,
            tasks=tasks,
        )

    # --- 3. OTHER / לא נתמך ---
    logger.info("start_from_image | subject OTHER")
    return StartFromImageResponse(
        allowed=False,
        subject=subject.value,
        message=build_off_topic_response(),
    )
