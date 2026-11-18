from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password, utc_now
from app.models import Company, Job, User
from tests.conftest import register_and_login


def _setup_recruiter_and_job(client: TestClient, database, smtp_outbox, email="rec-workflow@example.com"):
    token = register_and_login(client, email, "recruiter", smtp_outbox)
    headers = {"Authorization": f"Bearer {token}"}
    company_res = client.post("/api/companies", json={"name": f"WorkflowCo-{email}"}, headers=headers)
    assert company_res.status_code == 200
    with database() as db:
        comp = db.get(Company, company_res.json()["id"])
        comp.is_approved = True
        db.commit()

    job_res = client.post(
        "/api/jobs",
        json={
            "title": "Full-Stack Python Engineer",
            "description": "Develop modern web applications with Python, FastAPI, and React.",
            "location": "Bengaluru",
            "employment_type": "full_time",
            "experience_min": 2,
            "experience_max": 6,
            "skills": ["Python", "FastAPI", "React"],
        },
        headers=headers,
    )
    assert job_res.status_code == 201
    job_id = job_res.json()["id"]
    with database() as db:
        db.get(Job, job_id).status = "published"
        db.commit()
    return headers, job_id


def _create_admin(client: TestClient, database, smtp_outbox, email="workflow-admin@example.com"):
    with database() as db:
        if not db.scalar(select(User).where(User.email == email)):
            db.add(User(
                email=email,
                password_hash=hash_password("StrongPass123"),
                full_name="Workflow Admin",
                role="admin",
                is_active=True,
            ))
            db.commit()
    from tests.conftest import login_with_otp
    session = login_with_otp(client, smtp_outbox, email, "StrongPass123")
    return {"Authorization": f"Bearer {session['access_token']}"}


def test_recruiter_assessment_workflow_end_to_end_23_steps(
    client: TestClient, database, smtp_outbox
):
    admin_headers = _create_admin(client, database, smtp_outbox)
    rec_headers, job_id = _setup_recruiter_and_job(client, database, smtp_outbox)

    # 1. Admin adds 3 technical MCQs to centralized question bank
    q1 = client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "Python",
        "category": "Core",
        "difficulty": "Easy",
        "question_text": "Which Python keyword defines a generator function?",
        "options": ["yield", "return", "generate", "async"],
        "correct_option_index": 0,
        "marks": 5,
    }, headers=admin_headers)
    assert q1.status_code == 201
    q1_id = q1.json()["id"]

    q2 = client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "FastAPI",
        "category": "API",
        "difficulty": "Medium",
        "question_text": "Which tool does FastAPI use for data validation and OpenAPI schema?",
        "options": ["Pydantic", "Marshmallow", "Cerberus", "Schema"],
        "correct_option_index": 0,
        "marks": 5,
    }, headers=admin_headers)
    assert q2.status_code == 201
    q2_id = q2.json()["id"]

    q3 = client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "React",
        "category": "Frontend",
        "difficulty": "Medium",
        "question_text": "Which hook is used for side effects in React function components?",
        "options": ["useEffect", "useState", "useMemo", "useContext"],
        "correct_option_index": 0,
        "marks": 5,
    }, headers=admin_headers)
    assert q3.status_code == 201
    q3_id = q3.json()["id"]

    # 2. Recruiter attempts to publish an empty assessment -> Rejected with 422
    empty_pub = client.post("/api/recruiter/assessments", json={
        "job_id": job_id,
        "title": "Empty Assessment",
        "instructions": "No questions here.",
        "duration_minutes": 30,
        "passing_marks": 5,
        "question_ids": [],
        "status": "published",
    }, headers=rec_headers)
    assert empty_pub.status_code == 422
    assert "at least 1 MCQ question" in empty_pub.json()["detail"]

    # 3. Recruiter attempts to publish with passing_marks >= total_marks -> Rejected with 422
    invalid_marks = client.post("/api/recruiter/assessments", json={
        "job_id": job_id,
        "title": "Invalid Marks Test",
        "instructions": "All marks needed.",
        "duration_minutes": 30,
        "passing_marks": 10,  # total marks of [q1] is 5, 10 >= 5
        "question_ids": [q1_id],
        "status": "published",
    }, headers=rec_headers)
    assert invalid_marks.status_code == 422
    assert "strictly less than total marks" in invalid_marks.json()["detail"]

    # 4. Recruiter creates an assessment and saves as DRAFT (with tentative past expiry)
    past_date = (utc_now() - timedelta(days=2)).isoformat()
    draft_res = client.post("/api/recruiter/assessments", json={
        "job_id": job_id,
        "title": "Technical Round 1 Assessment",
        "description": "Comprehensive screening for Python and FastAPI",
        "instructions": "Answer all 2 questions carefully within 30 minutes.",
        "duration_minutes": 30,
        "passing_marks": 5,
        "expires_at": past_date,  # Created in the past as a draft
        "question_ids": [q1_id, q2_id],
        "status": "draft",
    }, headers=rec_headers)
    assert draft_res.status_code == 201
    draft_data = draft_res.json()
    assessment_id = draft_data["id"]
    assert draft_data["status"] == "draft"
    assert draft_data["total_questions"] == 2
    assert draft_data["total_marks"] == 10
    assert "job_skills" in draft_data
    assert "covered_skills" in draft_data
    assert "Python" in draft_data["covered_skills"]
    assert "FastAPI" in draft_data["covered_skills"]
    assert "React" in draft_data["missing_skills"]

    # 5. Recruiter reopens and edits draft: adds q3 (covering React) and reorders questions
    edit_res = client.put(f"/api/recruiter/assessments/{assessment_id}", json={
        "job_id": job_id,
        "title": "Technical Round 1 Assessment - Revised",
        "description": "Comprehensive screening for Python, FastAPI, and React",
        "instructions": "Answer all 3 questions carefully within 45 minutes.",
        "duration_minutes": 45,
        "passing_marks": 9,  # total marks = 15, passing = 9 (> 9 means 10+ to pass)
        "expires_at": None,
        "question_ids": [q3_id, q1_id, q2_id],  # Reordered: React first, Python second, FastAPI third
        "status": "draft",
    }, headers=rec_headers)
    assert edit_res.status_code == 200
    revised_data = edit_res.json()
    assert revised_data["total_questions"] == 3
    assert revised_data["total_marks"] == 15
    assert revised_data["missing_skills"] == []  # All 3 skills now covered!

    # 6. Recruiter publishes the assessment via POST /api/recruiter/assessments/{id}/publish
    pub_res = client.post(f"/api/recruiter/assessments/{assessment_id}/publish", headers=rec_headers)
    assert pub_res.status_code == 200
    assert pub_res.json()["status"] == "published"

    # 7. Recruiter verifies it appears in Published Assessments list
    list_res = client.get("/api/recruiter/assessments", headers=rec_headers)
    assert list_res.status_code == 200
    published_items = [a for a in list_res.json() if a["status"] == "published"]
    assert any(a["id"] == assessment_id for a in published_items)

    # 8. Candidate 1 applies and is shortlisted
    cand1_token = register_and_login(client, "workflow-cand1@example.com", "candidate", smtp_outbox)
    cand1_headers = {"Authorization": f"Bearer {cand1_token}"}
    client.put("/api/candidates/me", json={
        "education": "B.Tech Computer Science",
        "experience": "4 years full stack Python React",
        "skills": ["Python", "FastAPI", "React"],
    }, headers=cand1_headers)
    app1 = client.post(f"/api/jobs/{job_id}/apply", headers=cand1_headers).json()
    assert app1["status"] == "shortlisted"

    # Candidate 2 applies and is NOT shortlisted (status="applied")
    cand2_token = register_and_login(client, "workflow-cand2@example.com", "candidate", smtp_outbox)
    cand2_headers = {"Authorization": f"Bearer {cand2_token}"}
    app2 = client.post(f"/api/jobs/{job_id}/apply", headers=cand2_headers).json()
    with database() as db:
        from app.models import Application
        db.get(Application, app2["id"]).status = "applied"
        db.commit()

    # 9. Recruiter attempts to assign to non-shortlisted Candidate 2 -> Rejected with 409
    ineligible_assign = client.post(
        f"/api/recruiter/assessments/{assessment_id}/assign",
        json={"application_ids": [app2["id"]]},
        headers=rec_headers,
    )
    assert ineligible_assign.status_code == 409
    assert "Only shortlisted candidates can be assigned" in ineligible_assign.json()["detail"]

    # 10. Recruiter assigns published assessment to shortlisted Candidate 1
    assign_res = client.post(
        f"/api/recruiter/assessments/{assessment_id}/assign",
        json={"application_ids": [app1["id"]]},
        headers=rec_headers,
    )
    assert assign_res.status_code == 200
    assert assign_res.json()["assigned_count"] == 1
    assignment_id = assign_res.json()["results"][0]["assignment_id"]

    # 11. Duplicate assignment check -> Skipped safely
    dup_assign = client.post(
        f"/api/recruiter/assessments/{assessment_id}/assign",
        json={"application_ids": [app1["id"]]},
        headers=rec_headers,
    )
    assert dup_assign.status_code == 200
    assert dup_assign.json()["skipped_count"] == 1

    # 12. Candidate logs in, checks My Applications, and retrieves assessment launch token
    my_apps = client.get("/api/applications/me", headers=cand1_headers)
    assert my_apps.status_code == 200
    app_data = next(a for a in my_apps.json() if a["id"] == app1["id"])
    assert app_data["assessment_status"] == "assigned"
    launch_token = app_data["assessment_token"]
    assert launch_token is not None

    # 13. Candidate fetches invitation metadata using launch token
    info_res = client.get(f"/api/assessments/{launch_token}", headers=cand1_headers)
    assert info_res.status_code == 200
    assert info_res.json()["title"] == "Technical Round 1 Assessment - Revised"
    assert info_res.json()["total_questions"] == 3

    # Candidate 2 cannot access Candidate 1's test portal -> 403 Forbidden
    assert client.get(f"/api/assessments/{launch_token}", headers=cand2_headers).status_code == 403

    # 14. Candidate starts the assessment
    start_res = client.post(f"/api/assessments/{launch_token}/start", headers=cand1_headers)
    assert start_res.status_code == 200
    start_data = start_res.json()
    questions = start_data["questions"]
    assert len(questions) == 3

    # 15. Candidate answers: 2 correct (5+5 = 10 marks), 1 wrong (0 marks)
    # Total marks = 15, passing_marks = 9. Since 10 > 9, candidate qualifies!
    q_map = {q["order_index"]: q["id"] for q in questions}
    # q[1] is React (option 0 is correct)
    save1 = client.put(f"/api/assessments/{launch_token}/answer", json={
        "question_id": q_map[1],
        "selected_option_index": 0,
    }, headers=cand1_headers)
    assert save1.status_code == 200

    # q[2] is Python (option 0 is correct)
    save2 = client.put(f"/api/assessments/{launch_token}/answer", json={
        "question_id": q_map[2],
        "selected_option_index": 0,
    }, headers=cand1_headers)
    assert save2.status_code == 200

    # q[3] is FastAPI (option 1 is wrong, correct is 0)
    save3 = client.put(f"/api/assessments/{launch_token}/answer", json={
        "question_id": q_map[3],
        "selected_option_index": 1,
    }, headers=cand1_headers)
    assert save3.status_code == 200

    # 16. Log proctoring events during test
    evt1 = client.post(f"/api/assessments/{launch_token}/proctoring-events", json={
        "event_type": "tab_switch",
        "details": {"reason": "switched tabs"},
    }, headers=cand1_headers)
    assert evt1.status_code == 200

    evt2 = client.post(f"/api/assessments/{launch_token}/proctoring-events", json={
        "event_type": "window_blur",
        "details": {},
    }, headers=cand1_headers)
    assert evt2.status_code == 200

    # 17. Candidate submits assessment
    submit_res = client.post(f"/api/assessments/{launch_token}/submit", json={
        "answers": {
            str(q_map[1]): 0,
            str(q_map[2]): 0,
            str(q_map[3]): 1,
        },
        "auto_submitted": False,
    }, headers=cand1_headers)
    assert submit_res.status_code == 200
    # Candidate-facing response preserves privacy: no answers or score leaked
    assert "submitted successfully" in submit_res.json()["message"]

    # 18. Prevent retake after submission -> 409 Conflict
    retake_res = client.post(f"/api/assessments/{launch_token}/start", headers=cand1_headers)
    assert retake_res.status_code == 409

    # 19. Recruiter checks Assessment Results list
    results_res = client.get("/api/recruiter/assessment-results", headers=rec_headers)
    assert results_res.status_code == 200
    rec_results = results_res.json()
    result_row = next(r for r in rec_results if r["assignment_id"] == assignment_id)
    assert result_row["candidate_name"] == "Workflow Candidate" or "workflow-cand1" in result_row["candidate_email"]
    assert result_row["assessment_title"] == "Technical Round 1 Assessment - Revised"
    assert result_row["obtained_marks"] == 10
    assert result_row["total_marks"] == 15
    assert result_row["passing_marks"] == 9
    assert result_row["is_passed"] is True
    assert result_row["result_status"] == "Selected for next round"
    assert result_row["test_status"] == "submitted"
    assert result_row["proctoring_event_count"] >= 2

    # 20. Recruiter opens detailed answers & submission review
    detail_res = client.get(f"/api/recruiter/assessment-results/{assignment_id}", headers=rec_headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["obtained_marks"] == 10
    assert detail["total_marks"] == 15
    assert len(detail["questions"]) == 3
    assert len(detail["proctoring_events"]) >= 2
    # Verify submitted answers are recorded with correctness
    q1_detail = next(q for q in detail["questions"] if q["order_index"] == 1)
    assert q1_detail["is_correct"] is True
    assert q1_detail["marks_awarded"] == 5

    q3_detail = next(q for q in detail["questions"] if q["order_index"] == 3)
    assert q3_detail["is_correct"] is False
    assert q3_detail["marks_awarded"] == 0

    # 21. Deletion guard: cannot delete assessment once assigned
    del_res = client.delete(f"/api/recruiter/assessments/{assessment_id}", headers=rec_headers)
    assert del_res.status_code == 409
    assert "cannot be deleted" in del_res.json()["detail"]


def test_recruiter_ai_question_generation_fallback(
    client: TestClient, database, smtp_outbox
):
    rec_headers, job_id = _setup_recruiter_and_job(client, database, smtp_outbox, email="rec-ai-gen@example.com")

    # Generate questions with curated bank fallback
    gen_res = client.post("/api/recruiter/question-bank/generate", json={
        "job_id": job_id,
        "skills": ["Python"],
        "difficulty": "Medium",
        "question_count": 3,
        "marks": 2,
    }, headers=rec_headers)
    assert gen_res.status_code == 201
    items = gen_res.json()["items"]
    assert len(items) == 3
    for item in items:
        assert item["skill"] == "Python"
        assert len(item["options"]) == 4
        assert item["is_editable"] is True

    # Recruiter edits the generated question
    q_id = items[0]["id"]
    edit_res = client.put(f"/api/recruiter/question-bank/{q_id}", json={
        "question_type": "mcq",
        "skill": "Python",
        "category": "AI Generated",
        "difficulty": "Medium",
        "question_text": "Updated question text for Python",
        "options": ["A", "B", "C", "D"],
        "correct_option_index": 2,
        "marks": 3,
    }, headers=rec_headers)
    assert edit_res.status_code == 200
    assert edit_res.json()["question_text"] == "Updated question text for Python"
    assert edit_res.json()["marks"] == 3


def test_recruiter_assessment_link_expiry_and_resend(
    client: TestClient, database, smtp_outbox
):
    rec_headers, job_id = _setup_recruiter_and_job(client, database, smtp_outbox, email="rec-resend@example.com")
    admin_headers = _create_admin(client, database, smtp_outbox, email="admin-resend@example.com")

    q = client.post("/api/admin/question-bank", json={
        "question_type": "mcq",
        "skill": "Python",
        "category": "Core",
        "difficulty": "Easy",
        "question_text": "What is Python's boolean type?",
        "options": ["bool", "boolean", "bit", "binary"],
        "correct_option_index": 0,
        "marks": 2,
    }, headers=admin_headers)
    q_id = q.json()["id"]

    pub = client.post("/api/recruiter/assessments", json={
        "job_id": job_id,
        "title": "Quick Expiry Test",
        "instructions": "Answer quickly.",
        "duration_minutes": 10,
        "passing_marks": 0,
        "question_ids": [q_id],
        "status": "published",
    }, headers=rec_headers)
    assert pub.status_code == 201
    assessment_id = pub.json()["id"]

    cand_token = register_and_login(client, "cand-resend@example.com", "candidate", smtp_outbox)
    cand_headers = {"Authorization": f"Bearer {cand_token}"}
    client.put("/api/candidates/me", json={
        "education": "BS",
        "experience": "1 yr",
        "skills": ["Python"],
    }, headers=cand_headers)
    app = client.post(f"/api/jobs/{job_id}/apply", headers=cand_headers).json()
    with database() as db:
        from app.models import Application
        db.get(Application, app["id"]).status = "shortlisted"
        db.commit()

    assign = client.post(
        f"/api/recruiter/assessments/{assessment_id}/assign",
        json={"application_ids": [app["id"]]},
        headers=rec_headers,
    )
    assert assign.status_code == 200
    assignment_id = assign.json()["results"][0]["assignment_id"]

    # Manually expire the assignment in DB
    with database() as db:
        from app.models import AssessmentAssignment
        a = db.get(AssessmentAssignment, assignment_id)
        a.expires_at = utc_now() - timedelta(hours=1)
        db.commit()

    # Recruiter resends assignment invitation -> automatically extends deadline
    resend = client.post(f"/api/recruiter/assignments/{assignment_id}/resend", headers=rec_headers)
    assert resend.status_code == 200
    assert resend.json()["assignment_id"] == assignment_id

    # Verify new expiry is in the future
    with database() as db:
        from app.core.security import ensure_utc
        from app.models import AssessmentAssignment
        a = db.get(AssessmentAssignment, assignment_id)
        assert ensure_utc(a.expires_at) > utc_now()

