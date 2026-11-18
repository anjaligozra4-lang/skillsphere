from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, Enum):
    candidate = "candidate"
    recruiter = "recruiter"
    admin = "admin"


class ApplicationStatus(str, Enum):
    applied = "applied"
    under_review = "under_review"
    screening = "screening"
    shortlisted = "shortlisted"
    interview = "interview"
    selected = "selected"
    accepted = "accepted"
    hired = "hired"
    rejected = "rejected"
    withdrawn = "withdrawn"


VALID_APPLICATION_STATUSES = {status.value for status in ApplicationStatus}
RECRUITER_SETTABLE_STATUSES = {
    "applied",
    "under_review",
    "screening",
    "shortlisted",
    "interview",
    "selected",
    "accepted",
    "hired",
    "rejected",
}
VALID_DIFFICULTIES = {"Easy", "Medium", "Hard"}
VALID_INTERVIEW_MODES = {"online", "in_person", "phone"}
VALID_INTERVIEW_STATUSES = {"scheduled", "rescheduled", "in_progress", "completed", "cancelled", "no_show"}
VALID_INTERVIEW_RECOMMENDATIONS = {"strong_hire", "hire", "hold", "no_hire"}
VALID_NOTIFICATION_STATUSES = {"pending", "sent", "failed"}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    candidate: Mapped["Candidate | None"] = relationship(back_populates="user", uselist=False)
    recruiter: Mapped["Recruiter | None"] = relationship(back_populates="user", uselist=False)


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    contact_email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    headline: Mapped[str | None] = mapped_column(String(255))
    education: Mapped[str | None] = mapped_column(Text)
    experience: Mapped[str | None] = mapped_column(Text)
    projects: Mapped[str | None] = mapped_column(Text)
    certifications: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(150))
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    user: Mapped["User"] = relationship(back_populates="candidate")
    skills: Mapped[list["CandidateSkill"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    resumes: Mapped[list["Resume"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(back_populates="candidate")


class Recruiter(Base):
    __tablename__ = "recruiters"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    title: Mapped[str | None] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    user: Mapped["User"] = relationship(back_populates="recruiter")
    company: Mapped["Company | None"] = relationship(back_populates="recruiters")
    jobs: Mapped[list["Job"]] = relationship(back_populates="recruiter")


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(150))
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    recruiters: Mapped[list["Recruiter"]] = relationship(back_populates="company")
    jobs: Mapped[list["Job"]] = relationship(back_populates="company")


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    normalized_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)


class CandidateSkill(Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (UniqueConstraint("candidate_id", "skill_id", name="uq_candidate_skill"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"))
    candidate: Mapped["Candidate"] = relationship(back_populates="skills")
    skill: Mapped["Skill"] = relationship()


class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    page_text: Mapped[str | None] = mapped_column(Text)
    extracted_data: Mapped[str | None] = mapped_column(Text)
    processing_status: Mapped[str] = mapped_column(String(20), default="processed")
    processing_error: Mapped[str | None] = mapped_column(Text)
    is_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    candidate: Mapped["Candidate"] = relationship(back_populates="resumes")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("recruiters.id", ondelete="CASCADE"))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(150))
    employment_type: Mapped[str] = mapped_column(String(50), default="full_time")
    experience_min: Mapped[int | None] = mapped_column(Integer)
    experience_max: Mapped[int | None] = mapped_column(Integer)
    salary_min: Mapped[float | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[float | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    recruiter: Mapped["Recruiter"] = relationship(back_populates="jobs")
    company: Mapped["Company"] = relationship(back_populates="jobs")
    skills: Mapped[list["JobSkill"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(back_populates="job")


class JobSkill(Base):
    __tablename__ = "job_skills"
    __table_args__ = (UniqueConstraint("job_id", "skill_id", name="uq_job_skill"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"))
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    job: Mapped["Job"] = relationship(back_populates="skills")
    skill: Mapped["Skill"] = relationship()


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("candidate_id", "job_id", name="uq_candidate_job_application"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(30), default="applied", index=True)
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    shortlist_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    auto_shortlisted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    manual_status_override: Mapped[bool] = mapped_column(Boolean, default=False)
    decision_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    candidate: Mapped["Candidate"] = relationship(back_populates="applications")
    job: Mapped["Job"] = relationship(back_populates="applications")
    resume: Mapped["Resume | None"] = relationship()
    decided_by_user: Mapped["User | None"] = relationship(foreign_keys=[decided_by_user_id])
    status_history: Mapped[list["ApplicationStatusHistory"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationStatusHistory.created_at.desc(), ApplicationStatusHistory.id.desc()",
    )
    assessment_assignments: Mapped[list["AssessmentAssignment"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="AssessmentAssignment.assigned_at.desc(), AssessmentAssignment.id.desc()",
    )
    interviews: Mapped[list["Interview"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="Interview.round_number.asc(), Interview.scheduled_at.asc(), Interview.id.asc()",
    )
    email_notifications: Mapped[list["EmailNotification"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="EmailNotification.created_at.desc(), EmailNotification.id.desc()",
    )


class ApplicationStatusHistory(Base):
    __tablename__ = "application_status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30))
    changed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(150))
    actor_role: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(30), default="manual")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    application: Mapped["Application"] = relationship(back_populates="status_history")


class ResumeAnalysis(Base):
    __tablename__ = "resume_analysis"
    id: Mapped[int] = mapped_column(primary_key=True)
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), nullable=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=True, index=True)
    match_percentage: Mapped[float] = mapped_column(Numeric(5, 2))
    matched_skills: Mapped[str] = mapped_column(Text, default="[]")
    missing_skills: Mapped[str] = mapped_column(Text, default="[]")
    preferred_matched_skills: Mapped[str | None] = mapped_column(Text, default="[]")
    preferred_missing_skills: Mapped[str | None] = mapped_column(Text, default="[]")
    relevant_experience: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths: Mapped[str | None] = mapped_column(Text, default="[]")
    weaknesses: Mapped[str | None] = mapped_column(Text, default="[]")
    matching_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_breakdown: Mapped[str | None] = mapped_column(Text, default="{}")
    recommendations: Mapped[str] = mapped_column(Text, default="[]")
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class SavedJob(Base):
    __tablename__ = "saved_jobs"
    __table_args__ = (UniqueConstraint("candidate_id", "job_id", name="uq_candidate_saved_job"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    job: Mapped["Job"] = relationship()


class LoginOtpChallenge(Base):
    __tablename__ = "login_otp_challenges"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    challenge_token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    otp_salt: Mapped[str] = mapped_column(String(64))
    otp_hash: Mapped[str] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    resend_count: Mapped[int] = mapped_column(Integer, default=0)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    user: Mapped["User"] = relationship()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    user: Mapped["User"] = relationship()


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"
    __table_args__ = (UniqueConstraint("scope", "identifier", name="uq_auth_rate_limit"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(50), index=True)
    identifier: Mapped[str] = mapped_column(String(255), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)


class PlatformSetting(Base):
    __tablename__ = "platform_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    setting_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    setting_value: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class QuestionBank(Base):
    __tablename__ = "question_bank"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_type: Mapped[str] = mapped_column(String(20), default="mcq")
    skill: Mapped[str] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    difficulty: Mapped[str] = mapped_column(String(20), index=True)  # Easy, Medium, Hard
    question_text: Mapped[str] = mapped_column(Text)
    options_json: Mapped[str] = mapped_column(Text)  # JSON array of 4 strings
    correct_option_index: Mapped[int] = mapped_column(Integer)  # 0..3
    marks: Mapped[int] = mapped_column(Integer, default=1)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class Assessment(Base):
    __tablename__ = "assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("recruiters.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    passing_marks: Mapped[int] = mapped_column(Integer, default=0)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    total_marks: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft, published, archived
    assessment_type: Mapped[str] = mapped_column(String(30), default="mcq", index=True)  # mcq, video
    prep_time_seconds: Mapped[int] = mapped_column(Integer, default=30)
    response_time_seconds: Mapped[int] = mapped_column(Integer, default=120)
    allow_review: Mapped[bool] = mapped_column(Boolean, default=True)
    max_recordings_per_question: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    recruiter: Mapped["Recruiter"] = relationship()
    job: Mapped["Job"] = relationship()
    questions: Mapped[list["AssessmentQuestion"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="AssessmentQuestion.order_index",
    )
    assignments: Mapped[list["AssessmentAssignment"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="AssessmentAssignment.assigned_at.desc(), AssessmentAssignment.id.desc()",
    )


class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"
    __table_args__ = (
        UniqueConstraint("assessment_id", "order_index", name="uq_assessment_question_order"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    question_bank_id: Mapped[int | None] = mapped_column(ForeignKey("question_bank.id", ondelete="SET NULL"), nullable=True, index=True)
    order_index: Mapped[int] = mapped_column(Integer)
    question_type: Mapped[str] = mapped_column(String(30), default="mcq")  # mcq, video
    skill: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100))
    difficulty: Mapped[str] = mapped_column(String(20))
    question_text: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    prep_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    options_json: Mapped[str] = mapped_column(Text, default="[]")
    correct_option_index: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    marks: Mapped[int] = mapped_column(Integer, default=1)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    assessment: Mapped["Assessment"] = relationship(back_populates="questions")
    question_bank_item: Mapped["QuestionBank | None"] = relationship()


class AssessmentAssignment(Base):
    __tablename__ = "assessment_assignments"
    __table_args__ = (
        UniqueConstraint("assessment_id", "application_id", name="uq_assessment_application_assignment"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    assigned_by_recruiter_id: Mapped[int | None] = mapped_column(ForeignKey("recruiters.id", ondelete="SET NULL"), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    recipient_email: Mapped[str] = mapped_column(String(255))
    invitation_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    invitation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    test_status: Mapped[str] = mapped_column(String(20), default="assigned", index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_automatically: Mapped[bool] = mapped_column(Boolean, default=False)

    assessment: Mapped["Assessment"] = relationship(back_populates="assignments")
    application: Mapped["Application"] = relationship(back_populates="assessment_assignments")
    candidate: Mapped["Candidate"] = relationship()
    job: Mapped["Job"] = relationship()

    answers: Mapped[list["CandidateAnswer"]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
    )
    result: Mapped["AssessmentResult | None"] = relationship(
        back_populates="assignment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    recordings: Mapped[list["AssessmentRecording"]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
    )
    proctoring_events: Mapped[list["ProctoringEvent"]] = relationship(
        cascade="all, delete-orphan",
    )


class ProctoringEvent(Base):
    __tablename__ = "proctoring_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assessment_assignments.id", ondelete="CASCADE"),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class AssessmentRecording(Base):
    __tablename__ = "assessment_recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assessment_assignments.id", ondelete="CASCADE"),
        index=True,
    )
    assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("assessment_questions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cloudinary_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cloudinary_secure_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cloudinary_public_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    video_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    upload_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    assignment: Mapped["AssessmentAssignment"] = relationship(
        back_populates="recordings"
    )
    assessment: Mapped["Assessment | None"] = relationship()
    application: Mapped["Application | None"] = relationship()
    candidate: Mapped["Candidate | None"] = relationship()
    question: Mapped["AssessmentQuestion | None"] = relationship()


class CandidateAnswer(Base):
    __tablename__ = "candidate_answers"
    __table_args__ = (
        UniqueConstraint("assignment_id", "assessment_question_id", name="uq_assignment_question_answer"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assessment_assignments.id", ondelete="CASCADE"), index=True)
    assessment_question_id: Mapped[int] = mapped_column(ForeignKey("assessment_questions.id", ondelete="CASCADE"), index=True)
    selected_option_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    marks_awarded: Mapped[int] = mapped_column(Integer, default=0)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    assignment: Mapped["AssessmentAssignment"] = relationship(back_populates="answers")
    question: Mapped["AssessmentQuestion"] = relationship()


class AssessmentResult(Base):
    __tablename__ = "assessment_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assessment_assignments.id", ondelete="CASCADE"), unique=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    obtained_marks: Mapped[int] = mapped_column(Integer)
    total_marks: Mapped[int] = mapped_column(Integer)
    passing_marks: Mapped[int] = mapped_column(Integer)
    percentage: Mapped[float] = mapped_column(Numeric(5, 2))
    is_passed: Mapped[bool] = mapped_column(Boolean)
    result_status: Mapped[str] = mapped_column(String(40))
    result_message: Mapped[str] = mapped_column(String(255))
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    submitted_automatically: Mapped[bool] = mapped_column(Boolean, default=False)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    assignment: Mapped["AssessmentAssignment"] = relationship(back_populates="result")


class Interview(Base):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    recruiter_id: Mapped[int | None] = mapped_column(ForeignKey("recruiters.id", ondelete="SET NULL"), nullable=True, index=True)
    scheduled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    round_number: Mapped[int] = mapped_column(Integer, default=1)
    round_name: Mapped[str] = mapped_column(String(120), default="Interview Round 1")
    interview_mode: Mapped[str] = mapped_column(String(30), default="online")  # online, in_person, phone
    interview_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # live_recruiter, technical, hr
    livekit_room_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    candidate_joined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recruiter_joined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_waiting_room_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=45)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    meeting_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    interviewer_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    interviewer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes_for_candidate: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="scheduled", index=True)  # scheduled, rescheduled, completed, cancelled, no_show
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(String(30), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    application: Mapped["Application"] = relationship(back_populates="interviews")
    job: Mapped["Job"] = relationship()
    candidate: Mapped["Candidate"] = relationship()
    recruiter: Mapped["Recruiter | None"] = relationship()
    scheduled_by_user: Mapped["User | None"] = relationship(foreign_keys=[scheduled_by_user_id])
    notifications: Mapped[list["EmailNotification"]] = relationship(
        back_populates="interview",
        order_by="EmailNotification.created_at.desc(), EmailNotification.id.desc()",
    )
    recordings: Mapped[list["InterviewRecording"]] = relationship(
        back_populates="interview",
        cascade="all, delete-orphan",
        order_by="InterviewRecording.created_at.desc(), InterviewRecording.id.desc()",
    )


class EmailNotification(Base):
    __tablename__ = "email_notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True)
    interview_id: Mapped[int | None] = mapped_column(ForeignKey("interviews.id", ondelete="SET NULL"), nullable=True, index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    triggered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    notification_type: Mapped[str] = mapped_column(String(50), index=True)
    recipient_email: Mapped[str] = mapped_column(String(255), index=True)
    recipient_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    subject: Mapped[str] = mapped_column(String(255))
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending, sent, failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    application: Mapped["Application | None"] = relationship(back_populates="email_notifications")
    interview: Mapped["Interview | None"] = relationship(back_populates="notifications")
    candidate: Mapped["Candidate | None"] = relationship()
    job: Mapped["Job | None"] = relationship()
    triggered_by_user: Mapped["User | None"] = relationship(foreign_keys=[triggered_by_user_id])


class InterviewRecording(Base):
    __tablename__ = "interview_recordings"

    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(
        ForeignKey("interviews.id", ondelete="CASCADE"),
        index=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        index=True,
    )
    cloudinary_public_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    cloudinary_secure_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upload_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)  # pending, uploading, completed, failed
    egress_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    local_temp_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    interview: Mapped["Interview"] = relationship(back_populates="recordings")
    candidate: Mapped["Candidate"] = relationship()
