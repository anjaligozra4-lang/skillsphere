import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import utc_now
from app.models import (
    Application,
    ApplicationStatusHistory,
    Resume,
    ResumeAnalysis,
    User,
)
from app.services import evaluate_candidate_job_match


logger = logging.getLogger(__name__)


def record_status_history(
    db: Session,
    application: Application,
    previous_status: str | None,
    new_status: str,
    actor_name: str,
    actor_role: str,
    source: str,
    actor_user_id: int | None = None,
    note: str | None = None,
) -> ApplicationStatusHistory:
    entry = ApplicationStatusHistory(
        application_id=application.id,
        previous_status=previous_status,
        new_status=new_status,
        changed_by_user_id=actor_user_id,
        actor_name=actor_name,
        actor_role=actor_role,
        source=source,
        note=note,
        created_at=utc_now(),
    )
    db.add(entry)
    return entry


def _select_candidate_resume(db: Session, application: Application) -> Resume | None:
    if application.resume_id:
        resume = db.get(Resume, application.resume_id)
        if resume and resume.processing_status == "processed":
            return resume
    return db.scalar(
        select(Resume)
        .where(
            Resume.candidate_id == application.candidate_id,
            Resume.processing_status == "processed",
        )
        .order_by(Resume.created_at.desc(), Resume.id.desc())
        .limit(1)
    )


def run_application_matching_and_shortlisting(
    db: Session,
    application: Application,
    actor_user: User | None = None,
    force_refresh: bool = False,
) -> dict:
    """Calculate/refresh AI job match, persist evaluation, enforce 70% auto-shortlist rule.

    Per architecture rules, reaching >=70% shortlists the candidate automatically,
    while assessment assignment remains a separate manual recruiter action.
    """
    settings = get_settings()

    locked_app = db.scalar(
        select(Application)
        .where(Application.id == application.id)
        .with_for_update()
    )
    if locked_app is not None:
        application = locked_app

    resume = _select_candidate_resume(db, application)
    evaluation = evaluate_candidate_job_match(application.candidate, application.job, resume)

    existing_analysis = db.scalar(
        select(ResumeAnalysis)
        .where(ResumeAnalysis.application_id == application.id)
        .order_by(ResumeAnalysis.updated_at.desc(), ResumeAnalysis.id.desc())
        .limit(1)
    )

    if (
        existing_analysis
        and not force_refresh
        and existing_analysis.input_fingerprint == evaluation["input_fingerprint"]
    ):
        score = float(existing_analysis.match_percentage)
        recomputed = False
    else:
        recomputed = True
        score = evaluation["match_percentage"]
        if existing_analysis is None:
            analysis = ResumeAnalysis(
                resume_id=resume.id if resume else None,
                job_id=application.job_id,
                application_id=application.id,
                candidate_id=application.candidate_id,
                match_percentage=score,
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
        else:
            analysis = existing_analysis
            analysis.resume_id = resume.id if resume else analysis.resume_id
            analysis.candidate_id = application.candidate_id
            analysis.match_percentage = score
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

    application.match_score = score

    auto_shortlisted = False
    shortlist_note = None

    if score >= settings.auto_shortlist_threshold:
        if application.manual_status_override and application.status not in {"shortlisted", "interview", "selected", "accepted", "hired"}:
            shortlist_note = (
                f"Match score is {score:.2f}% (>=70%), but status '{application.status}' was preserved "
                "because a recruiter previously made a manual decision."
            )
        elif application.status in {"applied", "under_review", "screening"}:
            prev_status = application.status
            application.status = "shortlisted"
            application.shortlist_source = "automatic"
            application.auto_shortlisted_at = utc_now()
            record_status_history(
                db=db,
                application=application,
                previous_status=prev_status,
                new_status="shortlisted",
                actor_name="SkillSphere AI Shortlisting",
                actor_role="system",
                source="automatic_ai_rule",
                actor_user_id=actor_user.id if actor_user else None,
                note=f"Automatically shortlisted with {score:.2f}% AI match score (>= {settings.auto_shortlist_threshold:.0f}% rule). Assessment assignment awaits recruiter selection.",
            )
            auto_shortlisted = True
            shortlist_note = f"Automatically shortlisted ({score:.2f}% >= 70%). Ready for manual recruiter assessment assignment."
        else:
            shortlist_note = f"Match score is {score:.2f}% (>= 70%)."
    else:
        shortlist_note = f"Score {score:.2f}% is below the 70% automatic shortlisting threshold."

    db.flush()
    return {
        "application_id": application.id,
        "match_score": score,
        "recomputed": recomputed,
        "auto_shortlisted": auto_shortlisted,
        "shortlist_source": application.shortlist_source,
        "status": application.status,
        "shortlist_note": shortlist_note,
        "evaluation": evaluation,
    }
