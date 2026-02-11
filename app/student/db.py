from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import logger
from app.student.models import Base

# ==================== הגדרת ה-DB ====================

# ברירת מחדל מקומית: ./tutor.db
# ברנדר תגדיר משתנה סביבה DB_PATH=/var/data/tutor.db
DB_PATH = os.getenv("DB_PATH", "./tutor.db")

# sqlite:/// + path יחסי או מוחלט (SQLAlchemy יטפל ב-scheme נכון)
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # רק ל-SQLite
    echo=False,  # אפשר להפוך ל-True לדיבאג SQL
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
    Context manager לניהול Session:
    - נפתח בתחילת בלוק.
    - commit בסיום.
    - rollback אוטומטי במקרה של שגיאה.
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
