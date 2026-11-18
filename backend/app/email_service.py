from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
import html
import logging
import re
import smtplib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.core.security import ensure_utc


logger = logging.getLogger(__name__)


class EmailConfigurationError(RuntimeError):
    """Raised when SMTP settings are incomplete or missing."""


class EmailDeliveryError(RuntimeError):
    """Raised when the SMTP provider fails or rejects delivery."""


def missing_smtp_variables() -> list[str]:
    settings = get_settings()
    missing = []
    if not (settings.smtp_host or "").strip():
        missing.append("SMTP_HOST")
    if not settings.smtp_port:
        missing.append("SMTP_PORT")
    if not (settings.smtp_username or "").strip():
        missing.append("SMTP_USERNAME")
    if not (settings.smtp_password or "").strip():
        missing.append("SMTP_PASSWORD")
    if not (settings.smtp_from_email or "").strip():
        missing.append("SMTP_FROM_EMAIL")
    return missing


def is_smtp_configured() -> bool:
    return len(missing_smtp_variables()) == 0


def smtp_configuration_instructions() -> str:
    missing = missing_smtp_variables()
    missing_str = ", ".join(missing) if missing else "SMTP settings"
    return (
        f"Email delivery is not configured (missing: {missing_str}). "
        "Configure SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, "
        "SMTP_FROM_EMAIL, and SMTP_FROM_NAME=SkillSphere in backend/.env and restart the backend."
    )


def sanitize_email_error(exc: Exception | str, *secrets_to_scrub: str) -> str:
    """Return a clean error message with any SMTP credentials scrubbed."""
    msg = str(exc) or exc.__class__.__name__
    for secret in secrets_to_scrub:
        if secret and len(secret.strip()) >= 3:
            msg = msg.replace(secret, "[REDACTED]").replace(secret.strip(), "[REDACTED]")
    return msg


def _send_email_via_smtp(to_email: str, subject: str, text_body: str, html_body: str) -> None:
    if not is_smtp_configured():
        raise EmailConfigurationError(smtp_configuration_instructions())

    settings = get_settings()
    message = EmailMessage()
    sender_name = (settings.smtp_from_name or "SkillSphere").strip()
    sender_email = settings.smtp_from_email.strip()
    message["Subject"] = subject
    message["From"] = formataddr((sender_name, sender_email))
    message["To"] = to_email.strip()
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    host = settings.smtp_host.strip()
    port = int(settings.smtp_port)

    try:
        if settings.smtp_use_ssl or port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                server.login(settings.smtp_username.strip(), settings.smtp_password)
                refused = server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                if settings.smtp_use_tls:
                    server.starttls()
                    server.ehlo()
                server.login(settings.smtp_username.strip(), settings.smtp_password)
                refused = server.send_message(message)
        if refused:
            raise EmailDeliveryError(f"SMTP server refused recipient(s): {', '.join(refused.keys())}")
    except EmailDeliveryError:
        raise
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("SMTP email delivery failed for %s: %s", to_email, type(exc).__name__)
        raise EmailDeliveryError(
            f"Email delivery failed via SMTP provider: {sanitize_email_error(exc, settings.smtp_password, settings.smtp_username)}"
        ) from exc


def send_otp_email(to_email: str, full_name: str, otp_code: str, expire_minutes: int = 5) -> None:
    safe_name = html.escape(full_name or "SkillSphere User")
    safe_otp = html.escape(otp_code)
    subject = "Your SkillSphere Login Verification Code"

    text_body = (
        f"Hello {full_name or 'there'},\n\n"
        f"Your SkillSphere one-time login verification code is: {otp_code}\n\n"
        f"This code expires in {expire_minutes} minutes and allows up to 5 verification attempts.\n"
        "If you did not try to sign in to SkillSphere, please ignore this email and secure your password.\n\n"
        "— SkillSphere Security Team"
    )

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:24px;background:#f4f6fb;font-family:Arial,Helvetica,sans-serif;color:#18213a;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e2e8f0;">
    <tr>
      <td style="padding:24px 28px;background:linear-gradient(120deg,#4f46e5,#6366f1,#0891b2);color:#ffffff;">
        <div style="font-size:22px;font-weight:800;letter-spacing:-0.4px;">SkillSphere</div>
        <div style="font-size:13px;opacity:0.9;margin-top:4px;">Secure Account Verification</div>
      </td>
    </tr>
    <tr>
      <td style="padding:28px;">
        <p style="margin:0 0 14px;font-size:15px;">Hello <strong>{safe_name}</strong>,</p>
        <p style="margin:0 0 18px;font-size:14px;line-height:1.6;color:#475569;">
          Use the six-digit verification code below to complete your sign-in to SkillSphere.
        </p>
        <div style="margin:20px 0;padding:18px;text-align:center;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;">
          <span style="font-size:32px;font-weight:800;letter-spacing:8px;color:#4f46e5;font-family:monospace;">{safe_otp}</span>
        </div>
        <p style="margin:0 0 10px;font-size:13px;color:#475569;">
          This code expires in <strong>{expire_minutes} minutes</strong> and can only be used once.
        </p>
        <p style="margin:0;font-size:12px;color:#64748b;line-height:1.6;">
          If you did not request this sign-in, you can safely ignore this message. Never share your OTP with anyone.
        </p>
      </td>
    </tr>
    <tr>
      <td style="padding:16px 28px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:12px;color:#64748b;">
        SkillSphere Recruitment Platform · Automated Security Notification
      </td>
    </tr>
  </table>
</body>
</html>"""

    _send_email_via_smtp(to_email, subject, text_body, html_body)


def send_assessment_invitation_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    assessment_title: str,
    test_link: str,
    expires_at: datetime,
    instructions: str,
    duration_minutes: int,
    question_count: int,
) -> None:
    utc_exp = ensure_utc(expires_at)
    expiry_str = utc_exp.strftime("%B %d, %Y at %H:%M UTC") if utc_exp else "See portal"
    safe_name = html.escape(candidate_name or "Candidate")
    safe_job = html.escape(job_title)
    safe_company = html.escape(company_name)
    safe_assessment = html.escape(assessment_title)
    safe_link = html.escape(test_link, quote=True)
    safe_instructions = html.escape(instructions).replace("\n", "<br/>")
    subject = f"SkillSphere Assessment Invitation: {assessment_title} — {job_title} at {company_name}"

    text_body = (
        f"Hello {candidate_name},\n\n"
        f"You have been invited to take the '{assessment_title}' technical assessment for {job_title} at {company_name}.\n\n"
        f"Assessment Details:\n"
        f"- Assessment: {assessment_title}\n"
        f"- Questions: {question_count} MCQs\n"
        f"- Duration: {duration_minutes} minutes\n"
        f"- Expires: {expiry_str}\n\n"
        f"Instructions:\n{instructions}\n\n"
        f"Open your unique assessment link:\n{test_link}\n\n"
        "— SkillSphere Talent Team"
    )

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:24px;background:#f4f6fb;font-family:Arial,Helvetica,sans-serif;color:#18213a;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e2e8f0;">
    <tr>
      <td style="padding:24px 28px;background:linear-gradient(120deg,#4f46e5,#6366f1,#0891b2);color:#ffffff;">
        <div style="font-size:22px;font-weight:800;letter-spacing:-0.4px;">SkillSphere</div>
        <div style="font-size:13px;opacity:0.9;margin-top:4px;">Online Technical Assessment Invitation</div>
      </td>
    </tr>
    <tr>
      <td style="padding:28px;">
        <p style="margin:0 0 14px;font-size:15px;">Hello <strong>{safe_name}</strong>,</p>
        <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#334155;">
          You have been invited by <strong>{safe_company}</strong> to complete the <strong>{safe_assessment}</strong> assessment for the <strong>{safe_job}</strong> position.
        </p>
        <div style="margin:16px 0;padding:16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;font-size:13px;line-height:1.7;color:#334155;">
          <div><strong>Assessment:</strong> {safe_assessment}</div>
          <div><strong>Job Role:</strong> {safe_job} ({safe_company})</div>
          <div><strong>Format:</strong> {question_count} Multiple-Choice Questions</div>
          <div><strong>Duration:</strong> {duration_minutes} minutes once started</div>
          <div><strong>Link Expires:</strong> {html.escape(expiry_str)}</div>
        </div>
        <p style="margin:14px 0 8px;font-size:13px;font-weight:700;color:#18213a;">Instructions</p>
        <p style="margin:0 0 22px;font-size:13px;line-height:1.65;color:#475569;">{safe_instructions}</p>
        <div style="text-align:center;margin:24px 0;">
          <a href="{safe_link}" style="display:inline-block;padding:13px 26px;background:#4f46e5;color:#ffffff;text-decoration:none;font-weight:700;border-radius:10px;font-size:14px;">
            Open Assessment Portal
          </a>
        </div>
        <p style="margin:0;font-size:12px;color:#64748b;word-break:break-all;">
          If the button above does not work, copy and paste this unique link into your browser:<br/>
          <a href="{safe_link}" style="color:#4f46e5;">{safe_link}</a>
        </p>
      </td>
    </tr>
    <tr>
      <td style="padding:16px 28px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:12px;color:#64748b;">
        This invitation link allows one single attempt for your SkillSphere account and expires on {html.escape(expiry_str)}.
      </td>
    </tr>
  </table>
</body>
</html>"""

    _send_email_via_smtp(to_email, subject, text_body, html_body)


_SIMPLE_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_recipient_email(to_email: str | None) -> str:
    """Validate and normalize a recipient email address."""
    cleaned = (to_email or "").strip()
    if not cleaned or not _SIMPLE_EMAIL_RE.match(cleaned):
        raise ValueError("Candidate recipient email address is missing or invalid.")
    return cleaned


def _render_branded_email(
    header_subtitle: str,
    greeting_name: str,
    body_html: str,
    footer_text: str,
) -> str:
    safe_name = html.escape(greeting_name or "Candidate")
    safe_subtitle = html.escape(header_subtitle)
    safe_footer = html.escape(footer_text)
    return f"""<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:24px;background:#f4f6fb;font-family:Arial,Helvetica,sans-serif;color:#18213a;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e2e8f0;">
    <tr>
      <td style="padding:24px 28px;background:linear-gradient(120deg,#4f46e5,#6366f1,#0891b2);color:#ffffff;">
        <div style="font-size:22px;font-weight:800;letter-spacing:-0.4px;">SkillSphere</div>
        <div style="font-size:13px;opacity:0.92;margin-top:4px;">{safe_subtitle}</div>
      </td>
    </tr>
    <tr>
      <td style="padding:28px;">
        <p style="margin:0 0 14px;font-size:15px;">Hello <strong>{safe_name}</strong>,</p>
        {body_html}
      </td>
    </tr>
    <tr>
      <td style="padding:16px 28px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:12px;color:#64748b;">
        {safe_footer}
      </td>
    </tr>
  </table>
</body>
</html>"""


_APPLICATION_EMAIL_CONFIG: dict[str, dict[str, str]] = {
    "application_submitted": {
        "subtitle": "Application Confirmation",
        "subject": "SkillSphere Application Confirmed: {job_title} at {company_name}",
        "lead_text": "Thank you for applying for '{job_title}' at {company_name}. We have successfully received your application.",
        "lead_html": "Thank you for applying for <strong>{job_title}</strong> at <strong>{company_name}</strong>. We have successfully received your application.",
        "badge_label": "Application Submitted",
        "badge_bg": "#eff6ff",
        "badge_fg": "#1d4ed8",
        "cta_label": "View Candidate Dashboard",
        "cta_path": "/candidate",
        "closing_text": "Our recruitment team will review your profile and notify you automatically as your application progresses.",
        "footer": "SkillSphere Recruitment Platform · Application Confirmation",
    },
    "application_under_review": {
        "subtitle": "Application Under Review",
        "subject": "SkillSphere Update: Your application for {job_title} at {company_name} is Under Review",
        "lead_text": "Your application for '{job_title}' at {company_name} is currently under review by the hiring team.",
        "lead_html": "Your application for <strong>{job_title}</strong> at <strong>{company_name}</strong> is now <strong>under review</strong> by our recruitment team.",
        "badge_label": "Under Review",
        "badge_bg": "#f0f9ff",
        "badge_fg": "#0369a1",
        "cta_label": "View Application Status",
        "cta_path": "/candidate",
        "closing_text": "We will share another update as soon as the hiring team completes this review stage.",
        "footer": "SkillSphere Recruitment Platform · Application Status Notification",
    },
    "application_shortlisted": {
        "subtitle": "Application Shortlisted",
        "subject": "SkillSphere Update: Shortlisted for {job_title} at {company_name}",
        "lead_text": "Great news! Your application for '{job_title}' at {company_name} has been shortlisted for the next stage.",
        "lead_html": "Great news! Your application for <strong>{job_title}</strong> at <strong>{company_name}</strong> has been <strong>shortlisted</strong> for further review.",
        "badge_label": "Shortlisted",
        "badge_bg": "#eef2ff",
        "badge_fg": "#3730a3",
        "cta_label": "View Application Status",
        "cta_path": "/candidate",
        "closing_text": "Our recruitment team will reach out with next steps shortly.",
        "footer": "SkillSphere Recruitment Platform · Application Status Notification",
    },
    "application_selected": {
        "subtitle": "Final Selection Confirmation",
        "subject": "Congratulations! Selected for {job_title} at {company_name}",
        "lead_text": "Congratulations! You have been selected for the '{job_title}' position at {company_name}.",
        "lead_html": "Congratulations! We are delighted to inform you that you have been <strong>selected</strong> for the <strong>{job_title}</strong> position at <strong>{company_name}</strong>.",
        "badge_label": "Selected",
        "badge_bg": "#ecfdf5",
        "badge_fg": "#065f46",
        "cta_label": "Open Candidate Dashboard",
        "cta_path": "/candidate",
        "closing_text": "Please review any next steps shared below and sign in to your SkillSphere dashboard for details.",
        "footer": "SkillSphere Recruitment Platform · Selection Notification",
    },
    "application_hired": {
        "subtitle": "Final Hiring Confirmation",
        "subject": "Welcome Aboard! Hired for {job_title} at {company_name}",
        "lead_text": "Congratulations! Your recruitment process for '{job_title}' at {company_name} is complete, and your status is now Hired.",
        "lead_html": "Congratulations! We are thrilled to confirm that you have been <strong>hired</strong> for the <strong>{job_title}</strong> role at <strong>{company_name}</strong>.",
        "badge_label": "Hired",
        "badge_bg": "#ecfdf5",
        "badge_fg": "#065f46",
        "cta_label": "Open Candidate Dashboard",
        "cta_path": "/candidate",
        "closing_text": "Our HR and onboarding team will coordinate with you shortly regarding your start date and onboarding steps.",
        "footer": "SkillSphere Recruitment Platform · Hiring Confirmation",
    },
    "application_rejected": {
        "subtitle": "Application Status Update",
        "subject": "SkillSphere Application Update: {job_title} at {company_name}",
        "lead_text": "Thank you for applying for '{job_title}' at {company_name}. After careful review, we will not be moving forward with your application for this role.",
        "lead_html": "Thank you for taking the time to apply for <strong>{job_title}</strong> at <strong>{company_name}</strong>. After careful consideration, we regret to inform you that we will not be moving forward with your candidacy for this opening.",
        "badge_label": "Not Selected",
        "badge_bg": "#fef2f2",
        "badge_fg": "#991b1b",
        "cta_label": "Explore Other Opportunities",
        "cta_path": "/jobs",
        "closing_text": "We truly appreciate your interest in {company_name} and encourage you to apply for future openings on SkillSphere.",
        "footer": "SkillSphere Recruitment Platform · Candidate Communication",
    },
}


def build_application_status_email(
    notification_type: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    reason: str | None = None,
    note: str | None = None,
    portal_url: str | None = None,
) -> tuple[str, str, str]:
    """Build SkillSphere-branded (subject, text_body, html_body) for shortlist, selection, or rejection."""
    cfg = _APPLICATION_EMAIL_CONFIG.get(notification_type)
    if not cfg:
        raise ValueError(f"Unsupported application notification type: {notification_type}")

    settings = get_settings()
    base_url = (portal_url or settings.frontend_base_url or "http://localhost:5174").rstrip("/")
    action_url = f"{base_url}{cfg['cta_path']}"
    display_name = (candidate_name or "Candidate").strip()
    clean_job = job_title.strip()
    clean_company = company_name.strip()
    clean_reason = (reason or "").strip()
    clean_note = (note or "").strip()

    subject = cfg["subject"].format(job_title=clean_job, company_name=clean_company)
    lead_text = cfg["lead_text"].format(job_title=clean_job, company_name=clean_company)
    closing_text = cfg["closing_text"].format(job_title=clean_job, company_name=clean_company)

    text_lines = [
        f"Hello {display_name},",
        "",
        lead_text,
        "",
        f"Role: {clean_job}",
        f"Company: {clean_company}",
        f"Status: {cfg['badge_label']}",
    ]
    if clean_reason:
        text_lines.append(f"Summary / Reason: {clean_reason}")
    if clean_note:
        text_lines.extend(["", "Recruiter Notes / Next Steps:", clean_note])
    text_lines.extend([
        "",
        closing_text,
        f"Candidate Dashboard: {action_url}",
        "",
        "— SkillSphere Recruitment Team",
    ])
    text_body = "\n".join(text_lines)

    safe_job = html.escape(clean_job)
    safe_company = html.escape(clean_company)
    lead_html = cfg["lead_html"].format(job_title=safe_job, company_name=safe_company)
    details_html = (
        f'<div style="margin:16px 0;padding:16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;font-size:13px;line-height:1.7;color:#334155;">'
        f'<div><strong>Position:</strong> {safe_job}</div>'
        f'<div><strong>Company:</strong> {safe_company}</div>'
        f'<div><strong>Status:</strong> <span style="display:inline-block;padding:2px 8px;border-radius:999px;background:{cfg["badge_bg"]};color:{cfg["badge_fg"]};font-weight:700;">{html.escape(cfg["badge_label"])}</span></div>'
    )
    if clean_reason:
        details_html += f'<div><strong>Summary:</strong> {html.escape(clean_reason)}</div>'
    details_html += "</div>"

    notes_html = ""
    if clean_note:
        formatted_note = html.escape(clean_note).replace("\n", "<br/>")
        notes_html = (
            '<div style="margin:14px 0;padding:14px;background:#f8fafc;border-left:4px solid #4f46e5;border-radius:6px;">'
            '<div style="font-size:12px;font-weight:700;color:#4f46e5;margin-bottom:4px;">Recruiter Notes / Next Steps</div>'
            f'<div style="font-size:13px;line-height:1.6;color:#334155;">{formatted_note}</div>'
            "</div>"
        )

    safe_url = html.escape(action_url, quote=True)
    body_html = (
        f'<p style="margin:0 0 16px;font-size:14px;line-height:1.65;color:#334155;">{lead_html}</p>'
        f"{details_html}"
        f"{notes_html}"
        f'<p style="margin:16px 0 0;font-size:13px;line-height:1.6;color:#475569;">{html.escape(closing_text)}</p>'
        f'<div style="text-align:center;margin:22px 0;">'
        f'<a href="{safe_url}" style="display:inline-block;padding:12px 24px;background:#4f46e5;color:#ffffff;text-decoration:none;font-weight:700;border-radius:10px;font-size:14px;">{html.escape(cfg["cta_label"])}</a>'
        f"</div>"
        f'<p style="margin:12px 0 0;font-size:12px;color:#64748b;">Candidate Dashboard: <a href="{safe_url}" style="color:#4f46e5;">{safe_url}</a></p>'
        f'<p style="margin:16px 0 0;font-size:13px;color:#334155;">— SkillSphere Recruitment Team</p>'
    )
    html_body = _render_branded_email(cfg["subtitle"], display_name, body_html, cfg["footer"])
    return subject, text_body, html_body


_INTERVIEW_EMAIL_CONFIG: dict[str, dict[str, str]] = {
    "interview_scheduled": {
        "subtitle": "Interview Scheduled",
        "subject": "SkillSphere Interview Scheduled: {round_name} for {job_title} at {company_name}",
        "lead_text": "Your {round_name} (Round {round_number}) for '{job_title}' at {company_name} has been scheduled.",
        "lead_html": "Your <strong>{round_name}</strong> (Round {round_number}) for <strong>{job_title}</strong> at <strong>{company_name}</strong> has been scheduled.",
        "footer": "SkillSphere Recruitment Platform · Interview Invitation",
    },
    "interview_rescheduled": {
        "subtitle": "Interview Rescheduled",
        "subject": "SkillSphere Interview Rescheduled: {round_name} for {job_title} at {company_name}",
        "lead_text": "Please note that your {round_name} (Round {round_number}) for '{job_title}' at {company_name} has been rescheduled from the previous schedule to a new date and time.",
        "lead_html": "Please note that your <strong>{round_name}</strong> (Round {round_number}) for <strong>{job_title}</strong> at <strong>{company_name}</strong> has been <strong>rescheduled</strong> from its previous schedule. Updated details are below:",
        "footer": "SkillSphere Recruitment Platform · Updated Interview Schedule",
    },
    "interview_cancelled": {
        "subtitle": "Interview Cancelled",
        "subject": "SkillSphere Interview Cancelled: {round_name} for {job_title} at {company_name}",
        "lead_text": "Your {round_name} (Round {round_number}) for '{job_title}' at {company_name} previously scheduled for {schedule_str} has been cancelled.",
        "lead_html": "Your <strong>{round_name}</strong> (Round {round_number}) for <strong>{job_title}</strong> at <strong>{company_name}</strong> previously scheduled for <strong>{schedule_str}</strong> has been <strong>cancelled</strong>.",
        "footer": "SkillSphere Recruitment Platform · Interview Update",
    },
    "interview_reminder_24h": {
        "subtitle": "Interview Reminder (24 Hours)",
        "subject": "SkillSphere Interview Reminder (24 Hours): {round_name} for {job_title} at {company_name}",
        "lead_text": "This is a friendly reminder that your {round_name} (Round {round_number}) for '{job_title}' at {company_name} is scheduled within the next 24 hours.",
        "lead_html": "This is a friendly reminder that your <strong>{round_name}</strong> (Round {round_number}) for <strong>{job_title}</strong> at <strong>{company_name}</strong> is coming up within the next <strong>24 hours</strong>.",
        "footer": "SkillSphere Recruitment Platform · Automated Interview Reminder",
    },
    "interview_reminder_1h": {
        "subtitle": "Interview Reminder (1 Hour)",
        "subject": "SkillSphere Interview Reminder (1 Hour): {round_name} for {job_title} at {company_name}",
        "lead_text": "Your {round_name} (Round {round_number}) for '{job_title}' at {company_name} is starting soon (within 1 hour).",
        "lead_html": "Your <strong>{round_name}</strong> (Round {round_number}) for <strong>{job_title}</strong> at <strong>{company_name}</strong> is starting soon (within <strong>1 hour</strong>).",
        "footer": "SkillSphere Recruitment Platform · Automated Interview Reminder",
    },
}


_MODE_LABELS = {
    "online": "Online Video Interview",
    "in_person": "In-Person Interview",
    "phone": "Phone Interview",
}


def build_interview_notification_email(
    notification_type: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    round_number: int,
    round_name: str,
    interview_mode: str,
    scheduled_at: datetime,
    duration_minutes: int,
    timezone_name: str = "UTC",
    meeting_link: str | None = None,
    location: str | None = None,
    interviewer_name: str | None = None,
    notes_for_candidate: str | None = None,
    cancellation_reason: str | None = None,
    portal_url: str | None = None,
) -> tuple[str, str, str]:
    """Build SkillSphere-branded (subject, text_body, html_body) for interview lifecycle emails."""
    cfg = _INTERVIEW_EMAIL_CONFIG.get(notification_type)
    if not cfg:
        raise ValueError(f"Unsupported interview notification type: {notification_type}")

    settings = get_settings()
    base_url = (portal_url or settings.frontend_base_url or "http://localhost:5174").rstrip("/")
    dashboard_url = f"{base_url}/candidate"

    display_name = (candidate_name or "Candidate").strip()
    clean_job = job_title.strip()
    clean_company = company_name.strip()
    clean_round = (round_name or f"Round {round_number}").strip()
    tz_label = (timezone_name or "UTC").strip()
    dt_utc = ensure_utc(scheduled_at)
    display_dt = dt_utc
    effective_tz_label = tz_label
    if dt_utc is not None and tz_label and tz_label.upper() != "UTC":
        try:
            display_dt = dt_utc.astimezone(ZoneInfo(tz_label))
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            display_dt = dt_utc
            effective_tz_label = f"{tz_label} / UTC"
    date_str = display_dt.strftime("%B %d, %Y") if display_dt else "See candidate dashboard"
    time_str = display_dt.strftime("%I:%M %p") if display_dt else "See candidate dashboard"
    schedule_str = f"{date_str} at {time_str} ({effective_tz_label})" if display_dt else "See candidate dashboard"
    mode_label = _MODE_LABELS.get((interview_mode or "online").lower(), interview_mode or "Online")
    clean_link = (meeting_link or "").strip()
    clean_location = (location or "").strip()
    clean_interviewer = (interviewer_name or "").strip()
    clean_notes = (notes_for_candidate or "").strip()
    clean_cancel_reason = (cancellation_reason or "").strip()

    fmt_ctx = {
        "job_title": clean_job,
        "company_name": clean_company,
        "round_number": round_number,
        "round_name": clean_round,
        "schedule_str": schedule_str,
    }
    subject = cfg["subject"].format(**fmt_ctx)
    lead_text = cfg["lead_text"].format(**fmt_ctx)

    text_lines = [
        f"Hello {display_name},",
        "",
        lead_text,
        "",
        "Interview Details:",
        f"- Round: Round {round_number} — {clean_round}",
        f"- Role: {clean_job} ({clean_company})",
        f"- Mode: {mode_label}",
        f"- Date: {date_str}",
        f"- Time: {time_str}",
        f"- Timezone: {effective_tz_label}",
        f"- Duration: {duration_minutes} minutes",
    ]
    if clean_interviewer:
        text_lines.append(f"- Interviewer: {clean_interviewer}")
    if notification_type != "interview_cancelled":
        if clean_link:
            text_lines.append(f"- Meeting Link: {clean_link}")
        if clean_location:
            text_lines.append(f"- Location / Venue: {clean_location}")
        if clean_notes:
            text_lines.extend(["", "Preparation / Instructions:", clean_notes])
    elif clean_cancel_reason:
        text_lines.extend(["", f"Reason for Cancellation: {clean_cancel_reason}"])

    text_lines.extend(["", f"Candidate Dashboard: {dashboard_url}", "", "— SkillSphere Recruitment Team"])
    text_body = "\n".join(text_lines)

    lead_html = cfg["lead_html"].format(
        job_title=html.escape(clean_job),
        company_name=html.escape(clean_company),
        round_number=round_number,
        round_name=html.escape(clean_round),
        schedule_str=html.escape(schedule_str),
    )

    detail_rows = [
        f"<div><strong>Round:</strong> Round {round_number} — {html.escape(clean_round)}</div>",
        f"<div><strong>Position:</strong> {html.escape(clean_job)} ({html.escape(clean_company)})</div>",
        f"<div><strong>Mode:</strong> {html.escape(mode_label)}</div>",
        f"<div><strong>Interview Date:</strong> {html.escape(date_str)}</div>",
        f"<div><strong>Interview Time:</strong> {html.escape(time_str)}</div>",
        f"<div><strong>Timezone:</strong> {html.escape(effective_tz_label)}</div>",
        f"<div><strong>Duration:</strong> {int(duration_minutes)} minutes</div>",
    ]
    if clean_interviewer:
        detail_rows.append(f"<div><strong>Interviewer:</strong> {html.escape(clean_interviewer)}</div>")
    if notification_type != "interview_cancelled":
        if clean_link:
            safe_meet = html.escape(clean_link, quote=True)
            detail_rows.append(f'<div><strong>Meeting Link:</strong> <a href="{safe_meet}" style="color:#4f46e5;">{html.escape(clean_link)}</a></div>')
        if clean_location:
            detail_rows.append(f"<div><strong>Location / Venue:</strong> {html.escape(clean_location)}</div>")

    details_html = (
        '<div style="margin:16px 0;padding:16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;font-size:13px;line-height:1.7;color:#334155;">'
        + "".join(detail_rows)
        + "</div>"
    )

    extra_html = ""
    if notification_type != "interview_cancelled" and clean_notes:
        extra_html = (
            '<div style="margin:14px 0;padding:14px;background:#f8fafc;border-left:4px solid #4f46e5;border-radius:6px;">'
            '<div style="font-size:12px;font-weight:700;color:#4f46e5;margin-bottom:4px;">Preparation &amp; Instructions</div>'
            f'<div style="font-size:13px;line-height:1.6;color:#334155;">{html.escape(clean_notes).replace(chr(10), "<br/>")}</div>'
            "</div>"
        )
    elif notification_type == "interview_cancelled" and clean_cancel_reason:
        extra_html = (
            '<div style="margin:14px 0;padding:14px;background:#fef2f2;border-left:4px solid #dc2626;border-radius:6px;">'
            '<div style="font-size:12px;font-weight:700;color:#991b1b;margin-bottom:4px;">Cancellation Note</div>'
            f'<div style="font-size:13px;line-height:1.6;color:#7f1d1d;">{html.escape(clean_cancel_reason).replace(chr(10), "<br/>")}</div>'
            "</div>"
        )

    safe_dash = html.escape(dashboard_url, quote=True)
    body_html = (
        f'<p style="margin:0 0 16px;font-size:14px;line-height:1.65;color:#334155;">{lead_html}</p>'
        f"{details_html}"
        f"{extra_html}"
        '<div style="text-align:center;margin:22px 0;">'
        f'<a href="{safe_dash}" style="display:inline-block;padding:12px 24px;background:#4f46e5;color:#ffffff;text-decoration:none;font-weight:700;border-radius:10px;font-size:14px;">View Candidate Dashboard</a>'
        "</div>"
        f'<p style="margin:12px 0 0;font-size:12px;color:#64748b;">Candidate Dashboard: <a href="{safe_dash}" style="color:#4f46e5;">{safe_dash}</a></p>'
        '<p style="margin:16px 0 0;font-size:13px;color:#334155;">— SkillSphere Recruitment Team</p>'
    )
    html_body = _render_branded_email(cfg["subtitle"], display_name, body_html, cfg["footer"])
    return subject, text_body, html_body


def send_application_status_email(
    to_email: str,
    notification_type: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    reason: str | None = None,
    note: str | None = None,
    portal_url: str | None = None,
) -> None:
    recipient = validate_recipient_email(to_email)
    subject, text_body, html_body = build_application_status_email(
        notification_type,
        candidate_name,
        job_title,
        company_name,
        reason=reason,
        note=note,
        portal_url=portal_url,
    )
    _send_email_via_smtp(recipient, subject, text_body, html_body)


def send_application_shortlisted_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    reason: str | None = None,
    note: str | None = None,
    portal_url: str | None = None,
) -> None:
    send_application_status_email(
        to_email,
        "application_shortlisted",
        candidate_name,
        job_title,
        company_name,
        reason=reason,
        note=note,
        portal_url=portal_url,
    )


def send_application_rejected_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    reason: str | None = None,
    note: str | None = None,
    portal_url: str | None = None,
) -> None:
    send_application_status_email(
        to_email,
        "application_rejected",
        candidate_name,
        job_title,
        company_name,
        reason=reason,
        note=note,
        portal_url=portal_url,
    )


def send_application_selected_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    reason: str | None = None,
    note: str | None = None,
    portal_url: str | None = None,
) -> None:
    send_application_status_email(
        to_email,
        "application_selected",
        candidate_name,
        job_title,
        company_name,
        reason=reason,
        note=note,
        portal_url=portal_url,
    )


def send_interview_notification_email(
    to_email: str,
    notification_type: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    round_number: int,
    round_name: str,
    interview_mode: str,
    scheduled_at: datetime,
    duration_minutes: int,
    timezone_name: str = "UTC",
    meeting_link: str | None = None,
    location: str | None = None,
    interviewer_name: str | None = None,
    notes_for_candidate: str | None = None,
    cancellation_reason: str | None = None,
    portal_url: str | None = None,
) -> None:
    recipient = validate_recipient_email(to_email)
    subject, text_body, html_body = build_interview_notification_email(
        notification_type,
        candidate_name,
        job_title,
        company_name,
        round_number=round_number,
        round_name=round_name,
        interview_mode=interview_mode,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        timezone_name=timezone_name,
        meeting_link=meeting_link,
        location=location,
        interviewer_name=interviewer_name,
        notes_for_candidate=notes_for_candidate,
        cancellation_reason=cancellation_reason,
        portal_url=portal_url,
    )
    _send_email_via_smtp(recipient, subject, text_body, html_body)


def send_interview_scheduled_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    round_number: int,
    round_name: str,
    interview_mode: str,
    scheduled_at: datetime,
    duration_minutes: int,
    timezone_name: str = "UTC",
    meeting_link: str | None = None,
    location: str | None = None,
    interviewer_name: str | None = None,
    notes_for_candidate: str | None = None,
    portal_url: str | None = None,
) -> None:
    send_interview_notification_email(
        to_email,
        "interview_scheduled",
        candidate_name,
        job_title,
        company_name,
        round_number=round_number,
        round_name=round_name,
        interview_mode=interview_mode,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        timezone_name=timezone_name,
        meeting_link=meeting_link,
        location=location,
        interviewer_name=interviewer_name,
        notes_for_candidate=notes_for_candidate,
        portal_url=portal_url,
    )


def send_interview_rescheduled_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    round_number: int,
    round_name: str,
    interview_mode: str,
    scheduled_at: datetime,
    duration_minutes: int,
    timezone_name: str = "UTC",
    meeting_link: str | None = None,
    location: str | None = None,
    interviewer_name: str | None = None,
    notes_for_candidate: str | None = None,
    portal_url: str | None = None
) -> None:
    send_interview_notification_email(
        to_email,
        "interview_rescheduled",
        candidate_name,
        job_title,
        company_name,
        round_number=round_number,
        round_name=round_name,
        interview_mode=interview_mode,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        timezone_name=timezone_name,
        meeting_link=meeting_link,
        location=location,
        interviewer_name=interviewer_name,
        notes_for_candidate=notes_for_candidate,
        portal_url=portal_url,
    )


def send_application_submitted_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    reason: str | None = None,
    note: str | None = None,
    portal_url: str | None = None,
) -> None:
    send_application_status_email(
        to_email,
        "application_submitted",
        candidate_name,
        job_title,
        company_name,
        reason=reason,
        note=note,
        portal_url=portal_url,
    )


def send_application_under_review_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    reason: str | None = None,
    note: str | None = None,
    portal_url: str | None = None,
) -> None:
    send_application_status_email(
        to_email,
        "application_under_review",
        candidate_name,
        job_title,
        company_name,
        reason=reason,
        note=note,
        portal_url=portal_url,
    )


def send_application_hired_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    reason: str | None = None,
    note: str | None = None,
    portal_url: str | None = None,
) -> None:
    send_application_status_email(
        to_email,
        "application_hired",
        candidate_name,
        job_title,
        company_name,
        reason=reason,
        note=note,
        portal_url=portal_url,
    )


def send_interview_cancelled_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    round_number: int,
    round_name: str,
    interview_mode: str,
    scheduled_at: datetime,
    duration_minutes: int,
    timezone_name: str = "UTC",
    interviewer_name: str | None = None,
    cancellation_reason: str | None = None,
    portal_url: str | None = None,
) -> None:
    send_interview_notification_email(
        to_email,
        "interview_cancelled",
        candidate_name,
        job_title,
        company_name,
        round_number=round_number,
        round_name=round_name,
        interview_mode=interview_mode,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        timezone_name=timezone_name,
        interviewer_name=interviewer_name,
        cancellation_reason=cancellation_reason,
        portal_url=portal_url,
    )


def send_interview_reminder_email(
    to_email: str,
    notification_type: str,
    candidate_name: str,
    job_title: str,
    company_name: str,
    *,
    round_number: int,
    round_name: str,
    interview_mode: str,
    scheduled_at: datetime,
    duration_minutes: int,
    timezone_name: str = "UTC",
    meeting_link: str | None = None,
    location: str | None = None,
    interviewer_name: str | None = None,
    notes_for_candidate: str | None = None,
    portal_url: str | None = None,
) -> None:
    if notification_type not in {"interview_reminder_24h", "interview_reminder_1h"}:
        raise ValueError(f"Unsupported interview reminder type: {notification_type}")
    send_interview_notification_email(
        to_email,
        notification_type,
        candidate_name,
        job_title,
        company_name,
        round_number=round_number,
        round_name=round_name,
        interview_mode=interview_mode,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        timezone_name=timezone_name,
        meeting_link=meeting_link,
        location=location,
        interviewer_name=interviewer_name,
        notes_for_candidate=notes_for_candidate,
        portal_url=portal_url,
    )
