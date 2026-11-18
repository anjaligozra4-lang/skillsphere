import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment_bank import QUESTION_BANK
from app.models import PlatformSetting, QuestionBank


SKILL_CATEGORY_MAP = {
    "Python": "Backend",
    "FastAPI": "Backend",
    "Django": "Backend",
    "Flask": "Backend",
    "Node.js": "Backend",
    "Java": "Backend",
    "Spring Boot": "Backend",
    "Hibernate": "Backend",
    "REST API": "Backend",
    "React": "Frontend",
    "JavaScript": "Frontend",
    "TypeScript": "Frontend",
    "HTML": "Frontend",
    "CSS": "Frontend",
    "SQL": "Database",
    "MySQL": "Database",
    "PostgreSQL": "Database",
    "DBMS": "Database",
    "Docker": "Cloud & DevOps",
    "Kubernetes": "Cloud & DevOps",
    "AWS": "Cloud & DevOps",
    "Git": "Cloud & DevOps",
    "Pandas": "Data & AI",
    "Power BI": "Data & AI",
    "Excel": "Data & AI",
    "AI/ML": "Data & AI",
    "Machine Learning": "Data & AI",
    "API Testing": "Testing & QA",
    "Selenium": "Testing & QA",
    "Manual Testing": "Testing & QA",
    "Figma": "UI/UX Design",
    "User Research": "UI/UX Design",
    "Wireframing": "UI/UX Design",
    "Prototyping": "UI/UX Design",
    "SEO": "Digital Marketing",
    "Google Analytics": "Digital Marketing",
    "SEM": "Digital Marketing",
    "Content Marketing": "Digital Marketing",
    "Recruitment": "HR & Recruitment",
    "Candidate Screening": "HR & Recruitment",
    "Interview Coordination": "HR & Recruitment",
    "Communication": "HR & Recruitment",
    "OOP": "Core CS",
    "Computer Fundamentals": "Core CS",
}

DIFFICULTY_MAP = {
    "basic": "Easy",
    "intermediate": "Medium",
    "advanced": "Hard",
}


def ensure_platform_defaults(db: Session, seed_questions: bool = True) -> None:
    reveal_setting = db.scalar(
        select(PlatformSetting).where(PlatformSetting.setting_key == "reveal_assessment_answers")
    )
    if reveal_setting is None:
        db.add(PlatformSetting(setting_key="reveal_assessment_answers", setting_value="false"))

    if seed_questions:
        seeded_flag = db.scalar(
            select(PlatformSetting).where(PlatformSetting.setting_key == "question_bank_seeded")
        )
        if seeded_flag is None:
            existing_count = db.scalar(select(QuestionBank.id).limit(1))
            if existing_count is None:
                for item in QUESTION_BANK:
                    skill = item["skill_tag"]
                    category = SKILL_CATEGORY_MAP.get(skill, "General")
                    difficulty = DIFFICULTY_MAP.get(item["difficulty"], "Medium")
                    db.add(
                        QuestionBank(
                            question_type="mcq",
                            skill=skill,
                            category=category,
                            difficulty=difficulty,
                            question_text=item["question"].strip(),
                            options_json=json.dumps(item["options"]),
                            correct_option_index=int(item["correct_index"]),
                            marks=1,
                            explanation=item.get("explanation"),
                            is_active=True,
                        )
                    )
            db.add(PlatformSetting(setting_key="question_bank_seeded", setting_value="1"))
    db.commit()
