from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from app.core.config import app_config, logger
from app.core.prompts import (
    build_tutor_system_prompt,
    build_tutor_user_prompt_for_hint,
    build_answer_checker_system_prompt,
    build_answer_checker_user_prompt,
)
from app.domain.model import Subject, Skill, QuestionClassification
from app.student.db import db_session_scope
from app.student import crud
from app.student.models import Session as DbSession
from app.tutor.llm_client import chat_completion

LLM_TUTOR_MODEL = "gpt-4o-mini"
LLM_CHECKER_MODEL = "gpt-4o-mini"


# === Dataclasses חיצוניים ===

@dataclass
class TutorHintResult:
    hint_text: str
    hint_level: int
    new_exercise_required: bool = False


@dataclass
class AnswerCheckResult:
    is_correct: bool
    feedback_text: str


@dataclass
class SolutionStep:
    """
    צעד בודד בתכנית פתרון:
    - description: ניסוח טבעי של הצעד.
    - expression: ביטוי אלגברי/משוואה אחרי הצעד (אם רלוונטי), למשל "15x=60" או "2x=8".
    """
    description: str
    expression: Optional[str] = None


@dataclass
class SolutionPlan:
    """
    תכנית פתרון מלאה:
    - steps: רשימת צעדים, כל צעד כולל תיאור + ביטוי ביניים (אם יש).
    - final_answer: פתרון סופי קצר (x=4, משפט באנגלית וכו').
    """
    steps: List[SolutionStep]
    final_answer: str



# === המחלקה המרכזית ===

class TutorEngine:
    """
    הלוגיקה המרכזית של הטוטור:
    - ייצור רמזים.
    - בדיקת תשובות.
    - ניהול hint_level.
    - ניהול מצב תרגיל נוכחי per-session.
    """

    def __init__(self) -> None:
        self._config = app_config.tutor
        # state לכל session:
        # {
        #   session_id: {
        #       "original_question": str,
        #       "solution_steps": List[str],
        #       "final_answer": str,
        #       "current_step_index": int,
        #       "exercise_finished": bool,
        #   }
        # }
        self._session_state: Dict[int, Dict[str, Any]] = {}
        logger.debug("TutorEngine.__init__ | session_state initialized")

    # === רמזים: התחלת תרגיל חדש ===

    def generate_hint_for_new_exercise(
            self,
            student_name: str,
            question: QuestionClassification,
            raw_text: str,
            source_type: str,
            image_path: Optional[str] = None,
    ) -> Dict[str, any]:
        """
        התחלת תרגיל חדש (טקסט/תמונה):
        - יוצר student, exercise, session.
        - מייצר תכנית פתרון (SolutionPlan) ושומר ב-session_state.
        - מחזיר רמז ראשון.
        """
        logger.info(
            "TutorEngine.generate_hint_for_new_exercise | student=%s subject=%s",
            student_name,
            question.subject.value,
        )
        logger.debug(
            "generate_hint_for_new_exercise NEW | raw_text=%r subject=%s",
            raw_text,
            question.subject.value,
        )

        if not self._is_subject_allowed(question.subject):
            logger.warning(
                "generate_hint_for_new_exercise | disallowed subject=%s",
                question.subject.value,
            )
            return {
                "allowed": False,
                "reason": "subject_not_allowed",
            }

        hint_level = self._config.hints.initial_hint_level

        with db_session_scope() as db:
            # תלמיד
            student = crud.get_or_create_student(db, student_name)

            # תרגיל
            detected_skill_codes = [s.code for s in question.skills]
            exercise = crud.create_exercise(
                db=db,
                raw_text=raw_text,
                subject=question.subject,
                source_type=source_type,
                image_path=image_path,
                detected_skill_codes=detected_skill_codes,
            )
            logger.debug(
                "generate_hint_for_new_exercise | exercise_id=%s",
                exercise.id,
            )

            # session
            session = crud.create_session(
                db=db,
                student_id=student.id,
                exercise_id=exercise.id,
            )
            logger.debug(
                "generate_hint_for_new_exercise | session_id=%s",
                session.id,
            )

            # מצב סטודנט (כרגע לא בשימוש ל־LLM)
            _ = crud.get_student_skill_mastery(db, student_id=student.id)

            # מיומנויות כ־Skill
            skills: List[Skill] = question.skills

            # 1. תכנית פתרון בעזרת LLM (עם SolutionStep)
            plan = self._generate_solution_plan_llm(
                question_text=question.normalized_question,
                subject=question.subject,
                skills=skills,
            )

            # 2. שמירה ב-session_state
            #    solution_steps: List[SolutionStep] נשמר כמו שהוא, כדי ש-generate_next_hint
            #    יוכל להשתמש גם ב-expression של כל צעד.
            self._session_state[session.id] = {
                "original_question": question.normalized_question,
                "solution_steps": plan.steps,  # List[SolutionStep]
                "final_answer": plan.final_answer,
                "current_step_index": 0,
                "exercise_finished": False,
            }

            logger.debug(
                "Solution plan created | session_id=%s steps=%s final_answer=%r",
                session.id,
                len(plan.steps),
                plan.final_answer,
            )

            # 3. רמז ראשון
            #    כאן _generate_hint_llm עדיין עובד עם רשימת מחרוזות, אז מעבירים לו רק את ה-description.
            step_descriptions = [s.description for s in plan.steps]

            hint_result = self._generate_hint_llm(
                session_id=session.id,
                original_question=question.normalized_question,
                student_message=None,
                subject=question.subject,
                skills=skills,
                hint_level=hint_level,
                turns_history=[],
                solution_steps=step_descriptions,
                current_step_index=0,
                final_answer=plan.final_answer,
            )

            crud.add_turn(
                db=db,
                session_id=session.id,
                role="tutor",
                message_text=hint_result.hint_text,
                hint_level=hint_result.hint_level,
            )

            return {
                "allowed": True,
                "session_id": session.id,
                "question_text": question.normalized_question,
                "subject": question.subject.value,
                "skills": detected_skill_codes,
                "hint_text": hint_result.hint_text,
                "hint_level": hint_result.hint_level,
            }

    # === רמזים: המשך תרגיל קיים ===

    def generate_next_hint(
            self,
            session_id: int,
            student_message: str,
    ) -> Optional[TutorHintResult]:
        """
        רמז נוסף במהלך session קיים.
        - משתמש ב-session_state כדי לזהות פתרון סופי, לנהל plan וכו'.
        - אם מזהה תשובה סופית נכונה: מעדכן mastery ישירות ומחזיר פידבק סופי (בלי checker).
        - אם התשובה שקולה ל-expression של צעד מסוים ב-plan:
          מחזיר רמז דטרמיניסטי לצעד הבא בתכנית (אם קיים), בלי לקרוא ל-LLM.
        """
        logger.info(
            "TutorEngine.generate_next_hint | session_id=%s", session_id
        )

        state = self._session_state.get(session_id)
        logger.debug(
            "generate_next_hint | initial_state=%r",
            state,
        )

        with db_session_scope() as db:
            db_session: Optional[DbSession] = crud.get_session_with_history(
                db=db,
                session_id=session_id,
            )
            if not db_session:
                logger.error(
                    "generate_next_hint | session not found | session_id=%s",
                    session_id,
                )
                return None

            subject = self._parse_subject(db_session.exercise.subject)
            if not self._is_subject_allowed(subject):
                logger.warning(
                    "generate_next_hint | disallowed subject=%s session_id=%s",
                    subject.value,
                    session_id,
                )
                return None

            history_turns = sorted(db_session.turns, key=lambda t: t.created_at)
            hint_level = self._decide_next_hint_level(history_turns)

            detected_skill_codes = (db_session.exercise.detected_skills or {}).get(
                "codes", []
            )
            skills = [
                Skill(code=c, subject=subject, description=c)
                for c in detected_skill_codes
            ]

            # מוסיפים את הודעת שירה כ-turn ל-DB
            crud.add_turn(
                db=db,
                session_id=session_id,
                role="student",
                message_text=student_message,
                hint_level=None,
            )

            # טעינת state ותכנית הפתרון
            if not state:
                logger.warning(
                    "generate_next_hint | no session_state found, creating fallback | session_id=%s",
                    session_id,
                )
                state = {
                    "original_question": db_session.exercise.raw_text,
                    "solution_steps": [],
                    "final_answer": "",
                    "current_step_index": 0,
                    "exercise_finished": False,
                }
                self._session_state[session_id] = state

            original_question: str = state.get("original_question") or db_session.exercise.raw_text
            raw_steps = state.get("solution_steps", [])
            final_answer: str = state.get("final_answer", "")
            current_step_index: int = int(state.get("current_step_index", 0))
            exercise_finished: bool = bool(state.get("exercise_finished", False))

            # נוודא ש‑solution_steps הוא List[SolutionStep]
            solution_steps: List[SolutionStep] = []
            for s in raw_steps:
                if isinstance(s, SolutionStep):
                    solution_steps.append(s)
                elif isinstance(s, str):
                    solution_steps.append(SolutionStep(description=s, expression=None))
                elif isinstance(s, dict):
                    desc = str(s.get("description", "")).strip()
                    expr_raw = s.get("expression")
                    expr = str(expr_raw).strip() if isinstance(expr_raw, str) else None
                    if desc:
                        solution_steps.append(SolutionStep(description=desc, expression=expr))

            logger.debug(
                "next_hint_state | session_id=%s | original_question=%r | final_answer=%r | current_step_index=%s | student=%r | steps=%s",
                session_id,
                original_question,
                final_answer,
                current_step_index,
                student_message,
                len(solution_steps),
            )

            looks_like_exercise = "=" in student_message  # אפשר לשפר בהמשך
            is_new_exercise = False

            # --- 0. תרגיל חדש אחרי שהקודם הוגדר כסגור ---
            if exercise_finished and looks_like_exercise:
                is_different_exercise = student_message.strip() != original_question.strip()
                if is_different_exercise:
                    logger.debug(
                        "generate_next_hint | finished exercise and got different exercise -> reset state and create new plan | session_id=%s",
                        session_id,
                    )

                    plan = self._generate_solution_plan_llm(
                        question_text=student_message,
                        subject=subject,
                        skills=skills,
                    )

                    state = {
                        "original_question": student_message,
                        "solution_steps": plan.steps,
                        "final_answer": plan.final_answer,
                        "current_step_index": 0,
                        "exercise_finished": False,
                    }
                    self._session_state[session_id] = state
                    original_question = student_message
                    solution_steps = plan.steps
                    final_answer = plan.final_answer
                    current_step_index = 0
                    exercise_finished = False
                    is_new_exercise = True

                    logger.debug(
                        "generate_next_hint | new plan for new exercise | session_id=%s steps=%s final_answer=%r",
                        session_id,
                        len(plan.steps),
                        plan.final_answer,
                    )

            # --- 0.5 התאמה ל-expression של צעד → רמז דטרמיניסטי לצעד הבא ---
            original_index = current_step_index
            if solution_steps and not exercise_finished and not is_new_exercise:
                matched_index: Optional[int] = None

                # מחפשים את הצעד הראשון קדימה שה-expression שלו שקול לתשובה של שירה
                for idx in range(current_step_index, len(solution_steps)):
                    expr = solution_steps[idx].expression
                    if not expr:
                        continue
                    if self._is_answer_equivalent(
                            subject=subject,
                            question=original_question,
                            student=student_message,
                            target=expr,
                    ):
                        matched_index = idx
                        break

                if matched_index is not None:
                    next_index = matched_index + 1
                    logger.debug(
                        "generate_next_hint | student matched step expression  session_id=%s matched_index=%s next_index=%s",
                        session_id,
                        matched_index,
                        next_index,
                    )

                    # אם יש צעד הבא – נחזיר רמז פשוט עליו בלי LLM
                    if next_index < len(solution_steps):
                        prev_expr = solution_steps[matched_index].expression or original_question
                        next_step = solution_steps[next_index]

                        hint_text = (
                            f"שירה, הגעת למשוואה {prev_expr}, שזה צעד מצוין. "
                            f"הצעד הבא הוא: {next_step.description}. "
                            "נסי לבצע את הצעד הזה וכתבי לי מה קיבלת."
                        )

                        # נורמליזציה לאותו פורמט כמו שאר הרמזים
                        hint_text = self._normalize_hint_text(hint_text)

                        current_step_index = next_index
                        state["current_step_index"] = current_step_index

                        return TutorHintResult(
                            hint_text=hint_text,
                            hint_level=hint_level,
                            new_exercise_required=False,
                        )

                    # אם אין צעד הבא (אנחנו בעצם כבר בסוף ה-plan), רק נעדכן אינדקס ונמשיך לזרימה הרגילה
                    current_step_index = matched_index
                    state["current_step_index"] = current_step_index

            # --- 1. בדיקה: האם יש פתרון סופי נכון לתרגיל הנוכחי ---
            if final_answer and self._is_answer_equivalent(
                    subject=subject,
                    question=original_question,
                    student=student_message,
                    target=final_answer,
            ):
                state["exercise_finished"] = True
                logger.debug(
                    "generate_next_hint | student gave final correct answer | session_id=%s",
                    session_id,
                )

                if detected_skill_codes:
                    delta = self._config.mastery.correct_delta
                    logger.debug(
                        "generate_next_hint | updating mastery (correct answer, no checker) | student_id=%s skills=%s delta=%s",
                        db_session.student.id,
                        detected_skill_codes,
                        delta,
                    )
                    for code in detected_skill_codes:
                        crud.update_skill_mastery(
                            db=db,
                            student_id=db_session.student.id,
                            skill_code=code,
                            subject=subject,
                            delta=delta,
                        )
                else:
                    logger.debug(
                        "generate_next_hint | no detected skills for exercise_id=%s, skipping mastery update",
                        db_session.exercise.id,
                    )

                feedback_text = (
                    "כל הכבוד שירה, התשובה שלך נכונה! "
                    f"{final_answer} אכן פותר את התרגיל. "
                    "רוצה לנסות עוד תרגיל? אם כן, כתבי לי תרגיל חדש או צלמי תרגיל נוסף."
                )

                return TutorHintResult(
                    hint_text=feedback_text,
                    hint_level=hint_level,
                    new_exercise_required=False,
                )

            # --- 2. תשובה שנראית כמו תשובה סופית אך שגויה ---
            looks_like_final = ("=" in student_message) or student_message.strip().isdigit()
            if (
                    final_answer
                    and looks_like_final
                    and solution_steps
                    and not exercise_finished
                    and not is_new_exercise
                    and current_step_index == original_index  # לא מחזירים אחורה אם כבר קפצנו לפי expression ורק החזרנו רמז דטרמיניסטי
                    and current_step_index < len(solution_steps) - 1
            ):
                prev_index = max(current_step_index - 1, 0)
                state["current_step_index"] = prev_index
                current_step_index = prev_index
                logger.debug(
                    "generate_next_hint | incorrect final-like answer, moving back one step | session_id=%s current_step_index=%s",
                    session_id,
                    prev_index,
                )

            # --- 3. רמז רגיל לפי השלב בתכנית (רק כשאין התאמת expression) ---
            effective_hint_level = (
                self._config.hints.initial_hint_level if is_new_exercise else hint_level
            )
            effective_history = [] if is_new_exercise else history_turns
            effective_student_message: Optional[str] = None if is_new_exercise else student_message

            step_descriptions = [s.description for s in solution_steps] if solution_steps else []

            hint_result = self._generate_hint_llm(
                session_id=session_id,
                original_question=original_question,
                student_message=effective_student_message,
                subject=subject,
                skills=skills,
                hint_level=effective_hint_level,
                turns_history=effective_history,
                solution_steps=step_descriptions,
                current_step_index=current_step_index,
                final_answer=final_answer or None,
                is_new_exercise=is_new_exercise,
            )

            # עדכון current_step_index קדימה (אם יש plan)
            if solution_steps:
                state["current_step_index"] = min(
                    current_step_index + 1,
                    len(solution_steps) - 1,
                )
                logger.debug(
                    "generate_next_hint | advance_step | session_id=%s new_index=%s",
                    session_id,
                    state["current_step_index"],
                )

            return hint_result

    # === יצירת תכנית פתרון ===


    def _generate_solution_plan_llm(
        self,
        question_text: str,
        subject: Subject,
        skills: List[Skill],
    ) -> SolutionPlan:
        """
        יוצר תכנית פתרון מלאה (steps + final_answer) בעזרת LLM.
        לכל צעד יש:
        - description: טקסט חופשי.
        - expression: ביטוי ביניים (למשל "15x=60"), אם רלוונטי.

        זה רץ פעם אחת בתחילת תרגיל ונשמר ב-session_state.
        עובד לכל המקצועות – המשמעות של expression תלויה ב-subject.
        """
        system_prompt = (
            "אתה מורה שמייצר תכנית פתרון לתרגיל עבור עוזר הוראה.\n"
            "אתה לא מדבר עם תלמידה, אלא מחזיר רק תכנית למורה.\n"
            "המטרה שלך: לפרק את הפתרון לצעדים קטנים וברורים, ולהחזיר JSON בלבד בפורמט הבא:\n"
            "{\n"
            '  \"steps\": [\n'
            '    {\"description\": \"תיאור צעד ראשון בעברית פשוטה\", \"expression\": \"ביטוי ביניים אחרי הצעד\"},\n'
            '    {\"description\": \"תיאור צעד שני\", \"expression\": \"ביטוי ביניים נוסף\"}\n'
            "  ],\n"
            '  \"final_answer\": \"הפתרון הסופי בצורה קצרה, למשל x=4 או משפט באנגלית\"\n'
            "}\n"
            "חובה להחזיר JSON תקין בלבד, בלי טקסט מחוץ ל-JSON.\n"
            "אם אין ביטוי ביניים מתאים לצעד מסוים (למשל באנגלית), אפשר לשים expression=null או להשמיט את השדה.\n"
        )

        user_parts: List[str] = []
        user_parts.append("התרגיל הוא:\n")
        user_parts.append(question_text.strip() + "\n\n")

        if skills:
            skill_codes = ", ".join(s.code for s in skills)
            user_parts.append(f"מיומנויות רלוונטיות (לעזרתך בלבד): {skill_codes}.\n")

        user_prompt = "".join(user_parts)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.debug("Calling LLM for solution plan | subject=%s", subject.value)
        content = chat_completion(
            model=LLM_TUTOR_MODEL,
            messages=messages,
            temperature=0.1,
            max_tokens=700,
        ).strip()

        import json

        steps: List[SolutionStep] = []
        final_answer: str = ""

        try:
            data = json.loads(content)
            raw_steps = data.get("steps", [])
            final_answer = str(data.get("final_answer", "")).strip()

            for s in raw_steps:
                # תומך גם במקרה שה‑LLM החזיר string פשוט (backward compatible)
                if isinstance(s, str):
                    desc = s.strip()
                    if desc:
                        steps.append(SolutionStep(description=desc, expression=None))
                elif isinstance(s, dict):
                    desc = str(s.get("description", "")).strip()
                    expr_raw = s.get("expression")
                    expr = str(expr_raw).strip() if isinstance(expr_raw, str) else None
                    if desc:
                        steps.append(SolutionStep(description=desc, expression=expr))
        except Exception as e:
            logger.error(
                "Failed to parse solution plan JSON | error=%s | content=%s",
                e,
                content,
            )
            steps = []
            final_answer = ""

        if not steps:
            # fallback מינימלי – צעד טקסטואלי בלבד
            steps = [
                SolutionStep(
                    description=f"פתור את התרגיל צעד-צעד, למשל כמו בשאלה: {question_text}",
                    expression=None,
                )
            ]

        return SolutionPlan(steps=steps, final_answer=final_answer)


    def _normalize_expr(self, s: str) -> str:
        """
        נירמול גס לביטוי מתמטי/אלגברי:
        - מוריד רווחים.
        - מוריד רישיות.
        """
        return "".join(s.split()).lower()

    def _normalize_text(self, s: str) -> str:
        """
        נירמול גס לטקסט (למשל באנגלית):
        - lowercase
        - רווחים כפולים -> רווח אחד
        - הסרת סימני פיסוק פשוטים בסוף המשפט.
        """
        import re

        s = s.strip().lower()
        s = " ".join(s.split())
        s = re.sub(r"[.!?]+$", "", s)
        return s

    def _normalize_hint_text(self, text: str) -> str:
        """
        נורמליזציה עדינה לטקסטי רמזים:
        - מסירה תחביר inline LaTeX פשוט \( ... \) ע"י החלפת '\(' → '(' ו-'\)' → ')'.
        - לא נוגעת בביטויים כמו 25/5 או בסלאשים אחרים.
        """
        if not text:
            return text

        # מנקים רק backslash לפני סוגריים – תחביר LaTeX inline
        text = text.replace(r"\(", "(").replace(r"\)", ")")

        return text

    def _is_answer_equivalent(
            self,
            subject: Subject,
            question: str,
            student: str,
            target: str,
    ) -> bool:
        """
        בודק אם תשובת שירה שקולה לפתרון הסופי.

        מתמטיקה/גאומטריה:
        - קודם השוואה טקסטואלית מנורמלת.
        - אם לא שווה, ובתשובה יש צורה של x=מספר – ננסה להציב במשוואה ולראות אם שני האגפים שווים.
        - בנוסף, נזהה וריאציות שונות של x=מספר (עם רווחים/נקודה) וגם מקרה בו שירה כתבה רק את המספר.

        אנגלית:
        - נירמול טקסט כללי.
        """
        if not student or not target:
            return False

        # מתמטיקה / גאומטריה
        if subject in (Subject.MATH, getattr(Subject, "GEOMETRY", Subject.MATH)):
            # נירמול טקסטואלי כללי (x=7 מול x = 7)
            if self._normalize_expr(student) == self._normalize_expr(target):
                return True

            import re

            # אם ה-target הוא x=מספר והסטודנט כתבה x=מספר (עם רווחים/נקודה)
            m_target = re.match(r"\s*x\s*=\s*([\-+]?\d+(\.\d+)?)\s*$", target, re.IGNORECASE)
            m_student = re.match(r"\s*x\s*=\s*([\-+]?\d+(\.\d+)?)\s*$", student, re.IGNORECASE)
            if m_target and m_student:
                try:
                    return float(m_target.group(1)) == float(m_student.group(1))
                except Exception:
                    pass

            # אם ה-target הוא x=מספר והסטודנט כתבה רק מספר
            m_student_num = re.match(r"\s*([\-+]?\d+(\.\d+)?)\s*$", student)
            if m_target and m_student_num:
                try:
                    return float(m_target.group(1)) == float(m_student_num.group(1))
                except Exception:
                    pass

            # ניסיון נוסף: אם התשובה בצורה x=number, נבדוק אם היא פותרת את המשוואה המקורית
            m = re.match(r"\s*x\s*=\s*([\-+]?\d+)\s*$", student, re.IGNORECASE)
            if m:
                try:
                    x_val = float(m.group(1))
                    # מאוד פשטני: מחליף x בערך ומחשב שני אגפים אם יש '=' אחד
                    if "=" in question:
                        left, right = question.split("=", 1)
                        left = left.replace("X", "x")
                        expr_left = left.replace("x", f"({x_val})")
                        expr_right = right.replace("X", "x").replace("x", f"({x_val})")
                        # שימוש ב-eval רק על ביטויים מספריים פשוטים
                        from math import isclose
                        val_left = eval(expr_left)  # כאן זה 2*4+3
                        val_right = eval(expr_right)  # כאן זה 11
                        return isclose(val_left, val_right)
                except Exception:
                    return False

            return False

        # אנגלית
        if subject == Subject.ENGLISH:
            return self._normalize_text(student) == self._normalize_text(target)

        # ברירת מחדל
        return self._normalize_text(student) == self._normalize_text(target)

    # === בדיקת תשובה ===

    def check_answer(
            self,
            session_id: int,
            student_answer: str,
            add_turn: bool = True,
    ) -> Optional[AnswerCheckResult]:
        """
        בדיקת תשובה סופית ל-session.
        - משתמש ב-LLM checker.
        - מוסיף turn (אופציונלי) ו-attempt.
        - מעדכן mastery לכל ה-skills שזוהו בתרגיל.
        - אם התשובה נכונה: exercise_finished=True ב-state.
        """
        logger.info("TutorEngine.check_answer | session_id=%s", session_id)

        with db_session_scope() as db:
            db_session = crud.get_session_with_history(db, session_id=session_id)
            if not db_session:
                logger.error(
                    "check_answer | session not found | session_id=%s", session_id
                )
                return None

            subject = self._parse_subject(db_session.exercise.subject)
            if not self._is_subject_allowed(subject):
                logger.warning(
                    "check_answer | disallowed subject=%s session_id=%s",
                    subject.value,
                    session_id,
                )
                return None

            question_text = db_session.exercise.raw_text

            detected_skill_codes = (db_session.exercise.detected_skills or {}).get(
                "codes", []
            )
            skills = [
                Skill(code=c, subject=subject, description=c)
                for c in detected_skill_codes
            ]

            logger.debug(
                "check_answer | session_id=%s subject=%s skills=%s",
                session_id,
                subject.value,
                detected_skill_codes,
            )

            # מוסיפים את תשובת שירה כ-turn רק אם מתבקש
            if add_turn:
                crud.add_turn(
                    db=db,
                    session_id=session_id,
                    role="student",
                    message_text=student_answer,
                    hint_level=None,
                )

            # --- בדיקה מוקדמת מול final_answer מתוך ה-session_state (למתמטיקה) ---
            state = self._session_state.get(session_id) or {}
            final_answer = state.get("final_answer")
            logger.debug(
                "check_answer | session_id=%s final_answer_in_state=%r",
                session_id,
                final_answer,
            )
            if subject == Subject.MATH and final_answer:
                if self._is_answer_equivalent(
                        subject=subject,
                        question=question_text,
                        student=student_answer,
                        target=final_answer,
                ):
                    logger.debug(
                        "check_answer | student answer matches final_answer in state, skipping LLM checker | session_id=%s",
                        session_id,
                    )

                    if session_id not in self._session_state:
                        self._session_state[session_id] = {}
                    self._session_state[session_id]["exercise_finished"] = True

                    feedback_text = (
                        f"כל הכבוד שירה, התשובה שלך {student_answer} נכונה "
                        f"והיא שקולה לפתרון הסופי {final_answer}. "
                        "פתרת את המשוואה מצוין! "
                        "מה התרגיל הבא שאת רוצה לפתור?"
                    )

                    # שמירת Attempt
                    crud.add_attempt(
                        db=db,
                        session_id=session_id,
                        answer_text=student_answer,
                        is_correct=True,
                        feedback_text=feedback_text,
                    )

                    # עדכון mastery לכל המיומנויות
                    if detected_skill_codes:
                        delta = self._config.mastery.correct_delta
                        logger.debug(
                            "check_answer | updating mastery (early correct) | student_id=%s skills=%s delta=%s",
                            db_session.student.id,
                            detected_skill_codes,
                            delta,
                        )
                        for code in detected_skill_codes:
                            crud.update_skill_mastery(
                                db=db,
                                student_id=db_session.student.id,
                                skill_code=code,
                                subject=subject,
                                delta=delta,
                            )
                    else:
                        logger.debug(
                            "check_answer | no detected skills for exercise_id=%s, skipping mastery update (early)",
                            db_session.exercise.id,
                        )

                    return AnswerCheckResult(
                        is_correct=True,
                        feedback_text=feedback_text,
                    )
            # --- סוף בדיקה מוקדמת ---

            # קריאת LLM הבודק
            result = self._check_answer_llm(
                question_text=question_text,
                student_answer=student_answer,
                subject=subject,
                skills=skills,
            )

            # אם התשובה נכונה – נוסיף גם כאן הזמנה לתרגיל הבא
            if result.is_correct:
                result.feedback_text = (
                        result.feedback_text.rstrip() + " "
                                                        "מה התרגיל הבא שאת רוצה לפתור?"
                )

            # שמירת Attempt
            crud.add_attempt(
                db=db,
                session_id=session_id,
                answer_text=student_answer,
                is_correct=result.is_correct,
                feedback_text=result.feedback_text,
            )

            # עדכון mastery לכל המיומנויות
            if detected_skill_codes:
                delta = (
                    self._config.mastery.correct_delta
                    if result.is_correct
                    else self._config.mastery.incorrect_delta
                )
                logger.debug(
                    "check_answer | updating mastery | student_id=%s skills=%s delta=%s",
                    db_session.student.id,
                    detected_skill_codes,
                    delta,
                )
                for code in detected_skill_codes:
                    crud.update_skill_mastery(
                        db=db,
                        student_id=db_session.student.id,
                        skill_code=code,
                        subject=subject,
                        delta=delta,
                    )
            else:
                logger.debug(
                    "check_answer | no detected skills for exercise_id=%s, skipping mastery update",
                    db_session.exercise.id,
                )

            # סימון state של התרגיל כנגמר, אם התשובה נכונה
            if result.is_correct:
                if session_id not in self._session_state:
                    self._session_state[session_id] = {}
                self._session_state[session_id]["exercise_finished"] = True
                logger.debug(
                    "check_answer | exercise finished | session_id=%s", session_id
                )

            return result

    # === פונקציות פנימיות – עבודה מול LLM ו-lifecycle ===

    def _is_subject_allowed(self, subject: Subject) -> bool:
        allowed = subject in self._config.allowed_subjects
        if not allowed:
            logger.debug(
                "TutorEngine._is_subject_allowed | subject=%s allowed=False",
                subject.value,
            )
        return allowed

    def _parse_subject(self, value: str) -> Subject:
        try:
            return Subject(value)
        except ValueError:
            return Subject.OTHER

    def _decide_next_hint_level(self, history) -> int:
        """
        לוגיקה פשוטה: נספר כמה רמזים כבר נתנו ונעלה עד max_hint_level.
        """
        max_hint = self._config.hints.max_hint_level
        tutor_hints = [t for t in history if t.role == "tutor" and t.hint_level]
        used_levels = [t.hint_level for t in tutor_hints if t.hint_level is not None]
        current_level = (
            max(used_levels)
            if used_levels
            else self._config.hints.initial_hint_level
        )

        next_level = min(current_level + 1, max_hint)
        logger.debug(
            "TutorEngine._decide_next_hint_level | current=%s next=%s",
            current_level,
            next_level,
        )
        return next_level

    def _generate_hint_llm(
            self,
            session_id: int,
            original_question: str,
            student_message: Optional[str],
            subject: Subject,
            skills: List[Skill],
            hint_level: int,
            turns_history,
            solution_steps: Optional[List[str]] = None,
            current_step_index: int = 0,
            final_answer: Optional[str] = None,
            is_new_exercise: bool = False,
    ) -> TutorHintResult:
        """
        בניית פרומפט + קריאת LLM להפקת רמז.

        original_question: התרגיל המקורי כפי שנשמר ב-session.
        turns_history: רשימת turn-ים (DB models) להקשר.
        solution_steps: תכנית הפתרון שגובשה בתחילת התרגיל (אם קיימת).
        current_step_index: באיזה צעד בתכנית אנחנו (0‑based).
        final_answer: הפתרון הסופי שה‑plan יצר (למשל "x=4" או תשובה מילולית באנגלית).

        בכל צעד המודל נדרש:
        - להתייחס להיסטוריית השיחה.
        - לדעת מהו הצעד הבא בתכנית (אם יש plan).
        - להשוות את הצעד האחרון של שירה לתרגיל המקורי ולplan.
        - אם הצעד שלה הוא כבר התשובה הסופית → לסגור תרגיל.
        """

        if not self._is_subject_allowed(subject):
            logger.warning(
                "_generate_hint_llm | disallowed subject=%s", subject.value
            )
            return TutorHintResult(
                hint_text="אני עוזר רק באנגלית, מתמטיקה וגאומטריה. בואי נבחר תרגיל בתחום הזה.",
                hint_level=hint_level,
            )

        # === בניית system prompt לפי מקצוע ===
        system_prompt = build_tutor_system_prompt(subject=subject)

        # תקציר plan (אם קיים) – מידע פנימי למודל
        plan_text = ""
        if solution_steps:
            # נחתוך ל‑6 צעדים ראשונים כדי לא להתפוצץ בטוקנים
            shown_steps = solution_steps[:6]
            numbered = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(shown_steps))
            plan_text = (
                "תכנית פתרון (מידע פנימי, אל תקריא לשירה מילה במילה):\n"
                f"{numbered}\n"
                f"הצעד שבו את נמצאת עכשיו בתכנית (current_step_index): {current_step_index}.\n"
            )

        final_answer_text = ""
        if final_answer:
            final_answer_text = (
                f"הפתרון הסופי על פי התכנית הוא: \"{final_answer}\" "
                "(מידע פנימי, אל תגלה לשירה במפורש אלא אם התרגיל הסתיים).\n"
            )

        # הנחיות כלליות + ספציפיות לplan
        system_prompt += (
            "\n\n"
            "הנחיות נוספות (אל תציג לשירה את הטקסט הזה):\n"
            f"- התרגיל המקורי שאת פותרת איתה הוא: \"{original_question}\".\n"
            "- כשאת כותבת את המשוואה או מצטטת אותה, העתיקי אותה בדיוק כפי שהיא מופיעה בשאלה, "
            "בלי להפוך את סדר האגפים ובלי לשנות את הסימן של x.\n"
            "- current_step_index מייצג את הצעד בתכנית שהפתרון האחרון של שירה כבר השיג.\n"
            "- אם מה ששירה כתבה תואם לצעד מתקדם יותר בתכנית (למשל ביטוי ביניים כמו 15x = 60),\n"
            "  התייחסי אליה כאילו כבר הגיעה לצעד הזה והמשיכי משם – אל תחזירי אותה לצעד קודם.\n"
            "- אם הצעד הנוכחי לפי התכנית תקין ומתאים למה שהיא כתבה, חזקי אותה והמשיכי לצעד הבא בתכנית.\n"
            "- אם הצעד שלה לא שקול לצעד הנוכחי בתכנית או לתרגיל (למשל טעות בחישוב/חוק גאומטרי/דקדוק באנגלית),\n"
            "  הסבירי במפורש מה הטעות, ואיך להחזיר את הצעד להיות נכון. אל תמשיכי לבנות על צעד שגוי.\n"
            "- אם היא דילגה ישירות לפתרון הסופי נכון (התשובה שלה שקולה לפתרון הסופי),\n"
            "  אשרי בקצרה שהפתרון שלה נכון, הסבירי במשפט או שניים למה, והציעי לה לעבור לתרגיל חדש.\n"
            "- אם היא כתבה תשובה שנראית כמו תשובה סופית אך אינה נכונה, התייחסי לזה כאל טעות בסוף הדרך:\n"
            "  החזירי אותה צעד אחד אחורה בתכנית, הסבירי איפה כנראה היה הבלבול, ותני רמז לצעד שלפני הפתרון.\n"
            "- שמרי על תשובות קצרות (עד 3–4 משפטים) ושאלה אחת ברורה להמשך.\n"
            "- מותר להשתמש במשפט עידוד ארוך כמו \"שירה, זה ממש בסדר לא לדעת מאיפה להתחיל\" רק פעם אחת ובניסוח שונה בכל תרגיל.\n"
            "  לאחר מכן השתמשי בעידודים קצרים ושונים, לא באותו ניסוח.\n"
        )


        if plan_text or final_answer_text:
            system_prompt += "\n" + plan_text + final_answer_text

        # === בניית היסטוריית שיחה טקסטואלית ===
        history_text = ""
        if turns_history:
            sorted_turns = sorted(turns_history, key=lambda t: t.created_at)
            last_turns = sorted_turns[-6:]
            lines: List[str] = []
            for t in last_turns:
                role = "שירה" if t.role == "student" else "העוזר"
                lines.append(f"{role}: {t.message_text}")
            history_text = "\n".join(lines)

        # === user prompt ===
        user_prompt = build_tutor_user_prompt_for_hint(
            question_text=original_question,
            student_message=student_message,
            skills=skills,
            hint_level=hint_level,
            history_text=history_text,
            is_new_exercise=is_new_exercise,
        )

        # חיזוק מפורש לבדיקה מול התרגיל + plan
        user_prompt += (
            "\n\n"
            "לפני שאת נותנת את הרמז, נתחי במפורש את הצעד האחרון של שירה ביחס לתרגיל המקורי "
            "ולצעדי תכנית הפתרון.\n"
            "כשאת מזכירה את המשוואה, אל תשני את סדר האגפים ואל תעביר איברים צדדים כל עוד לא ביקשו ממך לבצע את הצעד הזה.\n"
            "- אם מה ששירה כתבה תואם לצעד מתקדם יותר בתכנית (למשל ביטוי ביניים כמו 15x = 60), "
            "התייחסי אליה כאילו כבר הגיעה לצעד הזה ותני רמז לצעד הבא בתכנית.\n"
            "- אם הצעד שלה מדלג ישר לפתרון הסופי, בדקי בשקט אם הוא זהה לפתרון הסופי שבתכנית.\n"
            "  אם כן – סגרי את התרגיל: אמרי שהתשובה נכונה, הסבירי בקצרה, והציעי עוד תרגיל.\n"
            "  אם לא – הסבירי שזה אינו פתרון נכון, והחזירי אותה לצעד שלפני הסוף (למשל עוד משוואה או צעד ביניים).\n"
            "- אם הצעד שלה שגוי ביחס לתרגיל או לתכנית, הסבירי למה, ותני רמז שיחזיר אותה לצעד המתוקן.\n"
            "בסיום, כתבי רמז אחד בלבד: הסבר קצר (1–3 משפטים) ושאלה אחת ברורה לשלב הבא.\n"
        )


        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.debug(
            "Calling LLM for hint | subject=%s hint_level=%s session_id=%s",
            subject.value,
            hint_level,
            session_id,
        )
        content = chat_completion(
            model=LLM_TUTOR_MODEL,
            messages=messages,
            temperature=0.35,
            max_tokens=400,
        )

        cleaned = self._normalize_hint_text(content.strip())
        return TutorHintResult(hint_text=cleaned, hint_level=hint_level)

    def _check_answer_llm(
        self,
        question_text: str,
        student_answer: str,
        subject: Subject,
        skills: List[Skill],
    ) -> AnswerCheckResult:
        """
        בניית פרומפט + קריאת LLM לבדיקה.
        """
        if not self._is_subject_allowed(subject):
            logger.warning(
                "_check_answer_llm | disallowed subject=%s", subject.value
            )
            return AnswerCheckResult(
                is_correct=False,
                feedback_text="אני עוזר רק באנגלית ומתמטיקה. בואי נבחר תרגיל בתחום הזה.",
            )

        system_prompt = build_answer_checker_system_prompt(subject=subject)
        user_prompt = build_answer_checker_user_prompt(
            question_text=question_text,
            student_answer=student_answer,
            skills=skills,
        )

        user_prompt += (
            "\n\n"
            "פורמט התשובה שלך (חובה):\n"
            "שורה ראשונה: \"נכון\" או \"לא נכון\" בלבד.\n"
            "לאחר מכן: שורה חדשה והסבר קצר.\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.debug("Calling LLM for answer check | subject=%s", subject.value)
        content = chat_completion(
            model=LLM_CHECKER_MODEL,
            messages=messages,
            temperature=0.2,
            max_tokens=400,
        ).strip()

        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            logger.error("Empty answer from checker LLM")
            return AnswerCheckResult(
                is_correct=False,
                feedback_text="לא הצלחתי לבדוק את התשובה, נסי שוב.",
            )

        first = lines[0].lower()
        is_correct = "נכון" in first and "לא" not in first

        feedback = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        if not feedback:
            feedback = "התשובה {}. ".format("נכונה" if is_correct else "לא נכונה")

        logger.debug(
            "Answer check result | is_correct=%s feedback_len=%s",
            is_correct,
            len(feedback),
        )

        return AnswerCheckResult(is_correct=is_correct, feedback_text=feedback)
