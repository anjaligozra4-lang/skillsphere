import logging
import secrets
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.database import SessionLocal
from app.main import app
from app.models import Candidate, User
from app.seed import ensure_admin


@pytest.fixture
def auth_client():
    return TestClient(app)


def test_admin_seeding_without_password_skips_safely(caplog):
    """
    When ADMIN_PASSWORD is empty or not configured, ensure_admin must:
    1. Log a clear warning explaining ADMIN_PASSWORD is not set.
    2. Safely return without raising exceptions.
    3. Not create or modify accounts with empty/dummy passwords.
    """
    settings = get_settings()
    original_pass = settings.admin_password
    settings.admin_password = ""

    try:
        with SessionLocal() as db, caplog.at_level(logging.WARNING):
            ensure_admin(db)

        warning_found = any(
            "ADMIN_PASSWORD environment variable is not configured" in record.message
            for record in caplog.records
        )
        assert warning_found, "A clear warning must be logged when ADMIN_PASSWORD is not set"
    finally:
        settings.admin_password = original_pass


def test_admin_seeding_with_configured_password_creates_admin():
    """
    When ADMIN_PASSWORD (and optionally ADMIN_EMAIL) is set via environment,
    ensure_admin creates the admin account with properly hashed password.
    """
    settings = get_settings()
    original_email = settings.admin_email
    original_pass = settings.admin_password
    original_name = settings.admin_full_name

    test_admin_email = f"testadmin_{secrets.token_hex(4)}@example.com"
    test_admin_pass = f"TestPass_{secrets.token_hex(6)}!A1"
    test_admin_name = "Test Administrator"

    settings.admin_email = test_admin_email
    settings.admin_password = test_admin_pass
    settings.admin_full_name = test_admin_name

    try:
        with SessionLocal() as db:
            ensure_admin(db)
            admin = db.scalar(select(User).where(func.lower(User.email) == test_admin_email.lower()))

            assert admin is not None, f"Admin account {test_admin_email} should be created"
            assert admin.role == "admin"
            assert admin.is_active is True
            assert admin.full_name == test_admin_name
            assert verify_password(test_admin_pass, admin.password_hash)
    finally:
        settings.admin_email = original_email
        settings.admin_password = original_pass
        settings.admin_full_name = original_name


def test_admin_seeding_does_not_overwrite_existing_passwords():
    """
    If a user already exists in the database, ensure_admin must NOT overwrite
    their existing password hash.
    """
    settings = get_settings()
    original_email = settings.admin_email
    original_pass = settings.admin_password

    existing_email = f"existing_user_{secrets.token_hex(4)}@example.com"
    existing_initial_pass = f"InitialSecret_{secrets.token_hex(4)}!1"
    new_admin_pass = f"NewAttemptedSecret_{secrets.token_hex(4)}!2"

    with SessionLocal() as db:
        user = User(
            email=existing_email,
            password_hash=hash_password(existing_initial_pass),
            full_name="Existing User",
            role="recruiter",
            is_active=True,
        )
        db.add(user)
        db.commit()

    settings.admin_email = existing_email
    settings.admin_password = new_admin_pass

    try:
        with SessionLocal() as db:
            ensure_admin(db)
            user_after = db.scalar(select(User).where(func.lower(User.email) == existing_email))

            assert user_after is not None
            assert user_after.role == "admin"
            # Crucial assertion: original password must still verify, new password must NOT
            assert verify_password(existing_initial_pass, user_after.password_hash), (
                "Existing user's original password must NOT be overwritten by seeding!"
            )
            assert not verify_password(new_admin_pass, user_after.password_hash), (
                "New password must not have replaced the existing password hash"
            )
    finally:
        settings.admin_email = original_email
        settings.admin_password = original_pass


def test_candidate_registration_and_login_flow(auth_client: TestClient):
    """
    Newly registered candidates must be able to sign up and log in cleanly.
    """
    test_email = f"candidate_{secrets.token_hex(4)}@example.com"
    test_pass = f"ValidPass_{secrets.token_hex(6)}!1"

    # Register
    reg_resp = auth_client.post("/api/auth/register", json={
        "full_name": "Test Candidate User",
        "email": test_email,
        "password": test_pass,
        "role": "candidate",
    })
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert reg_data["email"] == test_email
    assert reg_data["role"] == "candidate"

    # Verify Candidate profile row exists
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == test_email))
        assert user is not None
        cand = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
        assert cand is not None, "Candidate profile record must be created"

    # Login
    login_resp = auth_client.post("/api/auth/login", json={
        "email": test_email,
        "password": test_pass,
    })
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["role"] == "candidate"
    assert "access_token" in login_data


def test_email_case_insensitivity_on_login(auth_client: TestClient):
    """
    Login must be case-insensitive to prevent uppercase/lowercase mismatches.
    """
    test_email = f"case_test_{secrets.token_hex(4)}@example.com"
    test_pass = f"CasePass_{secrets.token_hex(6)}!1"

    # Register with lower case
    reg_resp = auth_client.post("/api/auth/register", json={
        "full_name": "Case Test User",
        "email": test_email.lower(),
        "password": test_pass,
        "role": "candidate",
    })
    assert reg_resp.status_code == 201

    # Login with UPPER CASE email
    upper_resp = auth_client.post("/api/auth/login", json={
        "email": test_email.upper(),
        "password": test_pass,
    })
    assert upper_resp.status_code == 200
    assert upper_resp.json()["role"] == "candidate"

    # Login with Mixed Case email
    mixed_email = test_email.capitalize()
    mixed_resp = auth_client.post("/api/auth/login", json={
        "email": mixed_email,
        "password": test_pass,
    })
    assert mixed_resp.status_code == 200


def test_invalid_password_returns_401(auth_client: TestClient):
    """
    Login with wrong password must return 401 with standard detail.
    """
    test_email = f"invalid_test_{secrets.token_hex(4)}@example.com"
    test_pass = f"CorrectPass_{secrets.token_hex(6)}!1"

    auth_client.post("/api/auth/register", json={
        "full_name": "Invalid Pass Tester",
        "email": test_email,
        "password": test_pass,
        "role": "candidate",
    })

    resp = auth_client.post("/api/auth/login", json={
        "email": test_email,
        "password": "WrongPassword999!",
    })
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"
