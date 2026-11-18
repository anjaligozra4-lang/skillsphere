from datetime import date, datetime, time
import re

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import require_roles
from app.core.security import ensure_utc, isoformat_utc, utc_now
from app.database import get_db
from app.matching_workflow import record_status_history
from app.models import (
    Application,
    Candidate,
    EmailNotification,
    Interview,
    Job,
    Recruiter,
    User,
    VALID_INTERVIEW_MODES,
    VALID_INTERVIEW_RECOMMENDATIONS,
    VALID_NOTIFICATION_STATUSES,
)
from app.notification_service import (
    NotificationAlreadySentError,
    NotificationNotFoundError,
    process_due_interview_reminders,
    retry_email_notification,
    send_interview_notification,
    serialize_email_notification,
)


recruiter_interview_router = APIRouter(
    prefix="/api/recruiter",
    tags=["Recruiter Interviews & Notifications"],
)
candidate_interview_router = APIRouter(
    prefix="/api/candidates",
    tags=["Candidate Interviews"],
)
admin_interview_router = APIRouter(
    prefix="/api/admin",
    tags=["Admin Oversight"],
)

_HTTP_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
_INELIGIBLE_APP_STATUSES = {"withdrawn", "rejected", "accepted", "hired"}
_AUTO_ADVANCE_TO_INTERVIEW_FROM = {"applied", "under_review", "screening", "shortlisted"}
_MODE_ALIASES = {
    "online": "online",
    "video": "online",
    "virtual": "online",
    "offline": "in_person",
    "in_person": "in_person",
    "in-person": "in_person",
    "in person": "in_person",
    "onsite": "in_person",
    "on-site": "in_person",
    "phone": "phone",
    "call": "phone",
    "telephone": "phone",
}
_RECOMMENDATION_ALIASES = {
    "strong_hire": "strong_hire",
    "strong hire": "strong_hire",
    "hire": "hire",
    "selected": "hire",
    "pass": "hire",
    "hold": "hold",
    "on hold": "hold",
    "no_hire": "no_hire",
    "no hire": "no_hire",
    "reject": "no_hire",
    "rejected": "no_hire",
}


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_mode(value: str) -> str:
    normalized = _MODE_ALIASES.get((value or "").strip().lower())
    if not normalized or normalized not in VALID_INTERVIEW_MODES:
        raise ValueError("Interview mode must be online, offline (in_person), or phone.")
    return normalized


def _validate_meeting_and_location(
    mode: str,
    meeting_link: str | None,
    location: str | None,
) -> tuple[str | None, str | None]:
    clean_link = _clean_text(meeting_link)
    clean_location = _clean_text(location)
    if clean_link and not _HTTP_URL_RE.match(clean_link):
        raise ValueError("Meeting link must be a valid http:// or https:// URL.")
    if mode == "online" and not clean_link:
        raise ValueError("Meeting link is required for online interviews.")
    if mode == "in_person" and (not clean_location or len(clean_location) < 3):
        raise ValueError("Physical location (minimum 3 characters) is required for offline / in-person interviews.")
    return clean_link, clean_location


def _normalize_scheduled_at(dt: datetime) -> datetime:
    normalized = ensure_utc(dt)
    assert normalized is not None
    normalized = normalized.replace(microsecond=0)
    if normalized <= utc_now().replace(microsecond=0):
        raise ValueError("Interview date and time must be in the future.")
    return normalized


# --- Schemas ---

class InterviewCreateRequest(BaseModel):
    application_id: int | None = Field(default=None, gt=0)
    round_number: int | None = Field(default=None, ge=1, le=20)
    round_name: str | None = Field(default=None, max_length=120)
    interview_mode: str = Field(default="online")
    interview_type: str | None = Field(default="live_recruiter", max_length=50)
    scheduled_at: datetime
    duration_minutes: int = Field(default=45, ge=10, le=480)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    meeting_link: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=255)
    interviewer_name: str | None = Field(default=None, max_length=150)
    interviewer_email: EmailStr | None = None
    notes_for_candidate: str | None = Field(default=None, max_length=2000)
    internal_notes: str | None = Field(default=None, max_length=2000)
    send_email: bool = True

    @field_validator("interview_mode")
    @classmethod
    def check_mode(cls, value: str) -> str:
        return _normalize_mode(value)

    @field_validator("scheduled_at")
    @classmethod
    def check_scheduled_at(cls, value: datetime) -> datetime:
        return _normalize_scheduled_at(value)

    @field_validator("timezone")
    @classmethod
    def strip_timezone(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Timezone cannot be blank.")
        return cleaned

    @model_validator(mode="after")
    def validate_mode_details(self):
        link, loc = _validate_meeting_and_location(self.interview_mode, self.meeting_link, self.location)
        self.meeting_link = link
        self.location = loc
        self.round_name = _clean_text(self.round_name)
        self.interviewer_name = _clean_text(self.interviewer_name)
        self.notes_for_candidate = _clean_text(self.notes_for_candidate)
        self.internal_notes = _clean_text(self.internal_notes)
        return self


class InterviewRescheduleRequest(BaseModel):
    round_number: int | None = Field(default=None, ge=1, le=20)
    round_name: str | None = Field(default=None, max_length=120)
    interview_mode: str | None = None
    scheduled_at: datetime
    duration_minutes: int | None = Field(default=None, ge=10, le=480)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    meeting_link: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=255)
    interviewer_name: str | None = Field(default=None, max_length=150)
    interviewer_email: EmailStr | None = None
    notes_for_candidate: str | None = Field(default=None, max_length=2000)
    internal_notes: str | None = Field(default=None, max_length=2000)
    send_email: bool = True

    @field_validator("interview_mode")
    @classmethod
    def check_mode(cls, value: str | None) -> str | None:
        return _normalize_mode(value) if value is not None else None

    @field_validator("scheduled_at")
    @classmethod
    def check_scheduled_at(cls, value: datetime) -> datetime:
        return _normalize_scheduled_at(value)


class InterviewCancelRequest(BaseModel):
    cancellation_reason: str | None = Field(default=None, max_length=1000)
    reason: str | None = Field(default=None, max_length=1000)
    send_email: bool = True


class InterviewFeedbackRequest(BaseModel):
    feedback: str | None = Field(default=None, max_length=4000)
    rating: int | None = Field(default=None, ge=1, le=5)
    recommendation: str | None = None
    outcome: str | None = None
    internal_notes: str | None = Field(default=None, max_length=2000)
    status: str = Field(default="completed")

    @field_validator("status")
    @classmethod
    def validate_completion_status(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in {"completed", "no_show"}:
            raise ValueError("Interview outcome status must be 'completed' or 'no_show'.")
        return normalized

    @model_validator(mode="after")
    def validate_recommendation_alias(self):
        raw_rec = self.recommendation if self.recommendation is not None else self.outcome
        if raw_rec is not None:
            cleaned = _RECOMMENDATION_ALIASES.get(raw_rec.strip().lower())
            if not cleaned or cleaned not in VALID_INTERVIEW_RECOMMENDATIONS:
                raise ValueError(
                    "Recommendation/outcome must be one of: strong_hire, hire, hold, no_hire."
                )
            self.recommendation = cleaned
        self.feedback = _clean_text(self.feedback)
        self.internal_notes = _clean_text(self.internal_notes)
        return self


# --- Serialization & Auth Helpers ---

def _serialize_interview_for_candidate(interview: Interview) -> dict:
    """Serialize candidate-safe interview view (excludes private internal notes/ratings/recommendations)."""
    job = interview.job
    return {
        "id": interview.id,
        "application_id": interview.application_id,
        "job_id": interview.job_id,
        "job_title": job.title if job else None,
        "company": job.company.name if job and job.company else None,
        "round_number": interview.round_number,
        "round_name": interview.round_name,
        "interview_mode": interview.interview_mode,
        "interview_type": getattr(interview, "interview_type", None) or "live_recruiter",
        "livekit_room_name": getattr(interview, "livekit_room_name", None),
        "scheduled_at": isoformat_utc(interview.scheduled_at),
        "started_at": isoformat_utc(getattr(interview, "started_at", None)),
        "ended_at": isoformat_utc(getattr(interview, "ended_at", None)),
        "duration_minutes": interview.duration_minutes,
        "timezone": interview.timezone,
        "meeting_link": interview.meeting_link if interview.status != "cancelled" else None,
        "location": interview.location if interview.status != "cancelled" else None,
        "interviewer_name": interview.interviewer_name,
        "notes_for_candidate": interview.notes_for_candidate,
        "status": interview.status,
        "completed_at": isoformat_utc(interview.completed_at),
        "cancelled_at": isoformat_utc(interview.cancelled_at),
        "cancellation_reason": interview.cancellation_reason,
        "created_at": isoformat_utc(interview.created_at),
        "updated_at": isoformat_utc(interview.updated_at),
    }


def _serialize_interview(interview: Interview, *, include_notifications: bool = False) -> dict:
    candidate = interview.candidate
    job = interview.job
    latest_notif = interview.notifications[0] if interview.notifications else None
    payload = {
        "id": interview.id,
        "application_id": interview.application_id,
        "application_status": interview.application.status if interview.application else None,
        "job_id": interview.job_id,
        "job_title": job.title if job else None,
        "company": job.company.name if job and job.company else None,
        "candidate_id": interview.candidate_id,
        "candidate_name": candidate.user.full_name if candidate and candidate.user else None,
        "candidate_email": candidate.user.email if candidate and candidate.user else None,
        "recruiter_id": interview.recruiter_id,
        "scheduled_by_user_id": interview.scheduled_by_user_id,
        "round_number": interview.round_number,
        "round_name": interview.round_name,
        "interview_mode": interview.interview_mode,
        "interview_type": getattr(interview, "interview_type", None) or "live_recruiter",
        "livekit_room_name": getattr(interview, "livekit_room_name", None),
        "scheduled_at": isoformat_utc(interview.scheduled_at),
        "started_at": isoformat_utc(getattr(interview, "started_at", None)),
        "ended_at": isoformat_utc(getattr(interview, "ended_at", None)),
        "duration_minutes": interview.duration_minutes,
        "timezone": interview.timezone,
        "meeting_link": interview.meeting_link,
        "location": interview.location,
        "interviewer_name": interview.interviewer_name,
        "interviewer_email": interview.interviewer_email,
        "notes_for_candidate": interview.notes_for_candidate,
        "internal_notes": interview.internal_notes,
        "status": interview.status,
        "feedback": interview.feedback,
        "rating": interview.rating,
        "recommendation": interview.recommendation,
        "final_outcome": interview.recommendation,
        "completed_at": isoformat_utc(interview.completed_at),
        "cancelled_at": isoformat_utc(interview.cancelled_at),
        "cancellation_reason": interview.cancellation_reason,
        "latest_notification": serialize_email_notification(latest_notif) if latest_notif else None,
        "created_at": isoformat_utc(interview.created_at),
        "updated_at": isoformat_utc(interview.updated_at),
    }
    if include_notifications:
        payload["notifications"] = [
            serialize_email_notification(item) for item in interview.notifications
        ]
    return payload


def _load_owned_application(db: Session, application_id: int, user: User) -> Application:
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    if not application.job or not application.job.recruiter or application.job.recruiter.user_id != user.id:
        raise HTTPException(403, "You are not authorized to manage interviews for this application.")
    return application


def _load_owned_interview(db: Session, interview_id: int, user: User) -> Interview:
    interview = db.get(Interview, interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")
    if not interview.job or not interview.job.recruiter or interview.job.recruiter.user_id != user.id:
        raise HTTPException(403, "You are not authorized to access or modify this interview.")
    return interview


def _notification_owner_user_id(notification: EmailNotification) -> int | None:
    if notification.job and notification.job.recruiter:
        return notification.job.recruiter.user_id
    if notification.application and notification.application.job and notification.application.job.recruiter:
        return notification.application.job.recruiter.user_id
    if notification.interview and notification.interview.job and notification.interview.job.recruiter:
        return notification.interview.job.recruiter.user_id
    return None


def _apply_date_range(stmt, column, from_date: date | None, to_date: date | None):
    if from_date is not None:
        start_dt = ensure_utc(datetime.combine(from_date, time.min))
        stmt = stmt.where(column >= start_dt)
    if to_date is not None:
        end_dt = ensure_utc(datetime.combine(to_date, time.max))
        stmt = stmt.where(column <= end_dt)
    return stmt


def _build_status_counts(rows: list, attr: str = "status") -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = getattr(row, attr)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _schedule_interview_for_application(
    db: Session,
    application: Application,
    payload: InterviewCreateRequest,
    user: User,
) -> dict:
    if application.status in _INELIGIBLE_APP_STATUSES:
        raise HTTPException(
            409,
            f"Cannot schedule an interview for an application with status '{application.status}'.",
        )

    existing_rounds = list(application.interviews)
    round_number = payload.round_number
    if round_number is None:
        round_number = max((item.round_number for item in existing_rounds), default=0) + 1
    round_name = payload.round_name or f"Interview Round {round_number}"

    for existing in existing_rounds:
        existing_dt = ensure_utc(existing.scheduled_at)
        if (
            existing.status in {"scheduled", "rescheduled"}
            and existing.round_number == round_number
            and existing_dt is not None
            and existing_dt.replace(microsecond=0) == payload.scheduled_at
            and existing.interview_mode == payload.interview_mode
        ):
            raise HTTPException(
                409,
                f"Interview Round {round_number} is already scheduled at this date and time.",
            )

    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
    import secrets
    from app.core.config import get_settings
    settings = get_settings()
    room_name = f"skillsphere-interview-{secrets.token_hex(6)}"
    meeting_link = payload.meeting_link
    if payload.interview_mode == "online" and not meeting_link:
        meeting_link = f"{settings.frontend_base_url}/live-interview"

    interview = Interview(
        application_id=application.id,
        job_id=application.job_id,
        candidate_id=application.candidate_id,
        recruiter_id=recruiter.id if recruiter else application.job.recruiter_id,
        scheduled_by_user_id=user.id,
        round_number=round_number,
        round_name=round_name,
        interview_mode=payload.interview_mode,
        interview_type=getattr(payload, "interview_type", None) or "live_recruiter",
        livekit_room_name=room_name,
        scheduled_at=payload.scheduled_at,
        duration_minutes=payload.duration_minutes,
        timezone=payload.timezone,
        meeting_link=meeting_link,
        location=payload.location,
        interviewer_name=payload.interviewer_name,
        interviewer_email=str(payload.interviewer_email).strip() if payload.interviewer_email else None,
        notes_for_candidate=payload.notes_for_candidate,
        internal_notes=payload.internal_notes,
        status="scheduled",
    )
    db.add(interview)
    db.flush()
    if interview.meeting_link and interview.meeting_link.endswith("/live-interview"):
        interview.meeting_link = f"{settings.frontend_base_url}/live-interview/{interview.id}"

    if application.status in _AUTO_ADVANCE_TO_INTERVIEW_FROM:
        prev_status = application.status
        application.status = "interview"
        application.manual_status_override = True
        record_status_history(
            db=db,
            application=application,
            previous_status=prev_status,
            new_status="interview",
            actor_name=user.full_name,
            actor_role="recruiter",
            source="interview_scheduler",
            actor_user_id=user.id,
            note=f"Scheduled {round_name} (Round {round_number}).",
        )

    db.commit()
    db.refresh(interview)

    notification = None
    if payload.send_email:
        notification = send_interview_notification(
            db,
            interview,
            "interview_scheduled",
            triggered_by_user_id=user.id,
            deduplicate_sent=True,
            commit=True,
        )
        db.refresh(interview)

    return {
        "interview": _serialize_interview(interview, include_notifications=True),
        "notification": serialize_email_notification(notification) if notification else None,
        "notification_status": notification.status if notification else "not_requested",
    }


# --- A & B. Recruiter Interview Management Endpoints ---

@recruiter_interview_router.post("/applications/{application_id}/interviews", status_code=201)
def schedule_application_interview(
    application_id: int,
    payload: InterviewCreateRequest = Body(...),
    user: User = Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    application = _load_owned_application(db, application_id, user)
    return _schedule_interview_for_application(db, application, payload, user)


@recruiter_interview_router.post("/applications/{application_id}/live-interview", status_code=201)
def schedule_live_interview(
    application_id: int,
    payload: dict = Body(...),
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Recruiter schedules a live recruiter interview powered by LiveKit."""
    application = _load_owned_application(db, application_id, user)
    scheduled_at_raw = payload.get("scheduled_at")
    if not scheduled_at_raw:
        raise HTTPException(400, "scheduled_at is required.")

    scheduled_at = ensure_utc(datetime.fromisoformat(str(scheduled_at_raw).replace("Z", "+00:00")))
    if scheduled_at <= utc_now():
        raise HTTPException(400, "Interview date and time must be in the future.")

    settings = get_settings()
    room_name = f"skillsphere-interview-{secrets.token_hex(6)}"

    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
    round_num = int(payload.get("round_number") or 1)
    round_name = (payload.get("round_name") or f"Interview Round {round_num}").strip()

    interview = Interview(
        application_id=application.id,
        job_id=application.job_id,
        candidate_id=application.candidate_id,
        recruiter_id=recruiter.id if recruiter else application.job.recruiter_id,
        scheduled_by_user_id=user.id,
        round_number=round_num,
        round_name=round_name,
        interview_mode="online",
        interview_type=(payload.get("interview_type") or "live_recruiter").strip(),
        livekit_room_name=room_name,
        scheduled_at=scheduled_at,
        duration_minutes=int(payload.get("duration_minutes") or 45),
        timezone=(payload.get("timezone") or "UTC").strip(),
        meeting_link=f"{settings.frontend_base_url}/live-interview",
        interviewer_name=(payload.get("interviewer_name") or user.full_name or "Recruiter").strip(),
        notes_for_candidate=(payload.get("notes_for_candidate") or "").strip() or None,
        internal_notes=(payload.get("internal_notes") or "").strip() or None,
        status="scheduled",
    )
    db.add(interview)
    db.flush()
    interview.meeting_link = f"{settings.frontend_base_url}/live-interview/{interview.id}"

    if application.status in _AUTO_ADVANCE_TO_INTERVIEW_FROM:
        prev_status = application.status
        application.status = "interview"
        application.manual_status_override = True
        record_status_history(
            db=db,
            application=application,
            previous_status=prev_status,
            new_status="interview",
            actor_name=user.full_name,
            actor_role="recruiter",
            source="livekit_scheduler",
            actor_user_id=user.id,
            note=f"Scheduled Live Interview (Round {interview.round_number}).",
        )

    db.commit()
    db.refresh(interview)

    if payload.get("send_email", True):
        try:
            send_interview_notification(
                db,
                interview,
                "interview_scheduled",
                triggered_by_user_id=user.id,
                deduplicate_sent=True,
                commit=True,
            )
            db.refresh(interview)
        except Exception:
            pass

    return {
        "interview": _serialize_interview(interview, include_notifications=True),
        "livekit_room_name": interview.livekit_room_name,
    }


@recruiter_interview_router.post("/interviews", status_code=201)
def schedule_interview_generic(
    payload: InterviewCreateRequest = Body(...),
    user: User = Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    if payload.application_id is None:
        raise HTTPException(422, "application_id is required when scheduling from /api/recruiter/interviews.")
    application = _load_owned_application(db, payload.application_id, user)
    return _schedule_interview_for_application(db, application, payload, user)


@recruiter_interview_router.get("/interviews")
def list_recruiter_interviews(
    job_id: int | None = Query(default=None, gt=0),
    application_id: int | None = Query(default=None, gt=0),
    status: str | None = None,
    interview_mode: str | None = None,
    round_number: int | None = Query(default=None, ge=1),
    from_date: date | None = None,
    to_date: date | None = None,
    q: str | None = None,
    user: User = Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
    stmt = (
        select(Interview)
        .join(Job, Interview.job_id == Job.id)
        .where(Job.recruiter_id == recruiter.id)
    )
    if job_id is not None:
        stmt = stmt.where(Interview.job_id == job_id)
    if application_id is not None:
        stmt = stmt.where(Interview.application_id == application_id)
    if status:
        stmt = stmt.where(Interview.status == status.strip().lower())
    if interview_mode:
        try:
            stmt = stmt.where(Interview.interview_mode == _normalize_mode(interview_mode))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if round_number is not None:
        stmt = stmt.where(Interview.round_number == round_number)
    stmt = _apply_date_range(stmt, Interview.scheduled_at, from_date, to_date)

    interviews = db.scalars(stmt.order_by(Interview.scheduled_at.asc(), Interview.id.asc())).all()
    if q:
        q_norm = q.strip().casefold()
        interviews = [
            item
            for item in interviews
            if q_norm
            in " ".join([
                item.candidate.user.full_name if item.candidate and item.candidate.user else "",
                item.candidate.user.email if item.candidate and item.candidate.user else "",
                item.job.title if item.job else "",
                item.round_name or "",
                item.interviewer_name or "",
            ]).casefold()
        ]

    return {
        "items": [_serialize_interview(item) for item in interviews],
        "total": len(interviews),
        "counts_by_status": _build_status_counts(interviews),
    }


@recruiter_interview_router.get("/applications/{application_id}/interviews")
def list_application_interviews(
    application_id: int,
    user: User = Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    application = _load_owned_application(db, application_id, user)
    return [_serialize_interview(item) for item in application.interviews]


@recruiter_interview_router.get("/interviews/{interview_id}")
def get_recruiter_interview_detail(
    interview_id: int,
    user: User = Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    interview = _load_owned_interview(db, interview_id, user)
    return _serialize_interview(interview, include_notifications=True)


def _perform_reschedule(
    db: Session,
    interview: Interview,
    payload: InterviewRescheduleRequest,
    user: User,
) -> dict:
    if interview.status == "cancelled":
        raise HTTPException(409, "Cancelled interviews cannot be modified or rescheduled.")
    if interview.status in {"completed", "no_show"}:
        raise HTTPException(409, f"Cannot reschedule an interview with status '{interview.status}'.")

    new_mode = payload.interview_mode if payload.interview_mode is not None else interview.interview_mode
    new_link = (
        payload.meeting_link
        if payload.meeting_link is not None
        else (None if new_mode == "in_person" else interview.meeting_link)
    )
    new_location = (
        payload.location
        if payload.location is not None
        else (None if new_mode == "online" else interview.location)
    )
    try:
        validated_link, validated_location = _validate_meeting_and_location(new_mode, new_link, new_location)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    new_round_number = payload.round_number if payload.round_number is not None else interview.round_number
    new_round_name = _clean_text(payload.round_name) if payload.round_name is not None else interview.round_name
    if not new_round_name:
        new_round_name = interview.round_name
    new_duration = payload.duration_minutes if payload.duration_minutes is not None else interview.duration_minutes
    new_timezone = payload.timezone.strip() if payload.timezone is not None else interview.timezone
    new_interviewer = (
        _clean_text(payload.interviewer_name) if payload.interviewer_name is not None else interview.interviewer_name
    )
    new_interviewer_email = (
        str(payload.interviewer_email).strip()
        if payload.interviewer_email is not None
        else interview.interviewer_email
    )
    new_notes_cand = (
        _clean_text(payload.notes_for_candidate)
        if payload.notes_for_candidate is not None
        else interview.notes_for_candidate
    )
    new_internal_notes = (
        _clean_text(payload.internal_notes) if payload.internal_notes is not None else interview.internal_notes
    )

    old_dt = ensure_utc(interview.scheduled_at)
    old_dt_clean = old_dt.replace(microsecond=0) if old_dt else None
    candidate_facing_changed = any([
        old_dt_clean != payload.scheduled_at,
        interview.round_number != new_round_number,
        interview.round_name != new_round_name,
        interview.interview_mode != new_mode,
        interview.duration_minutes != new_duration,
        interview.timezone != new_timezone,
        (interview.meeting_link or None) != validated_link,
        (interview.location or None) != validated_location,
        (interview.interviewer_name or None) != new_interviewer,
        (interview.notes_for_candidate or None) != new_notes_cand,
    ])
    internal_changed = (
        (interview.interviewer_email or None) != new_interviewer_email
        or (interview.internal_notes or None) != new_internal_notes
    )

    notification = None
    if candidate_facing_changed or internal_changed:
        interview.round_number = new_round_number
        interview.round_name = new_round_name
        interview.interview_mode = new_mode
        interview.scheduled_at = payload.scheduled_at
        interview.duration_minutes = new_duration
        interview.timezone = new_timezone
        interview.meeting_link = validated_link
        interview.location = validated_location
        interview.interviewer_name = new_interviewer
        interview.interviewer_email = new_interviewer_email
        interview.notes_for_candidate = new_notes_cand
        interview.internal_notes = new_internal_notes
        if candidate_facing_changed:
            interview.status = "rescheduled"

        db.commit()
        db.refresh(interview)

        if candidate_facing_changed and payload.send_email:
            notification = send_interview_notification(
                db,
                interview,
                "interview_rescheduled",
                triggered_by_user_id=user.id,
                deduplicate_sent=True,
                commit=True,
            )
            db.refresh(interview)

    notification_status = (
        notification.status
        if notification is not None
        else ("skipped_no_change" if not candidate_facing_changed else "not_requested")
    )
    return {
        "changed": candidate_facing_changed or internal_changed,
        "rescheduled": candidate_facing_changed,
        "interview": _serialize_interview(interview, include_notifications=True),
        "notification": serialize_email_notification(notification) if notification else None,
        "notification_status": notification_status,
    }


@recruiter_interview_router.put("/interviews/{interview_id}/reschedule")
@recruiter_interview_router.patch("/interviews/{interview_id}")
@recruiter_interview_router.put("/interviews/{interview_id}")
def reschedule_interview(
    interview_id: int,
    payload: InterviewRescheduleRequest = Body(...),
    user: User = Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    interview = _load_owned_interview(db, interview_id, user)
    return _perform_reschedule(db, interview, payload, user)


@recruiter_interview_router.post("/interviews/{interview_id}/cancel")
def cancel_interview(
    interview_id: int,
    payload: InterviewCancelRequest = Body(default_factory=InterviewCancelRequest),
    user: User = Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    interview = _load_owned_interview(db, interview_id, user)
    if interview.status in {"completed", "no_show"}:
        raise HTTPException(409, f"Cannot cancel an interview with status '{interview.status}'.")

    if interview.status == "cancelled":
        return {
            "cancelled_changed": False,
            "interview": _serialize_interview(interview, include_notifications=True),
            "notification": None,
            "notification_status": "skipped_no_change",
        }

    reason_text = _clean_text(payload.cancellation_reason) or _clean_text(payload.reason)
    interview.status = "cancelled"
    interview.cancelled_at = utc_now()
    interview.cancellation_reason = reason_text
    db.commit()
    db.refresh(interview)

    notification = None
    if payload.send_email:
        notification = send_interview_notification(
            db,
            interview,
            "interview_cancelled",
            triggered_by_user_id=user.id,
            deduplicate_sent=True,
            commit=True,
        )
        db.refresh(interview)

    return {
        "cancelled_changed": True,
        "interview": _serialize_interview(interview, include_notifications=True),
        "notification": serialize_email_notification(notification) if notification else None,
        "notification_status": notification.status if notification else "not_requested",
    }


@recruiter_interview_router.post("/interviews/{interview_id}/feedback")
@recruiter_interview_router.put("/interviews/{interview_id}/feedback")
def save_interview_feedback(
    interview_id: int,
    payload: InterviewFeedbackRequest = Body(...),
    user: User = Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    interview = _load_owned_interview(db, interview_id, user)
    if interview.status == "cancelled":
        raise HTTPException(409, "Cancelled interviews cannot receive feedback or outcomes.")

    if payload.feedback is not None:
        interview.feedback = payload.feedback
    if payload.rating is not None:
        interview.rating = payload.rating
    if payload.recommendation is not None:
        interview.recommendation = payload.recommendation
    if payload.internal_notes is not None:
        interview.internal_notes = payload.internal_notes
    interview.status = payload.status
    if payload.status == "completed":
        interview.completed_at = interview.completed_at or utc_now()

    db.commit()
    db.refresh(interview)
    return _serialize_interview(interview, include_notifications=True)


# --- C. Recruiter Notification Logs & Retry API ---

@recruiter_interview_router.get("/notifications")
def list_recruiter_notifications(
    status: str | None = None,
    notification_type: str | None = None,
    job_id: int | None = Query(default=None, gt=0),
    application_id: int | None = Query(default=None, gt=0),
    from_date: date | None = None,
    to_date: date | None = None,
    user: User = Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
    stmt = (
        select(EmailNotification)
        .join(Job, EmailNotification.job_id == Job.id)
        .where(Job.recruiter_id == recruiter.id)
    )
    if status:
        clean_status = status.strip().lower()
        if clean_status not in VALID_NOTIFICATION_STATUSES:
            raise HTTPException(422, "Invalid notification status filter.")
        stmt = stmt.where(EmailNotification.status == clean_status)
    if notification_type:
        stmt = stmt.where(EmailNotification.notification_type == notification_type.strip().lower())
    if job_id is not None:
        stmt = stmt.where(EmailNotification.job_id == job_id)
    if application_id is not None:
        stmt = stmt.where(EmailNotification.application_id == application_id)
    stmt = _apply_date_range(stmt, EmailNotification.created_at, from_date, to_date)

    rows = db.scalars(stmt.order_by(EmailNotification.created_at.desc(), EmailNotification.id.desc())).all()
    return {
        "items": [serialize_email_notification(row) for row in rows],
        "total": len(rows),
        "counts_by_status": _build_status_counts(rows),
    }


@recruiter_interview_router.post("/notifications/{notification_id}/resend")
def resend_failed_notification(
    notification_id: int,
    user: User = Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    notification = db.get(EmailNotification, notification_id)
    if not notification:
        raise HTTPException(404, "Email notification not found.")

    owner_user_id = _notification_owner_user_id(notification)
    if owner_user_id != user.id:
        raise HTTPException(403, "You are not authorized to resend notifications for another recruiter's job.")

    if notification.status == "sent":
        raise HTTPException(409, "This email notification has already been sent.")
    if notification.status != "failed":
        raise HTTPException(409, "Only failed email notifications can be retried.")

    try:
        retried = retry_email_notification(
            db,
            notification.id,
            triggered_by_user_id=user.id,
            commit=True,
        )
    except NotificationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except NotificationAlreadySentError as exc:
        raise HTTPException(409, str(exc)) from exc

    if retried.status == "failed":
        raise HTTPException(503, retried.error_message or "Email delivery failed via SMTP provider.")

    return {
        "message": f"Notification resent to {retried.recipient_email}.",
        "notification": serialize_email_notification(retried),
    }


# --- D. Admin Read-Only Oversight APIs ---

@admin_interview_router.get("/interviews/summary")
@admin_interview_router.get("/interviews/stats")
def admin_interview_summary(
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Interview)).all()
    counts = _build_status_counts(rows)
    return {
        "total": len(rows),
        "by_status": {
            "scheduled": counts.get("scheduled", 0),
            "rescheduled": counts.get("rescheduled", 0),
            "completed": counts.get("completed", 0),
            "cancelled": counts.get("cancelled", 0),
            "no_show": counts.get("no_show", 0),
        },
    }


@admin_interview_router.post("/interviews/send-reminders")
def admin_trigger_interview_reminders(
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    """Process due 24-hour and 1-hour interview reminder notifications."""
    return process_due_interview_reminders(db)


@admin_interview_router.get("/interviews")
def admin_list_interviews(
    status: str | None = None,
    interview_mode: str | None = None,
    job_id: int | None = Query(default=None, gt=0),
    candidate_id: int | None = Query(default=None, gt=0),
    recruiter_id: int | None = Query(default=None, gt=0),
    from_date: date | None = None,
    to_date: date | None = None,
    q: str | None = None,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    stmt = select(Interview)
    if status:
        stmt = stmt.where(Interview.status == status.strip().lower())
    if interview_mode:
        try:
            stmt = stmt.where(Interview.interview_mode == _normalize_mode(interview_mode))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if job_id is not None:
        stmt = stmt.where(Interview.job_id == job_id)
    if candidate_id is not None:
        stmt = stmt.where(Interview.candidate_id == candidate_id)
    if recruiter_id is not None:
        stmt = stmt.where(Interview.recruiter_id == recruiter_id)
    stmt = _apply_date_range(stmt, Interview.scheduled_at, from_date, to_date)

    rows = db.scalars(stmt.order_by(Interview.scheduled_at.desc(), Interview.id.desc())).all()
    if q:
        q_norm = q.strip().casefold()
        rows = [
            item
            for item in rows
            if q_norm
            in " ".join([
                item.candidate.user.full_name if item.candidate and item.candidate.user else "",
                item.candidate.user.email if item.candidate and item.candidate.user else "",
                item.job.title if item.job else "",
                item.job.company.name if item.job and item.job.company else "",
                item.round_name or "",
            ]).casefold()
        ]

    return {
        "items": [_serialize_interview(item) for item in rows],
        "total": len(rows),
        "counts_by_status": _build_status_counts(rows),
    }


@admin_interview_router.get("/interviews/{interview_id}")
def admin_get_interview_detail(
    interview_id: int,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    interview = db.get(Interview, interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")
    return _serialize_interview(interview, include_notifications=True)


@admin_interview_router.get("/notifications")
def admin_list_email_notifications(
    status: str | None = None,
    notification_type: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    job_id: int | None = Query(default=None, gt=0),
    application_id: int | None = Query(default=None, gt=0),
    q: str | None = None,
    user: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    stmt = select(EmailNotification)
    if status:
        clean_status = status.strip().lower()
        if clean_status not in VALID_NOTIFICATION_STATUSES:
            raise HTTPException(422, "Invalid notification status filter.")
        stmt = stmt.where(EmailNotification.status == clean_status)
    if notification_type:
        stmt = stmt.where(EmailNotification.notification_type == notification_type.strip().lower())
    if job_id is not None:
        stmt = stmt.where(EmailNotification.job_id == job_id)
    if application_id is not None:
        stmt = stmt.where(EmailNotification.application_id == application_id)
    stmt = _apply_date_range(stmt, EmailNotification.created_at, from_date, to_date)

    rows = db.scalars(stmt.order_by(EmailNotification.created_at.desc(), EmailNotification.id.desc())).all()
    if q:
        q_norm = q.strip().casefold()
        rows = [
            item
            for item in rows
            if q_norm
            in " ".join([
                item.recipient_email or "",
                item.recipient_name or "",
                item.subject or "",
                item.notification_type or "",
                item.job.title if item.job else "",
            ]).casefold()
        ]

    enriched = []
    for item in rows:
        data = serialize_email_notification(item)
        data["job_title"] = item.job.title if item.job else None
        data["company"] = item.job.company.name if item.job and item.job.company else None
        enriched.append(data)

    return {
        "items": enriched,
        "total": len(enriched),
        "counts_by_status": _build_status_counts(rows),
    }


# --- E. Candidate Interview Read APIs ---

@candidate_interview_router.get("/interviews")
def list_candidate_interviews(
    status: str | None = None,
    application_id: int | None = Query(default=None, gt=0),
    user: User = Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if not candidate:
        return []
    stmt = select(Interview).where(Interview.candidate_id == candidate.id)
    if status:
        stmt = stmt.where(Interview.status == status.strip().lower())
    if application_id is not None:
        stmt = stmt.where(Interview.application_id == application_id)

    interviews = db.scalars(stmt.order_by(Interview.scheduled_at.asc(), Interview.id.asc())).all()
    return [_serialize_interview_for_candidate(item) for item in interviews]


@candidate_interview_router.get("/interviews/{interview_id}")
def get_candidate_interview_detail(
    interview_id: int,
    user: User = Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    interview = db.get(Interview, interview_id)
    if not interview:
        raise HTTPException(404, "Interview not found")
    if not interview.candidate or interview.candidate.user_id != user.id:
        raise HTTPException(403, "You are not authorized to view this interview.")
    return _serialize_interview_for_candidate(interview)
