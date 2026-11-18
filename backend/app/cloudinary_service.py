"""SkillSphere Cloudinary Integration Service.

Provides secure, authenticated video uploads, signed playback URL generation,
and strict foreign key validation to prevent orphaned recordings.
"""
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import secrets
from typing import BinaryIO, Union

import cloudinary
import cloudinary.api
import cloudinary.uploader
from cloudinary.utils import cloudinary_url, private_download_url
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Application,
    Assessment,
    AssessmentQuestion,
    Candidate,
    Interview,
    utc_now,
)

logger = logging.getLogger("skillsphere.cloudinary")

CLOUDINARY_FOLDER_ROUND1 = "skillsphere/round1"
CLOUDINARY_FOLDER_VIDEO_ASSESSMENTS = "skillsphere/video-assessments"
CLOUDINARY_FOLDER_LIVE_INTERVIEWS = "skillsphere/live-interviews"


def is_cloudinary_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.cloudinary_cloud_name
        and settings.cloudinary_api_key
        and settings.cloudinary_api_secret
    )


def configure_cloudinary() -> None:
    settings = get_settings()
    if not is_cloudinary_configured():
        raise HTTPException(status_code=503, detail="Cloudinary recording storage is not configured.")
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )


def validate_foreign_keys_for_recording(
    db: Session,
    *,
    candidate_id: Union[int, str, None],
    application_id: Union[int, str, None] = None,
    assessment_id: Union[int, str, None] = None,
    interview_id: Union[int, str, None] = None,
    question_id: Union[int, str, None] = None,
) -> tuple[int, int | None, int | None, int | None, int | None]:
    """Strictly validates all candidate, application, assessment, interview, and question IDs.
    
    Prevents foreign key violations (such as frontend passing 'undefined' or null)
    and ensures referenced database records exist before any Cloudinary metadata is saved.
    """
    # 1. Candidate ID validation
    if candidate_id is None or str(candidate_id).strip().lower() in {"undefined", "null", "", "none"}:
        raise HTTPException(
            status_code=400,
            detail="Valid candidate_id is required. Received undefined or null.",
        )
    try:
        clean_candidate_id = int(candidate_id)
        if clean_candidate_id <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid candidate_id: {candidate_id}. Must be a positive integer.",
        )

    candidate = db.get(Candidate, clean_candidate_id)
    if not candidate:
        raise HTTPException(
            status_code=404,
            detail=f"Referenced candidate (ID: {clean_candidate_id}) does not exist.",
        )

    # 2. Application ID validation (if provided)
    clean_app_id = None
    if application_id is not None and str(application_id).strip().lower() not in {"undefined", "null", "", "none"}:
        try:
            clean_app_id = int(application_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"Invalid application_id: {application_id}")
        application = db.get(Application, clean_app_id)
        if not application:
            raise HTTPException(status_code=404, detail=f"Referenced application (ID: {clean_app_id}) not found.")
        if application.candidate_id != clean_candidate_id:
            raise HTTPException(
                status_code=409,
                detail="Application candidate_id does not match the provided candidate_id.",
            )

    # 3. Assessment ID validation (if provided)
    clean_assessment_id = None
    if assessment_id is not None and str(assessment_id).strip().lower() not in {"undefined", "null", "", "none"}:
        try:
            clean_assessment_id = int(assessment_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"Invalid assessment_id: {assessment_id}")
        assessment = db.get(Assessment, clean_assessment_id)
        if not assessment:
            raise HTTPException(status_code=404, detail=f"Referenced assessment (ID: {clean_assessment_id}) not found.")

    # 4. Interview ID validation (if provided)
    clean_interview_id = None
    if interview_id is not None and str(interview_id).strip().lower() not in {"undefined", "null", "", "none"}:
        try:
            clean_interview_id = int(interview_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"Invalid interview_id: {interview_id}")
        interview = db.get(Interview, clean_interview_id)
        if not interview:
            raise HTTPException(status_code=404, detail=f"Referenced interview (ID: {clean_interview_id}) not found.")
        if interview.candidate_id != clean_candidate_id:
            raise HTTPException(
                status_code=409,
                detail="Interview candidate_id does not match the provided candidate_id.",
            )

    # 5. Question ID validation (if provided)
    clean_question_id = None
    if question_id is not None and str(question_id).strip().lower() not in {"undefined", "null", "", "none"}:
        try:
            clean_question_id = int(question_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"Invalid question_id: {question_id}")
        question = db.get(AssessmentQuestion, clean_question_id)
        if not question:
            raise HTTPException(status_code=404, detail=f"Referenced assessment question (ID: {clean_question_id}) not found.")

    return clean_candidate_id, clean_app_id, clean_assessment_id, clean_interview_id, clean_question_id


def upload_video_to_cloudinary(
    file_data_or_path: Union[bytes, str, Path, BinaryIO],
    folder: str,
    public_id: str | None = None,
    resource_type: str = "video",
    authenticated: bool = True,
) -> dict:
    """Uploads video data or a local file to Cloudinary with secure parameters.
    
    Returns dict containing public_id, secure_url, duration, format, bytes, and resource_type.
    """
    configure_cloudinary()
    if not public_id:
        public_id = secrets.token_urlsafe(20)

    upload_params = {
        "resource_type": resource_type,
        "folder": folder,
        "public_id": public_id,
        "overwrite": False,
    }
    if authenticated:
        upload_params["type"] = "authenticated"

    try:
        if isinstance(file_data_or_path, (str, Path)):
            file_path = str(file_data_or_path)
            res = cloudinary.uploader.upload_large(file_path, **upload_params)
        else:
            res = cloudinary.uploader.upload(file_data_or_path, **upload_params)

        secure_url = res.get("secure_url") or res.get("url")
        public_id_result = res.get("public_id")
        duration = res.get("duration")
        if duration is not None:
            duration = int(round(float(duration)))
        video_format = res.get("format") or "mp4"
        file_size = res.get("bytes") or 0

        return {
            "public_id": public_id_result,
            "secure_url": secure_url,
            "duration": duration,
            "format": video_format,
            "bytes": file_size,
            "resource_type": res.get("resource_type", "video"),
        }
    except Exception as exc:
        logger.error(f"Cloudinary upload failed: {exc}", exc_info=False)
        raise HTTPException(
            status_code=502,
            detail=f"Video upload to Cloudinary failed: {str(exc)}",
        ) from exc


def generate_secure_playback_url(
    public_id: str,
    video_format: str | None = None,
    expires_in_seconds: int = 600,
    is_authenticated_asset: bool = True,
) -> str:
    """Generates an expiring, signed playback URL for Cloudinary video assets."""
    configure_cloudinary()
    settings = get_settings()

    fmt = video_format or "mp4"
    if is_authenticated_asset:
        expires_at = int((utc_now() + timedelta(seconds=expires_in_seconds)).timestamp())
        playback_url = private_download_url(
            public_id,
            fmt,
            resource_type="video",
            type="authenticated",
            expires_at=expires_at,
            secure=True,
        )
        return playback_url
    else:
        url, _ = cloudinary_url(
            public_id,
            resource_type="video",
            format=fmt,
            secure=True,
            sign_url=True,
        )
        return url


def delete_cloudinary_video(public_id: str, is_authenticated: bool = True) -> bool:
    """Safely deletes an uploaded asset from Cloudinary (e.g. for rollback on DB error)."""
    try:
        configure_cloudinary()
        kwargs = {"resource_type": "video"}
        if is_authenticated:
            kwargs["type"] = "authenticated"
        res = cloudinary.uploader.destroy(public_id, **kwargs)
        return res.get("result") == "ok"
    except Exception as exc:
        logger.warning(f"Failed to delete Cloudinary asset {public_id}: {exc}")
        return False
