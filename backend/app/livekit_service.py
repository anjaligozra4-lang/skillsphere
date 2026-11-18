"""SkillSphere LiveKit Real-Time Communication & Recording Transfer Pipeline.

Handles:
1. LiveKit AccessToken generation with role-based VideoGrants.
2. Server-side Egress room-composite recording start & stop.
3. Webhook signature verification via livekit.api.WebhookReceiver.
4. Temporary storage staging, verification, and automated transfer to Cloudinary.
5. Failed transfer retry and recovery mechanisms.
"""
import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import secrets
from typing import Any, Optional

from fastapi import HTTPException
from livekit.api import (
    AccessToken,
    EncodedFileOutput,
    EncodedFileType,
    LiveKitAPI,
    RoomCompositeEgressRequest,
    StopEgressRequest,
    TokenVerifier,
    VideoGrants,
    WebhookReceiver,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cloudinary_service import (
    CLOUDINARY_FOLDER_LIVE_INTERVIEWS,
    upload_video_to_cloudinary,
    validate_foreign_keys_for_recording,
)
from app.core.config import get_settings
from app.models import (
    Candidate,
    Interview,
    InterviewRecording,
    utc_now,
)

logger = logging.getLogger("skillsphere.livekit")

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
RECORDINGS_STAGING_DIR = UPLOAD_DIR / "recordings_staging"


def _ensure_staging_dir() -> Path:
    settings = get_settings()
    if settings.livekit_egress_staging_dir:
        staging_dir = Path(settings.livekit_egress_staging_dir)
    else:
        staging_dir = RECORDINGS_STAGING_DIR
    staging_dir.mkdir(parents=True, exist_ok=True)
    return staging_dir


def _get_livekit_credentials() -> tuple[str, str, str]:
    settings = get_settings()
    url = settings.livekit_url or "http://127.0.0.1:7880"
    api_key = settings.livekit_api_key.strip()
    api_secret = settings.livekit_api_secret.strip()
    if not api_key or not api_secret:
        raise HTTPException(
            status_code=503,
            detail="LiveKit is not configured. Set LIVEKIT_API_KEY and LIVEKIT_API_SECRET.",
        )
    return url, api_key, api_secret


def generate_livekit_access_token(
    room_name: str,
    identity: str,
    name: str,
    is_publisher: bool = True,
    is_admin: bool = False,
    can_publish_data: bool = True,
) -> str:
    """Generates an official LiveKit JWT access token with authenticated VideoGrants."""
    url, api_key, api_secret = _get_livekit_credentials()

    grants = VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=is_publisher,
        can_subscribe=True,
        can_publish_data=can_publish_data,
        room_admin=is_admin,
    )

    token = (
        AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_grants(grants)
    )
    return token.to_jwt()


def verify_livekit_webhook_event(body: str, auth_token: str) -> Any:
    """Verifies LiveKit webhook request signature using official livekit-api WebhookReceiver."""
    _, api_key, api_secret = _get_livekit_credentials()
    verifier = TokenVerifier(api_key, api_secret)
    receiver = WebhookReceiver(verifier)
    return receiver.receive(body, auth_token)


async def start_egress_recording_async(
    room_name: str,
    output_filepath: str,
) -> str:
    """Calls LiveKit server to start RoomCompositeEgress."""
    url, api_key, api_secret = _get_livekit_credentials()
    client = LiveKitAPI(url=url, api_key=api_key, api_secret=api_secret)
    try:
        req = RoomCompositeEgressRequest(
            room_name=room_name,
            file=EncodedFileOutput(
                filepath=output_filepath,
                file_type=EncodedFileType.MP4,
            ),
        )
        res = await client.egress.start_room_composite_egress(req)
        return res.egress_id
    finally:
        await client.aclose()


def start_livekit_recording(
    db: Session,
    interview: Interview,
) -> InterviewRecording:
    """Initiates an Egress recording for an interview room. Prevents duplicate recording jobs."""
    if not interview.livekit_room_name:
        raise HTTPException(status_code=400, detail="Interview does not have a LiveKit room.")

    # 1. Prevent duplicate active recording jobs
    existing = db.scalar(
        select(InterviewRecording)
        .where(
            InterviewRecording.interview_id == interview.id,
            InterviewRecording.upload_status.in_(["pending", "starting", "uploading"]),
        )
    )
    if existing:
        return existing

    # 2. Validate foreign keys
    clean_candidate_id, _, _, clean_interview_id, _ = validate_foreign_keys_for_recording(
        db,
        candidate_id=interview.candidate_id,
        interview_id=interview.id,
    )

    staging_dir = _ensure_staging_dir()
    unique_suffix = secrets.token_hex(6)
    staging_filename = f"interview_{interview.id}_{unique_suffix}.mp4"
    staging_path = staging_dir / staging_filename

    # 3. Create InterviewRecording database record
    recording = InterviewRecording(
        interview_id=clean_interview_id,
        candidate_id=clean_candidate_id,
        upload_status="pending",
        local_temp_path=str(staging_path),
        created_at=utc_now(),
    )
    db.add(recording)
    db.commit()
    db.refresh(recording)

    # 4. Start real LiveKit Egress. Never substitute a simulated recording on failure.
    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            egress_id = asyncio.run(
                start_egress_recording_async(interview.livekit_room_name, str(staging_path))
            )
        else:
            raise RuntimeError("LiveKit Egress start must run outside an active event loop.")

        recording.egress_id = egress_id
        db.commit()
        db.refresh(recording)
        return recording
    except Exception as exc:
        recording.upload_status = "failed"
        recording.error_message = "LiveKit Egress could not be started. Verify LiveKit and Egress configuration."
        db.commit()
        raise HTTPException(
            status_code=503,
            detail="LiveKit Egress is unavailable. No recording was started.",
        ) from exc


async def stop_egress_recording_async(egress_id: str) -> None:
    """Stops LiveKit Egress recording."""
    url, api_key, api_secret = _get_livekit_credentials()
    client = LiveKitAPI(url=url, api_key=api_key, api_secret=api_secret)
    try:
        await client.egress.stop_egress(StopEgressRequest(egress_id=egress_id))
    finally:
        await client.aclose()


def stop_livekit_recording(
    db: Session,
    interview: Interview,
) -> Optional[InterviewRecording]:
    """Stops the active recording for an interview."""
    recording = db.scalar(
        select(InterviewRecording)
        .where(
            InterviewRecording.interview_id == interview.id,
            InterviewRecording.upload_status.in_(["pending", "starting"]),
        )
        .order_by(InterviewRecording.created_at.desc())
    )
    if not recording:
        return None

    if recording.egress_id:
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                loop.run_until_complete(stop_egress_recording_async(recording.egress_id))
        except Exception as exc:
            logger.warning(f"Error stopping egress: {exc}")

    return recording


def transfer_recording_to_cloudinary(
    db: Session,
    recording: InterviewRecording,
) -> InterviewRecording:
    """Transfers a staged interview recording file to Cloudinary.
    
    Reliable recording-transfer pipeline:
    1. Validates local temporary file exists.
    2. Uploads video to Cloudinary under 'skillsphere/live-interviews/'.
    3. Verifies Cloudinary upload response (public ID, secure URL, format, duration, bytes).
    4. Validates foreign keys before updating database.
    5. Saves metadata and updates status to 'completed'.
    6. Safely deletes temporary recording file after successful transfer.
    7. If transfer fails, retains temporary file and sets status to 'failed'.
    """
    if recording.upload_status == "completed":
        return recording

    # Validate foreign keys before proceeding
    validate_foreign_keys_for_recording(
        db,
        candidate_id=recording.candidate_id,
        interview_id=recording.interview_id,
    )

    temp_path_str = recording.local_temp_path
    if not temp_path_str or not os.path.exists(temp_path_str):
        recording.upload_status = "failed"
        recording.error_message = "Local recording file not found in temporary staging."
        db.commit()
        return recording

    temp_path = Path(temp_path_str)
    recording.upload_status = "uploading"
    db.commit()

    uploaded_public_id = None
    try:
        public_id = f"livekit_{recording.interview_id}_{secrets.token_urlsafe(16)}"
        res = upload_video_to_cloudinary(
            file_data_or_path=temp_path,
            folder=CLOUDINARY_FOLDER_LIVE_INTERVIEWS,
            public_id=public_id,
            resource_type="video",
            authenticated=True,
        )
        uploaded_public_id = res.get("public_id")

        if not uploaded_public_id or not res.get("secure_url"):
            raise RuntimeError("Cloudinary upload did not return a valid public_id or secure_url.")

        recording.cloudinary_public_id = uploaded_public_id
        recording.cloudinary_secure_url = res.get("secure_url")
        recording.duration = res.get("duration") or 0
        recording.format = res.get("format") or "mp4"
        recording.file_size = res.get("bytes") or temp_path.stat().st_size
        recording.upload_status = "completed"
        recording.error_message = None
        recording.uploaded_at = utc_now()

        db.commit()
        db.refresh(recording)

        # Step 10: Delete temporary recording file after verified transfer
        try:
            if temp_path.exists():
                temp_path.unlink()
                recording.local_temp_path = None
                db.commit()
        except Exception as cleanup_err:
            logger.warning(f"Failed to delete temporary file {temp_path}: {cleanup_err}")

        return recording

    except Exception as exc:
        db.rollback()
        recording.upload_status = "failed"
        recording.error_message = str(exc)
        try:
            db.commit()
        except Exception:
            pass
        logger.error(
            f"Failed to transfer interview recording {recording.id} to Cloudinary: {exc}. "
            "Temporary file retained for retry.",
            exc_info=False,
        )
        return recording


def retry_recording_transfer(
    db: Session,
    recording_id: int,
) -> InterviewRecording:
    """Authorized recovery mechanism for failed recording transfers."""
    recording = db.get(InterviewRecording, recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Interview recording not found.")

    if recording.upload_status == "completed":
        return recording

    if not recording.local_temp_path or not os.path.exists(recording.local_temp_path):
        recording.upload_status = "failed"
        recording.error_message = "The original recording file is unavailable; a new recording is required."
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="The original recording file is unavailable. The candidate must record again.",
        )

    return transfer_recording_to_cloudinary(db, recording)
