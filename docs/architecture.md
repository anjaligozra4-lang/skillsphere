# SkillSphere Architecture

## Purpose

SkillSphere provides job-seeker, recruiter, and administrator workflows through a React client and FastAPI API.

## Backend Entry Point

`backend/app/main.py` creates the FastAPI application, configures CORS, exposes Swagger, and provides the health endpoint. `backend/app/routers.py` contains authenticated role-specific APIs for profiles, jobs, resumes, matching, and applications.

## Configuration

`backend/app/core/config.py` loads environment variables through Pydantic Settings. Database credentials and JWT secrets must be supplied through environment variables. Schema changes are applied with Alembic before the API is deployed.

## Frontend Entry Point

`frontend/src/main.jsx` mounts React inside the browser router. `frontend/src/App.jsx` provides the job search/detail, application, resume review, recruiter, and admin interfaces.

## Resume processing and matching

Uploads are validated by MIME type, file signature, and size before being stored. The backend extracts embedded PDF text first, uses Tesseract for scanned PDF pages and images, and persists both per-page text and parsed fields. Matching uses normalized profile and reviewed resume skills against job skill tags and recognized skills in the job description; each analysis is stored for later retrieval.

## Job search and applications

Public search returns only active jobs from approved companies and supports keyword/location/type/skill/experience filters, structured experience range overlap, sorting, and pagination. Salary and experience ranges are optional fields on jobs. Applications retain their submission date, selected resume, and status; withdrawn applications remain in history and may be reactivated only while the job remains open.
