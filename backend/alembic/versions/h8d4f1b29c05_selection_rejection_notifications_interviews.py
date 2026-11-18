"""Add Interview rounds, EmailNotification tracking, and Application decision metadata.

Revision ID: h8d4f1b29c05
Revises: g4c9e2a17b84
Create Date: 2026-11-12 10:47:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "h8d4f1b29c05"
down_revision: Union[str, None] = "g4c9e2a17b84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, column: str) -> bool:
    return any(col["name"] == column for col in insp.get_columns(table))


def _has_index(insp, table: str, index: str) -> bool:
    return any(idx["name"] == index for idx in insp.get_indexes(table))


def _has_fk(insp, table: str, fk_name: str) -> bool:
    return any(fk["name"] == fk_name for fk in insp.get_foreign_keys(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    existing = set(insp.get_table_names())

    # 1. Additive nullable decision metadata fields on existing `applications` table
    for col_name, col_type in [
        ("decision_reason", sa.String(length=255)),
        ("decision_note", sa.Text()),
        ("decided_at", sa.DateTime()),
        ("decided_by_user_id", sa.Integer()),
    ]:
        if not _has_column(insp, "applications", col_name):
            op.add_column("applications", sa.Column(col_name, col_type, nullable=True))

    insp = inspect(bind)
    if not _has_index(insp, "applications", "ix_applications_decided_at"):
        op.create_index("ix_applications_decided_at", "applications", ["decided_at"])
    if not _has_index(insp, "applications", "ix_applications_decided_by_user_id"):
        op.create_index("ix_applications_decided_by_user_id", "applications", ["decided_by_user_id"])

    if bind.dialect.name != "sqlite":
        if not _has_fk(insp, "applications", "fk_applications_decided_by_user_id"):
            op.create_foreign_key(
                "fk_applications_decided_by_user_id",
                "applications",
                "users",
                ["decided_by_user_id"],
                ["id"],
                ondelete="SET NULL",
            )

    # 2. Interviews table (supports multiple interview rounds per application)
    if "interviews" not in existing:
        op.create_table(
            "interviews",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("application_id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("candidate_id", sa.Integer(), nullable=False),
            sa.Column("recruiter_id", sa.Integer(), nullable=True),
            sa.Column("scheduled_by_user_id", sa.Integer(), nullable=True),
            sa.Column("round_number", sa.Integer(), nullable=False),
            sa.Column("round_name", sa.String(length=120), nullable=False),
            sa.Column("interview_mode", sa.String(length=30), nullable=False),
            sa.Column("scheduled_at", sa.DateTime(), nullable=False),
            sa.Column("duration_minutes", sa.Integer(), nullable=False),
            sa.Column("timezone", sa.String(length=64), nullable=False),
            sa.Column("meeting_link", sa.String(length=500), nullable=True),
            sa.Column("location", sa.String(length=255), nullable=True),
            sa.Column("interviewer_name", sa.String(length=150), nullable=True),
            sa.Column("interviewer_email", sa.String(length=255), nullable=True),
            sa.Column("notes_for_candidate", sa.Text(), nullable=True),
            sa.Column("internal_notes", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("feedback", sa.Text(), nullable=True),
            sa.Column("rating", sa.Integer(), nullable=True),
            sa.Column("recommendation", sa.String(length=30), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(), nullable=True),
            sa.Column("cancellation_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["recruiter_id"], ["recruiters.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["scheduled_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_interviews_application_id", "interviews", ["application_id"])
        op.create_index("ix_interviews_job_id", "interviews", ["job_id"])
        op.create_index("ix_interviews_candidate_id", "interviews", ["candidate_id"])
        op.create_index("ix_interviews_recruiter_id", "interviews", ["recruiter_id"])
        op.create_index("ix_interviews_scheduled_at", "interviews", ["scheduled_at"])
        op.create_index("ix_interviews_status", "interviews", ["status"])

    # 3. Email notifications audit log table
    if "email_notifications" not in existing:
        op.create_table(
            "email_notifications",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("application_id", sa.Integer(), nullable=True),
            sa.Column("interview_id", sa.Integer(), nullable=True),
            sa.Column("candidate_id", sa.Integer(), nullable=True),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("triggered_by_user_id", sa.Integer(), nullable=True),
            sa.Column("notification_type", sa.String(length=50), nullable=False),
            sa.Column("recipient_email", sa.String(length=255), nullable=False),
            sa.Column("recipient_name", sa.String(length=150), nullable=True),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("body_text", sa.Text(), nullable=True),
            sa.Column("body_html", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["interview_id"], ["interviews.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["triggered_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_email_notifications_application_id", "email_notifications", ["application_id"])
        op.create_index("ix_email_notifications_interview_id", "email_notifications", ["interview_id"])
        op.create_index("ix_email_notifications_candidate_id", "email_notifications", ["candidate_id"])
        op.create_index("ix_email_notifications_job_id", "email_notifications", ["job_id"])
        op.create_index("ix_email_notifications_triggered_by_user_id", "email_notifications", ["triggered_by_user_id"])
        op.create_index("ix_email_notifications_notification_type", "email_notifications", ["notification_type"])
        op.create_index("ix_email_notifications_recipient_email", "email_notifications", ["recipient_email"])
        op.create_index("ix_email_notifications_status", "email_notifications", ["status"])
        op.create_index("ix_email_notifications_created_at", "email_notifications", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    existing = set(insp.get_table_names())

    if "email_notifications" in existing:
        op.drop_table("email_notifications")
    if "interviews" in existing:
        op.drop_table("interviews")

    insp = inspect(bind)
    if bind.dialect.name != "sqlite" and _has_fk(insp, "applications", "fk_applications_decided_by_user_id"):
        op.drop_constraint("fk_applications_decided_by_user_id", "applications", type_="foreignkey")
    if _has_index(insp, "applications", "ix_applications_decided_by_user_id"):
        op.drop_index("ix_applications_decided_by_user_id", table_name="applications")
    if _has_index(insp, "applications", "ix_applications_decided_at"):
        op.drop_index("ix_applications_decided_at", table_name="applications")

    for col_name in ("decided_by_user_id", "decided_at", "decision_note", "decision_reason"):
        if _has_column(insp, "applications", col_name):
            op.drop_column("applications", col_name)
