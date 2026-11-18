from datetime import datetime, timedelta
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import ensure_utc, isoformat_utc, utc_now
from app.email_service import (
    EmailConfigurationError,
    EmailDeliveryError,
    _send_email_via_smtp,
    build_application_status_email,
    build_interview_notification_email,
    sanitize_email_error,
    validate_recipient_email,
)
from app.models import Application, EmailNotification, Interview


logger = logging.getLogger(__name__)

APPLICATION_NOTIFICATION_TYPES = {
    "application_submitted",
    "application_under_review",
    "application_shortlisted",
    "application_rejected",
    "application_selected",
    "application_hired",
}
INTERVIEW_NOTIFICATION_TYPES = {
    "interview_scheduled",
    "interview_rescheduled",
    "interview_cancelled",
    "interview_reminder_24h",
    "interview_reminder_1h",
}
VALID_NOTIFICATION_TYPES = APPLICATION_NOTIFICATION_TYPES | INTERVIEW_NOTIFICATION_TYPES


class NotificationError(RuntimeError):
    """Base error for email notification dispatch and retry workflows."""


class NotificationNotFoundError(NotificationError):
    """Raised when the requested notification log entry does not exist."""


class NotificationAlreadySentError(NotificationError):
    """Raised when attempting to resend an already-delivered notification."""


def _scrub_error(exc: Exception | str) -> str:
    settings = get_settings()
    return sanitize_email_error(
        exc,
        settings.smtp_password,
        settings.smtp_username,
        settings.jwt_secret_key,
        getattr(settings, "gemini_api_key", "") or "",
        getattr(settings, "ai_api_key", "") or "",
    )


def _find_duplicate_sent_notification(
    db: Session,
    *,
    application_id: int | None,
    interview_id: int | None,
    notification_type: str,
    recipient_email: str,
    body_text: str,
    exclude_id: int | None = None,
) -> EmailNotification | None:
    stmt = select(EmailNotification).where(
        EmailNotification.notification_type == notification_type,
        EmailNotification.recipient_email == recipient_email,
        EmailNotification.status == "sent",
        EmailNotification.body_text == body_text,
    )
    if application_id is None:
        stmt = stmt.where(EmailNotification.application_id.is_(None))
    else:
        stmt = stmt.where(EmailNotification.application_id == application_id)

    if interview_id is None:
        stmt = stmt.where(EmailNotification.interview_id.is_(None))
    else:
        stmt = stmt.where(EmailNotification.interview_id == interview_id)

    if exclude_id is not None:
        stmt = stmt.where(EmailNotification.id != exclude_id)

    return db.scalar(stmt.order_by(EmailNotification.id.desc()).limit(1))


def _attempt_smtp_delivery(
    db: Session,
    notification: EmailNotification,
    *,
    commit: bool = True,
) -> EmailNotification:
    try:
        recipient = validate_recipient_email(notification.recipient_email)
        _send_email_via_smtp(
            recipient,
            notification.subject,
            notification.body_text or "",
            notification.body_html or "",
        )
        notification.status = "sent"
        notification.sent_at = utc_now()
        notification.error_message = None
    except (EmailConfigurationError, EmailDeliveryError, ValueError, Exception) as exc:
        notification.status = "failed"
        notification.error_message = _scrub_error(exc)
        logger.warning(
            "Email notification %s (type=%s) failed: %s",
            notification.id,
            notification.notification_type,
            notification.error_message,
        )

    db.flush()
    if commit:
        db.commit()
        db.refresh(notification)
    return notification


def _resolve_recipient_info(candidate, job) -> tuple[str, str, str, str]:
    company_name = job.company.name if job and job.company else "SkillSphere Partner"
    job_title = job.title if job else "Role"
    candidate_name = candidate.user.full_name if candidate and candidate.user else "Candidate"
    raw_email = (
        (candidate.user.email if candidate and candidate.user else None)
        or (candidate.contact_email if candidate else None)
        or ""
    ).strip()
    return company_name, job_title, candidate_name, raw_email


def _dispatch_notification(
    db: Session,
    *,
    application_id: int | None,
    interview_id: int | None,
    candidate_id: int | None,
    job_id: int | None,
    triggered_by_user_id: int | None,
    notification_type: str,
    recipient_email: str,
    recipient_name: str,
    subject: str,
    body_text: str,
    body_html: str,
    deduplicate_sent: bool,
    commit: bool,
) -> EmailNotification:
    if deduplicate_sent and recipient_email:
        existing_sent = _find_duplicate_sent_notification(
            db,
            application_id=application_id,
            interview_id=interview_id,
            notification_type=notification_type,
            recipient_email=recipient_email,
            body_text=body_text,
        )
        if existing_sent is not None:
            return existing_sent

    notification = EmailNotification(
        application_id=application_id,
        interview_id=interview_id,
        candidate_id=candidate_id,
        job_id=job_id,
        triggered_by_user_id=triggered_by_user_id,
        notification_type=notification_type,
        recipient_email=recipient_email[:255],
        recipient_name=(recipient_name or "Candidate")[:150],
        subject=subject[:255],
        body_text=body_text,
        body_html=body_html,
        status="pending",
        retry_count=0,
    )
    db.add(notification)
    db.flush()
    return _attempt_smtp_delivery(db, notification, commit=commit)


def send_application_notification(
    db: Session,
    application: Application,
    notification_type: str,
    *,
    reason: str | None = None,
    note: str | None = None,
    triggered_by_user_id: int | None = None,
    deduplicate_sent: bool = True,
    commit: bool = True,
) -> EmailNotification:
    """Build, log, and non-blockingly send a shortlisted/rejected/selected candidate email."""
    if notification_type not in APPLICATION_NOTIFICATION_TYPES:
        raise ValueError(f"Unsupported application notification type: {notification_type}")

    company_name, job_title, candidate_name, raw_email = _resolve_recipient_info(
        application.candidate,
        application.job,
    )
    subject, text_body, html_body = build_application_status_email(
        notification_type,
        candidate_name,
        job_title,
        company_name,
        reason=reason,
        note=note,
    )
    return _dispatch_notification(
        db,
        application_id=application.id,
        interview_id=None,
        candidate_id=application.candidate_id,
        job_id=application.job_id,
        triggered_by_user_id=triggered_by_user_id,
        notification_type=notification_type,
        recipient_email=raw_email,
        recipient_name=candidate_name,
        subject=subject,
        body_text=text_body,
        body_html=html_body,
        deduplicate_sent=deduplicate_sent,
        commit=commit,
    )


def send_interview_notification(
    db: Session,
    interview: Interview,
    notification_type: str,
    *,
    triggered_by_user_id: int | None = None,
    deduplicate_sent: bool = True,
    commit: bool = True,
) -> EmailNotification:
    """Build, log, and non-blockingly send an interview scheduled/rescheduled/cancelled email."""
    if notification_type not in INTERVIEW_NOTIFICATION_TYPES:
        raise ValueError(f"Unsupported interview notification type: {notification_type}")

    company_name, job_title, candidate_name, raw_email = _resolve_recipient_info(
        interview.candidate,
        interview.job,
    )
    subject, text_body, html_body = build_interview_notification_email(
        notification_type,
        candidate_name,
        job_title,
        company_name,
        round_number=interview.round_number,
        round_name=interview.round_name,
        interview_mode=interview.interview_mode,
        scheduled_at=interview.scheduled_at,
        duration_minutes=interview.duration_minutes,
        timezone_name=interview.timezone,
        meeting_link=interview.meeting_link,
        location=interview.location,
        interviewer_name=interview.interviewer_name,
        notes_for_candidate=interview.notes_for_candidate,
        cancellation_reason=interview.cancellation_reason,
    )
    return _dispatch_notification(
        db,
        application_id=interview.application_id,
        interview_id=interview.id,
        candidate_id=interview.candidate_id,
        job_id=interview.job_id,
        triggered_by_user_id=triggered_by_user_id,
        notification_type=notification_type,
        recipient_email=raw_email,
        recipient_name=candidate_name,
        subject=subject,
        body_text=text_body,
        body_html=html_body,
        deduplicate_sent=deduplicate_sent,
        commit=commit,
    )


def retry_email_notification(
    db: Session,
    notification_id: int,
    *,
    triggered_by_user_id: int | None = None,
    commit: bool = True,
) -> EmailNotification:
    """Safely retry a failed/pending notification while preventing duplicate delivered emails."""
    notification = db.scalar(
        select(EmailNotification)
        .where(EmailNotification.id == notification_id)
        .with_for_update()
    )
    if notification is None:
        raise NotificationNotFoundError(f"Email notification {notification_id} not found.")

    if notification.status == "sent":
        raise NotificationAlreadySentError(
            f"Email notification {notification_id} has already been sent."
        )

    sibling_sent = _find_duplicate_sent_notification(
        db,
        application_id=notification.application_id,
        interview_id=notification.interview_id,
        notification_type=notification.notification_type,
        recipient_email=notification.recipient_email,
        body_text=notification.body_text or "",
        exclude_id=notification.id,
    )
    if sibling_sent is not None:
        raise NotificationAlreadySentError(
            "An identical email notification has already been sent for this candidate event."
        )

    notification.retry_count = (notification.retry_count or 0) + 1
    notification.status = "pending"
    if triggered_by_user_id is not None:
        notification.triggered_by_user_id = triggered_by_user_id
    db.flush()
    return _attempt_smtp_delivery(db, notification, commit=commit)


def process_due_interview_reminders(
    db: Session,
    *,
    now: datetime | None = None,
) -> dict:
    """Send due 24-hour and 1-hour reminders for active scheduled/rescheduled interviews.

    Re-checks live interview status, excludes cancelled/completed/past interviews,
    prevents duplicates per schedule, and follows updated schedules after rescheduling.
    """
    ref_now = ensure_utc(now) or utc_now()
    horizon_24h = ref_now + timedelta(hours=24)

    due_interviews = db.scalars(
        select(Interview)
        .where(
            Interview.status.in_(["scheduled", "rescheduled"]),
            Interview.scheduled_at > ref_now,
            Interview.scheduled_at <= horizon_24h,
        )
        .order_by(Interview.scheduled_at.asc(), Interview.id.asc())
    ).all()

    summary = {
        "checked": len(due_interviews),
        "sent_24h": 0,
        "sent_1h": 0,
        "skipped": 0,
        "failed": 0,
    }

    for interview in due_interviews:
        if interview.application and interview.application.status in {"withdrawn", "rejected"}:
            summary["skipped"] += 1
            continue

        sched_utc = ensure_utc(interview.scheduled_at)
        if sched_utc is None or sched_utc <= ref_now:
            summary["skipped"] += 1
            continue

        remaining = sched_utc - ref_now
        if remaining <= timedelta(hours=1):
            reminder_type = "interview_reminder_1h"
        elif remaining <= timedelta(hours=24):
            reminder_type = "interview_reminder_24h"
        else:
            summary["skipped"] += 1
            continue

        company_name, job_title, candidate_name, raw_email = _resolve_recipient_info(
            interview.candidate,
            interview.job,
        )
        subject, text_body, html_body = build_interview_notification_email(
            reminder_type,
            candidate_name,
            job_title,
            company_name,
            round_number=interview.round_number,
            round_name=interview.round_name,
            interview_mode=interview.interview_mode,
            scheduled_at=interview.scheduled_at,
            duration_minutes=interview.duration_minutes,
            timezone_name=interview.timezone,
            meeting_link=interview.meeting_link,
            location=interview.location,
            interviewer_name=interview.interviewer_name,
            notes_for_candidate=interview.notes_for_candidate,
            cancellation_reason=None,
        )

        existing_sent = None
        if raw_email:
            existing_sent = _find_duplicate_sent_notification(
                db,
                application_id=interview.application_id,
                interview_id=interview.id,
                notification_type=reminder_type,
                recipient_email=raw_email,
                body_text=text_body,
            )
        if existing_sent is not None:
            summary["skipped"] += 1
            continue

        notif = _dispatch_notification(
            db,
            application_id=interview.application_id,
            interview_id=interview.id,
            candidate_id=interview.candidate_id,
            job_id=interview.job_id,
            triggered_by_user_id=None,
            notification_type=reminder_type,
            recipient_email=raw_email,
            recipient_name=candidate_name,
            subject=subject,
            body_text=text_body,
            body_html=html_body,
            deduplicate_sent=True,
            commit=True,
        )
        if notif.status == "sent":
            if reminder_type == "interview_reminder_1h":
                summary["sent_1h"] += 1
            else:
                summary["sent_24h"] += 1
        else:
            summary["failed"] += 1

    return summary


def serialize_email_notification(notification: EmailNotification) -> dict:
    return {
        "id": notification.id,
        "application_id": notification.application_id,
        "interview_id": notification.interview_id,
        "candidate_id": notification.candidate_id,
        "job_id": notification.job_id,
        "triggered_by_user_id": notification.triggered_by_user_id,
        "notification_type": notification.notification_type,
        "recipient_email": notification.recipient_email,
        "recipient_name": notification.recipient_name,
        "subject": notification.subject,
        "status": notification.status,
        "error_message": notification.error_message,
        "retry_count": notification.retry_count,
        "sent_at": isoformat_utc(notification.sent_at),
        "created_at": isoformat_utc(notification.created_at),
        "updated_at": isoformat_utc(notification.updated_at),
    }
