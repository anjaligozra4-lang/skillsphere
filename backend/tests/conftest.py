import os
import re

os.environ["SKILLSPHERE_TESTING"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.database import Base, get_db
from app.main import app


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
def smtp_outbox(monkeypatch):
    sent_messages: list[dict] = []

    class DummySMTP:
        def __init__(self, host, port, timeout=15):
            self.host = host
            self.port = port

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def ehlo(self):
            return (250, b"ok")

        def starttls(self):
            return (220, b"ready")

        def login(self, user, password):
            return (235, b"auth ok")

        def send_message(self, message):
            body_text = ""
            if message.is_multipart():
                for part in message.walk():
                    if part.get_content_type() == "text/plain":
                        body_text = part.get_content()
                        break
            else:
                body_text = message.get_content()
            sent_messages.append({
                "to": message["To"],
                "subject": message["Subject"],
                "text": body_text,
            })
            return {}

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.test.local")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "noreply@test.local")
    monkeypatch.setattr(settings, "smtp_password", "test-smtp-secret")
    monkeypatch.setattr(settings, "smtp_from_email", "noreply@test.local")
    monkeypatch.setattr(settings, "smtp_from_name", "SkillSphere")
    monkeypatch.setattr("app.email_service.smtplib.SMTP", DummySMTP)
    monkeypatch.setattr("app.email_service.smtplib.SMTP_SSL", DummySMTP)
    return sent_messages


@pytest.fixture
def client(database, smtp_outbox):
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


def login_with_otp(client: TestClient, smtp_outbox: list[dict], email: str, password: str) -> dict:
    login = client.post("/api/auth/login", json={
        "email": email,
        "password": password,
    })
    assert login.status_code == 200
    data = login.json()
    assert data.get("access_token")
    assert data.get("refresh_token")
    assert "otp_required" not in data
    assert "challenge_token" not in data
    return data


def register_and_login(client: TestClient, email: str, role: str, smtp_outbox: list[dict]) -> str:
    registration = client.post("/api/auth/register", json={
        "full_name": f"Test {role.title()}",
        "email": email,
        "password": "StrongPass123",
        "role": role,
    })
    assert registration.status_code == 201
    return login_with_otp(client, smtp_outbox, email, "StrongPass123")["access_token"]
