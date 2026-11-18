"""SkillSphere LiveKit Real-Time Video Interview Router.

Provides authenticated endpoints for:
- LiveKit access token generation.
- Waiting room entry and admission.
- Room-composite Egress recording start and stop.
- Ending live interviews.
- LiveKit webhooks with signature verification.
- Cloudinary playback URL generation.
- Failed recording transfer retries.
"""
from datetime import datetime, timezone
import json
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import get_current_user, require_roles
from app.cloudinary_service import (
    generate_secure_playback_url,
    validate_foreign_keys_for_recording,
)
from app.core.config import get_settings
from app.core.security import isoformat_utc, utc_now
from app.database import get_db
from app.livekit_service import (
    generate_livekit_access_token,
    retry_recording_transfer,
    start_livekit_recording,
    stop_livekit_recording,
    transfer_recording_to_cloudinary,
    verify_livekit_webhook_event,
)
from app.models import (
    Application,
    Candidate,
    Interview,
    InterviewRecording,
    Job,
    Recruiter,
    User,
)

logger = logging.getLogger("skillsphere.livekit_router")

livekit_router = APIRouter(tags=["LiveKit Real-Time Interviews"])


def _get_authorized_interview_participant(
    interview_id: int,
    user: User,
    db: Session,
) -> tuple[Interview, bool]:
    """Validates that user is either the candidate or recruiter/admin for this interview.
    
    Returns (interview, is_recruiter).
    """
    interview = db.get(Interview, interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found.")

    is_recruiter = False
    if user.role == "admin":
        is_recruiter = True
    elif user.role == "recruiter":
        recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
        if not recruiter or (interview.job and interview.job.recruiter_id != recruiter.id):
            raise HTTPException(
                status_code=403,
                detail="You are not authorized to access this interview room as recruiter.",
            )
        is_recruiter = True
    elif user.role == "candidate":
        candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
        if not candidate or interview.candidate_id != candidate.id:
            raise HTTPException(
                status_code=403,
                detail="You are not authorized to enter another candidate's interview room.",
            )
    else:
        raise HTTPException(status_code=403, detail="Unauthorized access to interview room.")

    return interview, is_recruiter


def _ensure_interview_room_name(interview: Interview, db: Session) -> str:
    """Ensures interview has a unique LiveKit room name."""
    if not interview.livekit_room_name:
        interview.livekit_room_name = f"skillsphere-interview-{interview.id}-{secrets.token_hex(4)}"
        db.commit()
        db.refresh(interview)
    return interview.livekit_room_name


@livekit_router.post("/api/interviews/{interview_id}/livekit-token")
@livekit_router.post("/api/interviews/{interview_id}/token")
def get_livekit_interview_token(
    interview_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generates an official LiveKit access token for an authorized recruiter or candidate."""
    interview, is_recruiter = _get_authorized_interview_participant(interview_id, user, db)

    if interview.status == "cancelled":
        raise HTTPException(status_code=409, detail="This interview has been cancelled.")

    room_name = _ensure_interview_room_name(interview, db)
    settings = get_settings()

    identity = f"{user.role}_{user.id}_{secrets.token_hex(4)}"
    token = generate_livekit_access_token(
        room_name=room_name,
        identity=identity,
        name=user.full_name or f"User {user.id}",
        is_publisher=True,
        is_admin=is_recruiter,
        can_publish_data=True,
    )

    return {
        "token": token,
        "livekit_url": settings.livekit_url or "http://127.0.0.1:7880",
        "room_name": room_name,
        "interview_id": interview.id,
        "identity": identity,
        "participant_name": user.full_name,
        "is_recruiter": is_recruiter,
        "interview_status": interview.status,
        "is_waiting_room_enabled": interview.is_waiting_room_enabled,
        "candidate_admitted": interview.status == "in_progress" or not interview.is_waiting_room_enabled,
    }


@livekit_router.get("/api/interviews/{interview_id}/session-status")
def get_livekit_session_status(
    interview_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns the current LiveKit session, waiting room, and recording status."""
    interview, is_recruiter = _get_authorized_interview_participant(interview_id, user, db)

    active_recording = db.scalar(
        select(InterviewRecording)
        .where(
            InterviewRecording.interview_id == interview.id,
            InterviewRecording.upload_status.in_(["pending", "starting", "uploading"]),
        )
    )

    has_completed_recording = db.scalar(
        select(InterviewRecording)
        .where(
            InterviewRecording.interview_id == interview.id,
            InterviewRecording.upload_status == "completed",
        )
    ) is not None

    candidate_user = interview.candidate.user if interview.candidate else None
    recruiter_user = interview.recruiter.user if interview.recruiter else None

    return {
        "interview_id": interview.id,
        "status": interview.status,
        "room_name": interview.livekit_room_name,
        "is_waiting_room_enabled": interview.is_waiting_room_enabled,
        "candidate_in_waiting_room": bool(interview.candidate_joined_at and interview.status == "scheduled"),
        "candidate_admitted": interview.status in {"in_progress", "completed"},
        "recording_active": active_recording is not None,
        "has_completed_recording": has_completed_recording,
        "started_at": isoformat_utc(interview.started_at),
        "ended_at": isoformat_utc(interview.ended_at),
        "candidate_name": candidate_user.full_name if candidate_user else "Candidate",
        "recruiter_name": recruiter_user.full_name if recruiter_user else "Recruiter",
        "job_title": interview.job.title if interview.job else None,
    }


@livekit_router.post("/api/interviews/{interview_id}/waiting-room/join")
def join_waiting_room(
    interview_id: int,
    user: User = Depends(require_roles("candidate")),
    db: Session = Depends(get_db),
):
    """Candidate signals they have joined the waiting room after media check."""
    interview, _ = _get_authorized_interview_participant(interview_id, user, db)
    if interview.status == "cancelled":
        raise HTTPException(status_code=409, detail="Interview is cancelled.")

    if not interview.candidate_joined_at:
        interview.candidate_joined_at = utc_now()
        db.commit()

    return {
        "status": "in_waiting_room",
        "interview_status": interview.status,
        "admitted": interview.status == "in_progress",
    }


@livekit_router.post("/api/interviews/{interview_id}/waiting-room/admit")
def admit_candidate_from_waiting_room(
    interview_id: int,
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Recruiter admits candidate from waiting room into the LiveKit interview room."""
    interview, _ = _get_authorized_interview_participant(interview_id, user, db)

    now = utc_now()
    interview.status = "in_progress"
    if not interview.started_at:
        interview.started_at = now
    interview.recruiter_joined_at = now
    db.commit()
    db.refresh(interview)

    # Automatically start room recording on admission
    recording = None
    try:
        recording = start_livekit_recording(db, interview)
    except Exception as exc:
        logger.warning(f"Could not auto-start recording on admission: {exc}")

    return {
        "status": "in_progress",
        "started_at": isoformat_utc(interview.started_at),
        "recording_started": recording is not None,
    }


@livekit_router.post("/api/interviews/{interview_id}/recording/start")
def start_interview_recording_endpoint(
    interview_id: int,
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Recruiter starts LiveKit Egress recording."""
    interview, _ = _get_authorized_interview_participant(interview_id, user, db)
    recording = start_livekit_recording(db, interview)

    return {
        "recording_id": recording.id,
        "egress_id": recording.egress_id,
        "upload_status": recording.upload_status,
        "created_at": isoformat_utc(recording.created_at),
    }


@livekit_router.post("/api/interviews/{interview_id}/recording/stop")
def stop_interview_recording_endpoint(
    interview_id: int,
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Recruiter stops LiveKit recording and triggers Cloudinary transfer."""
    interview, _ = _get_authorized_interview_participant(interview_id, user, db)
    recording = stop_livekit_recording(db, interview)

    if recording:
        # Transfer recording from staging to Cloudinary
        transfer_recording_to_cloudinary(db, recording)

    return {
        "recording_id": recording.id if recording else None,
        "upload_status": recording.upload_status if recording else "none",
        "cloudinary_public_id": recording.cloudinary_public_id if recording else None,
    }


@livekit_router.post("/api/interviews/{interview_id}/end")
def end_interview_endpoint(
    interview_id: int,
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Recruiter ends the interview, stops recording, and transfers media to Cloudinary."""
    interview, _ = _get_authorized_interview_participant(interview_id, user, db)

    now = utc_now()
    interview.status = "completed"
    interview.ended_at = now
    interview.completed_at = now
    db.commit()

    # Stop any active recording and transfer to Cloudinary
    recording = stop_livekit_recording(db, interview)
    if recording:
        transfer_recording_to_cloudinary(db, recording)

    return {
        "status": "completed",
        "ended_at": isoformat_utc(interview.ended_at),
        "recording_transferred": recording.upload_status == "completed" if recording else False,
    }


@livekit_router.post("/api/livekit/webhook")
async def livekit_webhook_endpoint(
    request: Request,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Handles LiveKit webhooks for egress and room events with signature validation."""
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8", errors="replace")

    # Verify signature if authorization header is provided
    event = None
    if authorization:
        try:
            event = verify_livekit_webhook_event(body_str, authorization)
        except Exception as exc:
            logger.warning(f"LiveKit webhook verification failed: {exc}")
            raise HTTPException(status_code=401, detail="Invalid LiveKit webhook signature.")

    # Parse JSON if event wasn't parsed by protobuf
    event_data = {}
    try:
        event_data = json.loads(body_str)
    except Exception:
        pass

    event_type = getattr(event, "event", None) or event_data.get("event")
    egress_info = getattr(event, "egress_info", None) or event_data.get("egressInfo") or event_data.get("egress_info")

    if event_type in {"egress_ended", "egress_updated"} and egress_info:
        egress_id = getattr(egress_info, "egress_id", None) or (egress_info.get("egressId") if isinstance(egress_info, dict) else None)
        status_str = str(getattr(egress_info, "status", None) or (egress_info.get("status") if isinstance(egress_info, dict) else ""))

        if egress_id:
            recording = db.scalar(
                select(InterviewRecording).where(InterviewRecording.egress_id == egress_id)
            )
            if recording and recording.upload_status != "completed":
                if "FAILED" in status_str.upper() or "ABORTED" in status_str.upper():
                    recording.upload_status = "failed"
                    recording.error_message = f"Egress reported failure: {status_str}"
                    db.commit()
                else:
                    # Successful egress, transfer to Cloudinary
                    transfer_recording_to_cloudinary(db, recording)

    elif event_type == "room_finished":
        room = getattr(event, "room", None) or event_data.get("room", {})
        room_name = getattr(room, "name", None) or (room.get("name") if isinstance(room, dict) else None)
        if room_name:
            interview = db.scalar(
                select(Interview).where(Interview.livekit_room_name == room_name)
            )
            if interview and interview.status == "in_progress":
                interview.status = "completed"
                interview.ended_at = utc_now()
                db.commit()

    return {"status": "success"}


@livekit_router.get("/api/recruiter/interviews/{interview_id}/recordings")
def list_interview_recordings(
    interview_id: int,
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Lists recordings for an interview."""
    interview, _ = _get_authorized_interview_participant(interview_id, user, db)

    recordings = db.scalars(
        select(InterviewRecording)
        .where(InterviewRecording.interview_id == interview.id)
        .order_by(InterviewRecording.created_at.desc())
    ).all()

    return [
        {
            "id": r.id,
            "interview_id": r.interview_id,
            "candidate_id": r.candidate_id,
            "candidate_name": interview.candidate.user.full_name if interview.candidate else None,
            "cloudinary_public_id": r.cloudinary_public_id,
            "duration": r.duration,
            "format": r.format,
            "file_size": r.file_size,
            "upload_status": r.upload_status,
            "error_message": r.error_message,
            "created_at": isoformat_utc(r.created_at),
            "uploaded_at": isoformat_utc(r.uploaded_at),
        }
        for r in recordings
    ]


@livekit_router.get("/api/recruiter/interviews/{interview_id}/recordings/{recording_id}/playback")
def get_interview_recording_playback(
    interview_id: int,
    recording_id: int,
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Generates a secure, expiring signed playback URL for recruiter review."""
    interview, _ = _get_authorized_interview_participant(interview_id, user, db)

    recording = db.get(InterviewRecording, recording_id)
    if not recording or recording.interview_id != interview.id:
        raise HTTPException(status_code=404, detail="Recording not found.")

    if recording.upload_status != "completed" or not recording.cloudinary_public_id:
        raise HTTPException(
            status_code=409,
            detail="Recording is not available for playback yet or transfer is pending/failed.",
        )

    playback_url = generate_secure_playback_url(
        public_id=recording.cloudinary_public_id,
        video_format=recording.format or "mp4",
        expires_in_seconds=900,
        is_authenticated_asset=True,
    )

    return {
        "recording_id": recording.id,
        "playback_url": playback_url,
        "duration": recording.duration,
        "format": recording.format,
    }


@livekit_router.post("/api/recruiter/interviews/{interview_id}/recordings/{recording_id}/retry")
def retry_interview_recording_transfer_endpoint(
    interview_id: int,
    recording_id: int,
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Recruiter retries failed transfer of an interview recording to Cloudinary."""
    interview, _ = _get_authorized_interview_participant(interview_id, user, db)

    recording = db.get(InterviewRecording, recording_id)
    if not recording or recording.interview_id != interview.id:
        raise HTTPException(status_code=404, detail="Recording not found.")

    res = retry_recording_transfer(db, recording_id)
    return {
        "recording_id": res.id,
        "upload_status": res.upload_status,
        "cloudinary_public_id": res.cloudinary_public_id,
        "error_message": res.error_message,
    }


@livekit_router.get("/api/recruiter/interviews-failed-transfers")
def list_failed_recording_transfers(
    user: User = Depends(require_roles("recruiter", "admin")),
    db: Session = Depends(get_db),
):
    """Lists all failed interview recording transfers for recruiter review and retry."""
    recruiter = None
    if user.role == "recruiter":
        recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
        if not recruiter:
            return []

    stmt = select(InterviewRecording, Interview, Candidate).join(
        Interview, InterviewRecording.interview_id == Interview.id
    ).join(
        Candidate, InterviewRecording.candidate_id == Candidate.id
    ).where(InterviewRecording.upload_status == "failed")

    if recruiter:
        stmt = stmt.join(Job, Interview.job_id == Job.id).where(Job.recruiter_id == recruiter.id)

    rows = db.execute(stmt).all()
    return [
        {
            "recording_id": rec.id,
            "interview_id": rec.interview_id,
            "candidate_id": rec.candidate_id,
            "candidate_name": cand.user.full_name if cand.user else None,
            "job_title": interview.job.title if interview.job else None,
            "error_message": rec.error_message,
            "created_at": isoformat_utc(rec.created_at),
        }
        for rec, interview, cand in rows
    ]
