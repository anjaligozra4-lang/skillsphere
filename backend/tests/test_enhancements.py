from datetime import timedelta
import io
import json
import re
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import hash_opaque_token, hash_password, utc_now
from app.models import (
    Application,
    AssessmentAssignment,
    AssessmentRecording,
    AssessmentResult,
    Company,
    Job,
    LoginOtpChallenge,
    ResumeAnalysis,
    Recruiter,
    User,
)
from tests.conftest import login_with_otp, register_and_login


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        for text in paragraphs
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>')
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


def _extract_test_token(email_text: str) -> str:
    match = re.search(r"/assessment/([A-Za-z0-9_-]+)", email_text)
    assert match is not None, "Expected an assessment invitation link in test email."
    return match.group(1)


def _setup_approved_job(
    client: TestClient,
    database,
    smtp_outbox: list[dict],
    recruiter_email: str = "recruiter@example.com",
    title: str = "Python Developer",
    skills: list[str] | None = None,
) -> tuple[dict, int]:
    token = register_and_login(client, recruiter_email, "recruiter", smtp_outbox)
    headers = {"Authorization": f"Bearer {token}"}
    company_res = client.post("/api/companies", json={"name": f"TechCo-{recruiter_email}"}, headers=headers)
    assert company_res.status_code == 200
    with database() as db:
        comp = db.get(Company, company_res.json()["id"])
        comp.is_approved = True
        db.commit()

    job_res = client.post(
        "/api/jobs",
        json={
            "title": title,
            "description": "Build scalable Python and FastAPI backend services with SQL and MySQL databases and REST APIs.",
            "location": "Remote",
            "employment_type": "full_time",
            "experience_min": 0,
            "experience_max": 3,
            "skills": skills or ["Python", "FastAPI", "SQL", "MySQL", "REST API"],
        },
        headers=headers,
    )
    assert job_res.status_code == 201
    job_id = job_res.json()["id"]
    with database() as db:
        db.get(Job, job_id).status = "published"
        db.commit()
    return headers, job_id


def _create_admin_headers(client: TestClient, database, smtp_outbox, email: str = "qb-admin@example.com") -> dict:
    with database() as db:
        if not db.scalar(select(User).where(User.email == email)):
            db.add(User(
                email=email,
                password_hash=hash_password("StrongPass123"),
                full_name="Platform Admin",
                role="admin",
            ))
            db.commit()
    session = login_with_otp(client, smtp_outbox, email, "StrongPass123")
    return {"Authorization": f"Bearer {session['access_token']}"}


def test_latest_login_otp_replaces_prior_challenge_and_accepts_trimmed_code(
    client: TestClient, database, smtp_outbox
) -> None:
    email = "latest-otp@example.com"
    registered = client.post("/api/auth/register", json={
        "full_name": "Latest OTP Candidate",
        "email": f"  {email.upper()}  ",
        "password": "StrongPass123",
        "role": "candidate",
    })
    assert registered.status_code == 201
    assert registered.json()["email"] == email
    assert "otp_required" not in registered.json()

    for login_email in (email, email.upper()):
        response = client.post("/api/auth/login", json={
            "email": login_email,
            "password": "StrongPass123",
        })
        assert response.status_code == 200
        body = response.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["role"] == "candidate"
        assert "challenge_token" not in body
        identity = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {body['access_token']}"
        })
        assert identity.status_code == 200
        assert identity.json()["email"] == email


def test_admin_approved_job_is_visible_only_to_owning_recruiter(
    client: TestClient, database, smtp_outbox
) -> None:
    owner_email = "approved-job-owner@example.com"
    other_email = "approved-job-other@example.com"
    owner_token = register_and_login(client, owner_email, "recruiter", smtp_outbox)
    other_token = register_and_login(client, other_email, "recruiter", smtp_outbox)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}

    company_response = client.post(
        "/api/companies", json={"name": "Approved Job Owner Co"}, headers=owner_headers
    )
    assert company_response.status_code == 200
    with database() as db:
        company = db.get(Company, company_response.json()["id"])
        company.is_approved = True
        owner = db.scalar(select(Recruiter).where(Recruiter.user_id == db.scalar(
            select(User.id).where(User.email == owner_email)
        )))
        owner_recruiter_id = owner.id
        owner_company_id = owner.company_id
        db.commit()

    job_response = client.post("/api/recruiters/jobs", json={
        "title": "Approved Visibility Regression Job",
        "description": "A regression job used to verify recruiter visibility and admin approval.",
        "location": "Remote",
        "employment_type": "full_time",
        "skills": ["Python"],
    }, headers=owner_headers)
    assert job_response.status_code == 201
    job_id = job_response.json()["id"]
    pending_assessment = client.post("/api/recruiter/assessments", json={
        "job_id": job_id,
        "title": "Pending Job Assessment",
        "instructions": "This should wait for admin approval.",
        "duration_minutes": 30,
        "passing_marks": 0,
        "question_ids": [],
        "status": "draft",
    }, headers=owner_headers)
    assert pending_assessment.status_code == 409

    assert client.get(
        "/api/recruiter/question-bank", params={"job_id": job_id}, headers=owner_headers
    ).status_code == 409
    admin_headers = _create_admin_headers(
        client, database, smtp_outbox, email="approved-job-admin@example.com"
    )
    approval = client.patch(
        f"/api/admin/jobs/{job_id}/status",
        params={"status_value": "published"},
        headers=admin_headers,
    )
    assert approval.status_code == 200
    assert approval.json() == {"id": job_id, "status": "published"}

    with database() as db:
        approved_job = db.get(Job, job_id)
        assert approved_job.recruiter_id == owner_recruiter_id
        assert approved_job.company_id == owner_company_id
        assert approved_job.status == "published"

    owner_jobs = client.get("/api/recruiters/jobs", headers=owner_headers)
    owner_stats = client.get("/api/recruiters/stats", headers=owner_headers)
    owner_company = client.get("/api/companies/me", headers=owner_headers)
    assert owner_jobs.status_code == owner_stats.status_code == 200
    assert owner_company.status_code == 200
    assert owner_company.json()["id"] == owner_company_id
    assert owner_company.json()["is_approved"] is True
    assert [item["id"] for item in owner_jobs.json()] == [job_id]
    assert owner_jobs.json()[0]["status"] == "published"
    assert owner_stats.json() == {
        "jobs": 1,
        "active_jobs": 1,
        "applications": 0,
        "pending_applications": 0,
    }

    other_jobs = client.get("/api/recruiters/jobs", headers=other_headers)
    other_stats = client.get("/api/recruiters/stats", headers=other_headers)
    assert other_jobs.status_code == other_stats.status_code == 200
    assert client.get("/api/companies/me", headers=other_headers).status_code == 404
    assert other_jobs.json() == []
    assert other_stats.json() == {
        "jobs": 0,
        "active_jobs": 0,
        "applications": 0,
        "pending_applications": 0,
    }
    assert client.get(
        f"/api/recruiters/jobs/{job_id}/applicants", headers=other_headers
    ).status_code == 404


def test_otp_login_security_cooldown_lockout_expiry_and_refresh(
    client: TestClient, database, smtp_outbox, monkeypatch
) -> None:
    reg = client.post("/api/auth/register", json={
        "full_name": "Anjali Gozra",
        "email": "anjaligozra4@gmail.com",
        "password": "StrongPass123",
        "role": "candidate",
    })
    assert reg.status_code == 201

    bad1 = client.post("/api/auth/login", json={
        "email": "unknown@example.com", "password": "StrongPass123"
    })
    bad2 = client.post("/api/auth/login", json={
        "email": "anjaligozra4@gmail.com", "password": "WrongPassword"
    })
    assert bad1.status_code == bad2.status_code == 401
    assert bad1.json()["detail"] == bad2.json()["detail"]

    login = client.post("/api/auth/login", json={
        "email": "anjaligozra4@gmail.com", "password": "StrongPass123"
    })
    assert login.status_code == 200
    tokens = login.json()
    assert tokens["access_token"] and tokens["refresh_token"]
    assert "otp_required" not in tokens
    assert "challenge_token" not in tokens

    assert client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {tokens['access_token']}"
    }).status_code == 200
    assert client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {tokens['refresh_token']}"
    }).status_code == 401

    refreshed = client.post("/api/auth/refresh", json={
        "refresh_token": tokens["refresh_token"]
    })
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert new_tokens["access_token"] and new_tokens["refresh_token"]
    assert client.post("/api/auth/refresh", json={
        "refresh_token": tokens["refresh_token"]
    }).status_code == 401

    assert client.post("/api/auth/logout", json={
        "refresh_token": new_tokens["refresh_token"]
    }).status_code == 200
    assert client.post("/api/auth/refresh", json={
        "refresh_token": new_tokens["refresh_token"]
    }).status_code == 401

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "")
    direct_login = client.post("/api/auth/login", json={
        "email": "anjaligozra4@gmail.com", "password": "StrongPass123"
    })
    assert direct_login.status_code == 200
    assert direct_login.json()["access_token"]
    assert direct_login.json()["refresh_token"]


def test_placeholder_sanitization_docx_upload_and_resume_download_security(
    client: TestClient, tmp_path, monkeypatch, smtp_outbox, database
) -> None:
    monkeypatch.setattr("app.routers.UPLOAD_DIR", tmp_path)
    cand_token = register_and_login(client, "docx-cand@example.com", "candidate", smtp_outbox)
    cand_headers = {"Authorization": f"Bearer {cand_token}"}

    update = client.put("/api/candidates/me", json={
        "education": "[Degree / Diploma / 12th] â€” [College / School Name], [City]\n[Year of completion] | [Percentage / CGPA]",
        "experience": "1 year building Python FastAPI APIs",
        "projects": "SkillSphere Recruitment Portal",
        "certifications": "AWS Cloud Practitioner",
        "skills": ["Python", "FastAPI"],
    }, headers=cand_headers)
    assert update.status_code == 200
    profile = client.get("/api/candidates/me", headers=cand_headers).json()
    assert profile["education"] is None
    assert profile["projects"] == "SkillSphere Recruitment Portal"

    docx_bytes = _make_docx_bytes([
        "Asha Verma",
        "asha.verma@example.com",
        "Education",
        "B.Tech Computer Science, Chandigarh University",
        "Experience",
        "2 years Python and FastAPI Backend Developer",
        "Projects",
        "SkillSphere ATS Platform using FastAPI and React",
        "Certifications",
        "Python Backend Specialist",
        "Skills: Python, FastAPI, SQL, MySQL, React",
    ])
    upload = client.post(
        "/api/resumes/upload",
        files={"file": ("asha_resume.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        headers=cand_headers,
    )
    assert upload.status_code == 200
    resume_id = upload.json()["id"]

    rec_headers, job_id = _setup_approved_job(client, database, smtp_outbox)
    apply_res = client.post(f"/api/jobs/{job_id}/apply", params={"resume_id": resume_id}, headers=cand_headers)
    assert apply_res.status_code == 200

    download_res = client.get(f"/api/resumes/{resume_id}/download", headers=rec_headers)
    assert download_res.status_code == 200
    assert download_res.content == docx_bytes

    for p in tmp_path.glob("*.docx"):
        p.unlink()
    missing_res = client.get(f"/api/resumes/{resume_id}/download", headers=rec_headers)
    assert missing_res.status_code == 404


def test_ai_matching_70_rule_keeps_assessments_separate_and_manual(
    client: TestClient, database, smtp_outbox, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("app.routers.UPLOAD_DIR", tmp_path)
    rec_headers, job_id = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="sep-rec@example.com",
        title="Python Developer",
        skills=["Python", "FastAPI", "SQL", "MySQL", "REST API"],
    )

    strong_token = register_and_login(client, "sep-strong@example.com", "candidate", smtp_outbox)
    strong_headers = {"Authorization": f"Bearer {strong_token}"}
    client.put("/api/candidates/me", json={
        "headline": "Python & FastAPI Backend Developer",
        "education": "B.Tech Computer Science",
        "experience": "2 years building Python, FastAPI, SQL, MySQL REST APIs",
        "projects": "Backend API Service",
        "certifications": "Python Certified",
        "skills": ["Python", "FastAPI", "SQL", "MySQL", "REST API"],
    }, headers=strong_headers)

    smtp_outbox.clear()
    apply_res = client.post(f"/api/jobs/{job_id}/apply", headers=strong_headers)
    assert apply_res.status_code == 200
    data = apply_res.json()
    assert data["match_score"] >= 70.0
    assert data["status"] == "shortlisted"
    assert data["shortlist_source"] == "automatic"
    # Reaching 70% MUST NOT automatically assign an assessment or send test emails
    assert len(smtp_outbox) == 0
    with database() as db:
        assert len(db.scalars(select(AssessmentAssignment).where(AssessmentAssignment.application_id == data["id"])).all()) == 0
        assert len(db.scalars(select(ResumeAnalysis).where(ResumeAnalysis.application_id == data["id"])).all()) == 1

    # Recruiter manual status decision is preserved across AI match refreshes
    manual_reject = client.put(f"/api/applications/{data['id']}/status", json={"status": "rejected"}, headers=rec_headers)
    assert manual_reject.status_code == 200
    refresh = client.post(f"/api/recruiter/applicants/{data['id']}/match", headers=rec_headers)
    assert refresh.status_code == 200
    assert refresh.json()["status"] == "rejected"


def test_complete_centralized_question_bank_and_assessment_end_to_end_workflow(
    client: TestClient, database, smtp_outbox
) -> None:
    admin_headers = _create_admin_headers(client, database, smtp_outbox)
    rec_headers, job_id = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="e2e-rec@example.com",
        title="Python Backend Developer",
        skills=["Python", "FastAPI", "SQL"],
    )

    # 1. Admin creates MCQ questions in Centralized Question Bank; Round 1 rejects non-MCQ
    non_mcq = client.post("/api/admin/question-bank", json={
        "question_type": "short_answer",
        "skill": "Python",
        "category": "Backend",
        "difficulty": "Easy",
        "question_text": "Explain Python generators.",
        "options": ["A", "B", "C", "D"],
        "correct_option_index": 0,
        "marks": 2,
    }, headers=admin_headers)
    assert non_mcq.status_code == 422

    created_qids = []
    questions_payload = [
        ("Python", "Backend", "Easy", "What does Python's `with` statement manage?", ["Context manager cleanup", "Loop unrolling", "Type casting", "Thread spawning"], 0, 4),
        ("FastAPI", "Backend", "Medium", "Which library validates FastAPI request bodies?", ["Pydantic", "Flask-SQL", "Jinja2", "Click"], 0, 4),
        ("SQL", "Database", "Hard", "Which SQL clause filters groups after GROUP BY?", ["HAVING", "WHERE", "LIMIT", "DISTINCT"], 0, 4),
    ]
    for skill, cat, diff, text, opts, ans_idx, marks in questions_payload:
        res = client.post("/api/admin/question-bank", json={
            "question_type": "mcq",
            "skill": skill,
            "category": cat,
            "difficulty": diff,
            "question_text": text,
            "options": opts,
            "correct_option_index": ans_idx,
            "marks": marks,
        }, headers=admin_headers)
        assert res.status_code == 201
        created_qids.append(res.json()["id"])

    # Admin edit & delete check
    temp_q = client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "React",
        "category": "Frontend",
        "difficulty": "Easy",
        "question_text": "Temporary question to edit and delete?",
        "options": ["One", "Two", "Three", "Four"],
        "correct_option_index": 1,
        "marks": 1,
    }, headers=admin_headers)
    assert temp_q.status_code == 201
    temp_id = temp_q.json()["id"]
    upd_q = client.put(f"/api/admin/question-bank/{temp_id}", json={
        "question_type": "mcq",
        "skill": "React",
        "category": "Frontend",
        "difficulty": "Medium",
        "question_text": "Updated temporary React question?",
        "options": ["One", "Two", "Three", "Four"],
        "correct_option_index": 2,
        "marks": 2,
    }, headers=admin_headers)
    assert upd_q.status_code == 200
    assert upd_q.json()["difficulty"] == "Medium"
    assert client.delete(f"/api/admin/question-bank/{temp_id}", headers=admin_headers).status_code == 200

    # Recruiter & Candidate CANNOT modify Question Bank
    assert client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "Python",
        "category": "Backend",
        "difficulty": "Easy",
        "question_text": "Unauthorized question",
        "options": ["A", "B", "C", "D"],
        "correct_option_index": 0,
        "marks": 1,
    }, headers=rec_headers).status_code == 403

    # 2. Recruiter browses Question Bank filtered by job skills
    browse = client.get("/api/recruiter/question-bank", params={"job_id": job_id, "match_job_skills": True}, headers=rec_headers)
    assert browse.status_code == 200
    assert browse.json()["total"] == 3

    # 3. Recruiter creates Draft assessment (total_marks = 12, passing_marks = 8 -> strict > 8 requires > 8 marks!)
    draft = client.post("/api/recruiter/assessments", json={
        "job_id": job_id,
        "title": "Round 1 Python Technical Screening",
        "description": "Core backend screening",
        "instructions": "Answer all 3 MCQs within 20 minutes.",
        "duration_minutes": 20,
        "passing_marks": 8,
        "expires_at": (utc_now() + timedelta(days=5)).isoformat(),
        "question_ids": created_qids,
        "status": "draft",
    }, headers=rec_headers)
    assert draft.status_code == 201
    assessment_id = draft.json()["id"]
    assert draft.json()["total_questions"] == 3
    assert draft.json()["total_marks"] == 12

    # Recruiter reorders questions & publishes
    reordered = [created_qids[2], created_qids[0], created_qids[1]]
    pub = client.put(f"/api/recruiter/assessments/{assessment_id}", json={
        "job_id": job_id,
        "title": "Round 1 Python Technical Screening",
        "description": "Core backend screening",
        "instructions": "Answer all 3 MCQs within 20 minutes.",
        "duration_minutes": 20,
        "passing_marks": 8,
        "expires_at": (utc_now() + timedelta(days=5)).isoformat(),
        "question_ids": reordered,
        "status": "published",
    }, headers=rec_headers)
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"
    assert pub.json()["questions"][0]["skill"] == "SQL"

    # 4. Register 3 candidates:
    # - Cand A (strong >=70% -> auto-shortlisted)
    # - Cand B (strong >=70% -> auto-shortlisted)
    # - Cand C (weak <70% -> remains applied, cannot be assigned assessment!)
    cand_a_token = register_and_login(client, "cand-a@example.com", "candidate", smtp_outbox)
    cand_b_token = register_and_login(client, "cand-b@example.com", "candidate", smtp_outbox)
    cand_c_token = register_and_login(client, "cand-c@example.com", "candidate", smtp_outbox)
    cand_a_headers = {"Authorization": f"Bearer {cand_a_token}"}
    cand_b_headers = {"Authorization": f"Bearer {cand_b_token}"}
    cand_c_headers = {"Authorization": f"Bearer {cand_c_token}"}

    for hdr in (cand_a_headers, cand_b_headers):
        client.put("/api/candidates/me", json={
            "education": "B.Tech CS",
            "experience": "2 years Python FastAPI SQL MySQL REST API",
            "projects": "FastAPI Platform",
            "certifications": "Python Pro",
            "skills": ["Python", "FastAPI", "SQL", "MySQL", "REST API"],
        }, headers=hdr)
    client.put("/api/candidates/me", json={"skills": ["Communication"], "experience": "Fresher"}, headers=cand_c_headers)

    app_a = client.post(f"/api/jobs/{job_id}/apply", headers=cand_a_headers).json()
    app_b = client.post(f"/api/jobs/{job_id}/apply", headers=cand_b_headers).json()
    app_c = client.post(f"/api/jobs/{job_id}/apply", headers=cand_c_headers).json()
    assert app_a["status"] == "shortlisted"
    assert app_b["status"] == "shortlisted"
    assert app_c["status"] == "applied"

    # Non-shortlisted candidate cannot be assigned
    assert client.post(
        f"/api/recruiter/assessments/{assessment_id}/assign",
        json={"application_ids": [app_c["id"]]},
        headers=rec_headers,
    ).status_code == 409

    # 5. Recruiter manually selects Cand A & Cand B and assigns the published assessment
    smtp_outbox.clear()
    assign_res = client.post(
        f"/api/recruiter/assessments/{assessment_id}/assign",
        json={"application_ids": [app_a["id"], app_b["id"]]},
        headers=rec_headers,
    )
    assert assign_res.status_code == 200
    assert assign_res.json()["assigned_count"] == 2
    assert assign_res.json()["sent_count"] == 2
    assert len(smtp_outbox) == 2

    token_a = _extract_test_token(next(m["text"] for m in smtp_outbox if m["to"] == "cand-a@example.com"))
    token_b = _extract_test_token(next(m["text"] for m in smtp_outbox if m["to"] == "cand-b@example.com"))
    assert token_a != token_b

    # Cand B cannot access Cand A's link
    assert client.get(f"/api/assessments/{token_a}", headers=cand_b_headers).status_code == 403
    assert client.post(f"/api/assessments/{token_a}/start", headers=cand_b_headers).status_code == 403

    # 6. Cand A opens link, starts test, saves & changes answer, refreshes, and scores 12/12 (> 8 -> PASS!)
    verify_a = client.get(f"/api/assessments/{token_a}", headers=cand_a_headers)
    assert verify_a.status_code == 200
    for hidden_field in ("total_marks", "passing_marks", "obtained_marks", "is_passed", "result_status"):
        assert hidden_field not in verify_a.json()

    start_a = client.post(f"/api/assessments/{token_a}/start", headers=cand_a_headers)
    assert start_a.status_code == 200
    qs_a = start_a.json()["questions"]
    assert len(qs_a) == 3
    for q in qs_a:
        assert "correct_option_index" not in q
        assert "explanation" not in q
        assert "marks" not in q
    for hidden_field in ("total_marks", "passing_marks", "obtained_marks", "is_passed", "result_status"):
        assert hidden_field not in start_a.json()

    # Save wrong answer first, then change it to correct answer (0) before submission
    assert client.put(f"/api/assessments/{token_a}/answer", json={"question_id": qs_a[0]["id"], "selected_option_index": 2}, headers=cand_a_headers).status_code == 200
    assert client.put(f"/api/assessments/{token_a}/answer", json={"question_id": qs_a[0]["id"], "selected_option_index": 0}, headers=cand_a_headers).status_code == 200

    # Refresh simulation preserves updated answer
    resumed_a = client.post(f"/api/assessments/{token_a}/start", headers=cand_a_headers)
    assert resumed_a.json()["questions"][0]["selected_option_index"] == 0

    submit_a = client.post(
        f"/api/assessments/{token_a}/submit",
        json={"answers": {str(q["id"]): 0 for q in qs_a}},
        headers=cand_a_headers,
    )
    assert submit_a.status_code == 200
    res_a = submit_a.json()
    # Candidate receives confirmation only; assessment results remain recruiter-only.
    for hidden_field in ("obtained_marks", "total_marks", "passing_marks", "is_passed", "result_message", "reveal_correct_answers", "questions"):
        assert hidden_field not in res_a
    assert "message" in res_a

    # Cannot retake or resubmit
    assert client.post(f"/api/assessments/{token_a}/start", headers=cand_a_headers).status_code == 409
    assert client.post(f"/api/assessments/{token_a}/submit", json={}, headers=cand_a_headers).status_code == 409

    # 7. Cand B scores EXACTLY passing_marks (8/12: 2 correct * 4 marks = 8).
    # Under Sir's strict > rule (8 > 8 is False), Cand B MUST NOT qualify!
    start_b = client.post(f"/api/assessments/{token_b}/start", headers=cand_b_headers).json()
    qs_b = start_b["questions"]
    submit_b = client.post(
        f"/api/assessments/{token_b}/submit",
        json={"answers": {
            str(qs_b[0]["id"]): 0,
            str(qs_b[1]["id"]): 0,
            str(qs_b[2]["id"]): 1,  # wrong
        }},
        headers=cand_b_headers,
    )
    assert submit_b.status_code == 200
    res_b = submit_b.json()
    # Candidate B also receives no marks, pass/fail status, or selection decision.
    for hidden_field in ("obtained_marks", "total_marks", "passing_marks", "is_passed", "result_message", "reveal_correct_answers", "questions"):
        assert hidden_field not in res_b
    assert "message" in res_b

    # 8. Even when Admin enables answer review, candidate must not see marks or answer breakdown.
    policy_response = client.put("/api/admin/assessment-policy", json={"reveal_correct_answers_to_candidate": True}, headers=admin_headers)
    assert policy_response.status_code == 200
    assert policy_response.json()["reveal_correct_answers_to_candidate"] is False
    after_policy = client.get(f"/api/assessments/{token_a}", headers=cand_a_headers).json()
    for hidden_field in ("obtained_marks", "total_marks", "passing_marks", "is_passed", "result_message", "reveal_correct_answers", "questions"):
        assert hidden_field not in after_policy["result"]

    # 9. Recruiter views all results in Assessment Results Dashboard and inspects Cand B's answers
    all_results = client.get("/api/recruiter/assessment-results", headers=rec_headers).json()
    assert len(all_results) == 2
    row_b = next(r for r in all_results if r["candidate_email"] == "cand-b@example.com")
    assert row_b["obtained_marks"] == 8
    assert row_b["is_passed"] is False
    assert row_b["result_status"] == "Not qualified"

    detail_b = client.get(f"/api/recruiter/assessment-results/{row_b['assignment_id']}", headers=rec_headers).json()
    assert len(detail_b["questions"]) == 3
    assert detail_b["questions"][2]["selected_option_index"] == 1
    assert detail_b["questions"][2]["is_correct"] is False


def test_recruiter_ai_question_generation_validates_and_saves_reviewable_questions(
    client: TestClient, database, smtp_outbox, monkeypatch
) -> None:
    rec_headers, job_id = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="ai-question-rec@example.com",
        title="Python API Engineer",
        skills=["Python", "FastAPI"],
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "ai_api_key", "test-provider-key")
    monkeypatch.setattr(settings, "ai_model", "test-model")

    generated = {
        "questions": [
            {
                "skill": "Python",
                "question_text": "Which Python type stores key and value pairs?",
                "options": ["dict", "list", "tuple", "set"],
                "correct_option_index": 0,
                "explanation": "A dict maps keys to values.",
            },
            {
                "skill": "FastAPI",
                "question_text": "Which parameter declaration describes a request body?",
                "options": ["Body", "Header", "Cookie", "Path"],
                "correct_option_index": 0,
                "explanation": "Body marks values parsed from the request body.",
            },
        ]
    }

    class FakeProviderResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"output_text": json.dumps(generated)}

    def fake_provider_post(url, *, headers, json: dict, timeout):
        assert url == "https://api.openai.com/v1/responses"
        assert headers["Authorization"] == "Bearer test-provider-key"
        assert json["model"] == "test-model"
        assert timeout == 60.0
        return FakeProviderResponse()

    monkeypatch.setattr("app.assessment_router.httpx.post", fake_provider_post)
    response = client.post(
        "/api/recruiter/question-bank/generate",
        json={
            "job_id": job_id,
            "skills": ["Python", "FastAPI"],
            "difficulty": "Medium",
            "question_count": 2,
            "marks": 3,
        },
        headers=rec_headers,
    )
    assert response.status_code == 201
    assert response.json()["provider"] == "openai"
    assert len(response.json()["items"]) == 2
    assert {item["skill"] for item in response.json()["items"]} == {"Python", "FastAPI"}
    assert all(item["difficulty"] == "Medium" and item["marks"] == 3 for item in response.json()["items"])
    assert "test-provider-key" not in response.text

    wrong_skill = client.post(
        "/api/recruiter/question-bank/generate",
        json={
            "job_id": job_id,
            "skills": ["Go"],
            "difficulty": "Medium",
            "question_count": 2,
        },
        headers=rec_headers,
    )
    assert wrong_skill.status_code == 422

    reviewed = client.get(
        "/api/recruiter/question-bank",
        params={"job_id": job_id, "skill": "FastAPI"},
        headers=rec_headers,
    )
    assert reviewed.status_code == 200
    assert any("request body" in item["question_text"] for item in reviewed.json()["items"])
    generated_item = response.json()["items"][0]
    edit_payload = {
        "question_type": "mcq",
        "skill": generated_item["skill"],
        "category": generated_item["category"],
        "difficulty": generated_item["difficulty"],
        "question_text": "Which Python collection stores unique values?",
        "options": ["set", "list", "tuple", "dict"],
        "correct_option_index": 0,
        "marks": 4,
        "explanation": "A set stores unique values.",
        "is_active": True,
    }
    edited = client.put(
        f"/api/recruiter/question-bank/{generated_item['id']}",
        json=edit_payload,
        headers=rec_headers,
    )
    assert edited.status_code == 200
    assert edited.json()["question_text"] == edit_payload["question_text"]
    assert edited.json()["correct_option_index"] == 0
    assert edited.json()["marks"] == 4
    assert edited.json()["is_editable"] is True

    other_token = register_and_login(client, "other-question-editor@example.com", "recruiter", smtp_outbox)
    other_edit = client.put(
        f"/api/recruiter/question-bank/{generated_item['id']}",
        json=edit_payload,
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert other_edit.status_code == 404


def test_candidate_proctoring_recording_upload_and_secure_recruiter_playback(
    client: TestClient, database, smtp_outbox, monkeypatch
) -> None:
    recruiter_headers, job_id = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="recording-owner@example.com",
        title="Recording Test Engineer",
        skills=["Python"],
    )
    admin_headers = _create_admin_headers(
        client, database, smtp_outbox, email="recording-admin@example.com"
    )
    question = client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "Python",
        "category": "Backend",
        "difficulty": "Easy",
        "question_text": "Which type stores key-value pairs?",
        "options": ["dict", "list", "set", "tuple"],
        "correct_option_index": 0,
        "marks": 2,
    }, headers=admin_headers)
    assert question.status_code == 201

    assessment = client.post("/api/recruiter/assessments", json={
        "job_id": job_id,
        "title": "Recording Workflow Assessment",
        "instructions": "Complete the question and submit your response.",
        "duration_minutes": 30,
        "passing_marks": 1,
        "question_ids": [question.json()["id"]],
        "status": "published",
    }, headers=recruiter_headers)
    assert assessment.status_code == 201

    candidate_email = "recording-candidate@example.com"
    candidate_token = register_and_login(client, candidate_email, "candidate", smtp_outbox)
    candidate_headers = {"Authorization": f"Bearer {candidate_token}"}
    application = client.post(f"/api/jobs/{job_id}/apply", headers=candidate_headers)
    assert application.status_code == 200
    with database() as db:
        db.get(Application, application.json()["id"]).status = "shortlisted"
        db.commit()

    assignment_response = client.post(
        f"/api/recruiter/assessments/{assessment.json()['id']}/assign",
        json={"application_ids": [application.json()["id"]]},
        headers=recruiter_headers,
    )
    assert assignment_response.status_code == 200
    invite_token = _extract_test_token(next(
        message["text"] for message in smtp_outbox
        if message["to"] == candidate_email and "/assessment/" in message["text"]
    ))

    started = client.post(f"/api/assessments/{invite_token}/start", headers=candidate_headers)
    assert started.status_code == 200
    assert "correct_option_index" not in started.json()["questions"][0]
    event = client.post(
        f"/api/assessments/{invite_token}/proctoring-events",
        json={"event_type": "tab_switch", "details": {"warning_count": 1}},
        headers=candidate_headers,
    )
    assert event.status_code == 200
    with database() as db:
        assignment = db.scalar(select(AssessmentAssignment).where(
            AssessmentAssignment.token_hash == hash_opaque_token(invite_token)
        ))
        assert assignment.test_status == "started"

    settings = get_settings()
    monkeypatch.setattr(settings, "cloudinary_cloud_name", "test-cloud")
    monkeypatch.setattr(settings, "cloudinary_api_key", "test-key")
    monkeypatch.setattr(settings, "cloudinary_api_secret", "test-secret")
    upload_calls = []

    def fake_upload(data, **kwargs):
        upload_calls.append((data, kwargs))
        return {
            "public_id": "skillsphere-test/recording-1",
            "secure_url": "https://media.example.test/private-video",
            "format": "webm",
            "bytes": len(data),
        }

    monkeypatch.setattr("app.assessment_router.cloudinary_upload", fake_upload)
    uploaded = client.post(
        f"/api/assessments/{invite_token}/recording",
        data={"consent_given": "true", "duration_seconds": "8"},
        files={"file": ("recording.webm", b"synthetic test video", "video/webm")},
        headers=candidate_headers,
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["status"] == "uploaded"
    assert upload_calls[0][1]["resource_type"] == "video"
    assert upload_calls[0][1]["type"] == "authenticated"

    monkeypatch.setattr("app.assessment_router.cloudinary.config", lambda **kwargs: None)
    monkeypatch.setattr(
        "app.assessment_router.private_download_url",
        lambda *args, **kwargs: "https://media.example.test/short-lived-signed-playback",
    )
    playback = client.get(
        f"/api/recruiter/assessment-recordings/{uploaded.json()['recording_id']}/playback",
        headers=recruiter_headers,
    )
    assert playback.status_code == 200
    assert playback.json()["playback_url"].startswith("https://media.example.test/")

    listed_events = client.get("/api/recruiter/proctoring-events", headers=recruiter_headers)
    assert listed_events.status_code == 200
    assert listed_events.json()["total"] == 1
    assert listed_events.json()["items"][0]["event_type"] == "tab_switch"

    other_token = register_and_login(client, "recording-other@example.com", "recruiter", smtp_outbox)
    other_headers = {"Authorization": f"Bearer {other_token}"}
    assert client.get(
        f"/api/recruiter/assessment-recordings/{uploaded.json()['recording_id']}/playback",
        headers=other_headers,
    ).status_code == 404
    assert client.get("/api/recruiter/proctoring-events", headers=other_headers).json()["total"] == 0

    def failed_upload(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("app.assessment_router.cloudinary_upload", failed_upload)
    failed = client.post(
        f"/api/assessments/{invite_token}/recording",
        data={"consent_given": "true", "duration_seconds": "1"},
        files={"file": ("recording.webm", b"second synthetic clip", "video/webm")},
        headers=candidate_headers,
    )
    assert failed.status_code == 502
    with database() as db:
        assert db.scalar(select(func.count(AssessmentRecording.id))) == 1


def test_expired_assignment_timeout_auto_submit_and_smtp_failure_handling(
    client: TestClient, database, smtp_outbox, monkeypatch
) -> None:
    admin_headers = _create_admin_headers(client, database, smtp_outbox, email="timeout-admin@example.com")
    rec_headers, job_id = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="timeout-rec@example.com",
        title="Backend Engineer",
        skills=["Python"],
    )

    q_res = client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "Python",
        "category": "Backend",
        "difficulty": "Easy",
        "question_text": "What is len([1, 2, 3])?",
        "options": ["3", "2", "1", "0"],
        "correct_option_index": 0,
        "marks": 5,
    }, headers=admin_headers).json()

    assmt = client.post("/api/recruiter/assessments", json={
        "job_id": job_id,
        "title": "Quick Python Quiz",
        "instructions": "Complete within 10 minutes.",
        "duration_minutes": 10,
        "passing_marks": 2,
        "question_ids": [q_res["id"]],
        "status": "published",
    }, headers=rec_headers).json()

    cand_token = register_and_login(client, "timeout-cand@example.com", "candidate", smtp_outbox)
    cand_headers = {"Authorization": f"Bearer {cand_token}"}
    client.put("/api/candidates/me", json={
        "education": "B.Tech",
        "experience": "2 years Python FastAPI SQL MySQL REST API",
        "projects": "API Service",
        "certifications": "Python",
        "skills": ["Python", "FastAPI", "SQL", "MySQL", "REST API"],
    }, headers=cand_headers)
    app_data = client.post(f"/api/jobs/{job_id}/apply", headers=cand_headers).json()

    # Break SMTP before manual assignment -> honestly records invitation_status = "failed"
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "")
    assign_fail = client.post(
        f"/api/recruiter/assessments/{assmt['id']}/assign",
        json={"application_ids": [app_data["id"]]},
        headers=rec_headers,
    )
    assert assign_fail.status_code == 200
    assert assign_fail.json()["failed_count"] == 1
    assignment_id = assign_fail.json()["results"][0]["assignment_id"]
    assert assign_fail.json()["results"][0]["invitation_status"] == "failed"

    # Resend fails cleanly while SMTP unconfigured
    assert client.post(f"/api/recruiter/assignments/{assignment_id}/resend", headers=rec_headers).status_code == 503

    # Restore SMTP -> resend succeeds
    monkeypatch.setattr(settings, "smtp_host", "smtp.test.local")
    smtp_outbox.clear()
    resend_ok = client.post(f"/api/recruiter/assignments/{assignment_id}/resend", headers=rec_headers)
    assert resend_ok.status_code == 200
    assert resend_ok.json()["invitation_status"] == "sent"
    token = _extract_test_token(smtp_outbox[-1]["text"])

    # Start test, save answer, then expire deadline_at -> verify auto-submit evaluates saved answer
    start_data = client.post(f"/api/assessments/{token}/start", headers=cand_headers).json()
    qid = start_data["questions"][0]["id"]
    assert client.put(f"/api/assessments/{token}/answer", json={"question_id": qid, "selected_option_index": 0}, headers=cand_headers).status_code == 200

    with database() as db:
        assign_row = db.get(AssessmentAssignment, assignment_id)
        assign_row.deadline_at = utc_now() - timedelta(minutes=2)
        db.commit()

    # Checking status triggers automatic backend evaluation on timeout
    after_timeout = client.get(f"/api/assessments/{token}", headers=cand_headers).json()
    assert after_timeout["test_status"] == "submitted"
    assert set(after_timeout) == {"test_status", "result"}
    assert set(after_timeout["result"]) == {"message"}
    for hidden_field in ("obtained_marks", "total_marks", "passing_marks", "is_passed", "result_message", "questions"):
        assert hidden_field not in after_timeout["result"]
    assert "message" in after_timeout["result"]


def test_applicant_status_history_filters_sorting_and_admin_system_status(
    client: TestClient, database, smtp_outbox
) -> None:
    rec_headers, job_id = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="ats-rec@example.com",
        title="React Frontend Engineer",
        skills=["React", "JavaScript", "HTML", "CSS"],
    )

    c1_token = register_and_login(client, "alice@example.com", "candidate", smtp_outbox)
    c2_token = register_and_login(client, "bob@example.com", "candidate", smtp_outbox)
    c1_headers = {"Authorization": f"Bearer {c1_token}"}
    c2_headers = {"Authorization": f"Bearer {c2_token}"}

    client.put("/api/candidates/me", json={"skills": ["React", "JavaScript"], "experience": "1 year React"}, headers=c1_headers)
    client.put("/api/candidates/me", json={"skills": ["Python"], "experience": "Fresher"}, headers=c2_headers)

    a1 = client.post(f"/api/jobs/{job_id}/apply", headers=c1_headers).json()["id"]
    a2 = client.post(f"/api/jobs/{job_id}/apply", headers=c2_headers).json()["id"]

    for next_status in ["under_review", "screening", "shortlisted", "interview", "selected", "accepted", "hired"]:
        upd = client.put(f"/api/applications/{a1}/status", json={"status": next_status}, headers=rec_headers)
        assert upd.status_code == 200
        assert upd.json()["status"] == next_status

    assert client.put(f"/api/applications/{a1}/status", json={"status": "not_a_real_status"}, headers=rec_headers).status_code == 422

    detail = client.get(f"/api/recruiter/applicants/{a1}", headers=rec_headers).json()
    assert len(detail["status_history"]) >= 7
    assert detail["status_history"][0]["new_status"] == "hired"

    by_email = client.get("/api/recruiter/applicants", params={"q": "bob@example.com"}, headers=rec_headers).json()
    assert [item["id"] for item in by_email] == [a2]
    sorted_match = client.get(f"/api/recruiters/jobs/{job_id}/applicants", params={"sort_by": "match_desc"}, headers=rec_headers).json()
    assert sorted_match[0]["id"] == a1

    admin_headers = _create_admin_headers(client, database, smtp_outbox, email="sysadmin@example.com")
    sys_status = client.get("/api/admin/system-status", headers=admin_headers)
    assert sys_status.status_code == 200
    assert sys_status.json()["smtp_configured"] is True
    assert sys_status.json()["auto_shortlist_threshold"] == 70.0


def test_settings_resolves_backend_env_across_cwds_and_reloads_on_env_change(
    client: TestClient, database, smtp_outbox, tmp_path, monkeypatch
) -> None:
    from app.core import config as config_mod
    from app.email_service import (
        is_smtp_configured,
        missing_smtp_variables,
        smtp_configuration_instructions,
    )

    isolated_cwd = tmp_path / "outside_cwd"
    isolated_cwd.mkdir()
    fake_backend_env = tmp_path / "backend.env"
    fake_backend_env.write_text(
        "SMTP_HOST=\nSMTP_PORT=587\nSMTP_USERNAME=\nSMTP_PASSWORD=\nSMTP_FROM_EMAIL=\n",
        encoding="utf-8",
    )

    # Create an active candidate whose login triggers SMTP configuration check
    register_and_login(client, "envreload@example.com", "candidate", smtp_outbox)

    monkeypatch.chdir(isolated_cwd)
    monkeypatch.setattr(config_mod, "BACKEND_ENV_FILE", fake_backend_env)
    get_settings.cache_clear()
    try:
        initial_settings = get_settings()
        initial_secret = initial_settings.jwt_secret_key
        assert is_smtp_configured() is False
        assert missing_smtp_variables() == [
            "SMTP_HOST",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_FROM_EMAIL",
        ]
        assert (
            "Email delivery is not configured (missing: SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL)"
            in smtp_configuration_instructions()
        )

        direct_login = client.post(
            "/api/auth/login",
            json={"email": "envreload@example.com", "password": "StrongPass123"},
        )
        assert direct_login.status_code == 200
        assert direct_login.json()["access_token"]
        assert direct_login.json()["refresh_token"]
        assert "otp_required" not in direct_login.json()

        # Simulate updating backend/.env on disk after server boot without restarting the process
        fake_backend_env.write_text(
            "SMTP_HOST=smtp.example.test\n"
            "SMTP_PORT=587\n"
            "SMTP_USERNAME=test-user@example.test\n"
            "SMTP_PASSWORD=test-app-secret\n"
            "SMTP_FROM_EMAIL=noreply@example.test\n"
            "SMTP_FROM_NAME=SkillSphere\n",
            encoding="utf-8",
        )

        reloaded_settings = get_settings()
        assert reloaded_settings is not initial_settings
        assert reloaded_settings.jwt_secret_key == initial_secret
        assert is_smtp_configured() is True
        assert missing_smtp_variables() == []

        smtp_outbox.clear()
        ok_login = client.post(
            "/api/auth/login",
            json={"email": "envreload@example.com", "password": "StrongPass123"},
        )
        assert ok_login.status_code == 200
        assert ok_login.json()["access_token"]
        assert ok_login.json()["refresh_token"]
        assert "otp_required" not in ok_login.json()
        assert len(smtp_outbox) == 0
    finally:
        get_settings.cache_clear()


def test_step1_interview_notification_and_decision_schema_integrity(
    client: TestClient, database, smtp_outbox
) -> None:
    from app.models import Application, EmailNotification, Interview

    rec_headers, job_id = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="schema-rec@example.com",
        title="Backend Platform Engineer",
        skills=["Python", "FastAPI", "MySQL"],
    )
    cand_token = register_and_login(client, "schema-cand@example.com", "candidate", smtp_outbox)
    cand_headers = {"Authorization": f"Bearer {cand_token}"}
    apply_res = client.post(f"/api/jobs/{job_id}/apply", headers=cand_headers)
    assert apply_res.status_code == 200
    app_id = apply_res.json()["id"]

    with database() as db:
        application = db.get(Application, app_id)
        assert application is not None
        assert application.decision_reason is None
        assert application.decision_note is None
        assert application.decided_at is None
        assert application.decided_by_user_id is None

        rec_user = application.job.recruiter.user
        now = utc_now()
        round_2 = Interview(
            application_id=application.id,
            job_id=application.job_id,
            candidate_id=application.candidate_id,
            recruiter_id=application.job.recruiter_id,
            scheduled_by_user_id=rec_user.id,
            round_number=2,
            round_name="System Design & Architecture",
            interview_mode="online",
            scheduled_at=now + timedelta(days=2),
            duration_minutes=60,
            timezone="UTC",
            meeting_link="https://meet.example.com/round-2",
            interviewer_name="Principal Engineer",
            status="scheduled",
        )
        round_1 = Interview(
            application_id=application.id,
            job_id=application.job_id,
            candidate_id=application.candidate_id,
            recruiter_id=application.job.recruiter_id,
            scheduled_by_user_id=rec_user.id,
            round_number=1,
            round_name="Technical Screening",
            interview_mode="phone",
            scheduled_at=now + timedelta(days=1),
            duration_minutes=30,
            timezone="UTC",
            status="completed",
            rating=5,
            recommendation="strong_hire",
            completed_at=now,
        )
        db.add_all([round_2, round_1])
        db.flush()

        notif_failed = EmailNotification(
            application_id=application.id,
            interview_id=round_1.id,
            candidate_id=application.candidate_id,
            job_id=application.job_id,
            triggered_by_user_id=rec_user.id,
            notification_type="interview_scheduled",
            recipient_email="schema-cand@example.com",
            recipient_name=application.candidate.user.full_name,
            subject="Interview Round 1",
            status="failed",
            error_message="Simulated SMTP timeout",
            retry_count=1,
        )
        notif_sent = EmailNotification(
            application_id=application.id,
            interview_id=round_2.id,
            candidate_id=application.candidate_id,
            job_id=application.job_id,
            triggered_by_user_id=rec_user.id,
            notification_type="interview_scheduled",
            recipient_email="schema-cand@example.com",
            recipient_name=application.candidate.user.full_name,
            subject="Interview Round 2",
            status="sent",
            sent_at=now,
        )
        application.decision_reason = "Passed all technical rounds"
        application.decision_note = "Proceeding to final selection."
        application.decided_at = now
        application.decided_by_user_id = rec_user.id
        db.add_all([notif_failed, notif_sent])
        db.commit()

        db.refresh(application)
        assert [i.round_number for i in application.interviews] == [1, 2]
        assert len(application.email_notifications) == 3  # Includes the application-submitted email.
        assert sum(item.notification_type.startswith("interview_") for item in application.email_notifications) == 2
        assert application.decided_by_user.id == rec_user.id
        assert len(round_2.notifications) == 1
        assert round_2.notifications[0].status == "sent"


def test_step2_email_templates_non_blocking_logging_retry_and_secret_scrubbing(
    client: TestClient, database, smtp_outbox, monkeypatch, caplog
) -> None:
    import logging
    import smtplib

    import pytest

    from app.email_service import (
        build_application_status_email,
        build_interview_notification_email,
    )
    from app.models import Application, EmailNotification, Interview
    from app.notification_service import (
        NotificationAlreadySentError,
        NotificationNotFoundError,
        retry_email_notification,
        send_application_notification,
        send_interview_notification,
        serialize_email_notification,
    )

    rec_headers, job_id = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="notif-rec@example.com",
        title="Full Stack Engineer",
        skills=["Python", "React", "MySQL"],
    )
    cand_token = register_and_login(client, "notif-cand@example.com", "candidate", smtp_outbox)
    cand_headers = {"Authorization": f"Bearer {cand_token}"}
    apply_res = client.post(f"/api/jobs/{job_id}/apply", headers=cand_headers)
    assert apply_res.status_code == 200
    app_id = apply_res.json()["id"]

    # 1. Verify all 6 SkillSphere-branded templates (HTML + plain text + HTML escaping)
    now = utc_now()
    for ntype, expected_word in [
        ("application_shortlisted", "Shortlisted"),
        ("application_rejected", "Not Selected"),
        ("application_selected", "Selected"),
    ]:
        subj, text_body, html_body = build_application_status_email(
            ntype,
            "Anjali <Script>",
            "Full Stack Engineer",
            "TechCo",
            reason="Strong technical interview",
            note="Next step: onboarding call",
        )
        assert "Full Stack Engineer" in subj
        assert "SkillSphere" in html_body
        assert expected_word in html_body
        assert "<Script>" not in html_body
        assert "&lt;Script&gt;" in html_body
        assert "Strong technical interview" in text_body

    for ntype, expected_phrase in [
        ("interview_scheduled", "has been scheduled"),
        ("interview_rescheduled", "rescheduled"),
        ("interview_cancelled", "cancelled"),
    ]:
        subj, text_body, html_body = build_interview_notification_email(
            ntype,
            "Anjali Candidate",
            "Full Stack Engineer",
            "TechCo",
            round_number=1,
            round_name="Technical Panel",
            interview_mode="online",
            scheduled_at=now + timedelta(days=1),
            duration_minutes=45,
            timezone_name="Asia/Kolkata",
            meeting_link="https://meet.example.com/room-1",
            interviewer_name="Hiring Manager",
            notes_for_candidate="Prepare architecture notes.",
            cancellation_reason="Panel availability changed." if ntype == "interview_cancelled" else None,
        )
        assert "Technical Panel" in subj
        assert expected_phrase in text_body.lower()
        assert "SkillSphere" in html_body
        assert "Asia/Kolkata" in text_body

    # 2. Successful application + interview notification delivery & logging via mocked SMTP
    with database() as db:
        application = db.get(Application, app_id)
        rec_user = application.job.recruiter.user

        smtp_outbox.clear()
        shortlist_log = send_application_notification(
            db,
            application,
            "application_shortlisted",
            reason="Matched required stack",
            triggered_by_user_id=rec_user.id,
        )
        assert shortlist_log.status == "sent"
        assert shortlist_log.retry_count == 0
        assert shortlist_log.sent_at is not None
        assert shortlist_log.error_message is None
        assert shortlist_log.application_id == application.id
        assert shortlist_log.candidate_id == application.candidate_id
        assert shortlist_log.job_id == application.job_id
        assert shortlist_log.interview_id is None
        assert shortlist_log.recipient_email == "notif-cand@example.com"
        assert len(smtp_outbox) == 1

        # Duplicate identical notification is blocked safely without resending
        dedup_log = send_application_notification(
            db,
            application,
            "application_shortlisted",
            reason="Matched required stack",
            triggered_by_user_id=rec_user.id,
        )
        assert dedup_log.id == shortlist_log.id
        assert len(smtp_outbox) == 1

        interview = Interview(
            application_id=application.id,
            job_id=application.job_id,
            candidate_id=application.candidate_id,
            recruiter_id=application.job.recruiter_id,
            scheduled_by_user_id=rec_user.id,
            round_number=1,
            round_name="Technical Round 1",
            interview_mode="online",
            scheduled_at=now + timedelta(days=2),
            duration_minutes=45,
            timezone="UTC",
            meeting_link="https://meet.example.com/t1",
            status="scheduled",
        )
        db.add(interview)
        db.commit()
        db.refresh(interview)

        smtp_outbox.clear()
        sched_log = send_interview_notification(
            db,
            interview,
            "interview_scheduled",
            triggered_by_user_id=rec_user.id,
        )
        assert sched_log.status == "sent"
        assert sched_log.interview_id == interview.id
        assert len(smtp_outbox) == 1

        # 3. Non-blocking SMTP failure: must NOT roll back committed decision, and MUST scrub secrets
        settings = get_settings()
        secret_pwd = "super-secret-smtp-pass-987"
        monkeypatch.setattr(settings, "smtp_password", secret_pwd)

        class BrokenSMTP:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                raise smtplib.SMTPAuthenticationError(
                    535,
                    f"Auth failed for password {secret_pwd}".encode("utf-8"),
                )

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("app.email_service.smtplib.SMTP", BrokenSMTP)
        monkeypatch.setattr("app.email_service.smtplib.SMTP_SSL", BrokenSMTP)

        application.status = "selected"
        application.decision_reason = "Strong offer match"
        application.decided_at = utc_now()
        application.decided_by_user_id = rec_user.id
        db.commit()

        caplog.set_level(logging.WARNING)
        failed_log = send_application_notification(
            db,
            application,
            "application_selected",
            reason=application.decision_reason,
            note="Offer details follow.",
            triggered_by_user_id=rec_user.id,
        )
        db.refresh(application)
        assert application.status == "selected"  # Decision remains committed!
        assert failed_log.status == "failed"
        assert failed_log.retry_count == 0
        assert failed_log.sent_at is None
        assert failed_log.error_message is not None
        assert secret_pwd not in failed_log.error_message
        assert "[REDACTED]" in failed_log.error_message
        serialized = serialize_email_notification(failed_log)
        assert secret_pwd not in str(serialized)
        assert all(secret_pwd not in rec.getMessage() for rec in caplog.records)

        # 4. Retry while SMTP is still broken increments retry_count and stays failed
        retried_fail = retry_email_notification(db, failed_log.id, triggered_by_user_id=rec_user.id)
        assert retried_fail.status == "failed"
        assert retried_fail.retry_count == 1
        assert secret_pwd not in (retried_fail.error_message or "")

        # Restore working mocked SMTP via simple dummy class and retry -> succeeds
        class WorkingSMTP:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def ehlo(self):
                return (250, b"ok")

            def starttls(self):
                return (220, b"ok")

            def login(self, user, password):
                return (235, b"ok")

            def send_message(self, message):
                smtp_outbox.append({"to": message["To"], "subject": message["Subject"], "text": ""})
                return {}

        monkeypatch.setattr("app.email_service.smtplib.SMTP", WorkingSMTP)
        monkeypatch.setattr("app.email_service.smtplib.SMTP_SSL", WorkingSMTP)
        smtp_outbox.clear()

        retried_ok = retry_email_notification(db, failed_log.id, triggered_by_user_id=rec_user.id)
        assert retried_ok.status == "sent"
        assert retried_ok.retry_count == 2
        assert retried_ok.error_message is None
        assert retried_ok.sent_at is not None
        assert len(smtp_outbox) == 1

        # 5. Retrying an already-sent notification is blocked safely to prevent duplicates
        with pytest.raises(NotificationAlreadySentError):
            retry_email_notification(db, retried_ok.id, triggered_by_user_id=rec_user.id)
        assert len(smtp_outbox) == 1

        with pytest.raises(NotificationNotFoundError):
            retry_email_notification(db, 999999)

        # Check all recorded rows exist cleanly in email_notifications
        all_logs = db.scalars(
            select(EmailNotification).where(EmailNotification.application_id == application.id)
        ).all()
        assert len(all_logs) == 4  # Includes the application-submitted email.
        assert {log.notification_type for log in all_logs} == {
            "application_submitted",
            "application_shortlisted",
            "interview_scheduled",
            "application_selected",
        }


def test_step3_selection_rejection_decision_apis_rbac_history_and_notifications(
    client: TestClient, database, smtp_outbox, monkeypatch
) -> None:
    import smtplib

    rec_headers, job_id = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="dec-rec1@example.com",
        title="FastAPI Backend Engineer",
        skills=["Python", "FastAPI", "MySQL"],
    )
    other_rec_headers, _ = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="dec-rec2@example.com",
        title="Other Job",
        skills=["Java"],
    )
    admin_headers = _create_admin_headers(client, database, smtp_outbox, email="dec-admin@example.com")

    c1_token = register_and_login(client, "dec-cand1@example.com", "candidate", smtp_outbox)
    c2_token = register_and_login(client, "dec-cand2@example.com", "candidate", smtp_outbox)
    c3_token = register_and_login(client, "dec-cand3@example.com", "candidate", smtp_outbox)
    c4_token = register_and_login(client, "dec-cand4@example.com", "candidate", smtp_outbox)
    c1_headers = {"Authorization": f"Bearer {c1_token}"}
    c2_headers = {"Authorization": f"Bearer {c2_token}"}
    c3_headers = {"Authorization": f"Bearer {c3_token}"}
    c4_headers = {"Authorization": f"Bearer {c4_token}"}

    app1_id = client.post(f"/api/jobs/{job_id}/apply", headers=c1_headers).json()["id"]
    app2_id = client.post(f"/api/jobs/{job_id}/apply", headers=c2_headers).json()["id"]
    app3_id = client.post(f"/api/jobs/{job_id}/apply", headers=c3_headers).json()["id"]
    app4_id = client.post(f"/api/jobs/{job_id}/apply", headers=c4_headers).json()["id"]
    assert client.delete(f"/api/applications/{app4_id}", headers=c4_headers).status_code == 200

    # 1. RBAC checks: unauthenticated -> 401, candidate -> 403, admin -> 403, other recruiter -> 403
    assert client.post(f"/api/recruiter/applications/{app1_id}/select", json={}).status_code == 401
    assert client.post(f"/api/recruiter/applications/{app1_id}/select", json={}, headers=c1_headers).status_code == 403
    assert client.post(f"/api/recruiter/applications/{app1_id}/reject", json={}, headers=c1_headers).status_code == 403
    assert client.post(f"/api/recruiter/applications/{app1_id}/decision", json={"decision": "selected"}, headers=admin_headers).status_code == 403
    assert client.post(f"/api/recruiter/applications/{app1_id}/select", json={}, headers=other_rec_headers).status_code == 403
    assert client.post(f"/api/recruiter/applications/{app1_id}/reject", json={}, headers=other_rec_headers).status_code == 403
    assert client.get(f"/api/recruiter/applications/{app1_id}/notifications", headers=other_rec_headers).status_code == 403
    assert client.post("/api/recruiter/applications/999999/select", json={}, headers=rec_headers).status_code == 404

    # Validation check for invalid decision / selection status
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/decision",
        json={"decision": "invalid_choice"},
        headers=rec_headers,
    ).status_code == 422
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/select",
        json={"status": "rejected"},
        headers=rec_headers,
    ).status_code == 422

    # 2. Authorized recruiter selects candidate 1 -> saves metadata, history, and sends email
    smtp_outbox.clear()
    sel_res = client.post(
        f"/api/recruiter/applications/{app1_id}/select",
        json={
            "reason": "Strong assessment and interview performance",
            "note": "Offer letter will follow within 2 business days.",
            "send_email": True,
        },
        headers=rec_headers,
    )
    assert sel_res.status_code == 200
    sel_body = sel_res.json()
    assert sel_body["status"] == "selected"
    assert sel_body["decision_changed"] is True
    assert sel_body["decision_reason"] == "Strong assessment and interview performance"
    assert sel_body["decision_note"] == "Offer letter will follow within 2 business days."
    assert sel_body["decided_at"] is not None
    assert sel_body["notification_status"] == "sent"
    assert sel_body["notification"]["status"] == "sent"
    assert sel_body["notification"]["notification_type"] == "application_selected"
    assert sel_body["status_history"][0]["previous_status"] == "applied"
    assert sel_body["status_history"][0]["new_status"] == "selected"
    assert sel_body["status_history"][0]["source"] == "decision_api"
    assert len(smtp_outbox) == 1
    assert smtp_outbox[0]["to"] == "dec-cand1@example.com"
    assert "Selected" in smtp_outbox[0]["subject"]

    # 3. Repeated identical selection does NOT duplicate history or send another email
    history_count_before = len(sel_body["status_history"])
    smtp_outbox.clear()
    repeat_sel = client.post(
        f"/api/recruiter/applications/{app1_id}/decision",
        json={"decision": "selected", "reason": "Strong assessment and interview performance"},
        headers=rec_headers,
    )
    assert repeat_sel.status_code == 200
    assert repeat_sel.json()["decision_changed"] is False
    assert repeat_sel.json()["notification_status"] == "skipped_no_change"
    assert repeat_sel.json()["notification"] is None
    assert len(repeat_sel.json()["status_history"]) == history_count_before
    assert len(smtp_outbox) == 0

    # Contradictory backward transition (selected -> shortlisted) is rejected
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/decision",
        json={"decision": "shortlisted"},
        headers=rec_headers,
    ).status_code == 409

    # Forward progression (selected -> accepted) is permitted and updating candidate 1 -> finalized blocks rejection
    acc_res = client.post(
        f"/api/recruiter/applications/{app1_id}/select",
        json={"status": "accepted", "reason": "Candidate accepted offer", "send_email": False},
        headers=rec_headers,
    )
    assert acc_res.status_code == 200
    assert acc_res.json()["status"] == "accepted"
    assert acc_res.json()["notification_status"] == "not_requested"
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/reject",
        json={"reason": "Too late"},
        headers=rec_headers,
    ).status_code == 409

    # 4. Authorized recruiter rejects candidate 2 -> saves metadata, history, and logs email
    smtp_outbox.clear()
    rej_res = client.post(
        f"/api/recruiter/applications/{app2_id}/reject",
        json={
            "reason": "Missing FastAPI experience",
            "note": "Thank you for applying; please reapply after building backend projects.",
            "send_email": True,
        },
        headers=rec_headers,
    )
    assert rej_res.status_code == 200
    rej_body = rej_res.json()
    assert rej_body["status"] == "rejected"
    assert rej_body["decision_changed"] is True
    assert rej_body["decision_reason"] == "Missing FastAPI experience"
    assert rej_body["notification_status"] == "sent"
    assert rej_body["notification"]["notification_type"] == "application_rejected"
    assert rej_body["status_history"][0]["new_status"] == "rejected"
    assert len(smtp_outbox) == 1
    assert smtp_outbox[0]["to"] == "dec-cand2@example.com"

    # Repeated rejection -> no duplicate history or email; trying to select rejected -> 409
    smtp_outbox.clear()
    rej_repeat = client.post(
        f"/api/recruiter/applications/{app2_id}/reject",
        json={"reason": "Missing FastAPI experience"},
        headers=rec_headers,
    )
    assert rej_repeat.status_code == 200
    assert rej_repeat.json()["decision_changed"] is False
    assert len(rej_repeat.json()["status_history"]) == len(rej_body["status_history"])
    assert len(smtp_outbox) == 0
    assert client.post(
        f"/api/recruiter/applications/{app2_id}/select",
        json={},
        headers=rec_headers,
    ).status_code == 409

    # 5. SMTP failure during decision does NOT roll back the committed decision and scrubs secrets
    settings = get_settings()
    leaked_secret = "step3-smtp-secret-456"
    monkeypatch.setattr(settings, "smtp_password", leaked_secret)

    class FailingSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            raise smtplib.SMTPException(f"SMTP failure using {leaked_secret}")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.email_service.smtplib.SMTP", FailingSMTP)
    monkeypatch.setattr("app.email_service.smtplib.SMTP_SSL", FailingSMTP)

    fail_dec = client.post(
        f"/api/recruiter/applications/{app3_id}/decision",
        json={"decision": "rejected", "reason": "Position filled", "send_email": True},
        headers=rec_headers,
    )
    assert fail_dec.status_code == 200
    fail_body = fail_dec.json()
    assert fail_body["status"] == "rejected"
    assert fail_body["decision_reason"] == "Position filled"
    assert fail_body["notification_status"] == "failed"
    assert fail_body["notification"]["status"] == "failed"
    assert leaked_secret not in (fail_body["notification"]["error_message"] or "")
    assert "[REDACTED]" in fail_body["notification"]["error_message"]

    # Recruiter can inspect notification audit logs and applicant detail includes decision metadata
    notifs = client.get(f"/api/recruiter/applications/{app3_id}/notifications", headers=rec_headers)
    assert notifs.status_code == 200
    assert len(notifs.json()) == 2  # Includes the application-submitted email.
    rejected_notif = next(item for item in notifs.json() if item["notification_type"] == "application_rejected")
    assert rejected_notif["status"] == "failed"
    assert any(item["notification_type"] == "application_submitted" for item in notifs.json())

    detail = client.get(f"/api/recruiter/applicants/{app1_id}", headers=rec_headers)
    assert detail.status_code == 200
    assert detail.json()["decision_reason"] == "Candidate accepted offer"
    assert detail.json()["latest_email_notification"]["status"] == "sent"

    # Candidate sees their decision note/status cleanly via GET /api/applications/me (read-only)
    cand1_apps = client.get("/api/applications/me", headers=c1_headers).json()
    assert cand1_apps[0]["status"] == "accepted"
    assert cand1_apps[0]["decision_reason"] == "Candidate accepted offer"

    # Withdrawn application cannot receive decisions
    assert client.post(f"/api/recruiter/applications/{app4_id}/select", json={}, headers=rec_headers).status_code == 409


def test_step4_interview_management_notifications_retry_and_admin_oversight(
    client: TestClient, database, smtp_outbox, monkeypatch
) -> None:
    import smtplib

    rec1_headers, job1_id = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="int-rec1@example.com",
        title="Backend Lead",
        skills=["Python", "FastAPI", "MySQL"],
    )
    rec2_headers, job2_id = _setup_approved_job(
        client,
        database,
        smtp_outbox,
        recruiter_email="int-rec2@example.com",
        title="Frontend Architect",
        skills=["React", "TypeScript"],
    )
    admin_headers = _create_admin_headers(client, database, smtp_outbox, email="int-admin@example.com")

    c1_token = register_and_login(client, "int-cand1@example.com", "candidate", smtp_outbox)
    c2_token = register_and_login(client, "int-cand2@example.com", "candidate", smtp_outbox)
    c1_headers = {"Authorization": f"Bearer {c1_token}"}
    c2_headers = {"Authorization": f"Bearer {c2_token}"}

    app1_id = client.post(f"/api/jobs/{job1_id}/apply", headers=c1_headers).json()["id"]
    app2_id = client.post(f"/api/jobs/{job2_id}/apply", headers=c2_headers).json()["id"]
    # Shortlist candidate 1 first so we also test shortlist -> interview status progression
    assert client.put(
        f"/api/applications/{app1_id}/status",
        json={"status": "shortlisted"},
        headers=rec1_headers,
    ).status_code == 200

    future_dt1 = (utc_now() + timedelta(days=2)).replace(microsecond=0).isoformat()
    future_dt2 = (utc_now() + timedelta(days=4)).replace(microsecond=0).isoformat()
    future_dt3 = (utc_now() + timedelta(days=6)).replace(microsecond=0).isoformat()
    past_dt = (utc_now() - timedelta(hours=3)).replace(microsecond=0).isoformat()

    # 1. Validation checks: invalid mode, past date/time, missing/invalid online link, missing offline location
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/interviews",
        json={"interview_mode": "telepathy", "scheduled_at": future_dt1},
        headers=rec1_headers,
    ).status_code == 422
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/interviews",
        json={"interview_mode": "online", "scheduled_at": past_dt, "meeting_link": "https://meet.example.com/1"},
        headers=rec1_headers,
    ).status_code == 422
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/interviews",
        json={"interview_mode": "online", "scheduled_at": future_dt1},
        headers=rec1_headers,
    ).status_code == 422
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/interviews",
        json={"interview_mode": "online", "scheduled_at": future_dt1, "meeting_link": "not-a-url"},
        headers=rec1_headers,
    ).status_code == 422
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/interviews",
        json={"interview_mode": "offline", "scheduled_at": future_dt1},
        headers=rec1_headers,
    ).status_code == 422

    # 2. Recruiter 1 schedules Round 1 (online) -> commits, updates application status to interview, logs email
    smtp_outbox.clear()
    sched1 = client.post(
        f"/api/recruiter/applications/{app1_id}/interviews",
        json={
            "round_name": "Technical Round 1",
            "interview_mode": "online",
            "scheduled_at": future_dt1,
            "duration_minutes": 45,
            "timezone": "UTC",
            "meeting_link": "https://meet.example.com/round1",
            "interviewer_name": "Senior Backend Lead",
            "notes_for_candidate": "Be ready to share your screen.",
            "internal_notes": "Private rubric: focus on SQL joins.",
        },
        headers=rec1_headers,
    )
    assert sched1.status_code == 201
    r1_data = sched1.json()
    int1_id = r1_data["interview"]["id"]
    notif1_id = r1_data["notification"]["id"]
    assert r1_data["interview"]["round_number"] == 1
    assert r1_data["interview"]["status"] == "scheduled"
    assert r1_data["interview"]["application_status"] == "interview"
    assert r1_data["notification_status"] == "sent"
    assert len(smtp_outbox) == 1
    assert "Interview Scheduled" in smtp_outbox[0]["subject"]

    # Double-booking exact same round & timestamp is rejected
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/interviews",
        json={
            "round_number": 1,
            "interview_mode": "online",
            "scheduled_at": future_dt1,
            "meeting_link": "https://meet.example.com/round1",
        },
        headers=rec1_headers,
    ).status_code == 409

    # 3. Multiple interview rounds: Recruiter 1 schedules Round 2 (offline -> normalized in_person) via generic endpoint
    smtp_outbox.clear()
    sched2 = client.post(
        "/api/recruiter/interviews",
        json={
            "application_id": app1_id,
            "round_name": "Final Onsite Round",
            "interview_mode": "offline",
            "scheduled_at": future_dt3,
            "duration_minutes": 60,
            "location": "SkillSphere HQ, Floor 4, Bengaluru",
            "interviewer_name": "VP of Engineering",
        },
        headers=rec1_headers,
    )
    assert sched2.status_code == 201
    int2_id = sched2.json()["interview"]["id"]
    assert sched2.json()["interview"]["round_number"] == 2
    assert sched2.json()["interview"]["interview_mode"] == "in_person"
    assert len(smtp_outbox) == 1

    app1_interviews = client.get(f"/api/recruiter/applications/{app1_id}/interviews", headers=rec1_headers)
    assert app1_interviews.status_code == 200
    assert [row["round_number"] for row in app1_interviews.json()] == [1, 2]

    # 4. Cross-tenant & Role Authorization checks
    # Recruiter 2 cannot view or modify Recruiter 1's interviews or applications
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/interviews",
        json={"interview_mode": "online", "scheduled_at": future_dt2, "meeting_link": "https://meet.example.com/x"},
        headers=rec2_headers,
    ).status_code == 403
    assert client.get(f"/api/recruiter/interviews/{int1_id}", headers=rec2_headers).status_code == 403
    assert client.put(
        f"/api/recruiter/interviews/{int1_id}/reschedule",
        json={"scheduled_at": future_dt2},
        headers=rec2_headers,
    ).status_code == 403
    assert client.post(f"/api/recruiter/interviews/{int1_id}/cancel", json={}, headers=rec2_headers).status_code == 403
    assert client.post(f"/api/recruiter/interviews/{int1_id}/feedback", json={"feedback": "hack"}, headers=rec2_headers).status_code == 403
    assert client.post(f"/api/recruiter/notifications/{notif1_id}/resend", headers=rec2_headers).status_code == 403

    # Admin CANNOT modify recruiter interviews or resend recruiter notifications
    assert client.post(
        f"/api/recruiter/applications/{app1_id}/interviews",
        json={"interview_mode": "online", "scheduled_at": future_dt2, "meeting_link": "https://meet.example.com/a"},
        headers=admin_headers,
    ).status_code == 403
    assert client.put(
        f"/api/recruiter/interviews/{int1_id}/reschedule",
        json={"scheduled_at": future_dt2},
        headers=admin_headers,
    ).status_code == 403
    assert client.post(f"/api/recruiter/interviews/{int1_id}/cancel", json={}, headers=admin_headers).status_code == 403
    assert client.post(f"/api/recruiter/notifications/{notif1_id}/resend", headers=admin_headers).status_code == 403

    # Candidate CANNOT access recruiter or admin endpoints
    assert client.get("/api/recruiter/interviews", headers=c1_headers).status_code == 403
    assert client.get("/api/admin/interviews", headers=c1_headers).status_code == 403

    # 5. Candidate Interview Read APIs: isolation & internal field hiding
    c1_list = client.get("/api/candidates/interviews", headers=c1_headers)
    assert c1_list.status_code == 200
    assert len(c1_list.json()) == 2
    assert "internal_notes" not in c1_list.json()[0]
    assert "feedback" not in c1_list.json()[0]
    assert "rating" not in c1_list.json()[0]
    assert "recommendation" not in c1_list.json()[0]
    assert client.get(f"/api/candidates/interviews/{int1_id}", headers=c1_headers).status_code == 200
    assert client.get(f"/api/candidates/interviews/{int1_id}", headers=c2_headers).status_code == 403
    assert client.get("/api/candidates/interviews", headers=c2_headers).json() == []

    # 6. Reschedule genuinely to new date/time -> new notification; repeated identical request -> no duplicate notification
    smtp_outbox.clear()
    resched_ok = client.put(
        f"/api/recruiter/interviews/{int1_id}/reschedule",
        json={
            "scheduled_at": future_dt2,
            "meeting_link": "https://meet.example.com/round1-updated",
            "send_email": True,
        },
        headers=rec1_headers,
    )
    assert resched_ok.status_code == 200
    assert resched_ok.json()["rescheduled"] is True
    assert resched_ok.json()["interview"]["status"] == "rescheduled"
    assert resched_ok.json()["notification_status"] == "sent"
    assert resched_ok.json()["notification"]["notification_type"] == "interview_rescheduled"
    assert len(smtp_outbox) == 1
    assert "Rescheduled" in smtp_outbox[0]["subject"]

    smtp_outbox.clear()
    resched_repeat = client.put(
        f"/api/recruiter/interviews/{int1_id}/reschedule",
        json={
            "scheduled_at": future_dt2,
            "meeting_link": "https://meet.example.com/round1-updated",
            "send_email": True,
        },
        headers=rec1_headers,
    )
    assert resched_repeat.status_code == 200
    assert resched_repeat.json()["changed"] is False
    assert resched_repeat.json()["notification_status"] == "skipped_no_change"
    assert resched_repeat.json()["notification"] is None
    assert len(smtp_outbox) == 0

    # 7. Save feedback & final interview outcome on Round 1
    fb_res = client.post(
        f"/api/recruiter/interviews/{int1_id}/feedback",
        json={
            "feedback": "Excellent problem solving and clean API design.",
            "rating": 5,
            "recommendation": "strong_hire",
            "internal_notes": "Advance to final offer stage.",
            "status": "completed",
        },
        headers=rec1_headers,
    )
    assert fb_res.status_code == 200
    assert fb_res.json()["status"] == "completed"
    assert fb_res.json()["rating"] == 5
    assert fb_res.json()["recommendation"] == "strong_hire"
    assert fb_res.json()["final_outcome"] == "strong_hire"
    assert fb_res.json()["completed_at"] is not None
    # Completed interviews cannot be rescheduled or cancelled
    assert client.put(
        f"/api/recruiter/interviews/{int1_id}/reschedule",
        json={"scheduled_at": future_dt3},
        headers=rec1_headers,
    ).status_code == 409
    assert client.post(f"/api/recruiter/interviews/{int1_id}/cancel", json={}, headers=rec1_headers).status_code == 409

    # 8. Cancel Round 2 -> sends cancellation notification; repeated cancel -> no duplicate email; modifying cancelled -> 409
    smtp_outbox.clear()
    cancel_res = client.post(
        f"/api/recruiter/interviews/{int2_id}/cancel",
        json={"cancellation_reason": "Role requirements shifted; skipping final onsite."},
        headers=rec1_headers,
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["cancelled_changed"] is True
    assert cancel_res.json()["interview"]["status"] == "cancelled"
    assert cancel_res.json()["notification"]["notification_type"] == "interview_cancelled"
    assert len(smtp_outbox) == 1
    assert "Cancelled" in smtp_outbox[0]["subject"]

    smtp_outbox.clear()
    cancel_repeat = client.post(f"/api/recruiter/interviews/{int2_id}/cancel", json={}, headers=rec1_headers)
    assert cancel_repeat.status_code == 200
    assert cancel_repeat.json()["cancelled_changed"] is False
    assert cancel_repeat.json()["notification_status"] == "skipped_no_change"
    assert len(smtp_outbox) == 0

    assert client.put(
        f"/api/recruiter/interviews/{int2_id}/reschedule",
        json={"scheduled_at": future_dt2, "interview_mode": "offline", "location": "HQ"},
        headers=rec1_headers,
    ).status_code == 409
    assert client.post(
        f"/api/recruiter/interviews/{int2_id}/feedback",
        json={"feedback": "Should fail"},
        headers=rec1_headers,
    ).status_code == 409

    # Already-sent notification CANNOT be retried
    assert client.post(f"/api/recruiter/notifications/{notif1_id}/resend", headers=rec1_headers).status_code == 409

    # 9. SMTP failure while scheduling for Candidate 2 does NOT undo interview, and retry succeeds after SMTP recovery
    settings = get_settings()
    leaked_pwd = "step4-secret-token-xyz"
    monkeypatch.setattr(settings, "smtp_password", leaked_pwd)

    class BrokenSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            raise smtplib.SMTPException(f"Auth failure with secret {leaked_pwd}")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.email_service.smtplib.SMTP", BrokenSMTP)
    monkeypatch.setattr("app.email_service.smtplib.SMTP_SSL", BrokenSMTP)

    fail_sched = client.post(
        f"/api/recruiter/applications/{app2_id}/interviews",
        json={
            "round_name": "Frontend Screening",
            "interview_mode": "online",
            "scheduled_at": future_dt2,
            "meeting_link": "https://meet.example.com/fe-1",
            "send_email": True,
        },
        headers=rec2_headers,
    )
    assert fail_sched.status_code == 201
    assert fail_sched.json()["interview"]["status"] == "scheduled"  # Interview stays committed!
    failed_notif_id = fail_sched.json()["notification"]["id"]
    assert fail_sched.json()["notification_status"] == "failed"
    assert leaked_pwd not in (fail_sched.json()["notification"]["error_message"] or "")
    assert "[REDACTED]" in fail_sched.json()["notification"]["error_message"]

    # Retry while SMTP is still broken returns 503 with scrubbed error and increments retry_count
    retry_fail = client.post(f"/api/recruiter/notifications/{failed_notif_id}/resend", headers=rec2_headers)
    assert retry_fail.status_code == 503
    assert leaked_pwd not in retry_fail.json()["detail"]

    # Restore working SMTP mock -> retry succeeds and prevents subsequent retries
    class WorkingSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            return (250, b"ok")

        def starttls(self):
            return (220, b"ok")

        def login(self, user, password):
            return (235, b"ok")

        def send_message(self, message):
            smtp_outbox.append({"to": message["To"], "subject": message["Subject"], "text": ""})
            return {}

    monkeypatch.setattr("app.email_service.smtplib.SMTP", WorkingSMTP)
    monkeypatch.setattr("app.email_service.smtplib.SMTP_SSL", WorkingSMTP)
    smtp_outbox.clear()

    retry_ok = client.post(f"/api/recruiter/notifications/{failed_notif_id}/resend", headers=rec2_headers)
    assert retry_ok.status_code == 200
    assert retry_ok.json()["notification"]["status"] == "sent"
    assert retry_ok.json()["notification"]["retry_count"] == 2
    assert len(smtp_outbox) == 1
    assert client.post(f"/api/recruiter/notifications/{failed_notif_id}/resend", headers=rec2_headers).status_code == 409

    # 10. Admin read-only oversight APIs
    admin_all = client.get("/api/admin/interviews", headers=admin_headers)
    assert admin_all.status_code == 200
    assert admin_all.json()["total"] == 3
    assert admin_all.json()["counts_by_status"]["completed"] == 1
    assert admin_all.json()["counts_by_status"]["cancelled"] == 1
    assert admin_all.json()["counts_by_status"]["scheduled"] == 1

    admin_detail = client.get(f"/api/admin/interviews/{int1_id}", headers=admin_headers)
    assert admin_detail.status_code == 200
    assert len(admin_detail.json()["notifications"]) >= 2

    admin_summary = client.get("/api/admin/interviews/summary", headers=admin_headers)
    assert admin_summary.status_code == 200
    assert admin_summary.json()["total"] == 3
    assert admin_summary.json()["by_status"]["completed"] == 1

    today_str = utc_now().date().isoformat()
    admin_notifs = client.get(
        "/api/admin/notifications",
        params={
            "status": "sent",
            "notification_type": "interview_cancelled",
            "job_id": job1_id,
            "application_id": app1_id,
            "from_date": today_str,
            "to_date": today_str,
        },
        headers=admin_headers,
    )
    assert admin_notifs.status_code == 200
    assert admin_notifs.json()["total"] == 1
    assert admin_notifs.json()["items"][0]["notification_type"] == "interview_cancelled"

    rec1_notifs = client.get("/api/recruiter/notifications", headers=rec1_headers)
    assert rec1_notifs.status_code == 200
    assert rec1_notifs.json()["total"] == 6  # Includes the application-submitted emails for both candidates.
    assert sum(item["notification_type"].startswith("interview_") for item in rec1_notifs.json()["items"]) == 4
    assert all(item["job_id"] == job1_id for item in rec1_notifs.json()["items"])







