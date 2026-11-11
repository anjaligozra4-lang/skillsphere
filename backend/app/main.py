from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.database import SessionLocal, engine
from app.models import Base
from app.routers import (
    admin_router, application_router, auth_router, candidate_router, company_router,
    job_router, match_router, recruiter_applicant_router, recruiter_router, resume_router,
)
from app.seed import ensure_admin


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Career and job portal API for job seekers, recruiters, and administrators.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(engine)

with SessionLocal() as db:
    ensure_admin(db)

for router in (
    auth_router, candidate_router, recruiter_router, company_router, resume_router,
    job_router, application_router, recruiter_applicant_router, admin_router, match_router,
):
    app.include_router(router)


@app.get("/health", tags=["System"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
