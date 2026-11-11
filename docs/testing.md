# Validation and Security Tests

Run the backend regression suite from `backend`:

```powershell
.\\.venv\\Scripts\\python.exe -m pytest -q
```

The current suite passes **9 tests**. Each case checks the stated expected result; the actual result matched.

| Test case | Expected result | Actual result |
|---|---|---|
| Candidate registration, login, and profile access | Registration and authenticated profile access succeed; an unauthenticated request returns 401 | Passed |
| Invalid and expired authentication tokens | Protected profile requests return 401 | Passed |
| Role and resource ownership checks | Wrong roles and users cannot access protected administrative or resume resources | Passed |
| Injection-like job search input | Search succeeds without exposing unrelated jobs or interpreting the value as SQL | Passed |
| Duplicate applications | An active duplicate returns 409; a withdrawn application can be reactivated without creating a second record | Passed |
| Invalid, oversized, and mismatched resume uploads | Rejected uploads return 415 or 413, as appropriate | Passed |
| Empty, corrupt, and unreadable resumes | Upload returns a clear 422 error; unreadable processing is recorded as failed | Passed |
| Unavailable OCR service | Upload returns 503 with actionable Tesseract guidance and records a failed processing state | Passed |
| Invalid profile form data | Invalid email input returns 422 | Passed |

Database access uses SQLAlchemy ORM expressions, which bind user-supplied values as parameters. Resume processing failures are tested through the API response and persisted processing state so an OCR outage or unreadable file does not appear successful.
