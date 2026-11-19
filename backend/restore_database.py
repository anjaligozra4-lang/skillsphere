"""
SkillSphere Database Migration & Recovery Script
Safely imports historical users, candidates, recruiters, and companies from the MySQL
backup (skillsphere_backup_before_demo_cleanup.sql) into PostgreSQL.

Features:
- Idempotent: checks for existing emails/records and never overwrites or deletes data.
- Preserves newly registered users and candidates.
- Updates PostgreSQL auto-increment sequences after import.
"""

from datetime import datetime
import os
from pathlib import Path
import re
import sys

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

# Add backend directory to sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings
from app.database import SessionLocal, engine
from app.models import Candidate, Company, Job, Recruiter, User

BACKUP_FILE = BACKEND_DIR / "skillsphere_backup_before_demo_cleanup.sql"


def parse_sql_inserts(content: str, table_name: str) -> list[tuple]:
    pattern = rf"INSERT INTO `{table_name}` VALUES\s*(.*?);"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return []
    raw_values = match.group(1).strip()
    # Match tuple groups (1, '...', ...)
    # Each row starts with ( and ends with )
    rows = []
    # Simple regex for row values
    row_pattern = re.compile(r"\((.*?)\)(?:,|$)", re.DOTALL)
    for row_match in row_pattern.finditer(raw_values):
        row_str = row_match.group(1).strip()
        # Parse comma-separated fields handling quoted strings
        fields = []
        current = []
        in_quote = False
        escape = False
        for ch in row_str:
            if escape:
                current.append(ch)
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'" and not escape:
                in_quote = not in_quote
            elif ch == "," and not in_quote:
                fields.append("".join(current).strip().strip("'"))
                current = []
            else:
                current.append(ch)
        if current:
            fields.append("".join(current).strip().strip("'"))
        rows.append(tuple(fields))
    return rows


def restore_backup(db: Session) -> dict[str, int]:
    if not BACKUP_FILE.is_file():
        print(f"Backup file not found at: {BACKUP_FILE}")
        return {"users_imported": 0}

    print(f"Reading backup from: {BACKUP_FILE}...")
    content = BACKUP_FILE.read_text(encoding="utf-8", errors="ignore")

    stats = {
        "users_imported": 0,
        "users_skipped": 0,
        "candidates_created": 0,
        "companies_created": 0,
        "recruiters_created": 0,
    }

    # 1. Restore Users
    user_rows = parse_sql_inserts(content, "users")
    print(f"Found {len(user_rows)} users in backup.")

    for row in user_rows:
        if len(row) < 7:
            continue
        try:
            uid = int(row[0])
            email = row[1].strip().lower()
            password_hash = row[2]
            role = row[3]
            full_name = row[4]
            is_active = row[5] == "1"

            existing = db.scalar(select(User).where(func.lower(User.email) == email))
            if existing is not None:
                stats["users_skipped"] += 1
                continue

            user = User(
                email=email,
                password_hash=password_hash,
                role=role,
                full_name=full_name,
                is_active=is_active,
            )
            db.add(user)
            db.flush()
            stats["users_imported"] += 1

            if role == "candidate":
                cand_existing = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
                if cand_existing is None:
                    db.add(Candidate(user_id=user.id))
                    stats["candidates_created"] += 1
            elif role == "recruiter":
                rec_existing = db.scalar(select(Recruiter).where(Recruiter.user_id == user.id))
                if rec_existing is None:
                    db.add(Recruiter(user_id=user.id))
                    stats["recruiters_created"] += 1

        except Exception as e:
            print(f"Error importing user {row[1] if len(row) > 1 else 'unknown'}: {e}")

    # 2. Restore Companies & Recruiters
    company_rows = parse_sql_inserts(content, "companies")
    print(f"Found {len(company_rows)} companies in backup.")
    for row in company_rows:
        if len(row) < 6:
            continue
        try:
            cid = int(row[0])
            cname = row[1]
            desc = row[2] if row[2] != "NULL" else None
            web = row[3] if row[3] != "NULL" else None
            loc = row[4] if row[4] != "NULL" else None
            approved = row[5] == "1"

            existing_c = db.scalar(select(Company).where(Company.name == cname))
            if existing_c is None:
                db.add(Company(
                    name=cname,
                    description=desc,
                    website=web,
                    location=loc,
                    is_approved=approved,
                ))
                stats["companies_created"] += 1
        except Exception as e:
            print(f"Error importing company {row[1] if len(row) > 1 else 'unknown'}: {e}")

    db.commit()

    # If running on PostgreSQL, update sequences to prevent primary key collision
    if engine.dialect.name == "postgresql":
        try:
            with engine.connect() as conn:
                for table in ["users", "candidates", "companies", "recruiters", "jobs"]:
                    seq_query = text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(max(id), 1)) FROM {table};")
                    conn.execute(seq_query)
                    conn.commit()
            print("PostgreSQL primary key sequences updated successfully.")
        except Exception as e:
            print(f"Note: Sequence update notice: {e}")

    return stats


if __name__ == "__main__":
    print(f"Connecting to database: {engine.url.render_as_string(hide_password=True)}")
    with SessionLocal() as session:
        result = restore_backup(session)
        print("Restore results:", result)
