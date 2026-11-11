# SkillSphere API

The FastAPI OpenAPI schema and interactive Swagger UI are available at `/openapi.json` and `/docs`.

All application endpoints use the `/api` prefix. Requests to protected endpoints require `Authorization: Bearer <access_token>`. Responses use JSON except for resume downloads.

| Method | Endpoint | Access | Purpose |
|---|---|---|---|
| POST | `/auth/register` | Public | Register a candidate or recruiter |
| POST | `/auth/login` | Public | Authenticate and receive a JWT |
| GET | `/auth/me` | Authenticated user | Return the identity and role for the current JWT |
| GET / PUT | `/candidates/me` | Candidate | Read or update the candidate profile |
| POST | `/resumes/upload` | Candidate | Upload, process, and extract resume fields |
| GET | `/resumes/me` | Candidate | List resumes with processing state and per-page text |
| GET | `/resumes/profile` | Candidate | Compatibility alias for the candidate profile |
| PATCH | `/resumes/{id}/review` | Resume owner | Save corrected extracted fields to the profile |
| POST | `/resumes/analyze` | Candidate | Analyze `{ "resume_id": 1, "job_id": 1 }` |
| POST | `/matches/resume/{resume_id}/job/{job_id}` | Candidate | Analyze a resume against a published job |
| GET | `/matches/resume/{resume_id}` | Resume owner | List saved match analyses |
| GET | `/jobs` | Public | Search, filter, sort, and paginate active jobs |
| POST | `/jobs` | Recruiter | Create a job pending admin approval |
| GET | `/jobs/{job_id}` | Public | View published job details |
| POST | `/jobs/{job_id}/apply` | Candidate | Apply with an optional owned resume |
| GET | `/applications` | Candidate | View application history |
| PUT | `/applications/{id}/status` | The job's recruiter | Update an application status |
| GET | `/recruiter/applicants` | Recruiter | List applicants for the recruiter's own jobs |
| GET | `/recruiters/stats` | Recruiter | Read posted/active job and total/pending application counts |
| GET | `/admin/stats` or `/admin/analytics` | Admin | Read platform, candidate, recruiter, active-job, active-user, pending-job, and pending-company counts |
| GET | `/admin/analytics/trends` | Admin | Read daily account registrations and applications for the last 14 days |
| GET | `/admin/users` | Admin | List accounts and account status |
| PATCH | `/admin/users/{user_id}/status` | Admin | Enable or disable an account (admins cannot disable their own account) |
| GET | `/admin/jobs`, `/admin/companies` | Admin | Review job listings and company approval status |

The recruiter job routes under `/recruiters/jobs` and candidate application route `/applications/me` remain available. Applications cannot be duplicated while active; withdrawing retains history, and applying again reactivates the existing application record if the job is still published.

Resume uploads are limited to 10 MiB and checked against both extension and file signature. OCR runs in a worker thread. Install Tesseract for scanned PDFs and image resumes; if processing fails, the resume record exposes the processing error instead of treating the upload as successful.

Public registration is limited to candidates and recruiters. Administrator accounts are provisioned from `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `ADMIN_FULL_NAME` at backend startup; there is no public admin signup endpoint. Use `/admin/login` in the frontend to sign in as an existing administrator.
