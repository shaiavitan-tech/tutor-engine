from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import app_config, logger
from app.domain.model import Subject
from app.student.models import (
    Student,
    SkillModel,
    StudentSkillMastery,
    Exercise,
    Session as DbSession,
    Turn,
    Attempt,
)


# === Student & Skills ===

def get_or_create_student(db: Session, name: str) -> Student:
    logger.debug("get_or_create_student | name=%s", name)
    stmt = select(Student).where(Student.name == name)
    student = db.execute(stmt).scalar_one_or_none()

    if student:
        logger.debug("Student found | id=%s name=%s", student.id, student.name)
        return student

    student = Student(name=name)
    db.add(student)
    db.flush()  # כדי לקבל id לפני commit
    logger.info("Student created | id=%s name=%s", student.id, student.name)
    return student


def get_or_create_skill(
    db: Session,
    code: str,
    subject: Subject,
    description: str = "",
) -> SkillModel:
    logger.debug("get_or_create_skill | code=%s subject=%s", code, subject.value)
    stmt = select(SkillModel).where(SkillModel.code == code)
    skill = db.execute(stmt).scalar_one_or_none()

    if skill:
        return skill

    skill = SkillModel(
        code=code,
        subject=subject.value,
        description=description or code,
    )
    db.add(skill)
    db.flush()
    logger.info("Skill created | id=%s code=%s", skill.id, skill.code)
    return skill


def get_student_skill_mastery(
    db: Session,
    student_id: int,
) -> Dict[str, float]:
    """
    מחזיר mapping של skill_code → mastery עבור תלמיד.
    """
    logger.debug("get_student_skill_mastery | student_id=%s", student_id)
    stmt = (
        select(StudentSkillMastery)
        .options(joinedload(StudentSkillMastery.skill))
        .where(StudentSkillMastery.student_id == student_id)
    )
    records = db.execute(stmt).scalars().all()

    mastery_map = {rec.skill.code: rec.mastery for rec in records}
    logger.debug(
        "student mastery loaded | student_id=%s skill_count=%s",
        student_id,
        len(mastery_map),
    )
    return mastery_map


def update_skill_mastery(
    db: Session,
    student_id: int,
    skill_code: str,
    subject: Subject,
    delta: float,
) -> None:
    """
    מעדכן mastery למיומנות מסוימת – מוסיף delta, תוך שמירה על min/max מהקונפיג.
    """
    cfg = app_config.tutor.mastery
    logger.debug(
        "update_skill_mastery | student_id=%s skill_code=%s delta=%.4f",
        student_id,
        skill_code,
        delta,
    )

    skill = get_or_create_skill(db, code=skill_code, subject=subject)
    stmt = select(StudentSkillMastery).where(
        StudentSkillMastery.student_id == student_id,
        StudentSkillMastery.skill_id == skill.id,
    )
    record = db.execute(stmt).scalar_one_or_none()

    if not record:
        record = StudentSkillMastery(
            student_id=student_id,
            skill_id=skill.id,
            mastery=0.0,
        )
        db.add(record)
        db.flush()
        logger.info(
            "StudentSkillMastery created | student_id=%s skill_code=%s",
            student_id,
            skill_code,
        )

    new_mastery = record.mastery + delta
    new_mastery = max(cfg.min_mastery, min(cfg.max_mastery, new_mastery))
    logger.debug(
        "StudentSkillMastery update | student_id=%s skill_code=%s old=%.4f new=%.4f",
        student_id,
        skill_code,
        record.mastery,
        new_mastery,
    )

    record.mastery = new_mastery
    record.last_updated = datetime.utcnow()


# === Exercises & Sessions ===

def create_exercise(
    db: Session,
    raw_text: str,
    subject: Subject,
    source_type: str,
    image_path: Optional[str],
    detected_skill_codes: Optional[List[str]] = None,
) -> Exercise:
    logger.debug(
        "create_exercise | subject=%s source_type=%s image_path=%s",
        subject.value,
        source_type,
        image_path,
    )
    exercise = Exercise(
        raw_text=raw_text,
        subject=subject.value,
        source_type=source_type,
        image_path=image_path,
        detected_skills={"codes": detected_skill_codes or []},
    )
    db.add(exercise)
    db.flush()
    logger.info("Exercise created | id=%s subject=%s", exercise.id, subject.value)
    return exercise


def create_session(
    db: Session,
    student_id: int,
    exercise_id: int,
) -> DbSession:
    logger.debug(
        "create_session | student_id=%s exercise_id=%s",
        student_id,
        exercise_id,
    )
    session = DbSession(
        student_id=student_id,
        exercise_id=exercise_id,
    )
    db.add(session)
    db.flush()
    logger.info("Session created | id=%s", session.id)
    return session


def mark_session_finished(db: Session, session_id: int) -> None:
    stmt = select(DbSession).where(DbSession.id == session_id)
    session = db.execute(stmt).scalar_one_or_none()
    if not session:
        logger.warning("mark_session_finished | session not found | id=%s", session_id)
        return
    session.finished_at = datetime.utcnow()
    logger.debug("Session marked as finished | id=%s", session_id)


# === Turns & Attempts ===

def add_turn(
    db: Session,
    session_id: int,
    role: str,
    message_text: str,
    hint_level: Optional[int] = None,
) -> Turn:
    logger.debug(
        "add_turn | session_id=%s role=%s hint_level=%s",
        session_id,
        role,
        hint_level,
    )
    turn = Turn(
        session_id=session_id,
        role=role,
        message_text=message_text,
        hint_level=hint_level,
    )
    db.add(turn)
    db.flush()
    return turn


def add_attempt(
    db: Session,
    session_id: int,
    answer_text: str,
    is_correct: bool,
    feedback_text: str,
) -> Attempt:
    logger.debug(
        "add_attempt | session_id=%s is_correct=%s",
        session_id,
        is_correct,
    )
    attempt = Attempt(
        session_id=session_id,
        answer_text=answer_text,
        is_correct=is_correct,
        feedback_text=feedback_text,
    )
    db.add(attempt)
    db.flush()
    return attempt


def get_session_with_history(
    db: Session,
    session_id: int,
) -> Optional[DbSession]:
    """
    מחזיר Session כולל turns ו-attempts (Eager load) – לשימוש ב-TutorEngine.
    """
    logger.debug("get_session_with_history | session_id=%s", session_id)

    stmt = (
        select(DbSession)
        .where(DbSession.id == session_id)
        .options(
            joinedload(DbSession.turns),
            joinedload(DbSession.attempts),
            joinedload(DbSession.student),
            joinedload(DbSession.exercise),
        )
    )

    result = db.execute(stmt)
    session = result.unique().scalars().one_or_none()

    if session is None:
        logger.warning(
            "get_session_with_history | session not found | session_id=%s",
            session_id,
        )

    return session
