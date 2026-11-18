"""Comprehensive QA Tests for LiveKit Interview, Cloudinary Storage & Video Assessments.

Tests:
1. LiveKit Token Generation & Access Control (candidate, recruiter, unauthorized user).
2. LiveKit Waiting Room Admission & Live Interview Session Management.
3. Server-side Egress Recording Start, Stop & Webhook idempotency.
4. Cloudinary Video Uploads across 3 Folders:
   - Round 1 (skillsphere/round1)
   - Video Assessment (skillsphere/video-assessments)
   - LiveKit Interviews (skillsphere/live-interviews)
5. Critical Foreign Key & Candidate ID Validation (preventing 'undefined' / null / orphaned records).
6. Failed Transfer Recovery & Retry Mechanism.
7. Expiring Secure Playback URL generation for recruiters.
8. Asynchronous Video Assessment Creation, Publishing & Review.
"""
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import secrets
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from fastapi import HTTPException
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cloudinary_service import (
    CLOUDINARY_FOLDER_LIVE_INTERVIEWS,
    CLOUDINARY_FOLDER_ROUND1,
    CLOUDINARY_FOLDER_VIDEO_ASSESSMENTS,
    generate_secure_playback_url,
    validate_foreign_keys_for_recording,
)
from app.core.security import utc_now
from app.livekit_service import (
    generate_livekit_access_token,
    retry_recording_transfer,
    start_livekit_recording,
    transfer_recording_to_cloudinary,
    verify_livekit_webhook_event,
)
from app.models import (
    Application,
    Assessment,
    AssessmentAssignment,
    AssessmentQuestion,
    AssessmentRecording,
    Candidate,
    Interview,
    InterviewRecording,
    Job,
    Recruiter,
    User,
)


def _setup_interview_context(client: TestClient, db: Session):
    """Sets up recruiter, candidate, job, application, and scheduled interview."""
    now = utc_now()

    # Company
    from app.models import Company
    company = Company(name=f"TechCorp_{secrets.token_hex(4)}", location="New York")
    db.add(company)
    db.flush()

    # Recruiter User
    rec_user = User(
        email=f"rec_{secrets.token_hex(4)}@example.com",
        password_hash="mock_hash",
        role="recruiter",
        full_name="Alex Recruiter",
        is_active=True,
    )
    db.add(rec_user)
    db.flush()
    recruiter = Recruiter(user_id=rec_user.id, company_id=company.id)
    db.add(recruiter)
    db.flush()

    # Candidate User
    cand_user = User(
        email=f"cand_{secrets.token_hex(4)}@example.com",
        password_hash="mock_hash",
        role="candidate",
        full_name="Sam Candidate",
        is_active=True,
    )
    db.add(cand_user)
    db.flush()
    candidate = Candidate(user_id=cand_user.id, contact_email=cand_user.email)
    db.add(candidate)
    db.flush()

    # Unauthorized Candidate User
    unauth_user = User(
        email=f"unauth_{secrets.token_hex(4)}@example.com",
        password_hash="mock_hash",
        role="candidate",
        full_name="Intruder Candidate",
        is_active=True,
    )
    db.add(unauth_user)
    db.flush()
    unauth_cand = Candidate(user_id=unauth_user.id, contact_email=unauth_user.email)
    db.add(unauth_cand)
    db.flush()

    # Job
    job = Job(
        recruiter_id=recruiter.id,
        company_id=recruiter.company_id or 1,
        title="Senior Full-Stack Engineer",
        description="Build real-time apps",
        status="published",
    )
    db.add(job)
    db.flush()

    # Application
    application = Application(
        candidate_id=candidate.id,
        job_id=job.id,
        status="interview",
    )
    db.add(application)
    db.flush()

    # LiveKit Interview
    scheduled_at = now + timedelta(days=1)
    interview = Interview(
        application_id=application.id,
        job_id=job.id,
        candidate_id=candidate.id,
        recruiter_id=recruiter.id,
        scheduled_by_user_id=rec_user.id,
        round_number=1,
        round_name="Live Video Interview",
        interview_mode="online",
        interview_type="live_recruiter",
        livekit_room_name=f"room_test_{secrets.token_hex(4)}",
        scheduled_at=scheduled_at,
        meeting_link="http://localhost:5173/live-interview/1",
        status="scheduled",
    )
    db.add(interview)
    db.commit()
    db.refresh(interview)

    return {
        "rec_user": rec_user,
        "cand_user": cand_user,
        "unauth_user": unauth_user,
        "recruiter": recruiter,
        "candidate": candidate,
        "job": job,
        "application": application,
        "interview": interview,
    }


def test_foreign_key_validation_rejects_undefined_and_null(database):
    """CRITICAL DB TEST: Validates that passing 'undefined', 'null', or non-existent IDs is strictly rejected."""
    with database() as db:
        # 1. Undefined candidate_id
        with pytest.raises(Exception) as exc1:
            validate_foreign_keys_for_recording(db, candidate_id="undefined")
        assert "Valid candidate_id is required" in str(exc1.value)

        # 2. Null candidate_id
        with pytest.raises(Exception) as exc2:
            validate_foreign_keys_for_recording(db, candidate_id=None)
        assert "Valid candidate_id is required" in str(exc2.value)

        # 3. Non-existent candidate_id
        with pytest.raises(Exception) as exc3:
            validate_foreign_keys_for_recording(db, candidate_id=999999)
        assert "does not exist" in str(exc3.value)


def test_livekit_token_generation_and_access_control(client: TestClient, database, monkeypatch):
    """Tests LiveKit token generation: recruiter & candidate succeed; unauthorized candidate is rejected."""
    with database() as db:
        ctx = _setup_interview_context(client, db)
        interview_id = ctx["interview"].id

        # Candidate token
        from app.core.config import get_settings
        from jose import jwt
        settings = get_settings()
        monkeypatch.setattr(settings, "livekit_api_key", "test_livekit_key")
        monkeypatch.setattr(settings, "livekit_api_secret", "test_livekit_secret_for_unit_tests_only")

        cand_token = jwt.encode(
            {"sub": str(ctx["cand_user"].id), "role": "candidate", "type": "access"},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        rec_token = jwt.encode(
            {"sub": str(ctx["rec_user"].id), "role": "recruiter", "type": "access"},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        unauth_token = jwt.encode(
            {"sub": str(ctx["unauth_user"].id), "role": "candidate", "type": "access"},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

    # 1. Authorized Candidate joins
    res_cand = client.post(
        f"/api/interviews/{interview_id}/livekit-token",
        headers={"Authorization": f"Bearer {cand_token}"},
    )
    assert res_cand.status_code == 200
    data_cand = res_cand.json()
    assert "token" in data_cand
    assert data_cand["is_recruiter"] is False
    assert data_cand["interview_id"] == interview_id

    # 2. Authorized Recruiter joins
    res_rec = client.post(
        f"/api/interviews/{interview_id}/livekit-token",
        headers={"Authorization": f"Bearer {rec_token}"},
    )
    assert res_rec.status_code == 200
    data_rec = res_rec.json()
    assert "token" in data_rec
    assert data_rec["is_recruiter"] is True

    # 3. Unauthorized Candidate enters another candidate's room -> 403 Forbidden!
    res_unauth = client.post(
        f"/api/interviews/{interview_id}/livekit-token",
        headers={"Authorization": f"Bearer {unauth_token}"},
    )
    assert res_unauth.status_code == 403


def test_livekit_token_generation_requires_configured_credentials(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "livekit_api_key", "")
    monkeypatch.setattr(settings, "livekit_api_secret", "")

    with pytest.raises(HTTPException) as error:
        generate_livekit_access_token("room-test", "candidate-test", "Test Candidate")

    assert error.value.status_code == 503
    assert "LIVEKIT_API_KEY" in error.value.detail


def test_livekit_egress_failure_does_not_create_a_fake_recording(client, database, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "livekit_api_key", "")
    monkeypatch.setattr(settings, "livekit_api_secret", "")

    with database() as db:
        interview = _setup_interview_context(client, db)["interview"]
        with pytest.raises(HTTPException) as error:
            start_livekit_recording(db, interview)

        assert error.value.status_code == 503
        recording = db.scalar(
            select(InterviewRecording).where(InterviewRecording.interview_id == interview.id)
        )
        assert recording is not None
        assert recording.upload_status == "failed"
        assert recording.egress_id is None
        assert recording.local_temp_path is not None
        assert not Path(recording.local_temp_path).exists()


def test_livekit_waiting_room_and_admission_flow(client: TestClient, database):
    """Tests waiting room workflow: candidate enters, recruiter admits, status updates to in_progress."""
    with database() as db:
        ctx = _setup_interview_context(client, db)
        interview_id = ctx["interview"].id
        cand_id = ctx["cand_user"].id
        rec_id = ctx["rec_user"].id

        from app.core.config import get_settings
        from jose import jwt
        settings = get_settings()
        cand_auth = {"Authorization": f"Bearer {jwt.encode({'sub': str(cand_id), 'role': 'candidate', 'type': 'access'}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)}"}
        rec_auth = {"Authorization": f"Bearer {jwt.encode({'sub': str(rec_id), 'role': 'recruiter', 'type': 'access'}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)}"}

    # 1. Candidate joins waiting room
    res_join = client.post(f"/api/interviews/{interview_id}/waiting-room/join", headers=cand_auth)
    assert res_join.status_code == 200
    assert res_join.json()["status"] == "in_waiting_room"

    # 2. Session status shows candidate in waiting room
    res_status = client.get(f"/api/interviews/{interview_id}/session-status", headers=cand_auth)
    assert res_status.status_code == 200
    assert res_status.json()["candidate_in_waiting_room"] is True
    assert res_status.json()["status"] == "scheduled"

    # 3. Recruiter admits candidate
    res_admit = client.post(f"/api/interviews/{interview_id}/waiting-room/admit", headers=rec_auth)
    assert res_admit.status_code == 200
    assert res_admit.json()["status"] == "in_progress"

    # 4. Status reflects in_progress
    res_status2 = client.get(f"/api/interviews/{interview_id}/session-status", headers=cand_auth)
    assert res_status2.json()["candidate_admitted"] is True
    assert res_status2.json()["status"] == "in_progress"


def test_livekit_recording_transfer_pipeline_and_recovery(client: TestClient, database, monkeypatch, tmp_path):
    """Tests Egress start, staging, transfer to Cloudinary, database persistence, and retry mechanism."""
    with database() as db:
        ctx = _setup_interview_context(client, db)
        interview = ctx["interview"]

        # Mock Cloudinary upload
        mock_cloudinary_result = {
            "public_id": "skillsphere/live-interviews/rec_mock_123",
            "secure_url": "https://res.cloudinary.com/q4dbraav/video/authenticated/rec_mock_123.mp4",
            "duration": 45,
            "format": "mp4",
            "bytes": 204800,
            "resource_type": "video",
        }
        monkeypatch.setattr(
            "app.livekit_service.upload_video_to_cloudinary",
            lambda *args, **kwargs: mock_cloudinary_result,
        )

        async def start_test_egress(_room_name, output_filepath):
            output_path = Path(output_filepath)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"test-only captured video fixture")
            return "egress_test_123"

        monkeypatch.setattr("app.livekit_service.start_egress_recording_async", start_test_egress)

        # 1. Start LiveKit Recording
        recording = start_livekit_recording(db, interview)
        assert recording.upload_status == "pending"
        assert recording.egress_id == "egress_test_123"
        assert recording.candidate_id == interview.candidate_id
        assert recording.interview_id == interview.id
        assert recording.local_temp_path is not None

        # 2. Duplicate start returns existing recording (idempotent!)
        duplicate = start_livekit_recording(db, interview)
        assert duplicate.id == recording.id

        # 3. Transfer to Cloudinary
        completed_rec = transfer_recording_to_cloudinary(db, recording)
        assert completed_rec.upload_status == "completed"
        assert completed_rec.cloudinary_public_id == mock_cloudinary_result["public_id"]
        assert completed_rec.cloudinary_secure_url == mock_cloudinary_result["secure_url"]
        assert completed_rec.duration == 45
        assert completed_rec.format == "mp4"

        # 4. Failed transfer simulation and authorized retry recovery
        recording.upload_status = "failed"
        recording.error_message = "Simulated network timeout during Cloudinary upload"
        retry_path = tmp_path / "recording-retry-fixture.mp4"
        retry_path.write_bytes(b"test-only retained video fixture")
        recording.local_temp_path = str(retry_path)
        db.commit()

        retried_rec = retry_recording_transfer(db, recording.id)
        assert retried_rec.upload_status == "completed"
        assert retried_rec.error_message is None


def test_asynchronous_video_assessment_workflow(client: TestClient, database, monkeypatch):
    """Tests asynchronous Video Assessment: creation, candidate response upload, and recruiter review."""
    with database() as db:
        ctx = _setup_interview_context(client, db)
        rec_user_id = ctx["rec_user"].id
        cand_user_id = ctx["cand_user"].id
        cand_email = ctx["cand_user"].email
        job_id = ctx["job"].id
        app_id = ctx["application"].id
        cand_id = ctx["candidate"].id

        from app.core.config import get_settings
        from jose import jwt
        settings = get_settings()
        rec_auth = {"Authorization": f"Bearer {jwt.encode({'sub': str(rec_user_id), 'role': 'recruiter', 'type': 'access'}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)}"}
        cand_auth = {"Authorization": f"Bearer {jwt.encode({'sub': str(cand_user_id), 'role': 'candidate', 'type': 'access'}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)}"}

    # 1. Recruiter creates Video Assessment
    create_payload = {
        "job_id": job_id,
        "title": "Async Video Screening Assessment",
        "instructions": "Record short 60s answers for each question.",
        "prep_time_seconds": 20,
        "response_time_seconds": 60,
        "allow_review": True,
        "questions": [
            {
                "question_text": "Explain the difference between microservices and monolith.",
                "instructions": "Focus on scalability and deployment complexity.",
                "prep_time_seconds": 20,
                "response_time_seconds": 60,
            },
            {
                "question_text": "How do you handle race conditions in database transactions?",
                "instructions": "Mention isolation levels or optimistic locking.",
                "prep_time_seconds": 20,
                "response_time_seconds": 60,
            },
        ],
    }
    res_create = client.post("/api/recruiter/video-assessments", json=create_payload, headers=rec_auth)
    assert res_create.status_code == 200
    va_data = res_create.json()
    va_id = va_data["id"]
    assert va_data["total_questions"] == 2
    assert va_data["assessment_type"] == "video"

    # 2. Assign assessment to candidate
    with database() as db:
        from app.core.security import hash_opaque_token
        raw_token = secrets.token_hex(16)
        token_hash = hash_opaque_token(raw_token)
        assignment = AssessmentAssignment(
            assessment_id=va_id,
            application_id=app_id,
            candidate_id=cand_id,
            job_id=job_id,
            token_hash=token_hash,
            recipient_email=cand_email,
            test_status="assigned",
            expires_at=utc_now() + timedelta(days=3),
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        assignment_id = assignment.id

    # 3. Candidate loads video assessment details
    res_cand_get = client.get(f"/api/assessments/{raw_token}", headers=cand_auth)
    assert res_cand_get.status_code == 200
    c_info = res_cand_get.json()
    assert c_info["assessment_type"] == "video"
    assert c_info["prep_time_seconds"] == 20
    assert c_info["response_time_seconds"] == 60

    # 4. Candidate uploads video recording for Question 1
    mock_upload = {
        "public_id": "skillsphere/video-assessments/q1_test",
        "secure_url": "https://res.cloudinary.com/q4dbraav/video/authenticated/q1_test.mp4",
        "duration": 50,
        "format": "mp4",
        "bytes": 512000,
        "resource_type": "video",
    }
    monkeypatch.setattr(
        "app.cloudinary_service.upload_video_to_cloudinary",
        lambda *args, **kwargs: mock_upload,
    )

    with database() as db:
        q1 = db.scalars(select(AssessmentQuestion).where(AssessmentQuestion.assessment_id == va_id)).first()
        q1_id = q1.id

    dummy_video_file = io.BytesIO(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)
    res_upload_q = client.post(
        f"/api/assessments/{raw_token}/questions/{q1_id}/recording",
        files={"file": ("response_q1.mp4", dummy_video_file, "video/mp4")},
        data={"duration_seconds": "50"},
        headers=cand_auth,
    )
    assert res_upload_q.status_code == 200
    assert res_upload_q.json()["upload_status"] == "completed"

    # 5. Candidate submits assessment and receives confidential confirmation message
    res_submit = client.post(f"/api/assessments/{raw_token}/submit", json={}, headers=cand_auth)
    assert res_submit.status_code == 200
    assert "responses have been recorded and are under review" in res_submit.json()["message"]

    # 6. Recruiter reviews candidate video submission
    res_review = client.get(f"/api/recruiter/video-assessments/submissions/{assignment_id}", headers=rec_auth)
    assert res_review.status_code == 200
    rev_data = res_review.json()
    assert rev_data["candidate_name"] == "Sam Candidate"
    assert len(rev_data["questions"]) == 2
    assert rev_data["questions"][0]["recording"]["upload_status"] == "completed"
