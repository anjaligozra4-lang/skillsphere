from pathlib import Path

p = Path("tests/test_enhancements.py")
s = p.read_text(encoding="utf-8")

old1 = '''        failed_login = client.post(
            "/api/auth/login",
            json={"email": "envreload@example.com", "password": "StrongPass123"},
        )
        assert failed_login.status_code == 503
        assert "SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL" in failed_login.json()["detail"]
'''

new1 = '''        direct_login = client.post(
            "/api/auth/login",
            json={"email": "envreload@example.com", "password": "StrongPass123"},
        )
        assert direct_login.status_code == 200
        assert direct_login.json()["access_token"]
        assert direct_login.json()["refresh_token"]
        assert "otp_required" not in direct_login.json()
'''

old2 = '''        smtp_outbox.clear()
        ok_login = client.post(
            "/api/auth/login",
            json={"email": "envreload@example.com", "password": "StrongPass123"},
        )
        assert ok_login.status_code == 200
        assert ok_login.json()["otp_required"] is True
        assert len(smtp_outbox) == 1
'''

new2 = '''        smtp_outbox.clear()
        ok_login = client.post(
            "/api/auth/login",
            json={"email": "envreload@example.com", "password": "StrongPass123"},
        )
        assert ok_login.status_code == 200
        assert ok_login.json()["access_token"]
        assert ok_login.json()["refresh_token"]
        assert "otp_required" not in ok_login.json()
        assert len(smtp_outbox) == 0
'''

for old, new in ((old1, new1), (old2, new2)):
    if s.count(old) != 1:
        raise RuntimeError("Expected test block not found exactly once. No changes saved.")
    s = s.replace(old, new, 1)

p.write_text(s, encoding="utf-8")
print("SMTP-dependent login assertions updated.")
