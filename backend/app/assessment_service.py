from collections import defaultdict
import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import ensure_utc, utc_now
from app.email_service import (
    EmailConfigurationError,
    EmailDeliveryError,
    send_assessment_invitation_email,
)
from app.models import (
    AssessmentAssignment,
    AssessmentResult,
    CandidateAnswer,
    PlatformSetting,
)


logger = logging.getLogger(__name__)

PASS_MESSAGE = "You have been selected for the next round."
FAIL_MESSAGE = "You have not qualified for the next round."


def refresh_assignment_lifecycle(db: Session, assignment: AssessmentAssignment) -> None:
    now = utc_now()
    if (
        assignment.test_status == "assigned"
        and ensure_utc(assignment.expires_at) is not None
        and now > ensure_utc(assignment.expires_at)
    ):
        assignment.test_status = "expired"
        db.flush()
    elif (
        assignment.test_status == "started"
        and assignment.deadline_at is not None
        and now > ensure_utc(assignment.deadline_at)
    ):
        evaluate_assignment_submission(db, assignment, auto_submitted=True)
        db.flush()


def get_reveal_answers_policy(db: Session) -> bool:
    setting = db.scalar(
        select(PlatformSetting).where(PlatformSetting.setting_key == "reveal_assessment_answers")
    )
    return bool(setting and setting.setting_value.strip().lower() == "true")


def send_assignment_invitation_email(
    db: Session,
    assignment: AssessmentAssignment,
    raw_token: str,
) -> dict:
    settings = get_settings()
    assessment = assignment.assessment
    candidate = assignment.candidate
    job = assignment.job
    test_link = f"{settings.frontend_base_url.rstrip('/')}/assessment/{raw_token}"

    try:
        send_assessment_invitation_email(
            to_email=assignment.recipient_email,
            candidate_name=candidate.user.full_name,
            job_title=job.title,
            company_name=job.company.name,
            assessment_title=assessment.title,
            test_link=test_link,
            expires_at=assignment.expires_at,
            instructions=assessment.instructions,
            duration_minutes=assessment.duration_minutes,
            question_count=assessment.total_questions,
        )
        assignment.invitation_status = "sent"
        assignment.sent_at = utc_now()
        assignment.invitation_error = None
        db.flush()
        return {
            "invitation_status": "sent",
            "message": f"Invitation email sent to {assignment.recipient_email}.",
        }
    except (EmailConfigurationError, EmailDeliveryError) as exc:
        assignment.invitation_status = "failed"
        assignment.invitation_error = str(exc)
        db.flush()
        return {
            "invitation_status": "failed",
            "error": str(exc),
            "message": str(exc),
        }


def evaluate_assignment_submission(
    db: Session,
    assignment: AssessmentAssignment,
    auto_submitted: bool = False,
) -> AssessmentResult:
    """Evaluate all MCQ answers on backend using Sir's strict (obtained_marks > passing_marks) rule."""
    existing = db.scalar(
        select(AssessmentResult).where(AssessmentResult.assignment_id == assignment.id)
    )
    if existing is not None:
        return existing

    now = utc_now()
    assessment = assignment.assessment
    questions = list(assessment.questions)
    answer_by_qid = {ans.assessment_question_id: ans for ans in assignment.answers}

    obtained_marks = 0
    total_marks = 0
    answered_count = 0
    correct_count = 0
    by_difficulty: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0, "marks": 0, "max_marks": 0})
    by_skill: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0, "marks": 0, "max_marks": 0})

    for q in questions:
        total_marks += q.marks
        ans = answer_by_qid.get(q.id)
        if ans is None:
            ans = CandidateAnswer(
                assignment_id=assignment.id,
                assessment_question_id=q.id,
                selected_option_index=None,
                is_correct=False,
                marks_awarded=0,
            )
            db.add(ans)
        if ans.selected_option_index is not None:
            answered_count += 1

        is_right = (
            ans.selected_option_index is not None
            and ans.selected_option_index == q.correct_option_index
        )
        marks_awarded = q.marks if is_right else 0
        ans.is_correct = is_right
        ans.marks_awarded = marks_awarded

        if is_right:
            obtained_marks += q.marks
            correct_count += 1

        by_difficulty[q.difficulty]["total"] += 1
        by_difficulty[q.difficulty]["max_marks"] += q.marks
        by_skill[q.skill]["total"] += 1
        by_skill[q.skill]["max_marks"] += q.marks
        if is_right:
            by_difficulty[q.difficulty]["correct"] += 1
            by_difficulty[q.difficulty]["marks"] += q.marks
            by_skill[q.skill]["correct"] += 1
            by_skill[q.skill]["marks"] += q.marks

    percentage = round((obtained_marks / total_marks) * 100.0, 2) if total_marks > 0 else 0.0
    # Strict greater-than (>) passing rule confirmed by Sir
    is_passed = obtained_marks > assessment.passing_marks
    result_status = "Selected for next round" if is_passed else "Not qualified"
    result_message = PASS_MESSAGE if is_passed else FAIL_MESSAGE

    assignment.test_status = "submitted"
    assignment.submitted_at = now
    assignment.submitted_automatically = auto_submitted

    result = AssessmentResult(
        assignment_id=assignment.id,
        assessment_id=assessment.id,
        application_id=assignment.application_id,
        candidate_id=assignment.candidate_id,
        job_id=assignment.job_id,
        obtained_marks=obtained_marks,
        total_marks=total_marks,
        passing_marks=assessment.passing_marks,
        percentage=percentage,
        is_passed=is_passed,
        result_status=result_status,
        result_message=result_message,
        submitted_at=now,
        submitted_automatically=auto_submitted,
        summary_json=json.dumps(
            {
                "total_questions": len(questions),
                "answered_count": answered_count,
                "unanswered_count": max(0, len(questions) - answered_count),
                "correct_count": correct_count,
                "by_difficulty": dict(by_difficulty),
                "by_skill": dict(by_skill),
            }
        ),
    )
    db.add(result)
    db.flush()
    return result
