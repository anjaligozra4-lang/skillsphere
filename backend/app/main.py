from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.assessment_router import (
    admin_question_bank_router,
    assessment_router,
    recruiter_assessment_router,
    recruiter_question_bank_router,
)
from app.core.config import get_settings
from app.database import SessionLocal, engine
from app.interview_router import (
    admin_interview_router,
    candidate_interview_router,
    recruiter_interview_router,
)
from app.livekit_router import livekit_router
from app.models import Base
from app.question_bank_seed import ensure_platform_defaults
from app.routers import (
    admin_router,
    application_router,
    auth_router,
    candidate_router,
    company_router,
    job_router,
    match_router,
    recruiter_applicant_router,
    recruiter_router,
    resume_router,
)
from app.seed import ensure_admin


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("SKILLSPHERE_TESTING") != "1":
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            ensure_admin(db)
            ensure_platform_defaults(db, seed_questions=True)
    yield


app = FastAPI(
    title=settings.app_name,
    description="Career and job portal API for job seekers, recruiters, and administrators.",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    auth_router,
    candidate_router,
    recruiter_router,
    company_router,
    resume_router,
    job_router,
    application_router,
    recruiter_applicant_router,
    admin_router,
    admin_question_bank_router,
    admin_interview_router,
    candidate_interview_router,
    recruiter_question_bank_router,
    recruiter_assessment_router,
    recruiter_interview_router,
    match_router,
    assessment_router,
    livekit_router,
):
    app.include_router(router)


@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
