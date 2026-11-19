from datetime import datetime, timedelta
import json
import secrets

from jose import JWTError, jwt
import cloudinary
import httpx
from cloudinary.uploader import upload as cloudinary_upload
from cloudinary.utils import private_download_url

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import get_or_create_recruiter_profile, optional_current_user, require_roles
from app.core.config import get_settings
from app.assessment_service import (
    evaluate_assignment_submission,
    refresh_assignment_lifecycle as _refresh_assignment_lifecycle,
    send_assignment_invitation_email,
)
from app.core.security import ensure_utc, hash_opaque_token, isoformat_utc, utc_now
from app.database import get_db
from app.models import (
    Application,
    Assessment,
    AssessmentAssignment,
    AssessmentQuestion,
    AssessmentResult,
    AssessmentRecording,
    Candidate,
    CandidateAnswer,
    ProctoringEvent,
    Job,
    PlatformSetting,
    QuestionBank,
    Recruiter,
    User,
    VALID_DIFFICULTIES,
)
from app.services import normalize_skill


admin_question_bank_router = APIRouter(prefix="/api/admin", tags=["Admin Question Bank"])
recruiter_question_bank_router = APIRouter(prefix="/api/recruiter/question-bank", tags=["Recruiter Question Bank"])
recruiter_assessment_router = APIRouter(prefix="/api/recruiter", tags=["Recruiter Assessments"])
assessment_router = APIRouter(prefix="/api/assessments", tags=["Candidate Assessments"])


# --- Schemas ---

class QuestionBankRequest(BaseModel):
    question_type: str = Field(default="mcq")
    skill: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    difficulty: str
    question_text: str = Field(min_length=5)
    options: list[str]
    correct_option_index: int = Field(ge=0, le=3)
    marks: int = Field(default=1, ge=1, le=100)
    explanation: str | None = None
    is_active: bool = True

    @field_validator("question_type")
    @classmethod
    def validate_mcq_only(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned != "mcq":
            raise ValueError("Round 1 supports only MCQ questions.")
        return "mcq"

    @field_validator("difficulty")
    @classmethod
    def normalize_difficulty(cls, value: str) -> str:
        normalized = value.strip().capitalize()
        if normalized not in VALID_DIFFICULTIES:
            raise ValueError("Difficulty must be Easy, Medium, or Hard.")
        return normalized

    @field_validator("options")
    @classmethod
    def validate_four_options(cls, value: list[str]) -> list[str]:
        if len(value) != 4:
            raise ValueError("Each MCQ question must have exactly 4 options.")
        cleaned = [str(opt).strip() for opt in value]
        if any(not opt for opt in cleaned):
            raise ValueError("All four options must be non-empty.")
        if len({opt.casefold() for opt in cleaned}) != 4:
            raise ValueError("All four options must be distinct.")
        return cleaned

    @field_validator("skill", "category", "question_text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be blank.")
        return cleaned


class AssessmentPolicyRequest(BaseModel):
    reveal_correct_answers_to_candidate: bool


class GenerateAssessmentQuestionsRequest(BaseModel):
    job_id: int = Field(gt=0)
    skills: list[str] = Field(min_length=1, max_length=10)
    difficulty: str
    question_count: int = Field(default=5, ge=1, le=20)
    marks: int = Field(default=1, ge=1, le=100)

    @field_validator("difficulty")
    @classmethod
    def normalize_difficulty(cls, value: str) -> str:
        normalized = value.strip().capitalize()
        if normalized not in VALID_DIFFICULTIES:
            raise ValueError("Difficulty must be Easy, Medium, or Hard.")
        return normalized

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not cleaned:
            raise ValueError("Select at least one job skill.")
        return cleaned


class RecruiterQuestionUpdateRequest(QuestionBankRequest):
    """Editable MCQ fields; the route never accepts an active-state change."""


class AssessmentUpsertRequest(BaseModel):
    job_id: int = Field(gt=0)
    title: str = Field(min_length=3, max_length=255)
    description: str | None = None
    instructions: str = Field(min_length=5)
    duration_minutes: int = Field(ge=1, le=240)
    passing_marks: int = Field(ge=0)
    expires_at: datetime | None = None
    question_ids: list[int] = Field(default_factory=list)
    status: str = Field(default="draft", pattern="^(draft|published|archived)$")


class PublishAssessmentRequest(BaseModel):
    expires_at: datetime | None = None


class AssignAssessmentRequest(BaseModel):
    application_ids: list[int] = Field(min_length=1)
    expires_at: datetime | None = None


class SaveAnswerRequest(BaseModel):
    question_id: int = Field(gt=0)
    selected_option_index: int = Field(ge=0, le=3)


class ProctoringEventRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=50)
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        allowed = {
            "camera_missing",
            "camera_disconnected",
            "microphone_disconnected",
            "face_not_detected",
            "multiple_faces_detected",
            "tab_switch",
            "window_blur",
            "fullscreen_exit",
            "network_offline",
            "recording_error",
            "recording_stopped",
        }
        cleaned = value.strip().lower()
        if cleaned not in allowed:
            raise ValueError("Unsupported proctoring event type.")
        return cleaned

class SubmitAssessmentRequest(BaseModel):
    answers: dict[int, int] = Field(default_factory=dict)
    auto_submitted: bool = False


# --- Helpers ---

def _serialize_qb_item(item: QuestionBank, include_answer: bool = True) -> dict:
    payload = {
        "id": item.id,
        "question_type": item.question_type,
        "skill": item.skill,
        "category": item.category,
        "difficulty": item.difficulty,
        "question_text": item.question_text,
        "options": json.loads(item.options_json),
        "marks": item.marks,
        "is_active": item.is_active,
        "created_at": isoformat_utc(item.created_at),
        "updated_at": isoformat_utc(item.updated_at),
    }
    if include_answer:
        payload["correct_option_index"] = item.correct_option_index
        payload["explanation"] = item.explanation
    return payload


def _serialize_assessment_question(q: AssessmentQuestion, include_answer: bool = True) -> dict:
    options = []
    if q.options_json:
        try:
            options = json.loads(q.options_json)
        except Exception:
            options = []

    payload = {
        "id": q.id,
        "question_bank_id": q.question_bank_id,
        "order_index": q.order_index,
        "question_type": getattr(q, "question_type", "mcq") or "mcq",
        "skill": q.skill,
        "category": q.category,
        "difficulty": q.difficulty,
        "question_text": q.question_text,
        "instructions": getattr(q, "instructions", None),
        "prep_time_seconds": getattr(q, "prep_time_seconds", None),
        "response_time_seconds": getattr(q, "response_time_seconds", None),
        "options": options,
    }
    if include_answer:
        payload["marks"] = q.marks
        payload["correct_option_index"] = q.correct_option_index
        payload["explanation"] = q.explanation
    return payload


def _serialize_assessment_summary(assessment: Assessment, include_questions: bool = False) -> dict:
    assignments = assessment.assignments
    submitted_count = sum(1 for a in assignments if a.test_status == "submitted")
    job_skills = [js.skill.name for js in assessment.job.skills] if assessment.job else []
    norm_job_skills = {normalize_skill(s) for s in job_skills}
    question_skills = [q.skill for q in assessment.questions]
    norm_q_skills = {normalize_skill(qs) for qs in question_skills}
    covered_skills = [s for s in job_skills if normalize_skill(s) in norm_q_skills]
    missing_skills = [s for s in job_skills if normalize_skill(s) not in norm_q_skills]

    data = {
        "id": assessment.id,
        "job_id": assessment.job_id,
        "job_title": assessment.job.title if assessment.job else None,
        "company_name": assessment.job.company.name if (assessment.job and assessment.job.company) else None,
        "title": assessment.title,
        "description": assessment.description,
        "instructions": assessment.instructions,
        "duration_minutes": assessment.duration_minutes,
        "passing_marks": assessment.passing_marks,
        "total_questions": assessment.total_questions,
        "total_marks": assessment.total_marks,
        "status": assessment.status,
        "expires_at": isoformat_utc(assessment.expires_at),
        "assignments_count": len(assignments),
        "submitted_count": submitted_count,
        "job_skills": job_skills,
        "covered_skills": covered_skills,
        "missing_skills": missing_skills,
        "assessment_type": getattr(assessment, "assessment_type", "mcq") or "mcq",
        "prep_time_seconds": getattr(assessment, "prep_time_seconds", 30) or 30,
        "response_time_seconds": getattr(assessment, "response_time_seconds", 120) or 120,
        "allow_review": bool(getattr(assessment, "allow_review", True)),
        "max_recordings_per_question": getattr(assessment, "max_recordings_per_question", 1) or 1,
        "created_at": isoformat_utc(assessment.created_at),
        "updated_at": isoformat_utc(assessment.updated_at),
    }
    if include_questions:
        data["questions"] = [
            _serialize_assessment_question(q, include_answer=True)
            for q in assessment.questions
        ]
    return data


def _sync_assessment_questions(db: Session, assessment: Assessment, question_ids: list[int]) -> None:
    deduped_ids: list[int] = []
    seen = set()
    for qid in question_ids:
        if qid not in seen:
            seen.add(qid)
            deduped_ids.append(qid)

    by_id = {}
    if deduped_ids:
        qb_items = db.scalars(
            select(QuestionBank).where(
                QuestionBank.id.in_(deduped_ids),
                QuestionBank.is_active.is_(True),
            )
        ).all()
        by_id = {item.id: item for item in qb_items}
        missing = [qid for qid in deduped_ids if qid not in by_id]
        if missing:
            existing_questions_by_id = {q.id: q for q in assessment.questions}
            existing_questions_by_qb_id = {
                q.question_bank_id: q for q in assessment.questions if q.question_bank_id is not None
            }
            still_missing = []
            for qid in missing:
                existing_q = existing_questions_by_id.get(qid) or existing_questions_by_qb_id.get(qid)
                if existing_q is not None:
                    by_id[qid] = existing_q
                else:
                    still_missing.append(qid)
            if still_missing:
                raise HTTPException(404, f"Question bank items not found or inactive: {still_missing}")

    question_sources = [by_id[qid] for qid in deduped_ids]

    assessment.questions.clear()
    db.flush()

    total_marks = 0
    for idx, src in enumerate(question_sources, start=1):
        total_marks += src.marks
        qb_id = (
            getattr(src, "question_bank_id", None)
            if isinstance(src, AssessmentQuestion)
            else getattr(src, "id", None)
        )
        assessment.questions.append(
            AssessmentQuestion(
                assessment_id=assessment.id,
                question_bank_id=qb_id,
                order_index=idx,
                skill=src.skill,
                category=src.category,
                difficulty=src.difficulty,
                question_text=src.question_text,
                options_json=src.options_json,
                correct_option_index=src.correct_option_index,
                marks=src.marks,
                explanation=src.explanation,
            )
        )
    assessment.total_questions = len(deduped_ids)
    assessment.total_marks = total_marks


def _validate_publishable_assessment(assessment: Assessment) -> None:
    if assessment.total_questions < 1:
        raise HTTPException(422, "Select at least 1 MCQ question before publishing an assessment.")
    if assessment.passing_marks >= assessment.total_marks:
        raise HTTPException(
            422,
            f"Passing marks ({assessment.passing_marks}) must be strictly less than total marks ({assessment.total_marks}) "
            "because candidates must score strictly greater than passing marks to qualify.",
        )
    if assessment.expires_at is not None and ensure_utc(assessment.expires_at) <= utc_now():
        raise HTTPException(422, "Assessment expiry date must be in the future.")


def _get_eligible_recruiter_job(db: Session, recruiter: Recruiter | None, job_id: int) -> Job:
    if not recruiter:
        raise HTTPException(404, "Recruiter profile not found.")
    job = db.get(Job, job_id)
    if not job or job.recruiter_id != recruiter.id:
        raise HTTPException(404, "Job not found")
    if not job.company or not job.company.is_approved or job.status not in {"published", "open"}:
        raise HTTPException(409, "Assessments are available only for approved, published jobs.")
    return job


@admin_question_bank_router.get("/proctoring-events")
def admin_list_proctoring_events(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    stmt = (
        select(ProctoringEvent, AssessmentAssignment)
        .join(AssessmentAssignment, ProctoringEvent.assignment_id == AssessmentAssignment.id)
        .order_by(ProctoringEvent.created_at.desc(), ProctoringEvent.id.desc())
    )
    total = db.scalar(select(func.count(ProctoringEvent.id))) or 0
    rows = db.execute(stmt.offset(offset).limit(limit)).all()

    return {
        "items": [
            {
                "id": event.id,
                "assignment_id": event.assignment_id,
                "event_type": event.event_type,
                "details": json.loads(event.details) if event.details else {},
                "created_at": isoformat_utc(event.created_at),
                "candidate_name": assignment.candidate.user.full_name,
                "job_title": assignment.job.title,
                "assessment_title": assignment.assessment.title,
            }
            for event, assignment in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

@admin_question_bank_router.get("/assessment-recordings")
def admin_list_assessment_recordings(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    stmt = (
        select(AssessmentRecording, AssessmentAssignment)
        .join(
            AssessmentAssignment,
            AssessmentRecording.assignment_id == AssessmentAssignment.id,
        )
        .order_by(AssessmentRecording.created_at.desc(), AssessmentRecording.id.desc())
    )
    total = db.scalar(select(func.count(AssessmentRecording.id))) or 0
    rows = db.execute(stmt.offset(offset).limit(limit)).all()

    return {
        "items": [
            {
                "id": recording.id,
                "assignment_id": recording.assignment_id,
                "candidate_name": assignment.candidate.user.full_name,
                "candidate_email": assignment.candidate.contact_email,
                "job_title": assignment.job.title,
                "assessment_title": assignment.assessment.title,
                "status": recording.status,
                "video_format": recording.video_format,
                "duration_seconds": recording.duration_seconds,
                "file_size_bytes": recording.file_size_bytes,
                "consent_given": recording.consent_given,
                "consent_at": isoformat_utc(recording.consent_at),
                "created_at": isoformat_utc(recording.created_at),
                "uploaded_at": isoformat_utc(recording.uploaded_at),
            }
            for recording, assignment in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

@admin_question_bank_router.get("/assessment-recordings/{recording_id}/playback")
def admin_get_assessment_recording_playback(
    recording_id: int,
    user=Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    recording = db.get(AssessmentRecording, recording_id)
    if not recording:
        raise HTTPException(404, "Assessment recording not found.")

    if recording.status != "uploaded" or not recording.cloudinary_public_id:
        raise HTTPException(409, "This assessment recording is not available for playback.")

    if not recording.video_format:
        raise HTTPException(409, "Recording video format is unavailable.")

    settings = get_settings()
    if not all((
        settings.cloudinary_cloud_name,
        settings.cloudinary_api_key,
        settings.cloudinary_api_secret,
    )):
        raise HTTPException(503, "Recording storage is not configured.")

    try:
        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            secure=True,
        )

        expires_at = int((utc_now() + timedelta(minutes=10)).timestamp())
        playback_url = private_download_url(
            recording.cloudinary_public_id,
            recording.video_format,
            resource_type="video",
            type="authenticated",
            expires_at=expires_at,
            secure=True,
        )

        return {
            "recording_id": recording.id,
            "playback_url": playback_url,
            "expires_at": isoformat_utc(datetime.fromtimestamp(expires_at, tz=utc_now().tzinfo)),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Could not generate the secure recording playback link.") from exc

# --- 1. Admin Centralized Question Bank & Policy ---

@admin_question_bank_router.get("/question-bank")
def admin_list_question_bank(
    q: str | None = None,
    skill: str | None = None,
    category: str | None = None,
    difficulty: str | None = None,
    include_inactive: bool = False,
    user=Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    stmt = select(QuestionBank)
    if not include_inactive:
        stmt = stmt.where(QuestionBank.is_active.is_(True))
    if skill:
        stmt = stmt.where(QuestionBank.skill.ilike(f"%{skill.strip()}%"))
    if category:
        stmt = stmt.where(QuestionBank.category.ilike(f"%{category.strip()}%"))
    if difficulty:
        stmt = stmt.where(QuestionBank.difficulty.ilike(difficulty.strip()))
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                QuestionBank.question_text.ilike(pattern),
                QuestionBank.skill.ilike(pattern),
                QuestionBank.category.ilike(pattern),
            )
        )
    items = db.scalars(stmt.order_by(QuestionBank.created_at.desc(), QuestionBank.id.desc())).all()
    all_rows = db.scalars(select(QuestionBank)).all()
    return {
        "items": [_serialize_qb_item(item, include_answer=True) for item in items],
        "total": len(items),
        "skills": sorted({row.skill for row in all_rows if row.skill}),
        "categories": sorted({row.category for row in all_rows if row.category}),
    }


@admin_question_bank_router.post("/question-bank", status_code=201)
def admin_create_question(
    payload: QuestionBankRequest,
    user=Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    item = QuestionBank(
        question_type=payload.question_type,
        skill=payload.skill,
        category=payload.category,
        difficulty=payload.difficulty,
        question_text=payload.question_text,
        options_json=json.dumps(payload.options),
        correct_option_index=payload.correct_option_index,
        marks=payload.marks,
        explanation=payload.explanation.strip() if payload.explanation else None,
        is_active=payload.is_active,
        created_by_user_id=user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize_qb_item(item, include_answer=True)


@admin_question_bank_router.put("/question-bank/{question_id}")
def admin_update_question(
    question_id: int,
    payload: QuestionBankRequest,
    user=Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    item = db.get(QuestionBank, question_id)
    if not item:
        raise HTTPException(404, "Question not found")
    item.question_type = payload.question_type
    item.skill = payload.skill
    item.category = payload.category
    item.difficulty = payload.difficulty
    item.question_text = payload.question_text
    item.options_json = json.dumps(payload.options)
    item.correct_option_index = payload.correct_option_index
    item.marks = payload.marks
    item.explanation = payload.explanation.strip() if payload.explanation else None
    item.is_active = payload.is_active
    db.commit()
    db.refresh(item)
    return _serialize_qb_item(item, include_answer=True)


@admin_question_bank_router.delete("/question-bank/{question_id}")
def admin_delete_question(
    question_id: int,
    user=Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    item = db.get(QuestionBank, question_id)
    if not item:
        raise HTTPException(404, "Question not found")
    db.delete(item)
    db.commit()
    return {"id": question_id, "deleted": True}


@admin_question_bank_router.get("/assessment-policy")
def admin_get_assessment_policy(
    user=Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    return {
        "reveal_correct_answers_to_candidate": False,
    }


@admin_question_bank_router.put("/assessment-policy")
def admin_update_assessment_policy(
    payload: AssessmentPolicyRequest,
    user=Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    setting = db.scalar(
        select(PlatformSetting).where(PlatformSetting.setting_key == "reveal_assessment_answers")
    )
    # Candidate answer disclosure is prohibited by platform policy.
    value_str = "false"
    if setting is None:
        db.add(PlatformSetting(setting_key="reveal_assessment_answers", setting_value=value_str))
    else:
        setting.setting_value = value_str
    db.commit()
    return {"reveal_correct_answers_to_candidate": False}


# --- 2. Recruiter Question Bank Browse (Read-only) & Assessments ---

@recruiter_question_bank_router.get("")
def recruiter_browse_question_bank(
    q: str | None = None,
    skill: str | None = None,
    category: str | None = None,
    difficulty: str | None = None,
    job_id: int | None = Query(default=None, gt=0),
    match_job_skills: bool = False,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    job_skills: list[str] = []
    if job_id is not None:
        job = _get_eligible_recruiter_job(db, recruiter, job_id)
        job_skills = [js.skill.name for js in job.skills]

    stmt = select(QuestionBank).where(QuestionBank.is_active.is_(True))
    if skill:
        stmt = stmt.where(QuestionBank.skill.ilike(f"%{skill.strip()}%"))
    if category:
        stmt = stmt.where(QuestionBank.category.ilike(f"%{category.strip()}%"))
    if difficulty:
        stmt = stmt.where(QuestionBank.difficulty.ilike(difficulty.strip()))
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                QuestionBank.question_text.ilike(pattern),
                QuestionBank.skill.ilike(pattern),
                QuestionBank.category.ilike(pattern),
            )
        )

    items = db.scalars(stmt.order_by(QuestionBank.skill.asc(), QuestionBank.difficulty.asc(), QuestionBank.id.asc())).all()
    if match_job_skills and job_skills:
        norm_job_skills = {normalize_skill(s) for s in job_skills}
        items = [item for item in items if normalize_skill(item.skill) in norm_job_skills]

    all_active = db.scalars(select(QuestionBank).where(QuestionBank.is_active.is_(True))).all()
    return {
        "items": [
            {
                **_serialize_qb_item(item, include_answer=True),
                "is_editable": item.created_by_user_id == user.id,
            }
            for item in items
        ],
        "total": len(items),
        "skills": sorted({row.skill for row in all_active if row.skill}),
        "categories": sorted({row.category for row in all_active if row.category}),
        "job_skills": job_skills,
    }


@recruiter_question_bank_router.post("/generate", status_code=201)
def recruiter_generate_assessment_questions(
    payload: GenerateAssessmentQuestionsRequest,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    if not recruiter:
        raise HTTPException(404, "Recruiter profile not found.")
    job = _get_eligible_recruiter_job(db, recruiter, payload.job_id)

    available_skills = {item.skill.name.casefold(): item.skill.name for item in job.skills}
    selected_skills = []
    for skill in payload.skills:
        canonical = available_skills.get(skill.casefold())
        if not canonical:
            raise HTTPException(422, f"'{skill}' is not a skill listed on this job.")
        if canonical not in selected_skills:
            selected_skills.append(canonical)

    settings = get_settings()
    provider = (settings.ai_provider or "none").strip().lower()
    can_call_ai = (
        provider in {"openai", "gemini"}
        and bool(settings.ai_api_key.strip())
        and bool(settings.ai_model.strip())
    )

    accepted = []
    seen_texts: set[str] = set()

    if can_call_ai:
        prompt = (
            "Create original, accurate multiple-choice assessment questions. Return only JSON in this shape: "
            '{"questions":[{"skill":"...","question_text":"...","options":["...","...","...","..."],'
            '"correct_option_index":0,"explanation":"..."}]}. '
            f"Generate exactly {payload.question_count} questions at {payload.difficulty} difficulty. "
            f"Use only these job skills: {', '.join(selected_skills)}. "
            "Each question must have exactly four distinct options and one unambiguous correct answer. "
            "Avoid duplicates, trick wording, and questions requiring external context."
        )

        try:
            if provider == "openai":
                provider_response = httpx.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {settings.ai_api_key.strip()}"},
                    json={"model": settings.ai_model.strip(), "input": prompt},
                    timeout=60.0,
                )
                provider_response.raise_for_status()
                response_data = provider_response.json()
                generated_text = response_data.get("output_text")
                if not generated_text:
                    generated_text = "".join(
                        part.get("text", "")
                        for output in response_data.get("output", [])
                        for part in output.get("content", [])
                        if part.get("type") == "output_text"
                    )
            else:
                provider_response = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{settings.ai_model.strip()}:generateContent",
                    headers={"x-goog-api-key": settings.ai_api_key.strip()},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"responseMimeType": "application/json"},
                    },
                    timeout=60.0,
                )
                provider_response.raise_for_status()
                response_data = provider_response.json()
                generated_text = "".join(
                    part.get("text", "")
                    for part in response_data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                )
            decoded = json.loads(generated_text or "")
            generated_questions = decoded.get("questions") if isinstance(decoded, dict) else None
            if isinstance(generated_questions, list):
                for item in generated_questions:
                    if not isinstance(item, dict):
                        continue
                    question_text = str(item.get("question_text", "")).strip()
                    options = item.get("options")
                    answer_index = item.get("correct_option_index")
                    skill = available_skills.get(str(item.get("skill", "")).strip().casefold())
                    if skill not in selected_skills:
                        skill = selected_skills[len(accepted) % len(selected_skills)]
                    if (
                        len(question_text) < 5
                        or not isinstance(options, list)
                        or len(options) != 4
                        or not isinstance(answer_index, int)
                        or isinstance(answer_index, bool)
                        or answer_index not in range(4)
                    ):
                        continue
                    options = [str(option).strip() for option in options]
                    if any(not option for option in options) or len({option.casefold() for option in options}) != 4:
                        continue
                    fingerprint = question_text.casefold()
                    if fingerprint in seen_texts:
                        continue
                    seen_texts.add(fingerprint)
                    accepted.append({
                        "skill": skill,
                        "question_text": question_text,
                        "options": options,
                        "correct_option_index": answer_index,
                        "explanation": str(item.get("explanation") or "").strip() or None,
                    })
        except Exception:
            # Fall back to curated technical bank
            accepted = []

    # If AI call was skipped or did not yield required question count, supplement from curated bank
    if len(accepted) < payload.question_count:
        from app.assessment_bank import QUESTION_BANK
        norm_selected = {normalize_skill(s): s for s in selected_skills}
        diff_map = {
            "easy": ["basic"],
            "medium": ["intermediate", "basic"],
            "hard": ["advanced", "intermediate"],
        }
        target_diffs = set(diff_map.get(payload.difficulty.lower(), ["basic", "intermediate", "advanced"]))
        matching = [
            q for q in QUESTION_BANK
            if normalize_skill(q.get("skill_tag", "")) in norm_selected
        ] or QUESTION_BANK
        preferred = [q for q in matching if q.get("difficulty", "").lower() in target_diffs]
        pool = preferred if preferred else matching

        for item in pool:
            q_text = str(item.get("question", "")).strip()
            fingerprint = q_text.casefold()
            if fingerprint in seen_texts or len(q_text) < 5:
                continue
            seen_texts.add(fingerprint)
            skill_name = norm_selected.get(
                normalize_skill(item.get("skill_tag", "")),
                selected_skills[len(accepted) % len(selected_skills)],
            )
            raw_options = [str(opt).strip() for opt in item.get("options", [])][:4]
            if len(raw_options) < 4:
                continue
            accepted.append({
                "skill": skill_name,
                "question_text": q_text,
                "options": raw_options,
                "correct_option_index": int(item.get("correct_index", 0)),
                "explanation": str(item.get("explanation") or "").strip() or None,
            })
            if len(accepted) >= payload.question_count:
                break

    if not accepted:
        raise HTTPException(502, "Unable to generate valid assessment questions. Please retry generation.")
    accepted = accepted[:payload.question_count]

    created_items = []
    for item in accepted:
        question = QuestionBank(
            question_type="mcq",
            skill=item["skill"],
            category="AI Generated",
            difficulty=payload.difficulty,
            question_text=item["question_text"],
            options_json=json.dumps(item["options"]),
            correct_option_index=item["correct_option_index"],
            marks=payload.marks,
            explanation=item["explanation"],
            is_active=True,
            created_by_user_id=user.id,
        )
        db.add(question)
        created_items.append(question)
    db.commit()
    for question in created_items:
        db.refresh(question)
    return {
        "items": [
            {**_serialize_qb_item(question, include_answer=True), "is_editable": True}
            for question in created_items
        ],
        "total": len(created_items),
        "provider": provider,
    }


@recruiter_question_bank_router.put("/{question_id}")
def recruiter_update_generated_question(
    question_id: int,
    payload: RecruiterQuestionUpdateRequest,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    item = db.get(QuestionBank, question_id)
    if not item or item.created_by_user_id != user.id:
        raise HTTPException(404, "Editable question not found.")

    item.question_type = "mcq"
    item.skill = payload.skill
    item.category = payload.category
    item.difficulty = payload.difficulty
    item.question_text = payload.question_text
    item.options_json = json.dumps(payload.options)
    item.correct_option_index = payload.correct_option_index
    item.marks = payload.marks
    item.explanation = payload.explanation.strip() if payload.explanation else None
    db.commit()
    db.refresh(item)
    return {
        **_serialize_qb_item(item, include_answer=True),
        "is_editable": True,
    }


@recruiter_assessment_router.get("/assessments")
def recruiter_list_assessments(
    job_id: int | None = Query(default=None, gt=0),
    status: str | None = None,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    stmt = select(Assessment).where(Assessment.recruiter_id == recruiter.id)
    if job_id is not None:
        stmt = stmt.where(Assessment.job_id == job_id)
    if status:
        stmt = stmt.where(Assessment.status == status.strip().lower())
    items = db.scalars(stmt.order_by(Assessment.created_at.desc(), Assessment.id.desc())).all()
    return [_serialize_assessment_summary(item, include_questions=False) for item in items]


@recruiter_assessment_router.get("/assessments/{assessment_id}")
def recruiter_get_assessment(
    assessment_id: int,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    assessment = db.get(Assessment, assessment_id)
    if not assessment or assessment.recruiter_id != recruiter.id:
        raise HTTPException(404, "Assessment not found")
    return _serialize_assessment_summary(assessment, include_questions=True)


@recruiter_assessment_router.post("/assessments", status_code=201)
def recruiter_create_assessment(
    payload: AssessmentUpsertRequest,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    if not recruiter:
        raise HTTPException(404, "Recruiter profile not found.")
    job = _get_eligible_recruiter_job(db, recruiter, payload.job_id)

    assessment = Assessment(
        recruiter_id=recruiter.id,
        job_id=job.id,
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        instructions=payload.instructions.strip(),
        duration_minutes=payload.duration_minutes,
        passing_marks=payload.passing_marks,
        status=payload.status,
        expires_at=payload.expires_at,
    )
    db.add(assessment)
    db.flush()
    _sync_assessment_questions(db, assessment, payload.question_ids)

    if assessment.status == "published":
        _validate_publishable_assessment(assessment)

    db.commit()
    db.refresh(assessment)
    return _serialize_assessment_summary(assessment, include_questions=True)


@recruiter_assessment_router.put("/assessments/{assessment_id}")
def recruiter_update_assessment(
    assessment_id: int,
    payload: AssessmentUpsertRequest,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    assessment = db.get(Assessment, assessment_id)
    if not assessment or assessment.recruiter_id != recruiter.id:
        raise HTTPException(404, "Assessment not found")

    job = _get_eligible_recruiter_job(db, recruiter, payload.job_id)

    if assessment.assignments:
        raise HTTPException(
            409,
            "This assessment has already been assigned to candidates and cannot be edited. Create a new assessment instead.",
        )

    assessment.job_id = job.id
    assessment.title = payload.title.strip()
    assessment.description = payload.description.strip() if payload.description else None
    assessment.instructions = payload.instructions.strip()
    assessment.duration_minutes = payload.duration_minutes
    assessment.passing_marks = payload.passing_marks
    assessment.expires_at = payload.expires_at
    assessment.status = payload.status

    _sync_assessment_questions(db, assessment, payload.question_ids)
    if assessment.status == "published":
        _validate_publishable_assessment(assessment)

    db.commit()
    db.refresh(assessment)
    return _serialize_assessment_summary(assessment, include_questions=True)


@recruiter_assessment_router.post("/assessments/{assessment_id}/publish")
def recruiter_publish_assessment(
    assessment_id: int,
    payload: PublishAssessmentRequest | None = None,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    assessment = db.get(Assessment, assessment_id)
    if not assessment or assessment.recruiter_id != recruiter.id:
        raise HTTPException(404, "Assessment not found")
    _get_eligible_recruiter_job(db, recruiter, assessment.job_id)

    if payload and payload.expires_at is not None:
        if ensure_utc(payload.expires_at) <= utc_now():
            raise HTTPException(422, "Assessment expiry date must be in the future.")
        assessment.expires_at = payload.expires_at
    elif assessment.expires_at is not None and ensure_utc(assessment.expires_at) <= utc_now():
        # Draft's old deadline has passed: clear it so the assessment can be successfully published
        assessment.expires_at = None

    _validate_publishable_assessment(assessment)
    assessment.status = "published"
    db.commit()
    db.refresh(assessment)
    return _serialize_assessment_summary(assessment, include_questions=True)


@recruiter_assessment_router.delete("/assessments/{assessment_id}")
def recruiter_delete_assessment(
    assessment_id: int,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    assessment = db.get(Assessment, assessment_id)
    if not assessment or assessment.recruiter_id != recruiter.id:
        raise HTTPException(404, "Assessment not found")
    if assessment.assignments:
        raise HTTPException(409, "Assessments with assigned candidates cannot be deleted.")
    db.delete(assessment)
    db.commit()
    return {"id": assessment_id, "deleted": True}


# --- 3. Recruiter Manual Assignment & Results ---

@recruiter_assessment_router.post("/assessments/{assessment_id}/assign")
def recruiter_assign_assessment(
    assessment_id: int,
    payload: AssignAssessmentRequest,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    assessment = db.get(Assessment, assessment_id)
    if not assessment or assessment.recruiter_id != recruiter.id:
        raise HTTPException(404, "Assessment not found")
    if assessment.status != "published":
        raise HTTPException(409, "Publish the assessment before assigning it to candidates.")
    _get_eligible_recruiter_job(db, recruiter, assessment.job_id)
    if assessment.total_questions < 1:
        raise HTTPException(422, "Assessment has no questions.")

    now = utc_now()
    expires_at = ensure_utc(payload.expires_at) or ensure_utc(assessment.expires_at) or (now + timedelta(hours=72))
    if expires_at <= now:
        raise HTTPException(422, "Assignment expiry date must be in the future.")

    unique_app_ids = list(dict.fromkeys(payload.application_ids))
    outcomes = []
    sent_count = 0
    failed_count = 0
    skipped_count = 0

    for app_id in unique_app_ids:
        application = db.get(Application, app_id)
        if not application or application.job.recruiter_id != recruiter.id:
            raise HTTPException(404, f"Application {app_id} not found")
        if application.job_id != assessment.job_id:
            raise HTTPException(422, f"Application {app_id} belongs to a different job posting.")
        if application.status != "shortlisted":
            raise HTTPException(
                409,
                f"Candidate '{application.candidate.user.full_name}' has status '{application.status}'. "
                "Only shortlisted candidates can be assigned this assessment.",
            )

        existing = db.scalar(
            select(AssessmentAssignment).where(
                AssessmentAssignment.assessment_id == assessment.id,
                AssessmentAssignment.application_id == application.id,
            )
        )
        if existing is not None:
            skipped_count += 1
            outcomes.append({
                "application_id": application.id,
                "assignment_id": existing.id,
                "candidate": application.candidate.user.full_name,
                "email": existing.recipient_email,
                "invitation_status": existing.invitation_status,
                "test_status": existing.test_status,
                "skipped": True,
                "message": "Already assigned to this candidate.",
            })
            continue

        raw_token = secrets.token_urlsafe(32)
        recipient_email = (application.candidate.user.email or application.candidate.contact_email or "").strip()
        assignment = AssessmentAssignment(
            assessment_id=assessment.id,
            application_id=application.id,
            candidate_id=application.candidate_id,
            job_id=application.job_id,
            assigned_by_recruiter_id=recruiter.id,
            token_hash=hash_opaque_token(raw_token),
            recipient_email=recipient_email,
            invitation_status="pending",
            test_status="assigned",
            assigned_at=now,
            expires_at=expires_at,
        )
        try:
            with db.begin_nested():
                db.add(assignment)
                db.flush()
        except IntegrityError:
            skipped_count += 1
            continue

        email_result = send_assignment_invitation_email(db, assignment, raw_token)
        if email_result["invitation_status"] == "sent":
            sent_count += 1
        else:
            failed_count += 1

        outcomes.append({
            "application_id": application.id,
            "assignment_id": assignment.id,
            "candidate": application.candidate.user.full_name,
            "email": recipient_email,
            "invitation_status": assignment.invitation_status,
            "test_status": assignment.test_status,
            "skipped": False,
            "message": email_result["message"],
        })

    db.commit()
    return {
        "assessment_id": assessment.id,
        "assigned_count": len(outcomes) - skipped_count,
        "sent_count": sent_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "results": outcomes,
    }


@recruiter_assessment_router.post("/assignments/{assignment_id}/resend")
def recruiter_resend_assignment(
    assignment_id: int,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    assignment = db.get(AssessmentAssignment, assignment_id)
    if not assignment or assignment.job.recruiter_id != recruiter.id:
        raise HTTPException(404, "Assessment assignment not found")
    if assignment.test_status == "submitted":
        raise HTTPException(409, "Candidate has already submitted this assessment.")

    now = utc_now()
    if ensure_utc(assignment.expires_at) <= now:
        assignment.expires_at = now + timedelta(hours=72)
        if assignment.test_status == "expired":
            assignment.test_status = "assigned"

    raw_token = secrets.token_urlsafe(32)
    assignment.token_hash = hash_opaque_token(raw_token)
    email_result = send_assignment_invitation_email(db, assignment, raw_token)
    db.commit()
    if email_result["invitation_status"] == "failed":
        raise HTTPException(503, email_result.get("error") or "Failed to send invitation email.")
    return {
        "assignment_id": assignment.id,
        "invitation_status": assignment.invitation_status,
        "sent_at": isoformat_utc(assignment.sent_at),
        "message": email_result["message"],
    }


def _serialize_result_row(db: Session, assignment: AssessmentAssignment) -> dict:
    _refresh_assignment_lifecycle(db, assignment)
    result = assignment.result
    return {
        "assignment_id": assignment.id,
        "assessment_id": assignment.assessment_id,
        "assessment_title": assignment.assessment.title,
        "application_id": assignment.application_id,
        "job_id": assignment.job_id,
        "job_title": assignment.job.title,
        "candidate_id": assignment.candidate_id,
        "candidate_name": assignment.candidate.user.full_name,
        "candidate_email": assignment.recipient_email,
        "assigned_at": isoformat_utc(assignment.assigned_at),
        "expires_at": isoformat_utc(assignment.expires_at),
        "invitation_status": assignment.invitation_status,
        "invitation_error": assignment.invitation_error,
        "sent_at": isoformat_utc(assignment.sent_at),
        "test_status": assignment.test_status,
        "started_at": isoformat_utc(assignment.started_at),
        "submitted_at": isoformat_utc(assignment.submitted_at),
        "submitted_automatically": assignment.submitted_automatically,
        "obtained_marks": result.obtained_marks if result else None,
        "total_marks": result.total_marks if result else assignment.assessment.total_marks,
        "passing_marks": result.passing_marks if result else assignment.assessment.passing_marks,
        "percentage": float(result.percentage) if result else None,
        "is_passed": result.is_passed if result else None,
        "result_status": result.result_status if result else None,
        "result_message": result.result_message if result else None,
        "assessment_type": getattr(assignment.assessment, "assessment_type", "mcq") or "mcq",
        "proctoring_event_count": len(assignment.proctoring_events),
    }


@recruiter_assessment_router.get("/proctoring-events")
def recruiter_list_proctoring_events(
    job_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    if not recruiter:
        raise HTTPException(404, "Recruiter profile not found.")

    stmt = (
        select(ProctoringEvent, AssessmentAssignment)
        .join(AssessmentAssignment, ProctoringEvent.assignment_id == AssessmentAssignment.id)
        .join(Job, AssessmentAssignment.job_id == Job.id)
        .where(Job.recruiter_id == recruiter.id)
    )
    count_stmt = (
        select(func.count(ProctoringEvent.id))
        .join(AssessmentAssignment, ProctoringEvent.assignment_id == AssessmentAssignment.id)
        .join(Job, AssessmentAssignment.job_id == Job.id)
        .where(Job.recruiter_id == recruiter.id)
    )

    if job_id is not None:
        stmt = stmt.where(AssessmentAssignment.job_id == job_id)
        count_stmt = count_stmt.where(AssessmentAssignment.job_id == job_id)

    rows = db.execute(
        stmt.order_by(ProctoringEvent.created_at.desc(), ProctoringEvent.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    total = db.scalar(count_stmt) or 0

    return {
        "items": [
            {
                "id": event.id,
                "assignment_id": event.assignment_id,
                "event_type": event.event_type,
                "details": json.loads(event.details) if event.details else {},
                "created_at": isoformat_utc(event.created_at),
                "candidate_name": assignment.candidate.user.full_name,
                "job_title": assignment.job.title,
                "assessment_title": assignment.assessment.title,
            }
            for event, assignment in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

@recruiter_assessment_router.get("/assessment-results")
def recruiter_list_assessment_results(
    job_id: int | None = Query(default=None, gt=0),
    assessment_id: int | None = Query(default=None, gt=0),
    test_status: str | None = None,
    result_status: str | None = None,
    q: str | None = None,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    stmt = (
        select(AssessmentAssignment)
        .join(Job, AssessmentAssignment.job_id == Job.id)
        .where(Job.recruiter_id == recruiter.id)
    )
    if job_id is not None:
        stmt = stmt.where(AssessmentAssignment.job_id == job_id)
    if assessment_id is not None:
        stmt = stmt.where(AssessmentAssignment.assessment_id == assessment_id)

    assignments = db.scalars(
        stmt.order_by(AssessmentAssignment.assigned_at.desc(), AssessmentAssignment.id.desc())
    ).all()

    rows = [_serialize_result_row(db, item) for item in assignments]
    db.commit()

    if test_status:
        rows = [r for r in rows if r["test_status"] == test_status.strip().lower()]
    if result_status:
        rows = [r for r in rows if (r["result_status"] or "").lower() == result_status.strip().lower()]
    if q:
        q_norm = q.strip().casefold()
        rows = [
            r for r in rows
            if q_norm in " ".join([
                r["candidate_name"] or "",
                r["candidate_email"] or "",
                r["job_title"] or "",
                r["assessment_title"] or "",
            ]).casefold()
        ]
    return rows


@recruiter_assessment_router.get("/assessment-results/{assignment_id}")
def recruiter_get_assessment_result_detail(
    assignment_id: int,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    assignment = db.get(AssessmentAssignment, assignment_id)
    if not assignment or assignment.job.recruiter_id != recruiter.id:
        raise HTTPException(404, "Assessment assignment not found")

    row = _serialize_result_row(db, assignment)
    db.commit()

    from app.cloudinary_service import generate_secure_playback_url

    ans_map = {ans.assessment_question_id: ans for ans in assignment.answers}
    rec_list = db.scalars(
        select(AssessmentRecording).where(
            AssessmentRecording.assessment_id == assignment.assessment_id,
            AssessmentRecording.application_id == assignment.application_id,
            AssessmentRecording.upload_status == "uploaded",
        )
    ).all()
    rec_by_q = {}
    for r in rec_list:
        if r.question_id:
            try:
                play_url = generate_secure_playback_url(
                    public_id=r.cloudinary_public_id,
                    video_format=r.format or "mp4",
                    expires_in_seconds=900,
                    is_authenticated_asset=True,
                )
            except Exception:
                play_url = r.cloudinary_secure_url
            rec_by_q.setdefault(r.question_id, []).append({
                "id": r.id,
                "cloudinary_public_id": r.cloudinary_public_id,
                "cloudinary_secure_url": play_url,
                "duration": r.duration,
                "format": r.format,
                "file_size": r.file_size,
            })

    questions = []
    for q in assignment.assessment.questions:
        ans = ans_map.get(q.id)
        questions.append({
            "id": q.id,
            "order_index": q.order_index,
            "skill": q.skill,
            "category": q.category,
            "difficulty": q.difficulty,
            "question_type": getattr(q, "question_type", "mcq") or "mcq",
            "question_text": q.question_text,
            "instructions": getattr(q, "instructions", "") or "",
            "options": json.loads(q.options_json) if q.options_json else [],
            "correct_option_index": q.correct_option_index,
            "marks": q.marks,
            "selected_option_index": ans.selected_option_index if ans else None,
            "is_correct": ans.is_correct if ans else False,
            "marks_awarded": ans.marks_awarded if ans else 0,
            "explanation": q.explanation,
            "video_recordings": rec_by_q.get(q.id, []),
        })

    events = [
        {
            "id": e.id,
            "event_type": e.event_type,
            "details": json.loads(e.details) if e.details else {},
            "created_at": isoformat_utc(e.created_at),
        }
        for e in assignment.proctoring_events
    ]

    return {
        **row,
        "duration_minutes": assignment.assessment.duration_minutes,
        "instructions": assignment.assessment.instructions,
        "questions": questions,
        "proctoring_events": events,
        "proctoring_event_count": len(events),
    }


@recruiter_assessment_router.get("/assessment-recordings")
def recruiter_list_assessment_recordings(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    stmt = (
        select(AssessmentRecording, AssessmentAssignment)
        .join(AssessmentAssignment, AssessmentRecording.assignment_id == AssessmentAssignment.id)
        .join(Job, AssessmentAssignment.job_id == Job.id)
        .where(Job.recruiter_id == recruiter.id)
        .order_by(AssessmentRecording.created_at.desc(), AssessmentRecording.id.desc())
    )
    total = db.scalar(
        select(func.count(AssessmentRecording.id))
        .join(AssessmentAssignment, AssessmentRecording.assignment_id == AssessmentAssignment.id)
        .join(Job, AssessmentAssignment.job_id == Job.id)
        .where(Job.recruiter_id == recruiter.id)
    ) or 0
    rows = db.execute(stmt.offset(offset).limit(limit)).all()
    return {
        "items": [
            {
                "id": recording.id,
                "assignment_id": assignment.id,
                "candidate_name": assignment.candidate.user.full_name,
                "candidate_email": assignment.recipient_email,
                "job_title": assignment.job.title,
                "assessment_title": assignment.assessment.title,
                "status": recording.status,
                "video_format": recording.video_format,
                "duration_seconds": recording.duration_seconds,
                "file_size_bytes": recording.file_size_bytes,
                "consent_given": recording.consent_given,
                "uploaded_at": isoformat_utc(recording.uploaded_at),
            }
            for recording, assignment in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@recruiter_assessment_router.get("/assessment-recordings/{recording_id}/playback")
def recruiter_get_assessment_recording_playback(
    recording_id: int,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    recording = db.get(AssessmentRecording, recording_id)
    if not recording or recording.assignment.job.recruiter_id != recruiter.id:
        raise HTTPException(404, "Assessment recording not found.")
    if recording.status != "uploaded" or not recording.cloudinary_public_id or not recording.video_format:
        raise HTTPException(409, "This assessment recording is not available for playback.")

    settings = get_settings()
    if not all((settings.cloudinary_cloud_name, settings.cloudinary_api_key, settings.cloudinary_api_secret)):
        raise HTTPException(503, "Recording storage is not configured.")

    try:
        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            secure=True,
        )
        expires_at = int((utc_now() + timedelta(minutes=10)).timestamp())
        playback_url = private_download_url(
            recording.cloudinary_public_id,
            recording.video_format,
            resource_type="video",
            type="authenticated",
            expires_at=expires_at,
            secure=True,
        )
        return {
            "recording_id": recording.id,
            "playback_url": playback_url,
            "expires_at": isoformat_utc(datetime.fromtimestamp(expires_at, tz=utc_now().tzinfo)),
        }
    except Exception as exc:
        raise HTTPException(502, "Could not generate the secure recording playback link.") from exc


# --- 4. Candidate Online MCQ Assessment Portal ---

def create_candidate_assessment_launch_token(assignment_id: int, user_id: int, expires_at: datetime | None) -> str:
    settings = get_settings()
    now = utc_now()
    exp_dt = expires_at if expires_at else now + timedelta(days=7)
    payload = {
        "sub": str(user_id),
        "assignment_id": assignment_id,
        "scope": "assessment_launch",
        "iat": int(now.timestamp()),
        "exp": int(exp_dt.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _load_assignment_by_token(db: Session, token: str) -> AssessmentAssignment:
    cleaned = (token or "").strip()
    token_hash = hash_opaque_token(cleaned)
    assignment = db.scalar(
        select(AssessmentAssignment).where(AssessmentAssignment.token_hash == token_hash)
    )
    if not assignment:
        try:
            settings = get_settings()
            payload = jwt.decode(cleaned, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            if payload.get("scope") == "assessment_launch":
                assignment_id = int(payload.get("assignment_id"))
                candidate_user_id = int(payload.get("sub"))
                cand_assignment = db.get(AssessmentAssignment, assignment_id)
                if cand_assignment and cand_assignment.candidate and cand_assignment.candidate.user_id == candidate_user_id:
                    assignment = cand_assignment
        except Exception:
            pass

    if not assignment or not assignment.assessment:
        raise HTTPException(404, "Assessment invitation link is invalid or not found.")
    return assignment


def _verify_assignment_owner(assignment: AssessmentAssignment, user: User) -> None:
    if user.role != "candidate" or assignment.candidate.user_id != user.id:
        raise HTTPException(403, "This assessment invitation belongs to a different candidate account.")


def _serialize_candidate_result(assignment: AssessmentAssignment) -> dict:
    return {
        "message": "Your assessment has been successfully submitted. Your responses have been recorded and are under review. The assessment was submitted successfully. Our recruitment team will notify you about the next steps.",
    }


@assessment_router.get("/application/{application_id}/token")
def get_candidate_assessment_token(
    application_id: int,
    user: User = Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if not candidate:
        raise HTTPException(404, "Candidate profile not found.")

    application = db.get(Application, application_id)
    if not application or application.candidate_id != candidate.id:
        raise HTTPException(404, "Application not found.")

    assignment = db.scalar(
        select(AssessmentAssignment)
        .where(AssessmentAssignment.application_id == application.id)
        .order_by(AssessmentAssignment.id.desc())
    )
    if not assignment:
        raise HTTPException(404, "No assessment assigned for this application.")

    _refresh_assignment_lifecycle(db, assignment)
    db.commit()

    if assignment.test_status == "submitted":
        raise HTTPException(409, "This assessment has already been completed and submitted.")

    now = utc_now()
    exp = ensure_utc(assignment.expires_at)
    if assignment.test_status == "expired" or (exp is not None and now > exp):
        assignment.test_status = "expired"
        db.commit()
        raise HTTPException(410, "This assessment invitation has expired.")

    launch_token = create_candidate_assessment_launch_token(assignment.id, user.id, exp)
    return {
        "assignment_id": assignment.id,
        "token": launch_token,
        "test_status": assignment.test_status,
        "assessment_type": getattr(assignment.assessment, "assessment_type", "mcq") or "mcq",
        "title": assignment.assessment.title if assignment.assessment else None,
        "duration_minutes": assignment.assessment.duration_minutes if assignment.assessment else 30,
        "expires_at": isoformat_utc(assignment.expires_at),
    }


@assessment_router.get("/{token}")
def verify_assessment_invitation(
    token: str,
    user: User | None = Depends(optional_current_user),
    db: Session = Depends(get_db),
):
    assignment = _load_assignment_by_token(db, token)
    if user is not None:
        _verify_assignment_owner(assignment, user)

    _refresh_assignment_lifecycle(db, assignment)
    db.commit()

    if assignment.test_status == "submitted":
        return {
            "test_status": "submitted",
            "result": _serialize_candidate_result(assignment),
        }

    is_owner = user is not None and user.role == "candidate" and assignment.candidate.user_id == user.id

    assessment = assignment.assessment
    now = utc_now()
    remaining_seconds = None
    if assignment.test_status == "started" and assignment.deadline_at is not None:
        remaining_seconds = max(0, int((ensure_utc(assignment.deadline_at) - now).total_seconds()))

    response = {
        "invitation_status": assignment.invitation_status,
        "test_status": assignment.test_status,
        "job_title": assignment.job.title if assignment.job else None,
        "company_name": assignment.job.company.name if assignment.job and assignment.job.company else "SkillSphere",
        "candidate_name": assignment.candidate.user.full_name if is_owner else None,
        "title": assessment.title,
        "description": assessment.description,
        "assessment_type": getattr(assessment, "assessment_type", "mcq") or "mcq",
        "prep_time_seconds": getattr(assessment, "prep_time_seconds", 30) or 30,
        "response_time_seconds": getattr(assessment, "response_time_seconds", 120) or 120,
        "allow_review": getattr(assessment, "allow_review", True),
        "max_recordings_per_question": getattr(assessment, "max_recordings_per_question", 1) or 1,
        "total_questions": assessment.total_questions,
        "duration_minutes": assessment.duration_minutes,
        "instructions": assessment.instructions,
        "expires_at": isoformat_utc(assignment.expires_at),
        "started_at": isoformat_utc(assignment.started_at),
        "deadline_at": isoformat_utc(assignment.deadline_at),
        "remaining_seconds": remaining_seconds,
        "requires_auth": not is_owner,
    }
    return response


@assessment_router.post("/{token}/start")
def start_or_resume_assessment(
    token: str,
    user: User = Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    assignment = _load_assignment_by_token(db, token)
    _verify_assignment_owner(assignment, user)

    now = utc_now()
    if assignment.test_status == "submitted":
        raise HTTPException(409, "You have already completed this assessment. Retakes are not permitted.")

    exp = ensure_utc(assignment.expires_at)
    if assignment.test_status == "expired" or (
        assignment.test_status == "assigned" and exp is not None and now > exp
    ):
        assignment.test_status = "expired"
        db.commit()
        raise HTTPException(410, "This assessment invitation link has expired.")

    assessment = assignment.assessment
    if assignment.test_status == "assigned":
        assignment.test_status = "started"
        assignment.started_at = now
        computed_deadline = now + timedelta(minutes=assessment.duration_minutes)
        if exp is not None and exp < computed_deadline:
            computed_deadline = exp
        assignment.deadline_at = computed_deadline
        db.commit()
        db.refresh(assignment)
    elif assignment.deadline_at is not None and now > ensure_utc(assignment.deadline_at):
        evaluate_assignment_submission(db, assignment, auto_submitted=True)
        db.commit()
        raise HTTPException(409, "Assessment time expired and your saved answers were submitted automatically.")

    remaining_seconds = (
        max(0, int((ensure_utc(assignment.deadline_at) - now).total_seconds()))
        if assignment.deadline_at
        else assessment.duration_minutes * 60
    )

    ans_map = {ans.assessment_question_id: ans.selected_option_index for ans in assignment.answers}
    return {
        "assignment_id": assignment.id,
        "assessment_id": assessment.id,
        "title": assessment.title,
        "assessment_type": getattr(assessment, "assessment_type", "mcq") or "mcq",
        "prep_time_seconds": getattr(assessment, "prep_time_seconds", 30) or 30,
        "response_time_seconds": getattr(assessment, "response_time_seconds", 120) or 120,
        "allow_review": getattr(assessment, "allow_review", True),
        "max_recordings_per_question": getattr(assessment, "max_recordings_per_question", 1) or 1,
        "job_title": assignment.job.title if assignment.job else None,
        "company_name": assignment.job.company.name if assignment.job and assignment.job.company else "SkillSphere",
        "test_status": assignment.test_status,
        "total_questions": assessment.total_questions,
        "duration_minutes": assessment.duration_minutes,
        "started_at": isoformat_utc(assignment.started_at),
        "deadline_at": isoformat_utc(assignment.deadline_at),
        "remaining_seconds": remaining_seconds,
        "questions": [
            {
                **_serialize_assessment_question(q, include_answer=False),
                "selected_option_index": ans_map.get(q.id),
            }
            for q in assessment.questions
        ],
    }


@assessment_router.post("/{token}/proctoring-events")
def record_proctoring_event(
    token: str,
    payload: ProctoringEventRequest,
    user: User = Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    assignment = _load_assignment_by_token(db, token)
    _verify_assignment_owner(assignment, user)

    if assignment.test_status != "started":
        raise HTTPException(409, "Proctoring events can only be recorded during an active assessment.")

    forbidden_keys = {"image", "video", "frame", "photo", "screenshot", "base64"}
    if any(str(key).strip().lower() in forbidden_keys for key in payload.details):
        raise HTTPException(400, "Image and video data are not accepted.")

    details_json = json.dumps(payload.details)
    if len(details_json) > 1000:
        raise HTTPException(413, "Proctoring event details are too large.")

    event = ProctoringEvent(
        assignment_id=assignment.id,
        event_type=payload.event_type,
        details=details_json,
        created_at=utc_now(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return {
        "id": event.id,
        "event_type": event.event_type,
        "created_at": isoformat_utc(event.created_at),
        "message": "Proctoring event recorded.",
    }

@assessment_router.put("/{token}/answer")
def save_assessment_answer(
    token: str,
    payload: SaveAnswerRequest,
    user: User = Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    assignment = _load_assignment_by_token(db, token)
    _verify_assignment_owner(assignment, user)

    if assignment.test_status == "submitted":
        raise HTTPException(409, "This assessment has already been submitted.")
    if assignment.test_status != "started":
        raise HTTPException(409, "Start the assessment before saving answers.")

    now = utc_now()
    deadline = ensure_utc(assignment.deadline_at)
    if deadline and now > deadline + timedelta(seconds=10):
        evaluate_assignment_submission(db, assignment, auto_submitted=True)
        db.commit()
        raise HTTPException(409, "Time expired; your assessment has been submitted automatically.")

    question = db.scalar(
        select(AssessmentQuestion).where(
            AssessmentQuestion.id == payload.question_id,
            AssessmentQuestion.assessment_id == assignment.assessment_id,
        )
    )
    if not question:
        raise HTTPException(404, "Question not found in this assessment.")

    ans = db.scalar(
        select(CandidateAnswer).where(
            CandidateAnswer.assignment_id == assignment.id,
            CandidateAnswer.assessment_question_id == question.id,
        )
    )
    if ans is None:
        ans = CandidateAnswer(
            assignment_id=assignment.id,
            assessment_question_id=question.id,
            selected_option_index=payload.selected_option_index,
            answered_at=now,
        )
        db.add(ans)
    else:
        ans.selected_option_index = payload.selected_option_index
        ans.answered_at = now
    db.commit()

    return {
        "question_id": question.id,
        "selected_option_index": ans.selected_option_index,
        "saved_at": isoformat_utc(now),
    }



@assessment_router.post("/{token}/recording")
def upload_assessment_recording(
    token: str,
    file: UploadFile = File(...),
    consent_given: bool = Form(...),
    duration_seconds: int | None = Form(default=None, ge=0, le=7200),
    user: User = Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    assignment = _load_assignment_by_token(db, token)
    _verify_assignment_owner(assignment, user)

    if assignment.test_status != "started":
        raise HTTPException(409, "The assessment must be in progress to upload its recording.")

    if not consent_given:
        raise HTTPException(400, "Recording consent is required.")

    allowed_types = {"video/webm", "video/mp4", "video/quicktime"}
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in allowed_types:
        raise HTTPException(415, "Only WebM or MP4 video recordings are accepted.")

    max_size = 100 * 1024 * 1024
    video_data = file.file.read(max_size + 1)

    if not video_data:
        raise HTTPException(400, "The recording file is empty.")
    if len(video_data) > max_size:
        raise HTTPException(413, "The recording exceeds the 100 MB upload limit.")
    settings = get_settings()
    if not all((
        settings.cloudinary_cloud_name,
        settings.cloudinary_api_key,
        settings.cloudinary_api_secret,
    )):
        raise HTTPException(503, "Recording storage is not configured.")

    uploaded_public_id = None
    try:
        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            secure=True,
        )

        result = cloudinary_upload(
            video_data,
            resource_type="video",
            type="authenticated",
            folder="skillsphere/round1",
            public_id=secrets.token_urlsafe(24),
            overwrite=False,
        )
        uploaded_public_id = result.get("public_id")

        # Validate foreign keys before recording metadata insertion
        from app.cloudinary_service import validate_foreign_keys_for_recording
        clean_cand_id, clean_app_id, clean_ass_id, _, _ = validate_foreign_keys_for_recording(
            db,
            candidate_id=assignment.candidate_id,
            application_id=assignment.application_id,
            assessment_id=assignment.assessment_id,
        )

        now = utc_now()
        recording = AssessmentRecording(
            assignment_id=assignment.id,
            assessment_id=clean_ass_id,
            application_id=clean_app_id,
            candidate_id=clean_cand_id,
            cloudinary_url=result.get("secure_url"),
            cloudinary_secure_url=result.get("secure_url"),
            cloudinary_public_id=uploaded_public_id,
            video_format=result.get("format"),
            format=result.get("format"),
            duration_seconds=duration_seconds,
            duration=duration_seconds,
            file_size_bytes=result.get("bytes", len(video_data)),
            file_size=result.get("bytes", len(video_data)),
            status="uploaded",
            upload_status="completed",
            consent_given=True,
            consent_at=now,
            uploaded_at=now,
        )
        db.add(recording)
        db.commit()
        db.refresh(recording)

        return {
            "recording_id": recording.id,
            "status": recording.status,
            "duration_seconds": recording.duration_seconds,
            "file_size_bytes": recording.file_size_bytes,
            "uploaded_at": isoformat_utc(recording.uploaded_at),
        }

    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        if uploaded_public_id:
            try:
                cloudinary.uploader.destroy(
                    uploaded_public_id,
                    resource_type="video",
                    type="authenticated",
                )
            except Exception:
                pass
        raise HTTPException(502, "Recording upload failed. Please try again.") from exc
    finally:
        file.file.close()


@assessment_router.post("/{token}/submit")
def submit_assessment(
    token: str,
    payload: SubmitAssessmentRequest = Body(default_factory=SubmitAssessmentRequest),
    user: User = Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    assignment = _load_assignment_by_token(db, token)
    _verify_assignment_owner(assignment, user)

    if assignment.test_status == "submitted":
        raise HTTPException(409, "This assessment has already been submitted.")
    if assignment.test_status == "expired":
        raise HTTPException(410, "This assessment invitation has expired.")
    if assignment.test_status != "started":
        raise HTTPException(409, "Start the assessment before submitting.")

    now = utc_now()
    deadline = ensure_utc(assignment.deadline_at)
    timed_out = bool(deadline and now > deadline + timedelta(seconds=10))

    if payload.answers and not timed_out:
        valid_qids = {q.id for q in assignment.assessment.questions}
        existing_map = {ans.assessment_question_id: ans for ans in assignment.answers}
        for qid, option_idx in payload.answers.items():
            if qid in valid_qids and isinstance(option_idx, int) and 0 <= option_idx < 4:
                if qid in existing_map:
                    existing_map[qid].selected_option_index = option_idx
                    existing_map[qid].answered_at = now
                else:
                    db.add(
                        CandidateAnswer(
                            assignment_id=assignment.id,
                            assessment_question_id=qid,
                            selected_option_index=option_idx,
                            answered_at=now,
                        )
                    )
        db.flush()
        db.refresh(assignment)

    evaluate_assignment_submission(
        db,
        assignment,
        auto_submitted=bool(payload.auto_submitted or timed_out),
    )
    db.commit()
    db.refresh(assignment)
    return _serialize_candidate_result(assignment)


# ==============================================================================
# Asynchronous Video Assessment Endpoints
# ==============================================================================

@assessment_router.post("/{token}/questions/{question_id}/recording")
def upload_video_question_recording(
    token: str,
    question_id: int,
    file: UploadFile = File(...),
    duration_seconds: int | None = Form(default=None, ge=0, le=1800),
    user: User = Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    """Candidate uploads a recorded video response for a specific video interview question."""
    assignment = _load_assignment_by_token(db, token)
    _verify_assignment_owner(assignment, user)

    if assignment.test_status == "submitted":
        raise HTTPException(409, "This assessment has already been submitted.")
    if assignment.test_status == "expired":
        raise HTTPException(410, "This assessment has expired.")

    if assignment.test_status == "assigned":
        assignment.test_status = "started"
        assignment.started_at = utc_now()
        db.commit()

    question = db.get(AssessmentQuestion, question_id)
    if not question or question.assessment_id != assignment.assessment_id:
        raise HTTPException(404, "Assessment question not found on this assessment.")

    allowed_types = {"video/webm", "video/mp4", "video/quicktime"}
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in allowed_types:
        raise HTTPException(415, "Only WebM or MP4 video recordings are accepted.")

    max_size = 100 * 1024 * 1024
    video_data = file.file.read(max_size + 1)
    if not video_data:
        raise HTTPException(400, "Recording file is empty.")
    if len(video_data) > max_size:
        raise HTTPException(413, "Recording exceeds the 100 MB upload limit.")

    from app.cloudinary_service import (
        CLOUDINARY_FOLDER_VIDEO_ASSESSMENTS,
        upload_video_to_cloudinary,
        validate_foreign_keys_for_recording,
    )

    # Validate foreign keys
    clean_cand_id, clean_app_id, clean_ass_id, _, clean_q_id = validate_foreign_keys_for_recording(
        db,
        candidate_id=assignment.candidate_id,
        application_id=assignment.application_id,
        assessment_id=assignment.assessment_id,
        question_id=question_id,
    )

    try:
        public_id = f"video_q_{assignment.id}_{question_id}_{secrets.token_urlsafe(12)}"
        res = upload_video_to_cloudinary(
            file_data_or_path=video_data,
            folder=CLOUDINARY_FOLDER_VIDEO_ASSESSMENTS,
            public_id=public_id,
            resource_type="video",
            authenticated=True,
        )

        now = utc_now()
        # Find existing recording for this question to update, or create new
        recording = db.scalar(
            select(AssessmentRecording).where(
                AssessmentRecording.assignment_id == assignment.id,
                AssessmentRecording.question_id == question_id,
            )
        )
        if not recording:
            recording = AssessmentRecording(
                assignment_id=assignment.id,
                assessment_id=clean_ass_id,
                application_id=clean_app_id,
                candidate_id=clean_cand_id,
                question_id=clean_q_id,
                created_at=now,
            )
            db.add(recording)

        recording.cloudinary_public_id = res.get("public_id")
        recording.cloudinary_secure_url = res.get("secure_url")
        recording.cloudinary_url = res.get("secure_url")
        recording.duration = duration_seconds or res.get("duration")
        recording.duration_seconds = duration_seconds or res.get("duration")
        recording.format = res.get("format") or "mp4"
        recording.video_format = res.get("format") or "mp4"
        recording.file_size = res.get("bytes") or len(video_data)
        recording.file_size_bytes = res.get("bytes") or len(video_data)
        recording.upload_status = "completed"
        recording.status = "uploaded"
        recording.consent_given = True
        recording.consent_at = now
        recording.uploaded_at = now

        db.commit()
        db.refresh(recording)

        return {
            "recording_id": recording.id,
            "question_id": question_id,
            "upload_status": recording.upload_status,
            "duration": recording.duration,
            "cloudinary_public_id": recording.cloudinary_public_id,
            "uploaded_at": isoformat_utc(recording.uploaded_at),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(502, f"Video response upload failed: {str(exc)}") from exc
    finally:
        file.file.close()


@assessment_router.get("/{token}/recordings")
def get_candidate_assessment_recordings(
    token: str,
    user: User = Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    """Returns all question recordings uploaded for this assessment assignment."""
    assignment = _load_assignment_by_token(db, token)
    _verify_assignment_owner(assignment, user)

    recordings = db.scalars(
        select(AssessmentRecording)
        .where(AssessmentRecording.assignment_id == assignment.id)
        .order_by(AssessmentRecording.created_at.asc())
    ).all()

    return [
        {
            "id": r.id,
            "question_id": r.question_id,
            "duration": r.duration or r.duration_seconds,
            "format": r.format or r.video_format,
            "upload_status": r.upload_status or r.status,
            "uploaded_at": isoformat_utc(r.uploaded_at),
        }
        for r in recordings
    ]


@recruiter_assessment_router.post("/video-assessments")
def create_video_assessment(
    payload: dict = Body(...),
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Recruiter creates a new asynchronous video assessment for a job."""
    job_id = payload.get("job_id")
    if not job_id:
        raise HTTPException(400, "job_id is required.")

    job = db.get(Job, int(job_id))
    if not job:
        raise HTTPException(404, "Job not found.")

    recruiter = None
    if user.role == "recruiter":
        recruiter = get_or_create_recruiter_profile(db, user)
        if not recruiter or job.recruiter_id != recruiter.id:
            raise HTTPException(403, "You do not have permission to create an assessment for this job.")

    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Assessment title is required.")

    instructions = (payload.get("instructions") or "").strip() or "Please answer each question by recording your video response."
    prep_time = int(payload.get("prep_time_seconds") or 30)
    resp_time = int(payload.get("response_time_seconds") or 120)
    allow_review = bool(payload.get("allow_review", True))
    max_recordings = int(payload.get("max_recordings_per_question") or 1)

    questions_data = payload.get("questions") or []
    if not questions_data:
        raise HTTPException(400, "At least one video interview question is required.")

    now = utc_now()
    assessment = Assessment(
        recruiter_id=job.recruiter_id,
        job_id=job.id,
        title=title,
        description=(payload.get("description") or "").strip() or None,
        instructions=instructions,
        assessment_type="video",
        prep_time_seconds=prep_time,
        response_time_seconds=resp_time,
        allow_review=allow_review,
        max_recordings_per_question=max_recordings,
        duration_minutes=int(payload.get("duration_minutes") or (len(questions_data) * (resp_time + prep_time) // 60 + 5)),
        total_questions=len(questions_data),
        total_marks=len(questions_data) * 10,
        status="published" if payload.get("publish", True) else "draft",
        created_at=now,
        updated_at=now,
    )
    db.add(assessment)
    db.flush()

    for idx, q_data in enumerate(questions_data):
        q_text = (q_data.get("question_text") or "").strip()
        if not q_text:
            raise HTTPException(400, f"Question {idx + 1} text cannot be blank.")
        q = AssessmentQuestion(
            assessment_id=assessment.id,
            order_index=idx + 1,
            question_type="video",
            skill=(q_data.get("skill") or "General").strip(),
            category=(q_data.get("category") or "Interview").strip(),
            difficulty=(q_data.get("difficulty") or "Medium").strip(),
            question_text=q_text,
            instructions=(q_data.get("instructions") or "").strip() or None,
            prep_time_seconds=int(q_data.get("prep_time_seconds") or prep_time),
            response_time_seconds=int(q_data.get("response_time_seconds") or resp_time),
            options_json="[]",
            correct_option_index=0,
            marks=int(q_data.get("marks") or 10),
        )
        db.add(q)

    db.commit()
    db.refresh(assessment)

    return {
        "id": assessment.id,
        "title": assessment.title,
        "job_id": assessment.job_id,
        "job_title": job.title,
        "assessment_type": assessment.assessment_type,
        "total_questions": assessment.total_questions,
        "status": assessment.status,
        "prep_time_seconds": assessment.prep_time_seconds,
        "response_time_seconds": assessment.response_time_seconds,
        "created_at": isoformat_utc(assessment.created_at),
    }


@recruiter_assessment_router.get("/video-assessments")
def list_video_assessments(
    job_id: int | None = Query(None),
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Lists video assessments created by or visible to the recruiter."""
    stmt = select(Assessment).where(Assessment.assessment_type == "video")
    if user.role == "recruiter":
        recruiter = get_or_create_recruiter_profile(db, user)
        if recruiter:
            stmt = stmt.where(Assessment.recruiter_id == recruiter.id)
        else:
            return []
    if job_id:
        stmt = stmt.where(Assessment.job_id == job_id)

    assessments = db.scalars(stmt.order_by(Assessment.created_at.desc())).all()
    return [
        {
            "id": a.id,
            "title": a.title,
            "job_id": a.job_id,
            "job_title": a.job.title if a.job else None,
            "status": a.status,
            "total_questions": a.total_questions,
            "prep_time_seconds": a.prep_time_seconds,
            "response_time_seconds": a.response_time_seconds,
            "allow_review": a.allow_review,
            "created_at": isoformat_utc(a.created_at),
        }
        for a in assessments
    ]


@recruiter_assessment_router.get("/video-assessments/{assessment_id}")
def get_video_assessment(
    assessment_id: int,
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Retrieves full video assessment details with question list."""
    assessment = db.get(Assessment, assessment_id)
    if not assessment or assessment.assessment_type != "video":
        raise HTTPException(404, "Video assessment not found.")

    if user.role == "recruiter":
        recruiter = get_or_create_recruiter_profile(db, user)
        if not recruiter or assessment.recruiter_id != recruiter.id:
            raise HTTPException(403, "Access denied.")

    return {
        "id": assessment.id,
        "title": assessment.title,
        "description": assessment.description,
        "instructions": assessment.instructions,
        "job_id": assessment.job_id,
        "job_title": assessment.job.title if assessment.job else None,
        "status": assessment.status,
        "total_questions": assessment.total_questions,
        "prep_time_seconds": assessment.prep_time_seconds,
        "response_time_seconds": assessment.response_time_seconds,
        "allow_review": assessment.allow_review,
        "questions": [
            {
                "id": q.id,
                "order_index": q.order_index,
                "question_text": q.question_text,
                "instructions": q.instructions,
                "prep_time_seconds": q.prep_time_seconds,
                "response_time_seconds": q.response_time_seconds,
                "marks": q.marks,
            }
            for q in assessment.questions
        ],
    }


@recruiter_assessment_router.post("/video-assessments/{assessment_id}/publish")
def publish_video_assessment(
    assessment_id: int,
    payload: dict = Body(default_factory=dict),
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Publishes or unpublishes a video assessment."""
    assessment = db.get(Assessment, assessment_id)
    if not assessment or assessment.assessment_type != "video":
        raise HTTPException(404, "Video assessment not found.")

    publish = payload.get("published", True)
    assessment.status = "published" if publish else "draft"
    db.commit()
    return {"id": assessment.id, "status": assessment.status}


@recruiter_assessment_router.get("/video-assessments/submissions/{assignment_id}")
def get_video_assessment_submission(
    assignment_id: int,
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Recruiter reviews candidate video interview responses with secure playback URLs."""
    assignment = db.get(AssessmentAssignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assessment assignment not found.")

    if user.role == "recruiter":
        recruiter = get_or_create_recruiter_profile(db, user)
        if not recruiter or assignment.job.recruiter_id != recruiter.id:
            raise HTTPException(403, "Access denied.")

    from app.cloudinary_service import generate_secure_playback_url

    questions_with_videos = []
    recordings_map = {r.question_id: r for r in assignment.recordings if r.question_id}

    for q in assignment.assessment.questions:
        rec = recordings_map.get(q.id)
        playback_url = None
        if rec and rec.upload_status == "completed" and rec.cloudinary_public_id:
            try:
                playback_url = generate_secure_playback_url(
                    public_id=rec.cloudinary_public_id,
                    video_format=rec.format or "mp4",
                    expires_in_seconds=900,
                    is_authenticated_asset=True,
                )
            except Exception as e:
                logger.warning(f"Could not generate playback URL for question {q.id}: {e}")

        questions_with_videos.append({
            "question_id": q.id,
            "order_index": q.order_index,
            "question_text": q.question_text,
            "instructions": q.instructions,
            "recording": {
                "id": rec.id,
                "upload_status": rec.upload_status,
                "duration": rec.duration,
                "format": rec.format,
                "playback_url": playback_url,
                "uploaded_at": isoformat_utc(rec.uploaded_at),
            } if rec else None,
        })

    candidate_user = assignment.candidate.user if assignment.candidate else None

    return {
        "assignment_id": assignment.id,
        "candidate_id": assignment.candidate_id,
        "candidate_name": candidate_user.full_name if candidate_user else "Candidate",
        "candidate_email": assignment.recipient_email,
        "job_title": assignment.job.title if assignment.job else None,
        "assessment_title": assignment.assessment.title if assignment.assessment else None,
        "test_status": assignment.test_status,
        "submitted_at": isoformat_utc(assignment.submitted_at),
        "questions": questions_with_videos,
    }

