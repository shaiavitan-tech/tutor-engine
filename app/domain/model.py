from __future__ import annotations

from enum import Enum
from dataclasses import dataclass
from typing import List, Optional


class Subject(str, Enum):
    ENGLISH = "english"
    MATH = "math"
    OTHER = "other"


@dataclass(frozen=True)
class Skill:
    """
    מיומנות בודדת בתוך תחום – לדוגמה:
    - ENGLISH: grammar_past_simple, vocabulary_school
    - MATH: algebra_linear_equations, fractions_basic
    """
    code: str
    subject: Subject
    description: str


@dataclass
class QuestionClassification:
    """
    תוצאה של סיווג שאלה/טקסט:
    - subject: תחום (אנגלית/מתמטיקה/אחר)
    - skills: רשימת מיומנויות משוערות
    - normalized_question: טקסט מנורמל שהטוטור יעבוד עליו
    """
    subject: Subject
    skills: List[Skill]
    normalized_question: str


# מאגר ראשוני של מיומנויות בסיס – אפשר להרחיב אחר כך מה-DB
BASE_SKILLS: List[Skill] = [
    Skill(
        code="eng_grammar_past_simple",
        subject=Subject.ENGLISH,
        description="Past Simple grammar and sentence structure",
    ),
    Skill(
        code="eng_vocabulary_general",
        subject=Subject.ENGLISH,
        description="General English vocabulary for middle school",
    ),
    Skill(
        code="math_arithmetic_basics",
        subject=Subject.MATH,
        description="Basic arithmetic: addition, subtraction, multiplication, division",
    ),
    Skill(
        code="math_linear_equations",
        subject=Subject.MATH,
        description="Solving single-variable linear equations",
    ),
]


ALLOWED_SUBJECTS = {Subject.ENGLISH, Subject.MATH}


def is_allowed_subject(subject: Subject) -> bool:
    """
    מחזיר האם התחום מותר (אנגלית/מתמטיקה).
    """
    return subject in ALLOWED_SUBJECTS


def _guess_subject_by_keywords(text: str) -> Subject:
    """
    סיווג מהיר לפי מילות מפתח כסף ראשון – אפשר לשדרג אח״כ ל-LLM / מודל כוונה.
    """
    lowered = text.lower()

    # זיהוי מתמטיקה – מספרים, סימנים, מילים אופייניות
    math_keywords = [
        "solve", "equation", "fraction", "percent", "percentage",
        "x +", "x -", "x *", "x /", "=", "triangle", "angle",
        "algebra", "geometry",
    ]
    english_keywords = [
        "translate", "grammar", "verb", "tense", "sentence",
        "past simple", "present simple", "present progressive",
        "vocabulary", "word", "meaning", "synonym",
    ]

    if any(k in lowered for k in math_keywords):
        return Subject.MATH
    if any(k in lowered for k in english_keywords):
        return Subject.ENGLISH

    # fallback – אם יש הרבה ספרות/סימנים מתמטיים, כנראה מתמטיקה
    digit_count = sum(ch.isdigit() for ch in lowered)
    math_symbol_count = sum(ch in "+-*/=%" for ch in lowered)
    if digit_count + math_symbol_count >= 3:
        return Subject.MATH

    return Subject.OTHER


def _guess_skills_for_math(text: str) -> List[Skill]:
    lowered = text.lower()
    skills: List[Skill] = []

    if any(sym in lowered for sym in ["+", "-", "*", "/", "%"]):
        skills.append(_get_skill_by_code("math_arithmetic_basics"))

    if any(token in lowered for token in ["equation", "solve for x", "x +", "x -", "x *", "x /"]):
        skills.append(_get_skill_by_code("math_linear_equations"))

    # ברירת מחדל – אם לא זיהינו כלום אבל זה מתמטיקה, לפחות מיומנות בסיסית
    if not skills:
        skills.append(_get_skill_by_code("math_arithmetic_basics"))

    return skills


def _guess_skills_for_english(text: str) -> List[Skill]:
    lowered = text.lower()
    skills: List[Skill] = []

    if any(token in lowered for token in ["past simple", "yesterday", "last week", "ago"]):
        skills.append(_get_skill_by_code("eng_grammar_past_simple"))

    if any(token in lowered for token in ["translate", "meaning", "synonym", "definition"]):
        skills.append(_get_skill_by_code("eng_vocabulary_general"))

    # ברירת מחדל – אם לא זיהינו כלום אבל זה אנגלית, מיומנות vocabulary כללית
    if not skills:
        skills.append(_get_skill_by_code("eng_vocabulary_general"))

    return skills


def _normalize_question_text(text: str) -> str:
    """
    ניקוי בסיסי של טקסט השאלה כדי לשלוח ל-LLM בצורה עקבית.
    (אפשר לשפר אחר כך ל-normalization חכם יותר.)
    """
    normalized = " ".join(text.split())
    return normalized.strip()


def _get_skill_by_code(code: str) -> Skill:
    for skill in BASE_SKILLS:
        if skill.code == code:
            return skill
    # אם לא מצאנו – נייצר Skill דינמי כללי, כדי לא להפיל את הזרימה
    # אבל נרצה לעקוב אחרי זה בלוגים
    return Skill(
        code=code,
        subject=Subject.OTHER,
        description=f"Unknown skill code `{code}` (dynamic fallback)",
    )


def classify_question(text: str) -> QuestionClassification:
    """
    סיווג שאלה לטובת הטוטור:
    - קובע subject (ENGLISH / MATH / OTHER).
    - מעריך skills רלוונטיים.
    - מחזיר normalized_question.

    בשלב ראשון זה rule-based; אפשר להחליף למודל ML/LLM בלי לשנות את ה-API.
    """
    if not text or not text.strip():
        return QuestionClassification(
            subject=Subject.OTHER,
            skills=[],
            normalized_question="",
        )

    subject = _guess_subject_by_keywords(text)

    if subject == Subject.MATH:
        skills = _guess_skills_for_math(text)
    elif subject == Subject.ENGLISH:
        skills = _guess_skills_for_english(text)
    else:
        skills = []

    normalized_question = _normalize_question_text(text)

    return QuestionClassification(
        subject=subject,
        skills=skills,
        normalized_question=normalized_question,
    )
