from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.config import logger
from app.domain.filters import is_math_or_english_question, build_off_topic_response
from app.tutor.engine import TutorEngine

router = APIRouter(prefix="/sessions", tags=["sessions"])


class StudentReplyRequest(BaseModel):
    session_id: int
    message: str
    mode: str  # "continue_hints" or "final_answer"


class StudentReplyResponse(BaseModel):
    done: bool
    tutor_message: str
    hint_level: Optional[int] = None
    is_correct: Optional[bool] = None


@router.post("/reply", response_model=StudentReplyResponse)
async def student_reply(payload: StudentReplyRequest):
    logger.info(
        "API /sessions/reply | session_id=%s mode=%s",
        payload.session_id,
        payload.mode,
    )

    # Guard נוסף: כל הודעה נבדקת אם היא עדיין בתחום אנגלית/מתמטיקה
    if not is_math_or_english_question(payload.message):
        logger.info(
            "student_reply | off-topic message in existing session | session_id=%s",
            payload.session_id,
        )
        return StudentReplyResponse(
            done=False,
            tutor_message=build_off_topic_response(),
            hint_level=None,
            is_correct=None,
        )

    if payload.mode == "continue_hints":
        hint_result = tutor_engine.generate_next_hint(
            session_id=payload.session_id,
            student_message=payload.message,
        )
        if hint_result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or subject not allowed",
            )
        return StudentReplyResponse(
            done=False,
            tutor_message=hint_result.hint_text,
            hint_level=hint_result.hint_level,
            is_correct=None,
        )

    if payload.mode == "final_answer":
        check_result = tutor_engine.check_answer(
            session_id=payload.session_id,
            student_answer=payload.message,
        )
        if check_result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or subject not allowed",
            )
        return StudentReplyResponse(
            done=True,
            tutor_message=check_result.feedback_text,
            hint_level=None,
            is_correct=check_result.is_correct,
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid mode, use 'continue_hints' or 'final_answer'",
    )
