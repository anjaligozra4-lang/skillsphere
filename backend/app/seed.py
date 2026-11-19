
import logging
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Company, Recruiter, User

logger = logging.getLogger("skillsphere.seed")


DEMO_COMPANIES = [
    {
        "name": "TechNova Solutions",
        "description": "Fictional software development and technology company.",
        "website": "https://technova.example.com",
        "location": "Bengaluru, Karnataka",
        "email": "recruiter1@skillsphere.demo",
        "full_name": "TechNova Demo Recruiter",
    },
    {
        "name": "WebCraft Technologies",
        "description": "Fictional web development and digital solutions company.",
        "website": "https://webcraft.example.com",
        "location": "Pune, Maharashtra",
        "email": "recruiter2@skillsphere.demo",
        "full_name": "WebCraft Demo Recruiter",
    },
    {
        "name": "DataWorks India",
        "description": "Fictional data analytics and business intelligence company.",
        "website": "https://dataworks.example.com",
        "location": "Hyderabad, Telangana",
        "email": "recruiter3@skillsphere.demo",
        "full_name": "DataWorks Demo Recruiter",
    },
    {
        "name": "CodeBridge Systems",
        "description": "Fictional enterprise software engineering company.",
        "website": "https://codebridge.example.com",
        "location": "Chennai, Tamil Nadu",
        "email": "recruiter4@skillsphere.demo",
        "full_name": "CodeBridge Demo Recruiter",
    },
    {
        "name": "CloudBridge Technologies",
        "description": "Fictional cloud and backend engineering company.",
        "website": "https://cloudbridge.example.com",
        "location": "Gurugram, Haryana",
        "email": "recruiter5@skillsphere.demo",
        "full_name": "CloudBridge Demo Recruiter",
    },
    {
        "name": "AppVision Labs",
        "description": "Fictional full-stack application development company.",
        "website": "https://appvision.example.com",
        "location": "Noida, Uttar Pradesh",
        "email": "recruiter6@skillsphere.demo",
        "full_name": "AppVision Demo Recruiter",
    },
    {
        "name": "DesignSphere Studio",
        "description": "Fictional UI and UX design studio.",
        "website": "https://designsphere.example.com",
        "location": "Mumbai, Maharashtra",
        "email": "recruiter7@skillsphere.demo",
        "full_name": "DesignSphere Demo Recruiter",
    },
]


def ensure_admin(db: Session) -> None:
    settings = get_settings()

    admin_email = (settings.admin_email or "").strip().lower()
    admin_password = (settings.admin_password or "").strip()
    admin_name = (settings.admin_full_name or "").strip() or "SkillSphere Administrator"

    if not admin_password:
        logger.warning(
            "ADMIN_PASSWORD environment variable is not configured. "
            "Skipping administrator account initial provisioning. "
            "Configure ADMIN_PASSWORD (and optionally ADMIN_EMAIL) in Render environment variables to manage administrator provisioning safely."
        )
        return

    if not admin_email:
        admin_email = "admin@skillsphere.com"

    user = db.scalar(select(User).where(func.lower(User.email) == admin_email))

    if user is None:
        user = User(
            email=admin_email,
            password_hash=hash_password(admin_password),
            full_name=admin_name,
            role="admin",
            is_active=True,
        )
        db.add(user)
        db.commit()
        logger.info("Created administrator account for %s", admin_email)
    else:
        # Crucial: NEVER overwrite existing user passwords
        updated = False
        if not user.is_active:
            user.is_active = True
            updated = True
        if user.role != "admin":
            user.role = "admin"
            updated = True
        if updated:
            db.commit()
            logger.info("Ensured active admin role for existing user %s without changing password", admin_email)
        else:
            logger.info("Administrator account already exists for %s; preserving existing credentials", admin_email)


def seed_demo_companies(db: Session) -> None:
    settings = get_settings()
    demo_password = settings.demo_recruiter_password

    if not demo_password:
        raise RuntimeError(
            "Set DEMO_RECRUITER_PASSWORD in .env before creating demo recruiter accounts."
        )

    try:
        for item in DEMO_COMPANIES:
            company = db.scalar(
                select(Company).where(Company.name == item["name"])
            )

            if company is None:
                company = Company(
                    name=item["name"],
                    description=item["description"],
                    website=item["website"],
                    location=item["location"],
                    is_approved=False,
                )
                db.add(company)
                db.flush()

            email = item["email"].strip().lower()
            user = db.scalar(select(User).where(User.email == email))

            if user is None:
                user = User(
                    email=email,
                    password_hash=hash_password(demo_password),
                    full_name=item["full_name"],
                    role="recruiter",
                    is_active=True,
                )
                db.add(user)
                db.flush()

                recruiter = Recruiter(
                    user_id=user.id,
                    company_id=company.id
                )
                db.add(recruiter)

            elif user.role == "recruiter":
                recruiter = db.scalar(
                    select(Recruiter).where(Recruiter.user_id == user.id)
                )

                if recruiter is None:
                    db.add(
                        Recruiter(
                            user_id=user.id,
                            company_id=company.id
                        )
                    )
                elif recruiter.company_id is None:
                    recruiter.company_id = company.id

        db.commit()

    except Exception:
        db.rollback()
        raise
