from datetime import timedelta
from decimal import Decimal
import json
import logging
import math
from pathlib import Path
import shutil
from uuid import uuid4

import fitz
import pytesseract
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api import (
    current_user,
    get_or_create_candidate_profile,
    get_or_create_recruiter_profile,
    require_roles,
)
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token_value,
    ensure_utc,
    hash_opaque_token,
    hash_password,
    isoformat_utc,
    utc_now,
    verify_password,
)
from app.database import get_db
from app.email_service import (
    is_smtp_configured,
    missing_smtp_variables,
    smtp_configuration_instructions,
)
from app.assessment_service import refresh_assignment_lifecycle
from app.assessment_router import create_candidate_assessment_launch_token
from app.matching_workflow import (
    record_status_history,
    run_application_matching_and_shortlisting,
)
from app.notification_service import (
    send_application_notification,
    serialize_email_notification,
)
from app.models import (
    Application,
    ApplicationStatusHistory,
    AssessmentAssignment,
    AssessmentResult,
    AuthRateLimit,
    Candidate,
    CandidateSkill,
    Company,
    EmailNotification,
    Job,
    JobSkill,
    RECRUITER_SETTABLE_STATUSES,
    Recruiter,
    RefreshToken,
    Resume,
    ResumeAnalysis,
    SavedJob,
    Skill,
    User,
)
from app.services import (
    evaluate_candidate_job_match,
    extract_resume_fields,
    extract_resume_pages,
    extract_skills,
    normalize_skill,
    sanitize_contact_email,
    sanitize_profile_text,
)


logger = logging.getLogger(__name__)
auth_router = APIRouter(prefix="/api/auth", tags=["Auth"])
candidate_router = APIRouter(prefix="/api/candidates", tags=["Candidates"])
recruiter_router = APIRouter(prefix="/api/recruiters", tags=["Recruiters"])
company_router = APIRouter(prefix="/api/companies", tags=["Companies"])
resume_router = APIRouter(prefix="/api/resumes", tags=["Resumes"])
job_router = APIRouter(prefix="/api/jobs", tags=["Jobs"])
application_router = APIRouter(prefix="/api/applications", tags=["Applications"])
recruiter_applicant_router = APIRouter(prefix="/api/recruiter", tags=["Recruiters"])
admin_router = APIRouter(prefix="/api/admin", tags=["Admin"])
match_router = APIRouter(prefix="/api/matches", tags=["Resume Matching"])


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern="^(candidate|recruiter)$")

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Full name must contain at least 2 characters")
        return value

    @field_validator("password")
    @classmethod
    def validate_password_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("password")
    @classmethod
    def validate_password_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return value


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=256)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class CandidateRequest(BaseModel):
    contact_email: EmailStr | None = None
    phone: str | None = None
    headline: str | None = None
    education: str | None = None
    experience: str | None = None
    projects: str | None = None
    certifications: str | None = None
    location: str | None = None
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)


class JobRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=10)
    location: str | None = None
    employment_type: str = Field(
        default="full_time",
        pattern="^(full_time|part_time|contract|internship)$",
    )
    experience_min: int | None = Field(default=None, ge=0, le=60)
    experience_max: int | None = Field(default=None, ge=0, le=60)
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    skills: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.experience_min is not None and self.experience_max is not None:
            if self.experience_min > self.experience_max:
                raise ValueError("Minimum experience cannot exceed maximum experience")
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_min > self.salary_max:
                raise ValueError("Minimum salary cannot exceed maximum salary")
        return self


class ResumeReviewRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=150)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    education: str | None = None
    experience: str | None = None
    projects: str | None = None
    certifications: str | None = None
    skills: list[str] = Field(default_factory=list)


class ResumeAnalysisRequest(BaseModel):
    resume_id: int = Field(gt=0)
    job_id: int = Field(gt=0)


class ApplicationStatusRequest(BaseModel):
    status: str
    reason: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    send_email: bool = True


class ApplicationDecisionRequest(BaseModel):
    decision: str
    reason: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    send_email: bool = True

    @field_validator("decision")
    @classmethod
    def normalize_decision(cls, value: str) -> str:
        alias_map = {
            "select": "selected",
            "selected": "selected",
            "accept": "accepted",
            "accepted": "accepted",
            "hire": "hired",
            "hired": "hired",
            "shortlist": "shortlisted",
            "shortlisted": "shortlisted",
            "reject": "rejected",
            "rejected": "rejected",
        }
        normalized = alias_map.get((value or "").strip().lower())
        if not normalized:
            raise ValueError("Decision must be one of: shortlisted, selected, accepted, hired, rejected")
        return normalized


class ApplicationSelectRequest(BaseModel):
    status: str = Field(default="selected")
    reason: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    send_email: bool = True

    @field_validator("status")
    @classmethod
    def validate_select_status(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in {"selected", "accepted", "hired"}:
            raise ValueError("Selection status must be 'selected', 'accepted', or 'hired'")
        return normalized


class ApplicationRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)
    send_email: bool = True


class CompanyRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    website: str | None = None
    location: str | None = None


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _enforce_rate_limit(
    db: Session,
    scope: str,
    identifier: str,
    max_attempts: int,
    window_minutes: int = 15,
    increment: bool = True,
) -> None:
    now = utc_now()
    entry = db.scalar(
        select(AuthRateLimit).where(
            AuthRateLimit.scope == scope,
            AuthRateLimit.identifier == identifier,
        )
    )
    if entry is None:
        if increment:
            try:
                with db.begin_nested():
                    db.add(
                        AuthRateLimit(
                            scope=scope,
                            identifier=identifier,
                            window_start=now,
                            attempt_count=1,
                        )
                    )
                    db.flush()
            except IntegrityError:
                pass
        return

    window_start = ensure_utc(entry.window_start) or now
    elapsed = (now - window_start).total_seconds()
    window_seconds = window_minutes * 60
    if elapsed >= window_seconds:
        entry.window_start = now
        entry.attempt_count = 1 if increment else 0
        db.flush()
        return

    if entry.attempt_count >= max_attempts:
        retry_after = max(1, math.ceil(window_seconds - elapsed))
        raise HTTPException(
            status_code=429,
            detail=f"Too many attempts. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    if increment:
        entry.attempt_count += 1
        db.flush()


def _reset_rate_limit(db: Session, scope: str, identifier: str) -> None:
    db.execute(
        delete(AuthRateLimit).where(
            AuthRateLimit.scope == scope,
            AuthRateLimit.identifier == identifier,
        )
    )


def _issue_session_tokens(db: Session, user: User) -> dict:
    settings = get_settings()
    access_token = create_access_token(str(user.id), user.role)
    raw_refresh = create_refresh_token_value()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_opaque_token(raw_refresh),
            expires_at=utc_now() + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "id": user.id,
        "role": user.role,
        "full_name": user.full_name,
        "email": user.email,
    }


@auth_router.post("/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = str(payload.email).strip().lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "Email is already registered")
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    try:
        db.add(user)
        db.flush()
        if payload.role == "candidate":
            db.add(Candidate(user_id=user.id))
        else:
            db.add(Recruiter(user_id=user.id))
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Email is already registered") from exc

    return {"id": user.id, "email": user.email, "role": user.role}


@auth_router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = str(payload.email).strip().lower()
    client_ip = _client_ip(request)

    _enforce_rate_limit(db, "login_ip", client_ip, max_attempts=30, window_minutes=15, increment=False)
    _enforce_rate_limit(db, "login_email", email, max_attempts=10, window_minutes=15, increment=False)

    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if not user or not verify_password(payload.password, user.password_hash) or not user.is_active:
        _enforce_rate_limit(db, "login_ip", client_ip, max_attempts=30, window_minutes=15, increment=True)
        _enforce_rate_limit(db, "login_email", email, max_attempts=10, window_minutes=15, increment=True)
        db.commit()
        raise HTTPException(401, "Invalid email or password")

    session_payload = _issue_session_tokens(db, user)
    _reset_rate_limit(db, "login_email", email)
    db.commit()
    return session_payload


@auth_router.post("/refresh")
def refresh_auth_token(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    token_hash = hash_opaque_token(payload.refresh_token.strip())
    record = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .with_for_update()
    )
    now = utc_now()
    if (
        not record
        or record.revoked_at is not None
        or (ensure_utc(record.expires_at) is not None and ensure_utc(record.expires_at) < now)
    ):
        db.commit()
        raise HTTPException(401, "Invalid or expired refresh token")

    user = db.get(User, record.user_id)
    if not user or not user.is_active:
        record.revoked_at = now
        db.commit()
        raise HTTPException(401, "Inactive or unknown user")

    record.revoked_at = now
    session_payload = _issue_session_tokens(db, user)
    db.commit()
    return session_payload


@auth_router.post("/logout")
def logout_user(payload: LogoutRequest = Body(default_factory=LogoutRequest), db: Session = Depends(get_db)):
    if payload.refresh_token:
        token_hash = hash_opaque_token(payload.refresh_token.strip())
        record = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        if record and record.revoked_at is None:
            record.revoked_at = utc_now()
            db.commit()
    return {"message": "Logged out"}


@auth_router.get("/me")
def authenticated_user(user=Depends(current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
    }


@candidate_router.get("/me")
@resume_router.get("/profile")
def candidate_profile(user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    candidate = get_or_create_candidate_profile(db, user)
    return {
        "id": candidate.id,
        "full_name": user.full_name,
        "email": user.email,
        "contact_email": sanitize_contact_email(candidate.contact_email) or user.email,
        "phone": sanitize_profile_text(candidate.phone),
        "headline": sanitize_profile_text(candidate.headline),
        "education": sanitize_profile_text(candidate.education),
        "experience": sanitize_profile_text(candidate.experience),
        "projects": sanitize_profile_text(candidate.projects),
        "certifications": sanitize_profile_text(candidate.certifications),
        "location": sanitize_profile_text(candidate.location),
        "summary": sanitize_profile_text(candidate.summary),
        "skills": [item.skill.name for item in candidate.skills],
    }


@candidate_router.get("/saved-jobs")
def saved_jobs(user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    saved = db.scalars(
        select(SavedJob)
        .join(Job, SavedJob.job_id == Job.id)
        .join(Company, Job.company_id == Company.id)
        .where(
            SavedJob.candidate_id == candidate.id,
            Job.status.in_(["published", "open"]),
            Company.is_approved.is_(True),
        )
        .order_by(SavedJob.created_at.desc())
    ).all()
    return [{**serialize_job(item.job), "saved_at": item.created_at.isoformat()} for item in saved]


@candidate_router.put("/saved-jobs/{job_id}")
def save_job(job_id: int, user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    job = db.get(Job, job_id)
    if not job or job.status not in {"published", "open"} or not job.company.is_approved:
        raise HTTPException(404, "Published job not found")
    saved = db.scalar(
        select(SavedJob).where(
            SavedJob.candidate_id == candidate.id,
            SavedJob.job_id == job.id,
        )
    )
    if not saved:
        db.add(SavedJob(candidate_id=candidate.id, job_id=job.id))
        db.commit()
    return {"job_id": job.id, "saved": True}


@candidate_router.delete("/saved-jobs/{job_id}")
def unsave_job(job_id: int, user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    saved = db.scalar(
        select(SavedJob).where(
            SavedJob.candidate_id == candidate.id,
            SavedJob.job_id == job_id,
        )
    )
    if not saved:
        raise HTTPException(404, "Saved job not found")
    db.delete(saved)
    db.commit()
    return {"job_id": job_id, "saved": False}


@candidate_router.put("/me")
def update_candidate(payload: CandidateRequest, user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    candidate.contact_email = sanitize_contact_email(str(payload.contact_email) if payload.contact_email else None)
    for field in ("phone", "headline", "education", "experience", "projects", "certifications", "location", "summary"):
        setattr(candidate, field, sanitize_profile_text(getattr(payload, field)))
    replace_candidate_skills(db, candidate, payload.skills)
    db.commit()
    return {"message": "Profile updated"}


def replace_candidate_skills(db: Session, candidate: Candidate, names: list[str]) -> None:
    requested_skill_ids = set()
    processed_names = set()
    for name in names:
        name = name.strip()
        normalized = normalize_skill(name)
        if not normalized or normalized in processed_names:
            continue
        processed_names.add(normalized)
        skill = db.scalar(select(Skill).where(Skill.normalized_name == normalized))
        if not skill:
            skill = Skill(name=name.strip(), normalized_name=normalized)
            db.add(skill)
            db.flush()
        if not any(item.skill_id == skill.id for item in candidate.skills):
            db.add(CandidateSkill(candidate_id=candidate.id, skill_id=skill.id))
        requested_skill_ids.add(skill.id)
    for item in list(candidate.skills):
        if item.skill_id not in requested_skill_ids:
            candidate.skills.remove(item)


@company_router.post("")
def create_company(payload: CompanyRequest, user=Depends(require_roles("recruiter")), db: Session = Depends(get_db)):
    recruiter = get_or_create_recruiter_profile(db, user)
    if db.scalar(select(Company).where(Company.name == payload.name)):
        raise HTTPException(409, "Company already exists")
    company = Company(**payload.model_dump())
    db.add(company)
    db.flush()
    recruiter.company_id = company.id
    db.commit()
    return {"id": company.id, "name": company.name}


@company_router.put("")
def update_company(payload: CompanyRequest, user=Depends(require_roles("recruiter")), db: Session = Depends(get_db)):
    recruiter = get_or_create_recruiter_profile(db, user)
    company = recruiter.company if recruiter else None
    if not company:
        raise HTTPException(404, "Company profile not found")
    existing = db.scalar(select(Company).where(Company.name == payload.name, Company.id != company.id))
    if existing:
        raise HTTPException(409, "Company name is already used")
    for field, value in payload.model_dump().items():
        setattr(company, field, value)
    db.commit()
    return {"id": company.id, "name": company.name}


@company_router.get("/me")
def my_company(user=Depends(require_roles("recruiter")), db: Session = Depends(get_db)):
    recruiter = get_or_create_recruiter_profile(db, user)
    if not recruiter or not recruiter.company:
        raise HTTPException(404, "Company profile not found")
    return {
        "id": recruiter.company.id,
        "name": recruiter.company.name,
        "description": recruiter.company.description,
        "website": recruiter.company.website,
        "location": recruiter.company.location,
        "is_approved": recruiter.company.is_approved,
    }


@job_router.get("")
def search_jobs(
    q: str | None = None,
    location: str | None = None,
    employment_type: str | None = None,
    experience: str | None = None,
    skill: str | None = None,
    experience_min: int | None = Query(default=None, ge=0, le=60),
    experience_max: int | None = Query(default=None, ge=0, le=60),
    sort_by: str = Query(default="newest", pattern="^(newest|oldest|salary_asc|salary_desc|title_asc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if experience_min is not None and experience_max is not None and experience_min > experience_max:
        raise HTTPException(422, "Minimum experience filter cannot exceed maximum experience filter")
    statement = select(Job).join(Company, Job.company_id == Company.id).where(
        Job.status.in_(["published", "open"]),
        Company.is_approved.is_(True),
    )
    if q:
        pattern = f"%{q}%"
        statement = statement.where(or_(
            Job.title.ilike(pattern),
            Job.description.ilike(pattern),
            Job.location.ilike(pattern),
            Company.name.ilike(pattern),
            Job.id.in_(
                select(JobSkill.job_id)
                .join(Skill, JobSkill.skill_id == Skill.id)
                .where(Skill.name.ilike(pattern))
            ),
        ))
    if location:
        statement = statement.where(Job.location.ilike(f"%{location}%"))
    if employment_type:
        statement = statement.where(Job.employment_type == employment_type)
    if experience:
        statement = statement.where(Job.description.ilike(f"%{experience}%"))
    if experience_min is not None:
        statement = statement.where(
            or_(Job.experience_max.is_(None), Job.experience_max >= experience_min)
        )
    if experience_max is not None:
        statement = statement.where(
            or_(Job.experience_min.is_(None), Job.experience_min <= experience_max)
        )
    if skill:
        statement = statement.where(
            Job.id.in_(
                select(JobSkill.job_id)
                .join(Skill, JobSkill.skill_id == Skill.id)
                .where(Skill.name.ilike(f"%{skill}%"), JobSkill.is_required.is_(True))
            )
        )
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    ordering = _job_sort_order(sort_by)
    jobs = db.scalars(
        statement.order_by(*ordering).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [serialize_job(job) for job in jobs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


def _job_sort_order(sort_by: str):
    """Return portable ordering expressions (MySQL does not support NULLS LAST)."""
    return {
        "newest": (Job.created_at.desc(), Job.id.desc()),
        "oldest": (Job.created_at.asc(), Job.id.asc()),
        "salary_asc": (
            case((Job.salary_min.is_(None), 1), else_=0),
            Job.salary_min.asc(),
            Job.created_at.desc(),
        ),
        "salary_desc": (
            case((Job.salary_max.is_(None), 1), else_=0),
            Job.salary_max.desc(),
            Job.created_at.desc(),
        ),
        "title_asc": (Job.title.asc(), Job.id.asc()),
    }[sort_by]


def serialize_job(job: Job) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "description": job.description,
        "location": job.location,
        "employment_type": job.employment_type,
        "experience_min": job.experience_min,
        "experience_max": job.experience_max,
        "salary_min": float(job.salary_min) if job.salary_min is not None else None,
        "salary_max": float(job.salary_max) if job.salary_max is not None else None,
        "salary_currency": job.salary_currency,
        "company": job.company.name,
        "skills": [item.skill.name for item in job.skills],
        "created_at": job.created_at.isoformat(),
    }


@job_router.get("/{job_id}")
def job_details(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if (
        not job
        or job.status not in {"published", "open"}
        or not job.company.is_approved
    ):
        raise HTTPException(404, "Published job not found")
    return serialize_job(job)


@recruiter_router.post("/jobs", status_code=201)
@job_router.post("", status_code=201)
def create_job(payload: JobRequest, user=Depends(require_roles("recruiter")), db: Session = Depends(get_db)):
    recruiter = get_or_create_recruiter_profile(db, user)
    if not recruiter.company_id:
        raise HTTPException(400, "Create a company profile before posting jobs")
    if not recruiter.company or not recruiter.company.is_approved:
        raise HTTPException(403, "Company must be approved before posting jobs")
    job = Job(
        recruiter_id=recruiter.id,
        company_id=recruiter.company_id,
        title=payload.title,
        description=payload.description,
        location=payload.location,
        employment_type=payload.employment_type,
        experience_min=payload.experience_min,
        experience_max=payload.experience_max,
        salary_min=payload.salary_min,
        salary_max=payload.salary_max,
        salary_currency=payload.salary_currency.upper() if payload.salary_currency else None,
        status="pending",
    )
    db.add(job)
    db.flush()
    add_job_skills(db, job, payload.skills)
    db.commit()
    return {"id": job.id, "status": job.status}


@recruiter_router.get("/jobs")
def my_jobs(user=Depends(require_roles("recruiter")), db: Session = Depends(get_db)):
    recruiter = get_or_create_recruiter_profile(db, user)
    jobs = db.scalars(select(Job).where(Job.recruiter_id == recruiter.id).order_by(Job.created_at.desc())).all()
    return [
        {
            "id": job.id,
            "title": job.title,
            "description": job.description,
            "location": job.location,
            "employment_type": job.employment_type,
            "experience_min": job.experience_min,
            "experience_max": job.experience_max,
            "salary_min": float(job.salary_min) if job.salary_min is not None else None,
            "salary_max": float(job.salary_max) if job.salary_max is not None else None,
            "salary_currency": job.salary_currency,
            "status": job.status,
            "skills": [item.skill.name for item in job.skills],
            "applications_count": len(job.applications),
        }
        for job in jobs
    ]


@recruiter_router.delete("/jobs/{job_id}")
def delete_recruiter_job(job_id: int, user=Depends(require_roles("recruiter")), db: Session = Depends(get_db)):
    recruiter = get_or_create_recruiter_profile(db, user)
    job = db.get(Job, job_id)
    if not job or job.recruiter_id != recruiter.id:
        raise HTTPException(404, "Job not found")
    if db.scalar(select(func.count()).select_from(Application).where(Application.job_id == job.id)):
        raise HTTPException(409, "Jobs with applications cannot be deleted; close the job instead")
    db.execute(delete(SavedJob).where(SavedJob.job_id == job.id))
    db.delete(job)
    db.commit()
    return {"id": job_id, "deleted": True}


@recruiter_router.get("/stats")
def recruiter_stats(user=Depends(require_roles("recruiter")), db: Session = Depends(get_db)):
    recruiter = get_or_create_recruiter_profile(db, user)
    job_filter = Job.recruiter_id == recruiter.id
    application_query = select(func.count(Application.id)).join(
        Job, Application.job_id == Job.id
    ).where(job_filter)
    return {
        "jobs": db.scalar(select(func.count(Job.id)).where(job_filter)) or 0,
        "active_jobs": db.scalar(
            select(func.count(Job.id)).where(job_filter, Job.status.in_(["published", "open"]))
        ) or 0,
        "applications": db.scalar(application_query) or 0,
        "pending_applications": db.scalar(
            application_query.where(Application.status.in_(["applied", "under_review", "screening"]))
        ) or 0,
    }


@recruiter_router.put("/jobs/{job_id}")
def update_job(
    job_id: int,
    payload: JobRequest,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    job = db.get(Job, job_id)
    if not job or job.recruiter_id != recruiter.id:
        raise HTTPException(404, "Job not found")
    job.title = payload.title
    job.description = payload.description
    job.location = payload.location
    job.employment_type = payload.employment_type
    job.experience_min = payload.experience_min
    job.experience_max = payload.experience_max
    job.salary_min = payload.salary_min
    job.salary_max = payload.salary_max
    job.salary_currency = payload.salary_currency.upper() if payload.salary_currency else None
    if job.status == "published":
        job.status = "pending"
    job.skills.clear()
    db.flush()
    add_job_skills(db, job, payload.skills)
    db.commit()
    return {"id": job.id, "status": job.status}


@recruiter_router.patch("/jobs/{job_id}/status")
def update_recruiter_job_status(
    job_id: int,
    status_value: str,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    job = db.get(Job, job_id)
    if not job or job.recruiter_id != recruiter.id:
        raise HTTPException(404, "Job not found")
    if status_value not in {"published", "closed"}:
        raise HTTPException(422, "Recruiters may only publish or close their own jobs")
    if status_value == "published" and job.status not in {"published", "closed"}:
        raise HTTPException(409, "Job must be approved by an administrator before it can be published")
    if status_value == "published" and not job.company.is_approved:
        raise HTTPException(409, "Company must be approved before publishing jobs")
    job.status = status_value
    db.commit()
    return {"id": job.id, "status": job.status}


def add_job_skills(db: Session, job: Job, names: list[str]):
    processed_names = set()
    for name in names:
        normalized = normalize_skill(name)
        if not normalized or normalized in processed_names:
            continue
        processed_names.add(normalized)
        skill = db.scalar(select(Skill).where(Skill.normalized_name == normalized))
        if not skill:
            skill = Skill(name=name.strip(), normalized_name=normalized)
            db.add(skill)
            db.flush()
        db.add(JobSkill(job_id=job.id, skill_id=skill.id))


@application_router.post("")
@job_router.post("/{job_id}/apply")
def apply_job(job_id: int, resume_id: int | None = None, user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    job = db.get(Job, job_id)
    if not job or job.status not in {"published", "open"} or not job.company.is_approved:
        raise HTTPException(404, "Published job not found")
    if resume_id is not None:
        resume = db.get(Resume, resume_id)
        if not resume or resume.candidate_id != candidate.id:
            raise HTTPException(404, "Resume not found")
        if resume.processing_status != "processed":
            raise HTTPException(409, "Choose a successfully processed resume")
    application = db.scalar(
        select(Application).where(
            Application.candidate_id == candidate.id,
            Application.job_id == job_id,
        )
    )
    if application:
        if application.status != "withdrawn":
            raise HTTPException(409, "You have already applied for this job")
        prev_status = application.status
        application.status = "applied"
        application.resume_id = resume_id
        application.manual_status_override = False
        application.shortlist_source = None
        application.auto_shortlisted_at = None
        application.created_at = utc_now()
        db.flush()
        record_status_history(
            db=db,
            application=application,
            previous_status=prev_status,
            new_status="applied",
            actor_name=user.full_name,
            actor_role="candidate",
            source="candidate_reapply",
            actor_user_id=user.id,
            note="Candidate re-applied for this role.",
        )
    else:
        application = Application(candidate_id=candidate.id, job_id=job_id, resume_id=resume_id)
        db.add(application)
        db.flush()
        record_status_history(
            db=db,
            application=application,
            previous_status=None,
            new_status="applied",
            actor_name=user.full_name,
            actor_role="candidate",
            source="candidate_apply",
            actor_user_id=user.id,
            note="Candidate submitted job application.",
        )

    workflow_result = run_application_matching_and_shortlisting(db, application, actor_user=user)
    db.commit()
    db.refresh(application)

    submitted_notif = None
    if not workflow_result.get("auto_shortlisted"):
        submitted_notif = send_application_notification(
            db,
            application,
            "application_submitted",
            triggered_by_user_id=user.id,
            deduplicate_sent=True,
            commit=True,
        )

    return {
        "id": application.id,
        "status": application.status,
        "match_score": workflow_result["match_score"],
        "shortlist_source": application.shortlist_source,
        "shortlist_note": workflow_result.get("shortlist_note"),
        "notification_status": submitted_notif.status if submitted_notif else None,
    }


@application_router.get("/me")
@application_router.get("")
def my_applications(user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    applications = db.scalars(
        select(Application)
        .where(Application.candidate_id == candidate.id)
        .order_by(Application.created_at.desc())
    ).all()
    result = []
    for item in applications:
        resume = db.get(Resume, item.resume_id) if item.resume_id else None
        assignment = item.assessment_assignments[0] if item.assessment_assignments else None
        if assignment is not None:
            refresh_assignment_lifecycle(db, assignment)
        res_obj = assignment.result if assignment else None
        launch_token = None
        if assignment is not None and assignment.test_status in ("assigned", "started"):
            now = utc_now()
            exp = ensure_utc(assignment.expires_at)
            if exp is None or now <= exp:
                launch_token = create_candidate_assessment_launch_token(assignment.id, user.id, exp)
        result.append({
            "id": item.id,
            "job_id": item.job_id,
            "job": item.job.title,
            "company": item.job.company.name,
            "resume_id": item.resume_id,
            "resume_filename": resume.original_filename if resume else None,
            "created_at": isoformat_utc(item.created_at),
            "status": item.status,
            "match_score": float(item.match_score) if item.match_score is not None else None,
            "shortlist_source": item.shortlist_source,
            "decision_reason": item.decision_reason,
            "decision_note": item.decision_note,
            "decided_at": isoformat_utc(item.decided_at),
            "assessment_title": assignment.assessment.title if assignment else None,
            "invitation_status": assignment.invitation_status if assignment else None,
            "invitation_expires_at": isoformat_utc(assignment.expires_at) if assignment else None,
            "assessment_status": assignment.test_status if assignment else None,
            "assessment_token": launch_token,
            "assessment_score": res_obj.obtained_marks if res_obj else None,
            "assessment_max_score": res_obj.total_marks if res_obj else (assignment.assessment.total_marks if assignment else None),
            "assessment_passing_marks": res_obj.passing_marks if res_obj else (assignment.assessment.passing_marks if assignment else None),
            "assessment_percentage": float(res_obj.percentage) if res_obj else None,
            "assessment_is_passed": res_obj.is_passed if res_obj else None,
            "assessment_result_status": res_obj.result_status if res_obj else None,
            "assessment_result_message": res_obj.result_message if res_obj else None,
            "assessment_completed_at": isoformat_utc(res_obj.submitted_at) if res_obj else None,
        })
    db.commit()
    return result


@application_router.delete("/{application_id}")
def withdraw_application(
    application_id: int,
    user=Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    application = db.get(Application, application_id)
    if not application or application.candidate_id != candidate.id:
        raise HTTPException(404, "Application not found")
    if application.status not in {"applied", "under_review", "screening"}:
        raise HTTPException(409, "This application can no longer be withdrawn")
    prev_status = application.status
    application.status = "withdrawn"
    record_status_history(
        db=db,
        application=application,
        previous_status=prev_status,
        new_status="withdrawn",
        actor_name=user.full_name,
        actor_role="candidate",
        source="candidate_withdraw",
        actor_user_id=user.id,
        note="Candidate withdrew application.",
    )
    db.commit()
    return {"id": application_id, "message": "Application withdrawn"}


@resume_router.get("/me")
def my_resumes(user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    resumes = db.scalars(
        select(Resume)
        .where(Resume.candidate_id == candidate.id)
        .order_by(Resume.created_at.desc())
    ).all()
    return [
        {
            "id": resume.id,
            "original_filename": resume.original_filename,
            "extracted_data": _sanitize_extracted_data(json.loads(resume.extracted_data)) if resume.extracted_data else {},
            "processing_status": resume.processing_status,
            "processing_error": resume.processing_error,
            "page_text": json.loads(resume.page_text) if resume.page_text else [],
            "is_reviewed": resume.is_reviewed,
            "created_at": isoformat_utc(resume.created_at),
        }
        for resume in resumes
    ]


@resume_router.delete("/{resume_id}")
def delete_resume(resume_id: int, user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    resume = db.get(Resume, resume_id)
    if not resume or resume.candidate.user_id != user.id:
        raise HTTPException(404, "Resume not found")
    path = Path(resume.file_path).resolve()
    upload_root = UPLOAD_DIR.resolve()
    if path.parent != upload_root:
        logger.error("Refusing to delete resume outside upload directory: %s", resume.id)
        raise HTTPException(500, "Resume storage path is invalid")
    db.execute(
        Application.__table__.update()
        .where(Application.resume_id == resume.id)
        .values(resume_id=None)
    )
    db.delete(resume)
    db.commit()
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.exception("Could not remove stored file for deleted resume %s", resume_id)
        raise HTTPException(500, "Resume record was deleted but its stored file could not be removed") from exc
    return {"id": resume_id, "deleted": True}


def _sanitize_extracted_data(data: dict) -> dict:
    if not isinstance(data, dict):
        return {}
    return {
        "full_name": sanitize_profile_text(data.get("full_name")),
        "email": sanitize_contact_email(data.get("email")),
        "phone": sanitize_profile_text(data.get("phone")),
        "education": sanitize_profile_text(data.get("education")),
        "experience": sanitize_profile_text(data.get("experience")),
        "projects": sanitize_profile_text(data.get("projects")),
        "certifications": sanitize_profile_text(data.get("certifications")),
        "skills": data.get("skills") if isinstance(data.get("skills"), list) else [],
    }


def _serialize_status_history(application: Application) -> list[dict]:
    return [
        {
            "id": entry.id,
            "previous_status": entry.previous_status,
            "new_status": entry.new_status,
            "actor_name": entry.actor_name,
            "actor_role": entry.actor_role,
            "source": entry.source,
            "note": entry.note,
            "created_at": isoformat_utc(entry.created_at),
        }
        for entry in application.status_history
    ]


def _serialize_applicant_record(
    db: Session,
    application: Application,
    include_full_details: bool = False,
) -> dict:
    candidate = application.candidate
    job = application.job
    resume = db.get(Resume, application.resume_id) if application.resume_id else None
    if resume is None:
        resume = db.scalar(
            select(Resume)
            .where(
                Resume.candidate_id == candidate.id,
                Resume.processing_status == "processed",
            )
            .order_by(Resume.created_at.desc(), Resume.id.desc())
            .limit(1)
        )
    resume_data = {}
    if resume and resume.extracted_data:
        try:
            resume_data = _sanitize_extracted_data(json.loads(resume.extracted_data))
        except json.JSONDecodeError:
            resume_data = {}

    skills = [item.skill.name for item in candidate.skills]
    if not skills and resume_data.get("skills"):
        skills = resume_data["skills"]

    analysis = db.scalar(
        select(ResumeAnalysis)
        .where(ResumeAnalysis.application_id == application.id)
        .order_by(ResumeAnalysis.updated_at.desc(), ResumeAnalysis.id.desc())
        .limit(1)
    )
    if analysis is None and resume is not None:
        analysis = db.scalar(
            select(ResumeAnalysis)
            .where(
                ResumeAnalysis.resume_id == resume.id,
                ResumeAnalysis.job_id == job.id,
            )
            .order_by(ResumeAnalysis.updated_at.desc(), ResumeAnalysis.id.desc())
            .limit(1)
        )

    assignment = application.assessment_assignments[0] if application.assessment_assignments else None
    if assignment is not None:
        refresh_assignment_lifecycle(db, assignment)
    res_obj = assignment.result if assignment else None

    def _load_json(raw: str | None, fallback):
        if not raw:
            return fallback
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return fallback

    match_score = (
        float(application.match_score)
        if application.match_score is not None
        else (float(analysis.match_percentage) if analysis else None)
    )

    payload = {
        "id": application.id,
        "candidate_id": candidate.id,
        "candidate": candidate.user.full_name,
        "email": candidate.user.email,
        "contact_email": sanitize_contact_email(candidate.contact_email) or candidate.user.email,
        "phone": sanitize_profile_text(candidate.phone) or resume_data.get("phone"),
        "job_id": job.id,
        "job_title": job.title,
        "company": job.company.name,
        "status": application.status,
        "applied_at": isoformat_utc(application.created_at),
        "updated_at": isoformat_utc(application.updated_at),
        "resume_id": resume.id if resume else application.resume_id,
        "resume_filename": resume.original_filename if resume else None,
        "resume_processing_status": resume.processing_status if resume else None,
        "headline": sanitize_profile_text(candidate.headline),
        "education": sanitize_profile_text(candidate.education) or resume_data.get("education"),
        "experience": sanitize_profile_text(candidate.experience) or resume_data.get("experience"),
        "projects": sanitize_profile_text(candidate.projects) or resume_data.get("projects"),
        "certifications": sanitize_profile_text(candidate.certifications) or resume_data.get("certifications"),
        "location": sanitize_profile_text(candidate.location),
        "summary": sanitize_profile_text(candidate.summary),
        "skills": skills,
        "match_score": match_score,
        "matched_skills": _load_json(analysis.matched_skills, []) if analysis else [],
        "missing_skills": _load_json(analysis.missing_skills, []) if analysis else [],
        "preferred_matched_skills": _load_json(analysis.preferred_matched_skills, []) if analysis else [],
        "preferred_missing_skills": _load_json(analysis.preferred_missing_skills, []) if analysis else [],
        "relevant_experience": analysis.relevant_experience if analysis else None,
        "strengths": _load_json(analysis.strengths, []) if analysis else [],
        "weaknesses": _load_json(analysis.weaknesses, []) if analysis else [],
        "matching_explanation": analysis.matching_explanation if analysis else None,
        "score_breakdown": _load_json(analysis.score_breakdown, {}) if analysis else {},
        "shortlist_source": application.shortlist_source,
        "auto_shortlisted_at": isoformat_utc(application.auto_shortlisted_at),
        "manual_status_override": application.manual_status_override,
        "decision_reason": application.decision_reason,
        "decision_note": application.decision_note,
        "decided_at": isoformat_utc(application.decided_at),
        "decided_by_user_id": application.decided_by_user_id,
        "decided_by_name": application.decided_by_user.full_name if application.decided_by_user else None,
        "latest_email_notification": (
            serialize_email_notification(application.email_notifications[0])
            if application.email_notifications
            else None
        ),
        "assessment_assignment_id": assignment.id if assignment else None,
        "assessment_id": assignment.assessment_id if assignment else None,
        "assessment_title": assignment.assessment.title if assignment else None,
        "invitation_status": assignment.invitation_status if assignment else "not_invited",
        "invitation_sent_at": isoformat_utc(assignment.sent_at) if assignment else None,
        "invitation_expires_at": isoformat_utc(assignment.expires_at) if assignment else None,
        "invitation_error": assignment.invitation_error if assignment else None,
        "assessment_status": assignment.test_status if assignment else "not_assigned",
        "assessment_score": res_obj.obtained_marks if res_obj else None,
        "assessment_max_score": res_obj.total_marks if res_obj else (assignment.assessment.total_marks if assignment else None),
        "assessment_passing_marks": res_obj.passing_marks if res_obj else (assignment.assessment.passing_marks if assignment else None),
        "assessment_percentage": float(res_obj.percentage) if res_obj else None,
        "assessment_is_passed": res_obj.is_passed if res_obj else None,
        "assessment_result_status": res_obj.result_status if res_obj else None,
        "assessment_started_at": isoformat_utc(assignment.started_at) if assignment else None,
        "assessment_completed_at": isoformat_utc(res_obj.submitted_at if res_obj else (assignment.submitted_at if assignment else None)),
        "assessment_submitted_automatically": assignment.submitted_automatically if assignment else False,
        "status_history": _serialize_status_history(application),
    }

    if include_full_details:
        payload["resume_extracted_text"] = resume.extracted_text if resume else None
        payload["resume_page_text"] = _load_json(resume.page_text, []) if resume else []
        payload["assessment_summary"] = _load_json(res_obj.summary_json, {}) if res_obj else {}
        if assignment and assignment.test_status == "submitted":
            ans_map = {ans.assessment_question_id: ans for ans in assignment.answers}
            payload["assessment_questions"] = [
                {
                    "id": q.id,
                    "order_index": q.order_index,
                    "skill_tag": q.skill,
                    "difficulty": q.difficulty,
                    "question_text": q.question_text,
                    "options": _load_json(q.options_json, []),
                    "selected_option_index": ans_map[q.id].selected_option_index if q.id in ans_map else None,
                    "correct_option_index": q.correct_option_index,
                    "is_correct": ans_map[q.id].is_correct if q.id in ans_map else False,
                    "marks": q.marks,
                    "marks_awarded": ans_map[q.id].marks_awarded if q.id in ans_map else 0,
                    "explanation": q.explanation,
                }
                for q in assignment.assessment.questions
            ]
        else:
            payload["assessment_questions"] = []
    return payload


def _filter_and_sort_applicants(
    items: list[dict],
    q: str | None = None,
    skill: str | None = None,
    experience: str | None = None,
    status_filter: str | None = None,
    sort_by: str = "newest",
) -> list[dict]:
    q_norm = q.strip().casefold() if q else ""
    skill_norm = skill.strip().casefold() if skill else ""
    exp_norm = experience.strip().casefold() if experience else ""
    status_norm = status_filter.strip().casefold() if status_filter else ""

    filtered = []
    for item in items:
        if status_norm and item["status"].casefold() != status_norm:
            continue
        if skill_norm and not any(skill_norm in s.casefold() for s in item.get("skills", [])):
            continue
        if exp_norm and exp_norm not in (item.get("experience") or "").casefold():
            continue
        if q_norm:
            haystack = " ".join([
                item.get("candidate") or "",
                item.get("email") or "",
                item.get("job_title") or "",
                " ".join(item.get("skills", [])),
            ]).casefold()
            if q_norm not in haystack:
                continue
        filtered.append(item)

    if sort_by == "oldest":
        filtered.sort(key=lambda x: x["applied_at"] or "")
    elif sort_by == "match_desc":
        filtered.sort(key=lambda x: (x["match_score"] is not None, x["match_score"] or -1), reverse=True)
    elif sort_by == "match_asc":
        filtered.sort(key=lambda x: (x["match_score"] is None, x["match_score"] or 0))
    else:
        filtered.sort(key=lambda x: x["applied_at"] or "", reverse=True)
    return filtered


@recruiter_router.get("/jobs/{job_id}/applicants")
def job_applicants(
    job_id: int,
    q: str | None = None,
    skill: str | None = None,
    experience: str | None = None,
    status: str | None = None,
    sort_by: str = Query(default="newest", pattern="^(newest|oldest|match_desc|match_asc)$"),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    job = db.get(Job, job_id)
    if not job or job.recruiter_id != recruiter.id:
        raise HTTPException(404, "Job not found")
    items = [_serialize_applicant_record(db, app) for app in job.applications]
    db.commit()
    return _filter_and_sort_applicants(items, q=q, skill=skill, experience=experience, status_filter=status, sort_by=sort_by)


@recruiter_applicant_router.get("/applicants")
def recruiter_applicants(
    job_id: int | None = Query(default=None, gt=0),
    q: str | None = None,
    skill: str | None = None,
    experience: str | None = None,
    status: str | None = None,
    sort_by: str = Query(default="newest", pattern="^(newest|oldest|match_desc|match_asc)$"),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    statement = select(Job).where(Job.recruiter_id == recruiter.id)
    if job_id is not None:
        statement = statement.where(Job.id == job_id)
    jobs = db.scalars(statement.order_by(Job.created_at.desc())).all()
    if job_id is not None and not jobs:
        raise HTTPException(404, "Job not found")
    items = []
    for job in jobs:
        for app in job.applications:
            items.append(_serialize_applicant_record(db, app))
    db.commit()
    return _filter_and_sort_applicants(items, q=q, skill=skill, experience=experience, status_filter=status, sort_by=sort_by)


@recruiter_applicant_router.get("/applicants/{application_id}")
def recruiter_applicant_detail(
    application_id: int,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    application = db.get(Application, application_id)
    if not application or application.job.recruiter.user_id != user.id:
        raise HTTPException(404, "Application not found")
    payload = _serialize_applicant_record(db, application, include_full_details=True)
    db.commit()
    return payload


@recruiter_applicant_router.post("/applicants/{application_id}/match")
def trigger_applicant_match(
    application_id: int,
    force_refresh: bool = Query(default=True),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    application = db.get(Application, application_id)
    if not application or application.job.recruiter.user_id != user.id:
        raise HTTPException(404, "Application not found")
    if application.status == "withdrawn":
        raise HTTPException(409, "Cannot evaluate withdrawn application")
    workflow_result = run_application_matching_and_shortlisting(
        db,
        application,
        actor_user=user,
        force_refresh=force_refresh,
    )
    db.commit()
    db.refresh(application)
    if workflow_result.get("auto_shortlisted"):
        send_application_notification(
            db,
            application,
            "application_shortlisted",
            reason=workflow_result.get("shortlist_note"),
            triggered_by_user_id=user.id,
            deduplicate_sent=True,
            commit=True,
        )
        db.refresh(application)
    return {
        **workflow_result,
        "applicant": _serialize_applicant_record(db, application, include_full_details=True),
    }


@recruiter_applicant_router.post("/jobs/{job_id}/match-all")
def match_all_job_applicants(
    job_id: int,
    force_refresh: bool = Query(default=False),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = get_or_create_recruiter_profile(db, user)
    job = db.get(Job, job_id)
    if not job or job.recruiter_id != recruiter.id:
        raise HTTPException(404, "Job not found")
    processed = 0
    auto_shortlisted = 0
    newly_shortlisted_apps: list[tuple[Application, str | None]] = []
    for application in job.applications:
        if application.status == "withdrawn":
            continue
        res = run_application_matching_and_shortlisting(
            db,
            application,
            actor_user=user,
            force_refresh=force_refresh,
        )
        processed += 1
        if res["auto_shortlisted"]:
            auto_shortlisted += 1
            newly_shortlisted_apps.append((application, res.get("shortlist_note")))
    db.commit()
    for app_obj, shortlist_note in newly_shortlisted_apps:
        db.refresh(app_obj)
        send_application_notification(
            db,
            app_obj,
            "application_shortlisted",
            reason=shortlist_note,
            triggered_by_user_id=user.id,
            deduplicate_sent=True,
            commit=True,
        )
    return {
        "job_id": job_id,
        "processed": processed,
        "auto_shortlisted": auto_shortlisted,
    }


_DECISION_NOTIFICATION_TYPE = {
    "applied": "application_submitted",
    "under_review": "application_under_review",
    "screening": "application_under_review",
    "shortlisted": "application_shortlisted",
    "selected": "application_selected",
    "accepted": "application_selected",
    "hired": "application_hired",
    "rejected": "application_rejected",
}
_DECISION_TRACKED_STATUSES = {"shortlisted", "selected", "accepted", "hired", "rejected"}


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _dispatch_status_notification(
    db: Session,
    application: Application,
    target_status: str,
    *,
    reason: str | None,
    note: str | None,
    actor_user_id: int,
) -> EmailNotification | None:
    notification_type = _DECISION_NOTIFICATION_TYPE.get(target_status)
    if not notification_type:
        return None
    return send_application_notification(
        db,
        application,
        notification_type,
        reason=reason,
        note=note,
        triggered_by_user_id=actor_user_id,
        deduplicate_sent=True,
        commit=True,
    )


def _validate_decision_transition(current_status: str, target_status: str) -> None:
    if current_status == "withdrawn":
        raise HTTPException(409, "Withdrawn applications cannot be updated")
    if current_status == target_status:
        return
    if current_status == "hired":
        raise HTTPException(
            409,
            f"Cannot change finalized status '{current_status}' to '{target_status}'.",
        )
    if current_status == "accepted" and target_status != "hired":
        raise HTTPException(
            409,
            f"Cannot change finalized status '{current_status}' to '{target_status}'.",
        )
    if current_status == "rejected":
        raise HTTPException(
            409,
            "Rejected applications cannot be moved directly to selected or shortlisted.",
        )
    if current_status == "selected" and target_status == "shortlisted":
        raise HTTPException(
            409,
            "Selected applications cannot move backward to shortlisted.",
        )


def _load_owned_application_for_decision(db: Session, application_id: int, user: User) -> Application:
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    if not application.job or not application.job.recruiter or application.job.recruiter.user_id != user.id:
        raise HTTPException(403, "You are not authorized to make decisions on this application.")
    return application


def _execute_recruiter_decision(
    db: Session,
    application: Application,
    *,
    target_status: str,
    reason: str | None,
    note: str | None,
    send_email: bool,
    user: User,
) -> dict:
    prev_status = application.status
    _validate_decision_transition(prev_status, target_status)

    clean_reason = _clean_optional_text(reason)
    clean_note = _clean_optional_text(note)
    changed = prev_status != target_status

    notification: EmailNotification | None = None
    if changed:
        now = utc_now()
        application.status = target_status
        application.manual_status_override = True
        if target_status == "shortlisted" and application.shortlist_source != "automatic":
            application.shortlist_source = "manual"
        application.decision_reason = clean_reason
        application.decision_note = clean_note
        application.decided_at = now
        application.decided_by_user_id = user.id

        history_parts = [f"Recruiter decision: {prev_status} -> {target_status}."]
        if clean_reason:
            history_parts.append(f"Reason: {clean_reason}")
        if clean_note:
            history_parts.append(f"Note: {clean_note}")

        record_status_history(
            db=db,
            application=application,
            previous_status=prev_status,
            new_status=target_status,
            actor_name=user.full_name,
            actor_role="recruiter",
            source="decision_api",
            actor_user_id=user.id,
            note=" ".join(history_parts),
        )
        # Commit decision before sending email so SMTP failures never roll back decisions
        db.commit()
        db.refresh(application)

        if send_email:
            notification = _dispatch_status_notification(
                db,
                application,
                target_status,
                reason=clean_reason,
                note=clean_note,
                actor_user_id=user.id,
            )
            db.refresh(application)

    notification_status = (
        notification.status
        if notification is not None
        else ("skipped_no_change" if not changed else "not_requested")
    )
    return {
        "id": application.id,
        "application_id": application.id,
        "status": application.status,
        "decision_changed": changed,
        "decision_reason": application.decision_reason,
        "decision_note": application.decision_note,
        "decided_at": isoformat_utc(application.decided_at),
        "decided_by_user_id": application.decided_by_user_id,
        "shortlist_source": application.shortlist_source,
        "manual_status_override": application.manual_status_override,
        "status_history": _serialize_status_history(application),
        "notification": serialize_email_notification(notification) if notification else None,
        "notification_status": notification_status,
        "applicant": _serialize_applicant_record(db, application, include_full_details=True),
    }


@recruiter_router.patch("/applications/{application_id}")
def update_application(
    application_id: int,
    status_value: str | None = Query(default=None),
    payload: ApplicationStatusRequest | None = Body(default=None),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    target_status = (payload.status if payload is not None else status_value)
    if not target_status:
        raise HTTPException(422, "Application status is required")
    target_status = target_status.strip().lower()

    application = db.get(Application, application_id)
    if not application or application.job.recruiter.user_id != user.id:
        raise HTTPException(404, "Application not found")
    if application.status == "withdrawn":
        raise HTTPException(409, "Withdrawn applications cannot be updated")
    if target_status not in RECRUITER_SETTABLE_STATUSES:
        raise HTTPException(422, "Invalid application status")

    prev_status = application.status
    clean_reason = _clean_optional_text(payload.reason) if payload else None
    clean_note = _clean_optional_text(payload.note) if payload else None
    changed = prev_status != target_status

    notification: EmailNotification | None = None
    if changed:
        now = utc_now()
        application.status = target_status
        application.manual_status_override = True
        if target_status == "shortlisted" and application.shortlist_source != "automatic":
            application.shortlist_source = "manual"
        if target_status in _DECISION_TRACKED_STATUSES:
            application.decided_at = now
            application.decided_by_user_id = user.id
            if clean_reason is not None:
                application.decision_reason = clean_reason
            if clean_note is not None:
                application.decision_note = clean_note

        history_note = f"Status updated manually from {prev_status} to {target_status}."
        if clean_reason:
            history_note += f" Reason: {clean_reason}"
        if clean_note:
            history_note += f" Note: {clean_note}"

        record_status_history(
            db=db,
            application=application,
            previous_status=prev_status,
            new_status=target_status,
            actor_name=user.full_name,
            actor_role="recruiter",
            source="manual",
            actor_user_id=user.id,
            note=history_note,
        )
        db.commit()
        db.refresh(application)

        should_send = payload.send_email if payload is not None else True
        if should_send:
            notification = _dispatch_status_notification(
                db,
                application,
                target_status,
                reason=clean_reason or application.decision_reason,
                note=clean_note or application.decision_note,
                actor_user_id=user.id,
            )
            db.refresh(application)
    else:
        application.manual_status_override = True
        db.commit()
        db.refresh(application)

    return {
        "id": application.id,
        "status": application.status,
        "shortlist_source": application.shortlist_source,
        "manual_status_override": application.manual_status_override,
        "decision_reason": application.decision_reason,
        "decision_note": application.decision_note,
        "decided_at": isoformat_utc(application.decided_at),
        "notification": serialize_email_notification(notification) if notification else None,
        "status_history": _serialize_status_history(application),
    }


@application_router.put("/{application_id}/status")
def update_application_status(
    application_id: int,
    payload: ApplicationStatusRequest = Body(...),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    return update_application(application_id, status_value=payload.status, payload=payload, user=user, db=db)


@recruiter_applicant_router.post("/applications/{application_id}/decision")
def decide_application(
    application_id: int,
    payload: ApplicationDecisionRequest = Body(...),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    application = _load_owned_application_for_decision(db, application_id, user)
    return _execute_recruiter_decision(
        db,
        application,
        target_status=payload.decision,
        reason=payload.reason,
        note=payload.note,
        send_email=payload.send_email,
        user=user,
    )


@recruiter_applicant_router.post("/applications/{application_id}/select")
def select_candidate_application(
    application_id: int,
    payload: ApplicationSelectRequest = Body(default_factory=ApplicationSelectRequest),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    application = _load_owned_application_for_decision(db, application_id, user)
    return _execute_recruiter_decision(
        db,
        application,
        target_status=payload.status,
        reason=payload.reason,
        note=payload.note,
        send_email=payload.send_email,
        user=user,
    )


@recruiter_applicant_router.post("/applications/{application_id}/reject")
def reject_candidate_application(
    application_id: int,
    payload: ApplicationRejectRequest = Body(default_factory=ApplicationRejectRequest),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    application = _load_owned_application_for_decision(db, application_id, user)
    return _execute_recruiter_decision(
        db,
        application,
        target_status="rejected",
        reason=payload.reason,
        note=payload.note,
        send_email=payload.send_email,
        user=user,
    )


@recruiter_applicant_router.get("/applications/{application_id}/notifications")
def list_application_notifications(
    application_id: int,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    application = _load_owned_application_for_decision(db, application_id, user)
    return [serialize_email_notification(item) for item in application.email_notifications]


ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
}
MAX_RESUME_SIZE = 10 * 1024 * 1024
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
ALLOWED_EXTENSIONS = {
    "application/pdf": {".pdf"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {".docx"},
    "application/msword": {".doc"},
}


@resume_router.post("/upload")
async def upload_resume(file: UploadFile = File(...), user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(415, "Resume must be PDF, DOC, DOCX, JPG, JPEG, or PNG")
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS[file.content_type]:
        raise HTTPException(415, "File extension does not match the selected resume type")
    data = await file.read(MAX_RESUME_SIZE + 1)
    if len(data) > MAX_RESUME_SIZE:
        raise HTTPException(413, "Resume must not exceed 10 MB")
    if not data:
        raise HTTPException(422, "The selected resume is empty")
    signatures = {
        "application/pdf": data.startswith(b"%PDF-"),
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": data.startswith(b"PK\x03\x04"),
        "application/msword": data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
    }
    if not signatures[file.content_type]:
        raise HTTPException(415, "File content does not match the selected resume file type")
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid4().hex}{ALLOWED_MIME[file.content_type]}"
    path = UPLOAD_DIR / stored
    path.write_bytes(data)
    resume = Resume(
        candidate_id=candidate.id,
        original_filename=Path(file.filename or "resume").name,
        stored_filename=stored,
        file_path=str(path),
        mime_type=file.content_type,
        extracted_data=json.dumps({}),
        processing_status="processing",
    )
    db.add(resume)
    db.commit()
    try:
        pages = await run_in_threadpool(extract_resume_pages, path, file.content_type)
        text = "\n".join(pages).strip()
        resume.extracted_text = text
        resume.page_text = json.dumps(pages)
        if not text:
            raise ValueError(
                "No readable text was found. Check that the file is legible or run Tesseract OCR and upload it again."
            )
        extracted = extract_resume_fields(text)
    except pytesseract.TesseractNotFoundError as exc:
        message = "Tesseract OCR is not installed or is not available on the backend PATH."
        logger.exception("Resume OCR is unavailable for resume %s", resume.id)
        resume.processing_status = "failed"
        resume.processing_error = message
        db.commit()
        raise HTTPException(503, message) from exc
    except (fitz.FileDataError, OSError, ValueError, pytesseract.TesseractError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else (
            "The file is corrupted or could not be processed. Upload a valid PDF, DOC, DOCX, JPG, or PNG."
        )
        logger.warning("Resume processing failed for resume %s: %s", resume.id, exc)
        resume.processing_status = "failed"
        resume.processing_error = message
        db.commit()
        raise HTTPException(422, message) from exc
    except Exception as exc:
        logger.exception("Unexpected resume processing failure for resume %s", resume.id)
        resume.processing_status = "failed"
        resume.processing_error = "Resume processing failed unexpectedly. Please contact support."
        db.commit()
        raise HTTPException(500, resume.processing_error) from exc
    resume.extracted_data = json.dumps(extracted)
    resume.processing_status = "processed"
    resume.processing_error = None
    db.commit()
    return {
        "id": resume.id,
        "processing_status": resume.processing_status,
        "page_text": pages,
        **extracted,
    }


@resume_router.get("/{resume_id}/download")
def download_resume(resume_id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    resume = db.get(Resume, resume_id)
    if not resume:
        raise HTTPException(404, "Resume not found")
    if user.role != "admin" and resume.candidate.user_id != user.id:
        recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
        if not recruiter:
            raise HTTPException(403, "Forbidden")
        application = db.scalar(
            select(Application)
            .join(Job, Application.job_id == Job.id)
            .where(
                Application.candidate_id == resume.candidate_id,
                Application.status != "withdrawn",
                Job.recruiter_id == recruiter.id,
                or_(Application.resume_id == resume.id, Application.resume_id.is_(None)),
            )
            .limit(1)
        )
        if not application:
            raise HTTPException(403, "Forbidden")

    path = Path(resume.file_path).resolve()
    upload_root = UPLOAD_DIR.resolve()
    if path.parent != upload_root:
        raise HTTPException(403, "Invalid resume storage location")
    if not path.is_file():
        raise HTTPException(404, "Resume file is missing from storage")

    return FileResponse(
        path=str(path),
        filename=resume.original_filename,
        media_type=resume.mime_type or "application/octet-stream",
    )


@resume_router.patch("/{resume_id}/review")
def review_resume(
    resume_id: int,
    data: ResumeReviewRequest,
    user=Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    resume = db.get(Resume, resume_id)
    if not resume or resume.candidate.user_id != user.id:
        raise HTTPException(404, "Resume not found")
    if resume.processing_status != "processed":
        raise HTTPException(409, "Only successfully processed resumes can be reviewed")
    raw = data.model_dump(mode="json")
    corrected = {
        "full_name": sanitize_profile_text(raw.get("full_name")),
        "email": sanitize_contact_email(raw.get("email")),
        "phone": sanitize_profile_text(raw.get("phone")),
        "education": sanitize_profile_text(raw.get("education")),
        "experience": sanitize_profile_text(raw.get("experience")),
        "projects": sanitize_profile_text(raw.get("projects")),
        "certifications": sanitize_profile_text(raw.get("certifications")),
        "skills": raw.get("skills", []),
    }
    resume.extracted_data = json.dumps(corrected)
    resume.is_reviewed = True
    candidate = resume.candidate
    if corrected["full_name"]:
        candidate.user.full_name = corrected["full_name"]
    candidate.contact_email = corrected["email"]
    candidate.phone = corrected["phone"]
    candidate.education = corrected["education"]
    candidate.experience = corrected["experience"]
    candidate.projects = corrected["projects"]
    candidate.certifications = corrected["certifications"]
    replace_candidate_skills(db, candidate, corrected["skills"])
    db.commit()
    return {"id": resume.id, "message": "Resume reviewed and profile updated"}


@match_router.post("/resume/{resume_id}/job/{job_id}")
def analyze_match(resume_id: int, job_id: int, user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    resume = db.get(Resume, resume_id)
    job = db.get(Job, job_id)
    if not resume or resume.candidate.user_id != user.id or resume.processing_status != "processed":
        raise HTTPException(404, "Resume or job not found")
    if (
        not job
        or job.status not in {"published", "open"}
        or not job.company.is_approved
    ):
        raise HTTPException(404, "Published job not found")

    evaluation = evaluate_candidate_job_match(resume.candidate, job, resume)
    existing = db.scalar(
        select(ResumeAnalysis).where(
            ResumeAnalysis.resume_id == resume_id,
            ResumeAnalysis.job_id == job_id,
            ResumeAnalysis.application_id.is_(None),
        ).order_by(ResumeAnalysis.updated_at.desc())
    )
    if existing and existing.input_fingerprint == evaluation["input_fingerprint"]:
        analysis = existing
    elif existing:
        analysis = existing
        analysis.candidate_id = resume.candidate_id
        analysis.match_percentage = evaluation["match_percentage"]
        analysis.matched_skills = json.dumps(evaluation["matched_skills"])
        analysis.missing_skills = json.dumps(evaluation["missing_skills"])
        analysis.preferred_matched_skills = json.dumps(evaluation["preferred_matched_skills"])
        analysis.preferred_missing_skills = json.dumps(evaluation["preferred_missing_skills"])
        analysis.relevant_experience = evaluation["relevant_experience"]
        analysis.strengths = json.dumps(evaluation["strengths"])
        analysis.weaknesses = json.dumps(evaluation["weaknesses"])
        analysis.matching_explanation = evaluation["matching_explanation"]
        analysis.score_breakdown = json.dumps(evaluation["score_breakdown"])
        analysis.recommendations = json.dumps(evaluation["recommendations"])
        analysis.input_fingerprint = evaluation["input_fingerprint"]
        analysis.updated_at = utc_now()
    else:
        analysis = ResumeAnalysis(
            resume_id=resume_id,
            job_id=job_id,
            candidate_id=resume.candidate_id,
            match_percentage=evaluation["match_percentage"],
            matched_skills=json.dumps(evaluation["matched_skills"]),
            missing_skills=json.dumps(evaluation["missing_skills"]),
            preferred_matched_skills=json.dumps(evaluation["preferred_matched_skills"]),
            preferred_missing_skills=json.dumps(evaluation["preferred_missing_skills"]),
            relevant_experience=evaluation["relevant_experience"],
            strengths=json.dumps(evaluation["strengths"]),
            weaknesses=json.dumps(evaluation["weaknesses"]),
            matching_explanation=evaluation["matching_explanation"],
            score_breakdown=json.dumps(evaluation["score_breakdown"]),
            recommendations=json.dumps(evaluation["recommendations"]),
            input_fingerprint=evaluation["input_fingerprint"],
        )
        db.add(analysis)
    db.commit()
    return {
        "resume_id": resume_id,
        "job_id": job_id,
        **evaluation,
    }


@resume_router.post("/analyze")
def analyze_resume_request(
    payload: ResumeAnalysisRequest,
    user=Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    return analyze_match(payload.resume_id, payload.job_id, user, db)


@match_router.get("/resume/{resume_id}")
def resume_match_history(
    resume_id: int,
    user=Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    resume = db.get(Resume, resume_id)
    if not resume or resume.candidate.user_id != user.id:
        raise HTTPException(404, "Resume not found")
    analyses = db.scalars(
        select(ResumeAnalysis)
        .where(ResumeAnalysis.resume_id == resume_id)
        .order_by(ResumeAnalysis.created_at.desc())
    ).all()
    return [
        {
            "job_id": analysis.job_id,
            "job_title": analysis_job.title,
            "company": analysis_job.company.name,
            "match_percentage": float(analysis.match_percentage),
            "matched_skills": json.loads(analysis.matched_skills),
            "missing_skills": json.loads(analysis.missing_skills),
            "recommendations": json.loads(analysis.recommendations),
            "matching_explanation": analysis.matching_explanation,
            "created_at": analysis.created_at.isoformat(),
        }
        for analysis in analyses
        for analysis_job in [db.get(Job, analysis.job_id)]
        if analysis_job
    ]


@admin_router.get("/stats")
@admin_router.get("/analytics")
def admin_stats(user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    return {
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "candidates": db.scalar(select(func.count()).select_from(User).where(User.role == "candidate")) or 0,
        "recruiters": db.scalar(select(func.count()).select_from(User).where(User.role == "recruiter")) or 0,
        "active_users": db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0,
        "jobs": db.scalar(select(func.count()).select_from(Job)) or 0,
        "active_jobs": db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(["published", "open"]))) or 0,
        "pending_jobs": db.scalar(select(func.count()).select_from(Job).where(Job.status == "pending")) or 0,
        "companies": db.scalar(select(func.count()).select_from(Company)) or 0,
        "pending_companies": db.scalar(select(func.count()).select_from(Company).where(Company.is_approved.is_(False))) or 0,
        "applications": db.scalar(select(func.count()).select_from(Application)) or 0,
    }


@admin_router.get("/system-status")
def admin_system_status(user=Depends(require_roles("admin"))):
    settings = get_settings()
    ai_provider = (settings.ai_provider or "none").lower()
    ai_configured = bool((settings.ai_api_key or "").strip()) and ai_provider in {"openai", "gemini"}
    return {
        "smtp_configured": is_smtp_configured(),
        "missing_smtp_vars": missing_smtp_variables(),
        "ai_provider": ai_provider,
        "ai_configured": ai_configured,
        "ai_require_external": settings.ai_require_external,
        "tesseract_available": bool(shutil.which("tesseract")),
        "auto_shortlist_threshold": settings.auto_shortlist_threshold,
    }


@admin_router.get("/analytics/trends")
def admin_analytics_trends(user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    today = utc_now().date()
    first_day = today - timedelta(days=13)
    start = utc_now().replace(year=first_day.year, month=first_day.month, day=first_day.day, hour=0, minute=0, second=0, microsecond=0)
    dates = [first_day + timedelta(days=offset) for offset in range(14)]

    registrations = db.scalars(select(User.created_at).where(User.created_at >= start)).all()
    applications = db.scalars(select(Application.created_at).where(Application.created_at >= start)).all()
    registration_counts = {day: 0 for day in dates}
    application_counts = {day: 0 for day in dates}

    for created_at in registrations:
        day = created_at.date()
        if day in registration_counts:
            registration_counts[day] += 1
    for created_at in applications:
        day = created_at.date()
        if day in application_counts:
            application_counts[day] += 1

    return {
        "registrations": [{"date": day.isoformat(), "count": registration_counts[day]} for day in dates],
        "applications": [{"date": day.isoformat(), "count": application_counts[day]} for day in dates],
    }


@admin_router.get("/jobs")
def admin_jobs(user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    jobs = db.scalars(select(Job).order_by(Job.created_at.desc())).all()
    return [
        {"id": job.id, "title": job.title, "company": job.company.name, "status": job.status, "location": job.location}
        for job in jobs
    ]


@admin_router.get("/users")
def admin_users(user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return [
        {"id": item.id, "full_name": item.full_name, "email": item.email, "role": item.role, "is_active": item.is_active}
        for item in users
    ]


@admin_router.get("/companies")
def admin_companies(user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    companies = db.scalars(select(Company).order_by(Company.created_at.desc())).all()
    return [
        {"id": item.id, "name": item.name, "location": item.location, "is_approved": item.is_approved}
        for item in companies
    ]


@admin_router.patch("/companies/{company_id}/status")
def update_company_status(company_id: int, is_approved: bool, user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Company not found")
    company.is_approved = is_approved
    db.commit()
    return {"id": company.id, "is_approved": company.is_approved}


@admin_router.patch("/users/{user_id}/status")
def update_user_status(user_id: int, is_active: bool, user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == user.id:
        raise HTTPException(400, "You cannot deactivate your own account")
    target.is_active = is_active
    db.commit()
    return {"id": target.id, "is_active": target.is_active}


@admin_router.patch("/jobs/{job_id}/status")
def moderate_job(job_id: int, status_value: str, user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    allowed = {"draft", "pending", "published", "closed", "disabled"}
    if status_value not in allowed:
        raise HTTPException(422, "Invalid job status")
    if status_value == "published" and not job.company.is_approved:
        raise HTTPException(409, "Company must be approved before publishing jobs")
    job.status = status_value
    db.commit()
    return {"id": job.id, "status": job.status}

