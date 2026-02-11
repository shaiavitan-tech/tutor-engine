from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    String,
    Integer,
    Float,
    DateTime,
    Boolean,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)

    skill_mastery: Mapped[List["StudentSkillMastery"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[List["Session"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
    )


class SkillModel(Base):
    """
    מודל DB ל-Skill (נפרד מה-Skill הדאטה-קלאס ב-domain).
    """
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(50), index=True)
    description: Mapped[str] = mapped_column(String(255))

    mastery_records: Mapped[List["StudentSkillMastery"]] = relationship(
        back_populates="skill",
        cascade="all, delete-orphan",
    )


class StudentSkillMastery(Base):
    __tablename__ = "student_skill_mastery"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), index=True)

    mastery: Mapped[float] = mapped_column(Float, default=0.0)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    student: Mapped["Student"] = relationship(back_populates="skill_mastery")
    skill: Mapped["SkillModel"] = relationship(back_populates="mastery_records")


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    raw_text: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(String(50), index=True)
    source_type: Mapped[str] = mapped_column(String(20))  # image / text
    image_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    detected_skills: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    sessions: Mapped[List["Session"]] = relationship(
        back_populates="exercise",
        cascade="all, delete-orphan",
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"), index=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    student: Mapped["Student"] = relationship(back_populates="sessions")
    exercise: Mapped["Exercise"] = relationship(back_populates="sessions")
    turns: Mapped[List["Turn"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Turn.created_at",
    )
    attempts: Mapped[List["Attempt"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Attempt.evaluated_at",
    )


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)

    role: Mapped[str] = mapped_column(String(20))  # "student" / "tutor"
    message_text: Mapped[str] = mapped_column(String)
    hint_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    session: Mapped["Session"] = relationship(back_populates="turns")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)

    answer_text: Mapped[str] = mapped_column(String)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback_text: Mapped[str] = mapped_column(String)

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    session: Mapped["Session"] = relationship(back_populates="attempts")
