import json
from datetime import datetime, timedelta, timezone

import pytest
import fitz
import pytesseract
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import Company, Job, Resume, User


@pytest.fixture
def database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield test_session
    engine.dispose()


@pytest.fixture
def client(database):
    def override_get_db():
        db = database()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def register_and_login(client: TestClient, email: str, role: str) -> str:
    registration = client.post("/api/auth/register", json={
        "full_name": f"Test {role.title()}",
        "email": email,
        "password": "StrongPass123",
        "role": role,
    })
    assert registration.status_code == 201

    login = client.post("/api/auth/login", json={
        "email": email,
        "password": "StrongPass123",
    })
    assert login.status_code == 200
    return login.json()["access_token"]


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "SkillSphere"}


def test_candidate_registration_and_login(client: TestClient) -> None:
    token = register_and_login(client, "candidate@example.com", "candidate")

    assert token
    headers = {"Authorization": f"Bearer {token}"}
    identity = client.get("/api/auth/me", headers=headers)
    assert identity.status_code == 200
    assert identity.json() == {
        "id": 1,
        "email": "candidate@example.com",
        "full_name": "Test Candidate",
        "role": "candidate",
    }
    profile = client.get("/api/resumes/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["email"] == "candidate@example.com"
    assert client.get("/api/resumes/profile").status_code == 401
    assert client.get("/api/admin/analytics", headers=headers).status_code == 403


def test_admin_authentication_and_public_signup_restrictions(client: TestClient, database) -> None:
    forbidden_signup = client.post("/api/auth/register", json={
        "full_name": "Public Admin",
        "email": "public-admin@example.com",
        "password": "StrongPass123",
        "role": "admin",
    })
    assert forbidden_signup.status_code == 422

    oversized_password = client.post("/api/auth/register", json={
        "full_name": "Long Password",
        "email": "long-password@example.com",
        "password": "a" * 73,
        "role": "candidate",
    })
    assert oversized_password.status_code == 422

    with database() as db:
        db.add(User(
            email="admin@example.com",
            password_hash=hash_password("StrongPass123"),
            full_name="Platform Admin",
            role="admin",
        ))
        db.commit()

    admin_login = client.post("/api/auth/login", json={
        "email": "Admin@Example.com",
        "password": "StrongPass123",
    })
    assert admin_login.status_code == 200
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    identity = client.get("/api/auth/me", headers=admin_headers)
    assert identity.status_code == 200
    assert identity.json()["role"] == "admin"
    assert identity.json()["full_name"] == "Platform Admin"
    assert client.get("/api/admin/analytics", headers=admin_headers).status_code == 200

    assert client.post("/api/auth/login", json={
        "email": "admin@example.com",
        "password": "incorrect",
    }).status_code == 401


def test_admin_dashboard_counts_and_user_management(client: TestClient, database) -> None:
    candidate_registration = client.post("/api/auth/register", json={
        "full_name": "Dashboard Candidate",
        "email": "dashboard-candidate@example.com",
        "password": "StrongPass123",
        "role": "candidate",
    })
    recruiter_registration = client.post("/api/auth/register", json={
        "full_name": "Dashboard Recruiter",
        "email": "dashboard-recruiter@example.com",
        "password": "StrongPass123",
        "role": "recruiter",
    })
    assert candidate_registration.status_code == recruiter_registration.status_code == 201

    with database() as db:
        db.add(User(
            email="dashboard-admin@example.com",
            password_hash=hash_password("StrongPass123"),
            full_name="Dashboard Admin",
            role="admin",
        ))
        db.commit()

    login = client.post("/api/auth/login", json={
        "email": "dashboard-admin@example.com",
        "password": "StrongPass123",
    })
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    stats = client.get("/api/admin/stats", headers=headers)
    assert stats.status_code == 200
    assert stats.json() == {
        "users": 3,
        "candidates": 1,
        "recruiters": 1,
        "active_users": 3,
        "jobs": 0,
        "active_jobs": 0,
        "pending_jobs": 0,
        "companies": 0,
        "pending_companies": 0,
        "applications": 0,
    }
    trends = client.get("/api/admin/analytics/trends", headers=headers)
    assert trends.status_code == 200
    assert len(trends.json()["registrations"]) == 14
    assert len(trends.json()["applications"]) == 14
    assert sum(day["count"] for day in trends.json()["registrations"]) == 3
    assert sum(day["count"] for day in trends.json()["applications"]) == 0

    users = client.get("/api/admin/users", headers=headers)
    assert users.status_code == 200
    candidate_id = next(
        item["id"] for item in users.json()
        if item["email"] == "dashboard-candidate@example.com"
    )
    disabled = client.patch(
        f"/api/admin/users/{candidate_id}/status",
        params={"is_active": "false"},
        headers=headers,
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert client.post("/api/auth/login", json={
        "email": "dashboard-candidate@example.com",
        "password": "StrongPass123",
    }).status_code == 401

    enabled = client.patch(
        f"/api/admin/users/{candidate_id}/status",
        params={"is_active": "true"},
        headers=headers,
    )
    assert enabled.status_code == 200
    assert enabled.json()["is_active"] is True
    assert client.post("/api/auth/login", json={
        "email": "dashboard-candidate@example.com",
        "password": "StrongPass123",
    }).status_code == 200

    admin_id = next(
        item["id"] for item in users.json()
        if item["email"] == "dashboard-admin@example.com"
    )
    self_disable = client.patch(
        f"/api/admin/users/{admin_id}/status",
        params={"is_active": "false"},
        headers=headers,
    )
    assert self_disable.status_code == 400


def test_job_filters_and_withdrawal(client: TestClient, database) -> None:
    candidate_token = register_and_login(client, "candidate@example.com", "candidate")
    recruiter_token = register_and_login(client, "recruiter@example.com", "recruiter")
    candidate_headers = {"Authorization": f"Bearer {candidate_token}"}
    recruiter_headers = {"Authorization": f"Bearer {recruiter_token}"}
    profile = client.put("/api/candidates/me", json={
        "experience": "3 years building APIs",
        "skills": ["Python"],
    }, headers=candidate_headers)
    assert profile.status_code == 200
    candidate_id = client.get("/api/candidates/me", headers=candidate_headers).json()["id"]

    company = client.post("/api/companies", json={"name": "Example Company"}, headers=recruiter_headers)
    assert company.status_code == 200
    with database() as db:
        company_record = db.scalar(select(Company).where(Company.id == company.json()["id"]))
        company_record.is_approved = True
        db.commit()

    job = client.post("/api/jobs", json={
        "title": "Python Engineer",
        "description": "Need 3 years experience building APIs with Docker",
        "location": "Remote",
        "employment_type": "full_time",
        "experience_min": 2,
        "experience_max": 5,
        "salary_min": 80000,
        "salary_max": 120000,
        "salary_currency": "INR",
        "skills": ["Python", "FastAPI"],
    }, headers=recruiter_headers)
    assert job.status_code == 201
    assert client.post("/api/jobs", json={
        "title": "Forbidden Job",
        "description": "A job submission without an approved profile",
    }, headers=candidate_headers).status_code == 403

    with database() as db:
        job_record = db.scalar(select(Company).where(Company.name == "Example Company")).jobs[0]
        job_record.status = "published"
        db.commit()

    details = client.get(f"/api/jobs/{job.json()['id']}")
    assert details.status_code == 200
    assert details.json()["salary_currency"] == "INR"
    assert details.json()["experience_min"] == 2
    page_results = client.get("/api/jobs", params={
        "q": "Python",
        "experience_min": 3,
        "experience_max": 4,
        "page_size": 1,
    })
    assert page_results.status_code == 200
    assert page_results.json()["total"] == 1
    assert page_results.json()["pages"] == 1

    matching = client.get("/api/jobs", params={
        "q": "FastAPI",
        "location": "remote",
        "employment_type": "full_time",
        "experience": "3 years",
        "skill": "Python",
    })
    assert matching.status_code == 200
    assert [item["id"] for item in matching.json()["items"]] == [job.json()["id"]]
    injection_like_search = client.get("/api/jobs", params={"q": "' OR 1=1 --"})
    assert injection_like_search.status_code == 200
    assert injection_like_search.json()["total"] == 0

    second_job = client.post("/api/recruiters/jobs", json={
        "title": "React Developer",
        "description": "Build modern React client applications",
        "location": "Remote",
        "employment_type": "contract",
        "skills": ["React"],
    }, headers=recruiter_headers)
    assert second_job.status_code == 201
    with database() as db:
        db.get(Job, second_job.json()["id"]).status = "published"
        db.commit()
    oldest_first = client.get("/api/jobs", params={"sort_by": "oldest"})
    assert [item["id"] for item in oldest_first.json()["items"]] == [
        job.json()["id"],
        second_job.json()["id"],
    ]

    with database() as db:
        resume = Resume(
            candidate_id=candidate_id,
            original_filename="resume.pdf",
            stored_filename="resume.pdf",
            file_path="resume.pdf",
            mime_type="application/pdf",
            extracted_text="React",
            page_text=json.dumps(["React"]),
            extracted_data=json.dumps({"skills": ["React", "FastAPI"]}),
            processing_status="processed",
        )
        db.add(resume)
        db.commit()
        resume_id = resume.id

    first_match = client.post(
        f"/api/matches/resume/{resume_id}/job/{job.json()['id']}",
        headers=candidate_headers,
    )
    alias_match = client.post(
        "/api/resumes/analyze",
        json={"resume_id": resume_id, "job_id": job.json()["id"]},
        headers=candidate_headers,
    )
    second_match = client.post(
        f"/api/matches/resume/{resume_id}/job/{second_job.json()['id']}",
        headers=candidate_headers,
    )
    assert first_match.status_code == alias_match.status_code == second_match.status_code == 200
    assert set(first_match.json()["matched_skills"]) == {"Python", "FastAPI"}
    assert first_match.json()["missing_skills"] == ["Docker"]
    history = client.get(f"/api/matches/resume/{resume_id}", headers=candidate_headers)
    assert history.status_code == 200
    assert {item["job_id"] for item in history.json()} == {job.json()["id"], second_job.json()["id"]}

    application = client.post(
        f"/api/jobs/{job.json()['id']}/apply",
        params={"resume_id": resume_id},
        headers=candidate_headers,
    )
    assert application.status_code == 200
    assert client.get("/api/applications", headers=candidate_headers).json()[0]["id"] == application.json()["id"]
    stats = client.get("/api/recruiters/stats", headers=recruiter_headers)
    assert stats.status_code == 200
    assert stats.json() == {
        "jobs": 2,
        "active_jobs": 2,
        "applications": 1,
        "pending_applications": 1,
    }
    duplicate = client.post(
        "/api/applications",
        params={"job_id": job.json()["id"]},
        headers=candidate_headers,
    )
    assert duplicate.status_code == 409

    applicants = client.get(
        f"/api/recruiters/jobs/{job.json()['id']}/applicants",
        params={"skill": "Python", "experience": "3 years"},
        headers=recruiter_headers,
    )
    assert applicants.status_code == 200
    assert applicants.json()[0]["candidate"] == "Test Candidate"
    assert applicants.json()[0]["email"] == "candidate@example.com"
    recruiter_applicants = client.get("/api/recruiter/applicants", headers=recruiter_headers)
    assert recruiter_applicants.status_code == 200
    assert recruiter_applicants.json()[0]["job_id"] == job.json()["id"]
    competing_recruiter = register_and_login(client, "other-recruiter@example.com", "recruiter")
    competing_headers = {"Authorization": f"Bearer {competing_recruiter}"}
    assert client.get(
        f"/api/recruiters/jobs/{job.json()['id']}/applicants",
        headers=competing_headers,
    ).status_code == 404
    assert client.get(
        f"/api/resumes/{resume_id}/download",
        headers=competing_headers,
    ).status_code == 403
    status_update = client.put(
        f"/api/applications/{application.json()['id']}/status",
        json={"status": "under_review"},
        headers=recruiter_headers,
    )
    assert status_update.status_code == 200
    assert status_update.json()["status"] == "under_review"
    closed = client.patch(
        f"/api/recruiters/jobs/{job.json()['id']}/status",
        params={"status_value": "closed"},
        headers=recruiter_headers,
    )
    assert closed.status_code == 200
    reopened = client.patch(
        f"/api/recruiters/jobs/{job.json()['id']}/status",
        params={"status_value": "published"},
        headers=recruiter_headers,
    )
    assert reopened.status_code == 200

    updated_job = client.put(
        f"/api/recruiters/jobs/{job.json()['id']}",
        json={
            "title": "Senior Python Engineer",
            "description": "Need 5 years experience building APIs",
            "location": "Remote",
            "employment_type": "full_time",
            "skills": ["Python", "FastAPI"],
        },
        headers=recruiter_headers,
    )
    assert updated_job.status_code == 200
    assert updated_job.json()["status"] == "pending"

    withdrawn = client.delete(
        f"/api/applications/{application.json()['id']}",
        headers=candidate_headers,
    )
    assert withdrawn.status_code == 200
    assert client.get("/api/applications/me", headers=candidate_headers).json()[0]["status"] == "withdrawn"
    update_withdrawn = client.patch(
        f"/api/recruiters/applications/{application.json()['id']}",
        params={"status_value": "shortlisted"},
        headers=recruiter_headers,
    )
    assert update_withdrawn.status_code == 409
    update_withdrawn_alias = client.put(
        f"/api/applications/{application.json()['id']}/status",
        json={"status": "shortlisted"},
        headers=recruiter_headers,
    )
    assert update_withdrawn_alias.status_code == 409
    with database() as db:
        db.get(Job, job.json()["id"]).status = "published"
        db.commit()
    reapplication = client.post(
        "/api/applications",
        params={"job_id": job.json()["id"], "resume_id": resume_id},
        headers=candidate_headers,
    )
    assert reapplication.status_code == 200
    assert reapplication.json()["id"] == application.json()["id"]
    accepted = client.put(
        f"/api/applications/{application.json()['id']}/status",
        json={"status": "accepted"},
        headers=recruiter_headers,
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert client.get("/api/recruiters/stats", headers=recruiter_headers).json()[
        "pending_applications"
    ] == 0


def test_resume_upload_extracts_and_reviews_page_data(client: TestClient, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.routers.UPLOAD_DIR", tmp_path)
    token = register_and_login(client, "resume-candidate@example.com", "candidate")
    headers = {"Authorization": f"Bearer {token}"}
    document = fitz.open()
    first_page = document.new_page()
    first_page.insert_text(
        (72, 72),
        "Jordan Lee\njordan@example.com\n+1 415 555 0134\n\nEducation:\nBSc Computer Science",
    )
    second_page = document.new_page()
    second_page.insert_text((72, 72), "Experience:\n3 years Python and React")
    data = document.tobytes()
    document.close()

    upload = client.post(
        "/api/resumes/upload",
        files={"file": ("jordan.pdf", data, "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 200
    assert upload.json()["processing_status"] == "processed"
    assert upload.json()["full_name"] == "Jordan Lee"
    assert upload.json()["email"] == "jordan@example.com"
    assert upload.json()["education"] == "BSc Computer Science"
    assert upload.json()["experience"] == "3 years Python and React"
    assert len(upload.json()["page_text"]) == 2

    resumes = client.get("/api/resumes/me", headers=headers)
    assert resumes.status_code == 200
    resume = resumes.json()[0]
    assert resume["processing_status"] == "processed"
    assert len(resume["page_text"]) == 2

    review = client.patch(
        f"/api/resumes/{resume['id']}/review",
        json={
            "full_name": "Jordan Lee",
            "email": "jordan.personal@example.com",
            "phone": "+14155550134",
            "education": "BSc Computer Science",
            "experience": "3 years Python and React",
            "skills": ["Python", "React"],
        },
        headers=headers,
    )
    assert review.status_code == 200
    profile = client.get("/api/candidates/me", headers=headers)
    assert profile.json()["contact_email"] == "jordan.personal@example.com"
    assert profile.json()["skills"] == ["Python", "React"]


def test_resume_upload_reports_invalid_and_unreadable_files(client: TestClient, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.routers.UPLOAD_DIR", tmp_path)
    token = register_and_login(client, "invalid-candidate@example.com", "candidate")
    headers = {"Authorization": f"Bearer {token}"}

    wrong_signature = client.post(
        "/api/resumes/upload",
        files={"file": ("not-a-pdf.pdf", b"not a pdf", "application/pdf")},
        headers=headers,
    )
    assert wrong_signature.status_code == 415
    wrong_extension = client.post(
        "/api/resumes/upload",
        files={"file": ("resume.jpg", b"%PDF-1.7", "application/pdf")},
        headers=headers,
    )
    assert wrong_extension.status_code == 415

    empty_pdf = fitz.open()
    empty_pdf.new_page()
    empty_data = empty_pdf.tobytes()
    empty_pdf.close()
    monkeypatch.setattr("app.routers.extract_resume_pages", lambda path, mime_type: [""])
    unreadable = client.post(
        "/api/resumes/upload",
        files={"file": ("empty.pdf", empty_data, "application/pdf")},
        headers=headers,
    )
    assert unreadable.status_code == 422
    stored = client.get("/api/resumes/me", headers=headers).json()[0]
    assert stored["processing_status"] == "failed"
    assert "No readable text" in stored["processing_error"]

    oversized = client.post(
        "/api/resumes/upload",
        files={"file": ("large.pdf", b"%PDF-" + b"0" * (10 * 1024 * 1024), "application/pdf")},
        headers=headers,
    )
    assert oversized.status_code == 413


def test_candidate_cannot_access_another_candidates_resume(client: TestClient, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.routers.UPLOAD_DIR", tmp_path)
    owner_token = register_and_login(client, "owner@example.com", "candidate")
    other_token = register_and_login(client, "other@example.com", "candidate")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Sam Owner\nsam@example.com\nPython")
    data = document.tobytes()
    document.close()

    upload = client.post(
        "/api/resumes/upload",
        files={"file": ("owner.pdf", data, "application/pdf")},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert upload.status_code == 200
    resume_id = upload.json()["id"]

    other_headers = {"Authorization": f"Bearer {other_token}"}
    assert client.get("/api/resumes/me", headers=other_headers).json() == []
    assert client.get(
        f"/api/resumes/{resume_id}/download",
        headers=other_headers,
    ).status_code == 403
    assert client.patch(
        f"/api/resumes/{resume_id}/review",
        json={"full_name": "Changed Name"},
        headers=other_headers,
    ).status_code == 404


def test_authentication_rejects_invalid_and_expired_tokens(client: TestClient) -> None:
    settings = get_settings()
    expired_token = jwt.encode(
        {
            "sub": "1",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    assert client.get("/api/resumes/profile").status_code == 401
    assert client.get(
        "/api/resumes/profile",
        headers={"Authorization": "Bearer not-a-valid-token"},
    ).status_code == 401
    assert client.get(
        "/api/resumes/profile",
        headers={"Authorization": f"Bearer {expired_token}"},
    ).status_code == 401


def test_invalid_form_data_is_rejected(client: TestClient) -> None:
    token = register_and_login(client, "validation-candidate@example.com", "candidate")
    response = client.put(
        "/api/candidates/me",
        json={"contact_email": "not-an-email"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


def test_resume_upload_handles_empty_corrupt_and_unavailable_ocr(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("app.routers.UPLOAD_DIR", tmp_path)
    token = register_and_login(client, "failure-candidate@example.com", "candidate")
    headers = {"Authorization": f"Bearer {token}"}

    empty_upload = client.post(
        "/api/resumes/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
        headers=headers,
    )
    assert empty_upload.status_code == 422
    assert empty_upload.json()["detail"] == "The selected resume is empty"

    corrupt_upload = client.post(
        "/api/resumes/upload",
        files={"file": ("corrupt.pdf", b"%PDF-1.7\nnot a valid PDF document", "application/pdf")},
        headers=headers,
    )
    assert corrupt_upload.status_code == 422
    assert "corrupted or could not be processed" in corrupt_upload.json()["detail"]

    document = fitz.open()
    document.new_page().insert_text((72, 72), "A readable resume")
    data = document.tobytes()
    document.close()

    def unavailable_ocr(path, mime_type):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr("app.routers.extract_resume_pages", unavailable_ocr)
    ocr_failure = client.post(
        "/api/resumes/upload",
        files={"file": ("resume.pdf", data, "application/pdf")},
        headers=headers,
    )

    assert ocr_failure.status_code == 503
    assert "Tesseract OCR is not installed" in ocr_failure.json()["detail"]
    stored_resumes = client.get("/api/resumes/me", headers=headers).json()
    assert stored_resumes[0]["processing_status"] == "failed"
    assert "Tesseract OCR is not installed" in stored_resumes[0]["processing_error"]
