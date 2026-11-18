from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password, utc_now
from app.models import Company, Job, User
from tests.conftest import register_and_login


def _setup_recruiter_and_job(client: TestClient, database, smtp_outbox, email="audit-rec@example.com"):
    token = register_and_login(client, email, "recruiter", smtp_outbox)
    headers = {"Authorization": f"Bearer {token}"}
    company_res = client.post("/api/companies", json={"name": f"AuditCo-{email}"}, headers=headers)
    assert company_res.status_code == 200
    with database() as db:
        comp = db.get(Company, company_res.json()["id"])
        comp.is_approved = True
        db.commit()

    job_res = client.post(
        "/api/jobs",
        json={
            "title": "Senior Python Architect",
            "description": "Python, FastAPI, SQL backend services.",
            "location": "Remote",
            "employment_type": "full_time",
            "experience_min": 1,
            "experience_max": 5,
            "skills": ["Python", "FastAPI", "SQL"],
        },
        headers=headers,
    )
    assert job_res.status_code == 201
    job_id = job_res.json()["id"]
    with database() as db:
        db.get(Job, job_id).status = "published"
        db.commit()
    return headers, job_id


def _create_admin(client: TestClient, database, smtp_outbox, email="audit-admin@example.com"):
    with database() as db:
        if not db.scalar(select(User).where(User.email == email)):
            db.add(User(
                email=email,
                password_hash=hash_password("StrongPass123"),
                full_name="Audit Administrator",
                role="admin",
                is_active=True,
            ))
            db.commit()
    from tests.conftest import login_with_otp
    session = login_with_otp(client, smtp_outbox, email, "StrongPass123")
    return {"Authorization": f"Bearer {session['access_token']}"}


def test_assessment_workflow_end_to_end_candidate_launch_and_proctoring(
    client: TestClient, database, smtp_outbox
):
    admin_headers = _create_admin(client, database, smtp_outbox)
    rec_headers, job_id = _setup_recruiter_and_job(client, database, smtp_outbox)

    # 1. Admin adds 2 MCQ questions
    q1 = client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "Python",
        "category": "Backend",
        "difficulty": "Easy",
        "question_text": "What is the return type of a generator function in Python?",
        "options": ["Generator iterator", "List", "Tuple", "Dict"],
        "correct_option_index": 0,
        "marks": 5,
    }, headers=admin_headers)
    assert q1.status_code == 201
    q1_id = q1.json()["id"]

    q2 = client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "FastAPI",
        "category": "Backend",
        "difficulty": "Medium",
        "question_text": "Which HTTP status code signifies resource creation?",
        "options": ["200", "201", "204", "301"],
        "correct_option_index": 1,
        "marks": 5,
    }, headers=admin_headers)
    assert q2.status_code == 201
    q2_id = q2.json()["id"]

    # 2. Recruiter creates draft and publishes assessment (Total marks = 10, passing marks = 5 -> strict > 5 requires 10/10)
    draft_res = client.post("/api/recruiter/assessments", json={
        "job_id": job_id,
        "title": "Backend Screening Test",
        "description": "Evaluate core Python and FastAPI skills",
        "instructions": "Answer both MCQs within 15 minutes.",
        "duration_minutes": 15,
        "passing_marks": 5,
        "expires_at": (utc_now() + timedelta(days=3)).isoformat(),
        "question_ids": [q1_id, q2_id],
        "status": "draft",
    }, headers=rec_headers)
    assert draft_res.status_code == 201
    assessment_id = draft_res.json()["id"]

    pub_res = client.put(f"/api/recruiter/assessments/{assessment_id}", json={
        "job_id": job_id,
        "title": "Backend Screening Test",
        "description": "Evaluate core Python and FastAPI skills",
        "instructions": "Answer both MCQs within 15 minutes.",
        "duration_minutes": 15,
        "passing_marks": 5,
        "expires_at": (utc_now() + timedelta(days=3)).isoformat(),
        "question_ids": [q1_id, q2_id],
        "status": "published",
    }, headers=rec_headers)
    assert pub_res.status_code == 200
    assert pub_res.json()["status"] == "published"

    # 3. Candidate 1 applies & is shortlisted
    cand1_token = register_and_login(client, "cand-audit1@example.com", "candidate", smtp_outbox)
    cand1_headers = {"Authorization": f"Bearer {cand1_token}"}
    client.put("/api/candidates/me", json={
        "education": "M.Tech CS",
        "experience": "3 years Python FastAPI SQL",
        "skills": ["Python", "FastAPI", "SQL"],
    }, headers=cand1_headers)
    app1 = client.post(f"/api/jobs/{job_id}/apply", headers=cand1_headers).json()
    assert app1["status"] == "shortlisted"

    # Candidate 2 applies & is shortlisted
    cand2_token = register_and_login(client, "cand-audit2@example.com", "candidate", smtp_outbox)
    cand2_headers = {"Authorization": f"Bearer {cand2_token}"}
    client.put("/api/candidates/me", json={
        "education": "B.Tech CS",
        "experience": "2 years Python FastAPI",
        "skills": ["Python", "FastAPI", "SQL"],
    }, headers=cand2_headers)
    app2 = client.post(f"/api/jobs/{job_id}/apply", headers=cand2_headers).json()
    assert app2["status"] == "shortlisted"

    # 4. Recruiter assigns assessment to Candidate 1
    assign_res = client.post(
        f"/api/recruiter/assessments/{assessment_id}/assign",
        json={"application_ids": [app1["id"]]},
        headers=rec_headers,
    )
    assert assign_res.status_code == 200
    assert assign_res.json()["assigned_count"] == 1

    # 5. Candidate 1 checks My Applications -> must receive assessment_token directly
    my_apps = client.get("/api/applications/me", headers=cand1_headers)
    assert my_apps.status_code == 200
    app_data = my_apps.json()[0]
    assert app_data["assessment_status"] == "assigned"
    assert app_data["assessment_token"] is not None
    direct_token = app_data["assessment_token"]

    # 6. Candidate 1 checks dedicated launch endpoint
    launch_res = client.get(f"/api/assessments/application/{app1['id']}/token", headers=cand1_headers)
    assert launch_res.status_code == 200
    assert launch_res.json()["token"] is not None
    assert launch_res.json()["test_status"] == "assigned"
    assert launch_res.json()["title"] == "Backend Screening Test"

    # Candidate 2 cannot get Candidate 1's token
    assert client.get(f"/api/assessments/application/{app1['id']}/token", headers=cand2_headers).status_code == 404

    # 7. Candidate 1 verifies invitation using direct_token
    verify_res = client.get(f"/api/assessments/{direct_token}", headers=cand1_headers)
    assert verify_res.status_code == 200
    assert verify_res.json()["title"] == "Backend Screening Test"
    assert verify_res.json()["requires_auth"] is False

    # Candidate 2 cannot access Candidate 1's test portal
    assert client.get(f"/api/assessments/{direct_token}", headers=cand2_headers).status_code == 403

    # 8. Candidate 1 starts test
    start_res = client.post(f"/api/assessments/{direct_token}/start", headers=cand1_headers)
    assert start_res.status_code == 200
    assert start_res.json()["test_status"] == "started"
    questions = start_res.json()["questions"]
    assert len(questions) == 2

    # 9. Candidate 1 records proctoring events
    event1 = client.post(f"/api/assessments/{direct_token}/proctoring-events", json={
        "event_type": "tab_switch",
        "details": {"tab_hidden": True},
    }, headers=cand1_headers)
    assert event1.status_code == 200

    event2 = client.post(f"/api/assessments/{direct_token}/proctoring-events", json={
        "event_type": "window_blur",
        "details": {"blurred": True},
    }, headers=cand1_headers)
    assert event2.status_code == 200

    # 10. Candidate 1 answers questions (scores 10/10 > 5 -> PASS)
    ans1 = client.put(f"/api/assessments/{direct_token}/answer", json={
        "question_id": questions[0]["id"],
        "selected_option_index": 0,
    }, headers=cand1_headers)
    assert ans1.status_code == 200

    ans2 = client.put(f"/api/assessments/{direct_token}/answer", json={
        "question_id": questions[1]["id"],
        "selected_option_index": 1,
    }, headers=cand1_headers)
    assert ans2.status_code == 200

    # 11. Candidate 1 submits test
    sub_res = client.post(f"/api/assessments/{direct_token}/submit", json={
        "answers": {
            str(questions[0]["id"]): 0,
            str(questions[1]["id"]): 1,
        },
    }, headers=cand1_headers)
    assert sub_res.status_code == 200
    assert "message" in sub_res.json()

    # Retake prevented
    assert client.post(f"/api/assessments/{direct_token}/start", headers=cand1_headers).status_code == 409
    assert client.post(f"/api/assessments/{direct_token}/submit", json={}, headers=cand1_headers).status_code == 409

    # Launch endpoint reports already completed
    assert client.get(f"/api/assessments/application/{app1['id']}/token", headers=cand1_headers).status_code == 409

    # 12. Recruiter checks Assessment Results
    rec_results = client.get("/api/recruiter/assessment-results", headers=rec_headers)
    assert rec_results.status_code == 200
    res_list = rec_results.json()
    assert len(res_list) == 1
    row = res_list[0]
    assert row["test_status"] == "submitted"
    assert row["obtained_marks"] == 10
    assert row["total_marks"] == 10
    assert row["is_passed"] is True
    assert row["result_status"] == "Selected for next round"
    assert row["submitted_at"] is not None
    assert row["proctoring_event_count"] == 2

    # Recruiter views detailed answers and proctoring audit log
    detail_res = client.get(f"/api/recruiter/assessment-results/{row['assignment_id']}", headers=rec_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["proctoring_event_count"] == 2
    assert len(detail["proctoring_events"]) == 2
    assert detail["proctoring_events"][0]["event_type"] in ("tab_switch", "window_blur")
    assert len(detail["questions"]) == 2
    assert detail["questions"][0]["is_correct"] is True
    assert detail["questions"][1]["is_correct"] is True


def test_assessment_strict_passing_and_expired_and_submitted_guards(
    client: TestClient, database, smtp_outbox
):
    admin_headers = _create_admin(client, database, smtp_outbox, email="audit-admin2@example.com")
    rec_headers, job_id = _setup_recruiter_and_job(client, database, smtp_outbox, email="audit-rec2@example.com")

    # Create 2 questions with 5 marks each (total = 10, passing = 5)
    q1 = client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "Python",
        "category": "Backend",
        "difficulty": "Easy",
        "question_text": "Is Python dynamically typed?",
        "options": ["Yes", "No", "Only in 2.7", "None"],
        "correct_option_index": 0,
        "marks": 5,
    }, headers=admin_headers).json()["id"]

    q2 = client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "FastAPI",
        "category": "Backend",
        "difficulty": "Easy",
        "question_text": "Is FastAPI built on Starlette?",
        "options": ["Yes", "No", "Django", "Flask"],
        "correct_option_index": 0,
        "marks": 5,
    }, headers=admin_headers).json()["id"]

    # Passing marks = 5. Strict > rule: 5 > 5 is False!
    assessment_res = client.post("/api/recruiter/assessments", json={
        "job_id": job_id,
        "title": "Strict Passing Test",
        "description": "Verify strictly greater than passing marks",
        "instructions": "Test instructions",
        "duration_minutes": 20,
        "passing_marks": 5,
        "expires_at": (utc_now() + timedelta(days=2)).isoformat(),
        "question_ids": [q1, q2],
        "status": "published",
    }, headers=rec_headers)
    assert assessment_res.status_code == 201
    assessment_id = assessment_res.json()["id"]

    # Register candidate and ensure candidate is shortlisted
    cand_token = register_and_login(client, "borderline-cand@example.com", "candidate", smtp_outbox)
    cand_headers = {"Authorization": f"Bearer {cand_token}"}
    client.put("/api/candidates/me", json={"skills": ["Python", "FastAPI", "SQL"], "experience": "3 years Python"}, headers=cand_headers)
    app_id = client.post(f"/api/jobs/{job_id}/apply", headers=cand_headers).json()["id"]
    client.put(f"/api/applications/{app_id}/status", json={"status": "shortlisted"}, headers=rec_headers)

    # Assign
    assign_res = client.post(
        f"/api/recruiter/assessments/{assessment_id}/assign",
        json={"application_ids": [app_id]},
        headers=rec_headers,
    )
    assert assign_res.status_code == 200

    # Get launch token
    launch_data = client.get(f"/api/assessments/application/{app_id}/token", headers=cand_headers).json()
    test_token = launch_data["token"]

    # Candidate starts test
    client.post(f"/api/assessments/{test_token}/start", headers=cand_headers)

    # Candidate answers ONLY question 1 correctly (5 marks awarded). Question 2 wrong.
    # Obtained = 5, Passing = 5 -> Strict 5 > 5 is False -> NOT QUALIFIED
    client.post(f"/api/assessments/{test_token}/submit", json={
        "answers": {
            str(q1): 0,  # correct
            str(q2): 1,  # wrong
        },
    }, headers=cand_headers)

    # Verify recruiter outcome
    results = client.get("/api/recruiter/assessment-results", headers=rec_headers).json()
    cand_row = next(r for r in results if r["candidate_email"] == "borderline-cand@example.com")
    assert cand_row["obtained_marks"] == 5
    assert cand_row["total_marks"] == 10
    assert cand_row["is_passed"] is False
    assert cand_row["result_status"] == "Not qualified"

    # Verify launch endpoint returns 409 now that test is submitted
    sub_launch = client.get(f"/api/assessments/application/{app_id}/token", headers=cand_headers)
    assert sub_launch.status_code == 409
