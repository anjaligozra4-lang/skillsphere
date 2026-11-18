from pathlib import Path
import re

p = Path("tests/test_enhancements.py")
s = p.read_text(encoding="utf-8")

replacements = {
"test_latest_login_otp_replaces_prior_challenge_and_accepts_trimmed_code": '''def test_latest_login_otp_replaces_prior_challenge_and_accepts_trimmed_code(
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
''',
"test_otp_login_security_cooldown_lockout_expiry_and_refresh": '''def test_otp_login_security_cooldown_lockout_expiry_and_refresh(
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
'''
}

for name, replacement in replacements.items():
    pattern = rf"^def {re.escape(name)}\(.*?(?=^def |\Z)"
    s, count = re.subn(pattern, replacement + "\n\n", s, count=1, flags=re.M | re.S)
    if count != 1:
        raise RuntimeError(f"Expected exactly one function: {name}; found {count}")

p.write_text(s, encoding="utf-8")
print("Both OTP tests replaced successfully.")
