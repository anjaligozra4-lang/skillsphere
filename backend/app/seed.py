
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Company, Recruiter, User


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

    if not settings.admin_password:
        return

    email = settings.admin_email.strip().lower()

    if not email:
        return

    user = db.scalar(select(User).where(User.email == email))

    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(settings.admin_password),
            full_name=settings.admin_full_name.strip() or "SkillSphere Administrator",
            role="admin",
            is_active=True,
        )
        db.add(user)
    else:
        user.password_hash = hash_password(settings.admin_password)
        user.full_name = settings.admin_full_name.strip() or "SkillSphere Administrator"
        user.role = "admin"
        user.is_active = True

    db.commit()


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
