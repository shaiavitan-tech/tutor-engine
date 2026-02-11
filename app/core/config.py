from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Set

from app.domain.model import Subject


# === Logging setup בסיסי – אפשר להחליף אח"כ ל-structlog / JSON ===

LOGGER_NAME = "tutor_app"
from dotenv import load_dotenv
load_dotenv()

def get_logger() -> logging.Logger:
    """
    מחזיר Logger אפליקטיבי מרכזי.
    שים לב: לא ליצור לוגרים שונים בכל מודול, אלא להשתמש בשם אחיד + child loggers.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        # הגדרה בסיסית – ל-dev. ב-prod אפשר לעדכן רמה/פורמט/handlers.
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
    return logger


logger = get_logger()


@dataclass(frozen=True)
class MasteryConfig:
    """
    הגדרות עדכון mastery – כדי שתוכל לשחק עם הערכים בקלות.
    """
    correct_delta: float = 0.05
    incorrect_delta: float = -0.02
    min_mastery: float = 0.0
    max_mastery: float = 1.0


@dataclass(frozen=True)
class HintConfig:
    """
    הגדרת רמות רמז והתנהגות בסיסית.
    """
    max_hint_level: int = 3
    initial_hint_level: int = 1


@dataclass(frozen=True)
class TutorConfig:
    """
    קונפיג כללי של הטוטור.
    """
    allowed_subjects: Set[Subject]
    mastery: MasteryConfig
    hints: HintConfig
    default_language_level: str = "grade_8"
    tutor_name: str = "ShiraTutor"


@dataclass(frozen=True)
class AppConfig:
    """
    קונפיג גלובלי – נוכל להרחיב ל-DB, API keys וכו'.
    """
    tutor: TutorConfig


def build_default_config() -> AppConfig:
    logger.debug("Building default AppConfig")
    tutor_cfg = TutorConfig(
        allowed_subjects={Subject.ENGLISH, Subject.MATH},
        mastery=MasteryConfig(),
        hints=HintConfig(),
    )
    return AppConfig(tutor=tutor_cfg)


# אובייקט קונפיג גלובלי לשימוש בשאר המודולים
app_config: AppConfig = build_default_config()
logger.info("AppConfig initialized with allowed_subjects=%s",
            {s.value for s in app_config.tutor.allowed_subjects})
