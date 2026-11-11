# SkillSphere - Career & Job Portal

SkillSphere is a full-stack career portal for job seekers, recruiters, and platform administrators.

## Technology

- React and Vite
- FastAPI
- SQLAlchemy and Alembic
- MySQL
- JWT authentication
- PyMuPDF, Pillow, and Tesseract OCR

## Core Workflows

- Job seekers can maintain profiles, upload and correct OCR-extracted resume details, search published jobs by keyword, location, employment type, required skill, and experience text, apply once per job, review application status, and withdraw while an application is applied, under review, or in screening.
- Recruiters can manage their company profile, submit jobs for admin approval, edit postings, close published jobs, reopen closed jobs, filter applicants by profile skills and experience, review candidate profiles, and download application resumes.
- Administrators can manage accounts, approve companies, publish or disable job postings, and view platform totals. See [docs/api.md](./docs/api.md) for role-protected API routes.

Resume uploads are limited to 10 MB, checked against their actual file signatures, processed page-by-page, and retain extracted page text and a processing status. Tesseract OCR must be installed and available on the backend `PATH` for scanned PDFs and image resumes.

Job postings may include structured experience and salary ranges. Public job search is sorted and paginated, and each listing links to its full description. Match analyses compare reviewed resume/profile skills with explicit job skills and recognized skills in the description, and are saved per resume/job for later viewing.

Published job edits return to pending admin approval. The database migration adds candidate contact email, structured job ranges, and resume processing fields; apply it before starting the backend.

## Development Milestones

1. Project foundation
2. Database and migrations
3. Authentication and authorization
4. Candidate and resume features
5. Recruiter and job features
6. Matching and applications
7. Admin features
8. Integration testing and final documentation

## Important Configuration

Copy `.env.example` to `.env` and replace every example secret or password. Never commit `.env`.

## Milestone 1 Setup

### Backend

```powershell
cd "SkillSphere/backend"
py -3.12 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
python -m alembic upgrade head
python -m pytest -q
python -m uvicorn app.main:app --reload --port 8001
```

For a database created by an earlier SkillSphere version before Alembic was applied, first mark its existing schema as the initial migration (`python -m alembic stamp ee73bf78fa6e`), then run `python -m alembic upgrade head`. Do this before starting the updated backend.

Swagger documentation is available at `http://127.0.0.1:8001/docs`.
See [docs/api.md](./docs/api.md) for role-protected endpoints and compatibility routes.
See [docs/testing.md](./docs/testing.md) for the security and validation test cases and their results.

### Frontend

```powershell
cd "SkillSphere/frontend"
npm.cmd install
npm.cmd run build
npm.cmd test
npm.cmd run dev
```
