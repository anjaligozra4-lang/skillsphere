from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models import Candidate, Company, Recruiter, User
from tests.conftest import register_and_login


def test_recruiter_profile_self_healing_without_initial_row(client: TestClient, database):
    """
    Ensure that a recruiter user who has no row in the recruiters table
    can call recruiter endpoints without encountering an HTTP 500 AttributeError.
    The backend self-heals by creating the Recruiter record automatically.
    """
    with database() as db:
        user = User(
            email="orphaned-recruiter@example.com",
            password_hash=hash_password("StrongPassword123!"),
            full_name="Orphaned Recruiter",
            role="recruiter",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

        # Verify no Recruiter record exists initially
        assert db.scalar(select(Recruiter).where(Recruiter.user_id == user_id)) is None

    token = create_access_token(str(user_id), "recruiter")
    headers = {"Authorization": f"Bearer {token}"}

    # Calling jobs and stats should succeed (not 500)
    jobs_res = client.get("/api/recruiters/jobs", headers=headers)
    assert jobs_res.status_code == 200
    assert jobs_res.json() == []

    stats_res = client.get("/api/recruiters/stats", headers=headers)
    assert stats_res.status_code == 200
    assert "jobs" in stats_res.json()
    assert stats_res.json()["jobs"] == 0

    # Verify that the Recruiter profile record was self-healed and created
    with database() as db:
        recruiter = db.scalar(select(Recruiter).where(Recruiter.user_id == user_id))
        assert recruiter is not None
        assert recruiter.user_id == user_id


def test_candidate_profile_self_healing(client: TestClient, database):
    """
    Ensure that a candidate user without a Candidate table row gets
    transparently self-healed when requesting their profile.
    """
    with database() as db:
        user = User(
            email="orphaned-candidate@example.com",
            password_hash=hash_password("StrongPassword123!"),
            full_name="Orphaned Candidate",
            role="candidate",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

        assert db.scalar(select(Candidate).where(Candidate.user_id == user_id)) is None

    token = create_access_token(str(user_id), "candidate")
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/candidates/me", headers=headers)
    assert res.status_code == 200
    assert res.json()["id"] is not None

    with database() as db:
        candidate = db.scalar(select(Candidate).where(Candidate.user_id == user_id))
        assert candidate is not None
        assert candidate.user_id == user_id


def test_recruiter_company_creation_and_approval_workflow(client: TestClient, database, smtp_outbox):
    """
    Test the full recruiter lifecycle:
    1. New recruiter registration & login
    2. Attempting to post job without company -> 400
    3. Creating company profile (initially is_approved=False)
    4. Attempting to post job with unapproved company -> 403
    5. Admin approves company
    6. Recruiter posts job successfully -> 200/201 (pending approval)
    """
    token = register_and_login(client, "newrecruiter@example.com", "recruiter", smtp_outbox)
    headers = {"Authorization": f"Bearer {token}"}

    job_payload = {
        "title": "Senior Cloud Architect",
        "description": "Design and deploy scalable cloud microservices.",
        "location": "Remote",
        "employment_type": "full_time",
        "experience_min": 5,
        "experience_max": 10,
        "salary_min": 120000,
        "salary_max": 180000,
        "salary_currency": "USD",
        "skills": ["AWS", "Docker", "Kubernetes"],
    }

    # Step 2: Cannot post job without company profile
    no_comp_res = client.post("/api/recruiters/jobs", json=job_payload, headers=headers)
    assert no_comp_res.status_code == 400
    assert "company" in no_comp_res.json()["detail"].lower()

    # Step 3: Create company profile
    company_res = client.post("/api/companies", json={
        "name": "CloudWorks Technologies",
        "website": "https://cloudworks.example.com",
        "location": "San Francisco, CA",
        "description": "Leading cloud solutions provider",
    }, headers=headers)
    assert company_res.status_code == 200
    company_data = company_res.json()
    assert company_data["name"] == "CloudWorks Technologies"

    # Check /api/companies/me returns the company with is_approved=False
    my_company_res = client.get("/api/companies/me", headers=headers)
    assert my_company_res.status_code == 200
    assert my_company_res.json()["id"] == company_data["id"]
    assert my_company_res.json()["is_approved"] is False

    # Step 4: Cannot post job while company is unapproved
    unapproved_res = client.post("/api/recruiters/jobs", json=job_payload, headers=headers)
    assert unapproved_res.status_code == 403
    assert "approved" in unapproved_res.json()["detail"].lower()

    # Step 5: Admin approves company
    with database() as db:
        company = db.get(Company, company_data["id"])
        company.is_approved = True
        db.commit()

    # Step 6: Recruiter posts job successfully
    success_res = client.post("/api/recruiters/jobs", json=job_payload, headers=headers)
    assert success_res.status_code in (200, 201)
    job_info = success_res.json()
    assert "id" in job_info
    assert job_info["status"] == "pending"

    # Verify job appears in recruiter's job list
    my_jobs_res = client.get("/api/recruiters/jobs", headers=headers)
    assert my_jobs_res.status_code == 200
    job_ids = [j["id"] for j in my_jobs_res.json()]
    assert job_info["id"] in job_ids


def test_recruiter_role_access_boundaries(client: TestClient, smtp_outbox):
    """
    Verify RBAC security:
    - Candidate cannot call recruiter endpoints.
    - Recruiter cannot call admin endpoints.
    """
    cand_token = register_and_login(client, "test-candidate-rbac@example.com", "candidate", smtp_outbox)
    cand_headers = {"Authorization": f"Bearer {cand_token}"}

    # Candidate trying recruiter endpoints -> 403
    cand_jobs_res = client.get("/api/recruiters/jobs", headers=cand_headers)
    assert cand_jobs_res.status_code == 403

    cand_stats_res = client.get("/api/recruiters/stats", headers=cand_headers)
    assert cand_stats_res.status_code == 403

    rec_token = register_and_login(client, "test-recruiter-rbac@example.com", "recruiter", smtp_outbox)
    rec_headers = {"Authorization": f"Bearer {rec_token}"}

    # Recruiter trying admin endpoints -> 403
    rec_admin_stats = client.get("/api/admin/stats", headers=rec_headers)
    assert rec_admin_stats.status_code == 403

    rec_admin_users = client.get("/api/admin/users", headers=rec_headers)
    assert rec_admin_users.status_code == 403
