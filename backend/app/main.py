from contextlib import asynccontextmanager
import logging
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


logger = logging.getLogger("skillsphere.main")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("SKILLSPHERE_TESTING") != "1":
        logger.info(
            "Initializing database at: %s",
            engine.url.render_as_string(hide_password=True),
        )
        try:
            Base.metadata.create_all(engine)
            with SessionLocal() as db:
                ensure_admin(db)
                ensure_platform_defaults(db, seed_questions=True)
            logger.info("Database schema and platform defaults initialized successfully.")
        except Exception as exc:
            logger.critical(
                "Database initialization failed (%s): %s",
                engine.url.render_as_string(hide_password=True),
                exc,
            )
            raise
    yield


app = FastAPI(
    title=settings.app_name,
    description="Career and job portal API for job seekers, recruiters, and administrators.",
    version="0.3.0",
    lifespan=lifespan,
)

cors_origins_list = settings.allowed_origins
if "*" in cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://.*",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins_list,
        allow_origin_regex=r"^https://skillsphere(-[a-zA-Z0-9_-]+)?\.vercel\.app$|^https://skillsphere-[a-zA-Z0-9_-]+-anjaligozra4-langs-projects\.vercel\.app$",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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
