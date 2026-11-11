"""Add structured job ranges and resume processing results.

Revision ID: c13a4f20d6b1
Revises: ee73bf78fa6e
Create Date: 2026-11-09 21:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c13a4f20d6b1"
down_revision: Union[str, None] = "ee73bf78fa6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("candidates", sa.Column("contact_email", sa.String(length=255), nullable=True))
    op.add_column("jobs", sa.Column("experience_min", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("experience_max", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("salary_min", sa.Numeric(12, 2), nullable=True))
    op.add_column("jobs", sa.Column("salary_max", sa.Numeric(12, 2), nullable=True))
    op.add_column("jobs", sa.Column("salary_currency", sa.String(length=3), nullable=True))
    op.add_column("resumes", sa.Column("page_text", sa.Text(), nullable=True))
    op.add_column(
        "resumes",
        sa.Column("processing_status", sa.String(length=20), nullable=False, server_default="processed"),
    )
    op.add_column("resumes", sa.Column("processing_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("resumes", "processing_error")
    op.drop_column("resumes", "processing_status")
    op.drop_column("resumes", "page_text")
    op.drop_column("jobs", "salary_currency")
    op.drop_column("jobs", "salary_max")
    op.drop_column("jobs", "salary_min")
    op.drop_column("jobs", "experience_max")
    op.drop_column("jobs", "experience_min")
    op.drop_column("candidates", "contact_email")
