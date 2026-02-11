from __future__ import annotations

from typing import Optional

from .model import Subject, QuestionClassification, classify_question, is_allowed_subject


OFF_TOPIC_MESSAGE = (
    "אני עוזר רק בלמידה ותרגול של אנגלית ומתמטיקה. "
    "בואי נבחר יחד תרגיל או שאלה בתחום הזה 🙂"
)


def is_math_or_english_question(text: str) -> bool:
    """
    בדיקה מהירה האם השאלה עוסקת באנגלית/מתמטיקה בלבד.
    משתמש ב-classify_question כדי להישאר עקביים.
    """
    classification: QuestionClassification = classify_question(text)
    return is_allowed_subject(classification.subject)


def ensure_allowed_subject(text: str) -> Optional[QuestionClassification]:
    """
    מוודא שהשאלה בתחום מותר.
    - אם השאלה באנגלית/מתמטיקה → מחזיר QuestionClassification.
    - אחרת → מחזיר None (והשכבה מעל תחזיר ללקוח הודעת off-topic).
    """
    classification = classify_question(text)

    if not is_allowed_subject(classification.subject):
        return None

    return classification


def build_off_topic_response() -> str:
    """
    הודעת ברירת מחדל למקרה שהשאלה לא באנגלית או מתמטיקה.
    """
    return OFF_TOPIC_MESSAGE
