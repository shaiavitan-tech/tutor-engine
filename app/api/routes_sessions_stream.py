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

    # נשתמש במנוע המרכזי כדי לקבל את הרמז הבא (עם כל הלוגיקה החדשה)
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
        # אם חשוב לך ממש סטרימינג טוקן-טוקן מהמודל, אפשר להחליף שוב ל-chat_completion_stream,
        # אבל אז צריך להכניס לשם את ה-prompts מה-Engine. כרגע נזרים את הטקסט כמקשה אחת.
        yield text

    return StreamingResponse(token_generator(), media_type="text/plain")

