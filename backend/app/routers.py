import json
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import fitz
import pytesseract
from starlette.concurrency import run_in_threadpool

from app.api import current_user, require_roles
from app.core.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models import (
    Application, Candidate, CandidateSkill, Company, Job, JobSkill, Recruiter,
    Resume, ResumeAnalysis, SavedJob, Skill, User, utc_now,
)
from app.services import (
    calculate_match,
    extract_resume_fields,
    extract_resume_pages,
    extract_skills,
    normalize_skill,
)

from pathlib import Path
import logging


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


class CandidateRequest(BaseModel):
    contact_email: EmailStr | None = None
    phone: str | None = None
    headline: str | None = None
    education: str | None = None
    experience: str | None = None
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
    skills: list[str] = Field(default_factory=list)


class ResumeAnalysisRequest(BaseModel):
    resume_id: int = Field(gt=0)
    job_id: int = Field(gt=0)


class ApplicationStatusRequest(BaseModel):
    status: str


class CompanyRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    website: str | None = None
    location: str | None = None


@auth_router.post("/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = str(payload.email).strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email is already registered")
    user = User(
        email=email, password_hash=hash_password(payload.password),
        full_name=payload.full_name, role=payload.role,
    )
    try:
        db.add(user)
        db.flush()
        if payload.role == "candidate":
            db.add(Candidate(user_id=user.id))
        else:
            db.add(Recruiter(user_id=user.id))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Email is already registered") from exc
    return {"id": user.id, "email": user.email, "role": user.role}


@auth_router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(payload.email).strip().lower()))
    if not user or not verify_password(payload.password, user.password_hash) or not user.is_active:
        raise HTTPException(401, "Invalid email or password")
    return {
        "access_token": create_access_token(str(user.id), user.role),
        "token_type": "bearer",
        "id": user.id,
        "role": user.role,
        "full_name": user.full_name,
    }


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
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    return {
        "id": candidate.id, "full_name": user.full_name, "email": user.email,
        "contact_email": candidate.contact_email or user.email,
        "phone": candidate.phone, "headline": candidate.headline,
        "education": candidate.education, "experience": candidate.experience,
        "location": candidate.location, "summary": candidate.summary,
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
    for field in ("contact_email", "phone", "headline", "education", "experience", "location", "summary"):
        setattr(candidate, field, getattr(payload, field))
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
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
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
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
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
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
    if not recruiter or not recruiter.company:
        raise HTTPException(404, "Company profile not found")
    return {"id": recruiter.company.id, "name": recruiter.company.name,
            "description": recruiter.company.description, "website": recruiter.company.website,
            "location": recruiter.company.location, "is_approved": recruiter.company.is_approved}


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
    ordering = {
        "newest": (Job.created_at.desc(), Job.id.desc()),
        "oldest": (Job.created_at.asc(), Job.id.asc()),
        "salary_asc": (Job.salary_min.asc().nullslast(), Job.created_at.desc()),
        "salary_desc": (Job.salary_max.desc().nullslast(), Job.created_at.desc()),
        "title_asc": (Job.title.asc(), Job.id.asc()),
    }[sort_by]
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
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
    if not recruiter.company_id:
        raise HTTPException(400, "Create a company profile before posting jobs")
    if not recruiter.company.is_approved:
        raise HTTPException(403, "Company must be approved before posting jobs")
    job = Job(recruiter_id=recruiter.id, company_id=recruiter.company_id, title=payload.title,
              description=payload.description, location=payload.location,
              employment_type=payload.employment_type, experience_min=payload.experience_min,
              experience_max=payload.experience_max, salary_min=payload.salary_min,
              salary_max=payload.salary_max,
              salary_currency=payload.salary_currency.upper() if payload.salary_currency else None,
              status="pending")
    db.add(job)
    db.flush()
    add_job_skills(db, job, payload.skills)
    db.commit()
    return {"id": job.id, "status": job.status}


@recruiter_router.get("/jobs")
def my_jobs(user=Depends(require_roles("recruiter")), db: Session = Depends(get_db)):
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
    jobs = db.scalars(select(Job).where(Job.recruiter_id == recruiter.id).order_by(Job.created_at.desc())).all()
    return [{"id": job.id, "title": job.title, "description": job.description,
             "location": job.location, "employment_type": job.employment_type,
             "experience_min": job.experience_min, "experience_max": job.experience_max,
             "salary_min": float(job.salary_min) if job.salary_min is not None else None,
             "salary_max": float(job.salary_max) if job.salary_max is not None else None,
             "salary_currency": job.salary_currency,
             "status": job.status, "skills": [item.skill.name for item in job.skills],
             "applications_count": len(job.applications)} for job in jobs]


@recruiter_router.delete("/jobs/{job_id}")
def delete_recruiter_job(job_id: int, user=Depends(require_roles("recruiter")), db: Session = Depends(get_db)):
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
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
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
    job_filter = Job.recruiter_id == recruiter.id
    application_query = select(func.count(Application.id)).join(
        Job, Application.job_id == Job.id
    ).where(job_filter)
    return {
        "jobs": db.scalar(
            select(func.count(Job.id)).where(job_filter)
        ) or 0,
        "active_jobs": db.scalar(
            select(func.count(Job.id)).where(
                job_filter, Job.status.in_(["published", "open"])
            )
        ) or 0,
        "applications": db.scalar(application_query) or 0,
        "pending_applications": db.scalar(
            application_query.where(
                Application.status.in_(["applied", "under_review", "screening"])
            )
        ) or 0,
    }


@recruiter_router.put("/jobs/{job_id}")
def update_job(
    job_id: int,
    payload: JobRequest,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
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
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
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
        application.status = "applied"
        application.resume_id = resume_id
        application.created_at = utc_now()
        db.commit()
        return {"id": application.id, "status": application.status}
    application = Application(candidate_id=candidate.id, job_id=job_id, resume_id=resume_id)
    db.add(application)
    db.commit()
    return {"id": application.id, "status": application.status}


@application_router.get("/me")
@application_router.get("")
def my_applications(user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    applications = db.scalars(select(Application).where(Application.candidate_id == candidate.id).order_by(Application.created_at.desc())).all()
    result = []
    for item in applications:
        resume = db.get(Resume, item.resume_id) if item.resume_id else None
        result.append({
            "id": item.id,
            "job_id": item.job_id,
            "job": item.job.title,
            "company": item.job.company.name,
            "resume_id": item.resume_id,
            "resume_filename": resume.original_filename if resume else None,
            "created_at": item.created_at.isoformat(),
            "status": item.status,
        })
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
    application.status = "withdrawn"
    db.commit()
    return {"id": application_id, "message": "Application withdrawn"}


@resume_router.get("/me")
def my_resumes(user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    resumes = db.scalars(select(Resume).where(Resume.candidate_id == candidate.id).order_by(Resume.created_at.desc())).all()
    return [{"id": resume.id, "original_filename": resume.original_filename,
             "extracted_data": json.loads(resume.extracted_data) if resume.extracted_data else {},
             "processing_status": resume.processing_status,
             "processing_error": resume.processing_error,
             "page_text": json.loads(resume.page_text) if resume.page_text else [],
             "is_reviewed": resume.is_reviewed, "created_at": resume.created_at.isoformat()} for resume in resumes]


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


@recruiter_router.get("/jobs/{job_id}/applicants")
def job_applicants(
    job_id: int,
    skill: str | None = None,
    experience: str | None = None,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
    job = db.get(Job, job_id)
    if not job or job.recruiter_id != recruiter.id:
        raise HTTPException(404, "Job not found")
    applicants = []
    for application in job.applications:
        candidate = application.candidate
        skills = [item.skill.name for item in candidate.skills]
        if skill and not any(skill.casefold() in name.casefold() for name in skills):
            continue
        if experience and experience.casefold() not in (candidate.experience or "").casefold():
            continue
        resume = db.get(Resume, application.resume_id) if application.resume_id else None
        applicants.append({
            "id": application.id,
            "candidate": candidate.user.full_name,
            "email": candidate.user.email,
            "job_title": job.title,
            "status": application.status,
            "applied_at": application.created_at.isoformat(),
            "resume_id": application.resume_id,
            "resume_filename": resume.original_filename if resume else None,
            "headline": candidate.headline,
            "education": candidate.education,
            "experience": candidate.experience,
            "location": candidate.location,
            "summary": candidate.summary,
            "skills": skills,
        })
    return applicants


@recruiter_applicant_router.get("/applicants")
def recruiter_applicants(
    job_id: int | None = Query(default=None, gt=0),
    skill: str | None = None,
    experience: str | None = None,
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
    statement = select(Job).where(Job.recruiter_id == recruiter.id)
    if job_id is not None:
        statement = statement.where(Job.id == job_id)
    jobs = db.scalars(statement.order_by(Job.created_at.desc())).all()
    result = []
    for job in jobs:
        for applicant in job_applicants(job.id, skill, experience, user, db):
            result.append({
                **applicant,
                "job_id": job.id,
                "job_title": job.title,
                "company": job.company.name,
            })
    return result


@recruiter_router.patch("/applications/{application_id}")
def update_application(application_id: int, status_value: str, user=Depends(require_roles("recruiter")), db: Session = Depends(get_db)):
    application = db.get(Application, application_id)
    if not application or application.job.recruiter.user_id != user.id:
        raise HTTPException(404, "Application not found")
    if application.status == "withdrawn":
        raise HTTPException(409, "Withdrawn applications cannot be updated")
    allowed = {"applied", "under_review", "screening", "shortlisted", "interview", "selected", "accepted", "hired", "rejected"}
    if status_value not in allowed:
        raise HTTPException(422, "Invalid application status")
    application.status = status_value
    db.commit()
    return {"id": application.id, "status": application.status}


@application_router.put("/{application_id}/status")
def update_application_status(
    application_id: int,
    payload: ApplicationStatusRequest = Body(...),
    user=Depends(require_roles("recruiter")),
    db: Session = Depends(get_db),
):
    return update_application(application_id, payload.status, user, db)


ALLOWED_MIME = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
MAX_RESUME_SIZE = 10 * 1024 * 1024
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
ALLOWED_EXTENSIONS = {
    "application/pdf": {".pdf"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
}


@resume_router.post("/upload")
async def upload_resume(file: UploadFile = File(...), user=Depends(require_roles("candidate")), db: Session = Depends(get_db)):
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(415, "Resume must be PDF, JPG, JPEG or PNG")
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
    }
    if not signatures[file.content_type]:
        raise HTTPException(415, "File content does not match the selected PDF, JPG, or PNG type")
    candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    from uuid import uuid4
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
            "The file is corrupted or could not be processed. Upload a valid PDF, JPG, or PNG."
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
                Application.resume_id == resume.id,
                Application.status != "withdrawn",
                Job.recruiter_id == recruiter.id,
            )
            .limit(1)
        )
        if not application:
            raise HTTPException(403, "Forbidden")
    return FileResponse(resume.file_path, filename=resume.original_filename)


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
    corrected = data.model_dump(mode="json")
    resume.extracted_data = json.dumps(corrected)
    resume.is_reviewed = True
    candidate = resume.candidate
    if corrected["full_name"]:
        candidate.user.full_name = corrected["full_name"]
    candidate.contact_email = corrected["email"]
    candidate.phone = corrected["phone"]
    candidate.education = corrected["education"]
    candidate.experience = corrected["experience"]
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
    candidate_skill_names = {item.skill.name for item in resume.candidate.skills}
    resume_data = json.loads(resume.extracted_data) if resume.extracted_data else {}
    candidate_skill_names.update(resume_data.get("skills", []))
    candidate_skills = {
        normalize_skill(name): name
        for name in candidate_skill_names
        if isinstance(name, str) and normalize_skill(name)
    }
    required_skill_names = {
        item.skill.name for item in job.skills if item.is_required
    }
    required_skill_names.update(extract_skills(job.description))
    required_skills = {
        normalize_skill(name): name
        for name in required_skill_names
        if normalize_skill(name)
    }
    result = calculate_match(set(candidate_skills), set(required_skills))
    matched = [
        candidate_skills.get(skill, required_skills.get(skill, skill))
        for skill in json.loads(result["matched_skills"])
    ]
    missing = [required_skills.get(skill, skill) for skill in json.loads(result["missing_skills"])]
    recommendations = (
        [f"Add evidence of {skill} to your profile or resume." for skill in missing]
        if missing else ["Your skills cover all identified requirements for this job."]
    )
    analysis = ResumeAnalysis(resume_id=resume_id, job_id=job_id, match_percentage=result["match_percentage"],
                              matched_skills=json.dumps(matched), missing_skills=json.dumps(missing),
                              recommendations=json.dumps(recommendations))
    db.add(analysis)
    db.commit()
    return {"resume_id": resume_id, "job_id": job_id, "match_percentage": result["match_percentage"],
            "matched_skills": matched, "missing_skills": missing,
            "recommendations": recommendations}


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
    return [{
        "job_id": analysis.job_id,
        "job_title": analysis_job.title,
        "company": analysis_job.company.name,
        "match_percentage": float(analysis.match_percentage),
        "matched_skills": json.loads(analysis.matched_skills),
        "missing_skills": json.loads(analysis.missing_skills),
        "recommendations": json.loads(analysis.recommendations),
        "created_at": analysis.created_at.isoformat(),
    } for analysis in analyses for analysis_job in [db.get(Job, analysis.job_id)] if analysis_job]


@admin_router.get("/stats")
@admin_router.get("/analytics")
def admin_stats(user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    return {
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "candidates": db.scalar(
            select(func.count()).select_from(User).where(User.role == "candidate")
        ) or 0,
        "recruiters": db.scalar(
            select(func.count()).select_from(User).where(User.role == "recruiter")
        ) or 0,
        "active_users": db.scalar(
            select(func.count()).select_from(User).where(User.is_active.is_(True))
        ) or 0,
        "jobs": db.scalar(select(func.count()).select_from(Job)) or 0,
        "active_jobs": db.scalar(
            select(func.count()).select_from(Job).where(Job.status.in_(["published", "open"]))
        ) or 0,
        "pending_jobs": db.scalar(
            select(func.count()).select_from(Job).where(Job.status == "pending")
        ) or 0,
        "companies": db.scalar(select(func.count()).select_from(Company)) or 0,
        "pending_companies": db.scalar(
            select(func.count()).select_from(Company).where(Company.is_approved.is_(False))
        ) or 0,
        "applications": db.scalar(select(func.count()).select_from(Application)) or 0,
    }


@admin_router.get("/analytics/trends")
def admin_analytics_trends(user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).date()
    first_day = today - timedelta(days=13)
    start = datetime.combine(first_day, datetime.min.time())
    dates = [first_day + timedelta(days=offset) for offset in range(14)]

    registrations = db.scalars(
        select(User.created_at).where(User.created_at >= start)
    ).all()
    applications = db.scalars(
        select(Application.created_at).where(Application.created_at >= start)
    ).all()
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
        "registrations": [
            {"date": day.isoformat(), "count": registration_counts[day]}
            for day in dates
        ],
        "applications": [
            {"date": day.isoformat(), "count": application_counts[day]}
            for day in dates
        ],
    }


@admin_router.get("/jobs")
def admin_jobs(user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    jobs = db.scalars(select(Job).order_by(Job.created_at.desc())).all()
    return [{"id": job.id, "title": job.title, "company": job.company.name,
             "status": job.status, "location": job.location} for job in jobs]


@admin_router.get("/users")
def admin_users(user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return [{"id": item.id, "full_name": item.full_name, "email": item.email,
             "role": item.role, "is_active": item.is_active} for item in users]


@admin_router.get("/companies")
def admin_companies(user=Depends(require_roles("admin")), db: Session = Depends(get_db)):
    companies = db.scalars(select(Company).order_by(Company.created_at.desc())).all()
    return [{
        "id": item.id,
        "name": item.name,
        "location": item.location,
        "is_approved": item.is_approved,
    } for item in companies]


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
