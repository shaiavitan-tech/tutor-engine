from __future__ import annotations

from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import logger
from app.tutor import tutor_engine


router = APIRouter(prefix="/stream", tags=["stream"])


class StreamHintRequest(BaseModel):
    session_id: int
    student_message: str


class StreamCheckRequest(BaseModel):
    session_id: int
    student_answer: str


@router.post("/hint")
async def stream_hint(payload: StreamHintRequest):
    """
    סטרימינג של רמז נוסף בשיחה.
    משתמש בלוגיקה של TutorEngine.generate_next_hint (כולל plan וזיהוי פתרון סופי),
    ורק מזרים את הטקסט של הרמז במקום להחזיר אותו כתגובה רגילה.
    """
    logger.info(
        "API /stream/hint | session_id=%s",
        payload.session_id,
    )

    hint_result = tutor_engine.generate_next_hint(
        session_id=payload.session_id,
        student_message=payload.student_message,
    )
    if hint_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or subject not allowed",
        )

    text = hint_result.hint_text

    async def token_generator() -> AsyncGenerator[str, None]:
        yield text

    return StreamingResponse(token_generator(), media_type="text/plain")


@router.post("/check")
async def stream_check(payload: StreamCheckRequest):
    """
    סטרימינג של בדיקת תשובה סופית.
    קורא ל-TutorEngine.check_answer (ששומר attempt + mastery),
    ואז מזרים את טקסט הפידבק.
    """
    logger.info(
        "API /stream/check | session_id=%s",
        payload.session_id,
    )

    result = tutor_engine.check_answer(
        session_id=payload.session_id,
        student_answer=payload.student_answer,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or subject not allowed",
        )

    text = result.feedback_text

    async def token_generator() -> AsyncGenerator[str, None]:
        yield text

    return StreamingResponse(token_generator(), media_type="text/plain")
