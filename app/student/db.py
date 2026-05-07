from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import logger
from app.student.models import Base

# ==================== הגדרת ה-DB ====================

# ברירת מחדל: tutor.db ב-root של הפרויקט (ליד requirements.txt)
# ברנדר אפשר לשנות דרך משתנה סביבה DB_PATH אם צריך
_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),  # app/student/
    "..",                                         # app/
    "..",                                         # project root
    "tutor.db"
)
DB_PATH = os.getenv("DB_PATH", os.path.normpath(_DEFAULT_DB_PATH))

# וודא שהתיקייה קיימת לפני פתיחת ה-DB
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def init_db() -> None:
    """
    יצירת טבלאות – לקרוא פעם אחת ב-startup.
    """
    logger.info(
        "Initializing database and creating tables if not exist | DB_PATH=%s",
        DB_PATH,
    )
    Base.metadata.create_all(bind=engine)


@contextmanager
def db_session_scope() -> Iterator[Session]:
    """
    Context manager לניהול Session.
    """
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as exc:
        logger.error("DB error, rolling back transaction | error=%s", exc)
        db.rollback()
        raise
    finally:
        db.close()