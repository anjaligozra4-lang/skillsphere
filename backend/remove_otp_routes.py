from pathlib import Path
import re

p = Path("app/routers.py")
backup = Path("app/routers.py.before-otp-removal")

if not backup.exists():
    raise RuntimeError("Backup missing. Original file was not changed.")

s = p.read_text(encoding="utf-8")
original = s

def remove_block(pattern, label):
    global s
    updated, count = re.subn(pattern, "", s, count=1, flags=re.M | re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 block, found {count}")
    s = updated

def replace_once(old, new, label):
    global s
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 occurrence, found {count}")
    s = s.replace(old, new, 1)

# Remove both OTP request models.
remove_block(
    r"^class VerifyOtpRequest\(BaseModel\):.*?(?=^class RefreshTokenRequest)",
    "OTP request models"
)

# Remove OTP challenge helper and email masking helper.
remove_block(
    r"^def _issue_otp_challenge\(.*?(?=^@auth_router\.post\(\"/register\")",
    "OTP challenge helper"
)
remove_block(
    r"^def _mask_email\(.*?(?=^def _enforce_rate_limit)",
    "Email masking helper"
)

# Remove verify and resend routes together.
remove_block(
    r"^@auth_router\.post\(\"/verify-otp\"\).*?(?=^@auth_router\.post\(\"/refresh\")",
    "OTP verification and resend routes"
)

# Remove registration OTP option.
replace_once("    send_otp: bool = False\n", "", "Registration send_otp field")
replace_once(
    "def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):",
    "def register(payload: RegisterRequest, db: Session = Depends(get_db)):",
    "Registration signature"
)
replace_once(
    '''    response_payload: dict = {"id": user.id, "email": user.email, "role": user.role}
    if payload.send_otp:
        otp_payload = _issue_otp_challenge(db, user, _client_ip(request))
        db.commit()
        response_payload.update(otp_payload)
    return response_payload''',
    '''    return {"id": user.id, "email": user.email, "role": user.role}''',
    "Registration OTP response"
)

# Remove imports used only by OTP.
for line in [
    "import secrets\n",
    "    generate_otp_code,\n",
    "    hash_otp,\n",
    "    verify_otp_hash,\n",
    "    EmailConfigurationError,\n",
    "    EmailDeliveryError,\n",
    "    send_otp_email,\n",
    "    LoginOtpChallenge,\n",
]:
    if line not in s:
        raise RuntimeError(f"Expected import not found: {line.strip()}")
    s = s.replace(line, "", 1)

if s == original:
    raise RuntimeError("No changes detected. File not written.")

p.write_text(s, encoding="utf-8")
print("SUCCESS: OTP routes and registration OTP option removed.")
print("Database models and records were not modified.")
