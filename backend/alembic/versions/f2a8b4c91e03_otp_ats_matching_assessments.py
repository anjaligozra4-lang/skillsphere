"""Add OTP auth, ATS status history, rich matching, and online assessments.

Revision ID: f2a8b4c91e03
Revises: d84c9a13f2b1
Create Date: 2026-11-11 15:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "f2a8b4c91e03"
down_revision: Union[str, None] = "d84c9a13f2b1"
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
    existing_tables = set(insp.get_table_names())

    if not _has_column(insp, "candidates", "projects"):
        op.add_column("candidates", sa.Column("projects", sa.Text(), nullable=True))
    if not _has_column(insp, "candidates", "certifications"):
        op.add_column("candidates", sa.Column("certifications", sa.Text(), nullable=True))

    if not _has_column(insp, "applications", "match_score"):
        op.add_column("applications", sa.Column("match_score", sa.Numeric(5, 2), nullable=True))
    if not _has_column(insp, "applications", "shortlist_source"):
        op.add_column("applications", sa.Column("shortlist_source", sa.String(length=30), nullable=True))
    if not _has_column(insp, "applications", "auto_shortlisted_at"):
        op.add_column("applications", sa.Column("auto_shortlisted_at", sa.DateTime(), nullable=True))
    if not _has_column(insp, "applications", "manual_status_override"):
        op.add_column(
            "applications",
            sa.Column("manual_status_override", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    resume_id_col = next((c for c in insp.get_columns("resume_analysis") if c["name"] == "resume_id"), None)
    if resume_id_col and not resume_id_col.get("nullable", True):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("resume_analysis") as batch_op:
                batch_op.alter_column("resume_id", existing_type=sa.Integer(), nullable=True)
        else:
            op.alter_column("resume_analysis", "resume_id", existing_type=sa.Integer(), nullable=True)

    for col_name, col_type in [
        ("application_id", sa.Integer()),
        ("candidate_id", sa.Integer()),
        ("preferred_matched_skills", sa.Text()),
        ("preferred_missing_skills", sa.Text()),
        ("relevant_experience", sa.Text()),
        ("strengths", sa.Text()),
        ("weaknesses", sa.Text()),
        ("matching_explanation", sa.Text()),
        ("score_breakdown", sa.Text()),
        ("input_fingerprint", sa.String(length=64)),
    ]:
        if not _has_column(insp, "resume_analysis", col_name):
            op.add_column("resume_analysis", sa.Column(col_name, col_type, nullable=True))

    insp = inspect(bind)
    if not _has_index(insp, "resume_analysis", "ix_resume_analysis_application_id"):
        op.create_index("ix_resume_analysis_application_id", "resume_analysis", ["application_id"])
    if not _has_index(insp, "resume_analysis", "ix_resume_analysis_candidate_id"):
        op.create_index("ix_resume_analysis_candidate_id", "resume_analysis", ["candidate_id"])
    if not _has_index(insp, "resume_analysis", "ix_resume_analysis_input_fingerprint"):
        op.create_index("ix_resume_analysis_input_fingerprint", "resume_analysis", ["input_fingerprint"])

    if bind.dialect.name != "sqlite":
        if not _has_fk(insp, "resume_analysis", "fk_resume_analysis_application_id"):
            op.create_foreign_key(
                "fk_resume_analysis_application_id",
                "resume_analysis",
                "applications",
                ["application_id"],
                ["id"],
                ondelete="CASCADE",
            )
        if not _has_fk(insp, "resume_analysis", "fk_resume_analysis_candidate_id"):
            op.create_foreign_key(
                "fk_resume_analysis_candidate_id",
                "resume_analysis",
                "candidates",
                ["candidate_id"],
                ["id"],
                ondelete="CASCADE",
            )

    if "application_status_history" not in existing_tables:
        op.create_table(
            "application_status_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("application_id", sa.Integer(), nullable=False),
            sa.Column("previous_status", sa.String(length=30), nullable=True),
            sa.Column("new_status", sa.String(length=30), nullable=False),
            sa.Column("changed_by_user_id", sa.Integer(), nullable=True),
            sa.Column("actor_name", sa.String(length=150), nullable=False),
            sa.Column("actor_role", sa.String(length=30), nullable=False),
            sa.Column("source", sa.String(length=30), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["changed_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_application_status_history_application_id", "application_status_history", ["application_id"])
        op.create_index("ix_application_status_history_created_at", "application_status_history", ["created_at"])

    if "login_otp_challenges" not in existing_tables:
        op.create_table(
            "login_otp_challenges",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("challenge_token", sa.String(length=128), nullable=False),
            sa.Column("otp_salt", sa.String(length=64), nullable=False),
            sa.Column("otp_hash", sa.String(length=128), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("resend_count", sa.Integer(), nullable=False),
            sa.Column("last_sent_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("locked_at", sa.DateTime(), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_login_otp_challenges_user_id", "login_otp_challenges", ["user_id"])
        op.create_index("ix_login_otp_challenges_challenge_token", "login_otp_challenges", ["challenge_token"], unique=True)
        op.create_index("ix_login_otp_challenges_expires_at", "login_otp_challenges", ["expires_at"])

    if "refresh_tokens" not in existing_tables:
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
        op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
        op.create_index("ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"])

    if "auth_rate_limits" not in existing_tables:
        op.create_table(
            "auth_rate_limits",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("scope", sa.String(length=50), nullable=False),
            sa.Column("identifier", sa.String(length=255), nullable=False),
            sa.Column("window_start", sa.DateTime(), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("scope", "identifier", name="uq_auth_rate_limit"),
        )
        op.create_index("ix_auth_rate_limits_scope", "auth_rate_limits", ["scope"])
        op.create_index("ix_auth_rate_limits_identifier", "auth_rate_limits", ["identifier"])

    if "assessment_invitations" not in existing_tables:
        op.create_table(
            "assessment_invitations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("application_id", sa.Integer(), nullable=False),
            sa.Column("candidate_id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("recipient_email", sa.String(length=255), nullable=False),
            sa.Column("instructions", sa.Text(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("send_attempts", sa.Integer(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("application_id"),
        )
        op.create_index("ix_assessment_invitations_candidate_id", "assessment_invitations", ["candidate_id"])
        op.create_index("ix_assessment_invitations_job_id", "assessment_invitations", ["job_id"])
        op.create_index("ix_assessment_invitations_token_hash", "assessment_invitations", ["token_hash"], unique=True)
        op.create_index("ix_assessment_invitations_status", "assessment_invitations", ["status"])
        op.create_index("ix_assessment_invitations_expires_at", "assessment_invitations", ["expires_at"])

    if "assessments" not in existing_tables:
        op.create_table(
            "assessments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("application_id", sa.Integer(), nullable=False),
            sa.Column("invitation_id", sa.Integer(), nullable=False),
            sa.Column("candidate_id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("total_questions", sa.Integer(), nullable=False),
            sa.Column("duration_minutes", sa.Integer(), nullable=False),
            sa.Column("generation_source", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("deadline_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("submitted_automatically", sa.Boolean(), nullable=False),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("max_score", sa.Integer(), nullable=False),
            sa.Column("percentage", sa.Numeric(5, 2), nullable=True),
            sa.Column("result_summary", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["invitation_id"], ["assessment_invitations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("application_id"),
            sa.UniqueConstraint("invitation_id"),
        )
        op.create_index("ix_assessments_candidate_id", "assessments", ["candidate_id"])
        op.create_index("ix_assessments_job_id", "assessments", ["job_id"])
        op.create_index("ix_assessments_status", "assessments", ["status"])

    if "assessment_questions" not in existing_tables:
        op.create_table(
            "assessment_questions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("assessment_id", sa.Integer(), nullable=False),
            sa.Column("order_index", sa.Integer(), nullable=False),
            sa.Column("question_hash", sa.String(length=64), nullable=False),
            sa.Column("skill_tag", sa.String(length=100), nullable=False),
            sa.Column("difficulty", sa.String(length=20), nullable=False),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("options_json", sa.Text(), nullable=False),
            sa.Column("correct_option_index", sa.Integer(), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=True),
            sa.Column("selected_option_index", sa.Integer(), nullable=True),
            sa.Column("is_correct", sa.Boolean(), nullable=True),
            sa.Column("answered_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("assessment_id", "order_index", name="uq_assessment_question_order"),
            sa.UniqueConstraint("assessment_id", "question_hash", name="uq_assessment_question_hash"),
        )
        op.create_index("ix_assessment_questions_assessment_id", "assessment_questions", ["assessment_id"])
        op.create_index("ix_assessment_questions_question_hash", "assessment_questions", ["question_hash"])


def downgrade() -> None:
    op.drop_table("assessment_questions")
    op.drop_table("assessments")
    op.drop_table("assessment_invitations")
    op.drop_table("auth_rate_limits")
    op.drop_table("refresh_tokens")
    op.drop_table("login_otp_challenges")
    op.drop_table("application_status_history")

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("fk_resume_analysis_candidate_id", "resume_analysis", type_="foreignkey")
        op.drop_constraint("fk_resume_analysis_application_id", "resume_analysis", type_="foreignkey")
    op.drop_index("ix_resume_analysis_input_fingerprint", table_name="resume_analysis")
    op.drop_index("ix_resume_analysis_candidate_id", table_name="resume_analysis")
    op.drop_index("ix_resume_analysis_application_id", table_name="resume_analysis")
    for col_name in [
        "input_fingerprint",
        "score_breakdown",
        "matching_explanation",
        "weaknesses",
        "strengths",
        "relevant_experience",
        "preferred_missing_skills",
        "preferred_matched_skills",
        "candidate_id",
        "application_id",
    ]:
        op.drop_column("resume_analysis", col_name)

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("resume_analysis") as batch_op:
            batch_op.alter_column("resume_id", existing_type=sa.Integer(), nullable=False)
    else:
        op.alter_column("resume_analysis", "resume_id", existing_type=sa.Integer(), nullable=False)

    op.drop_column("applications", "manual_status_override")
    op.drop_column("applications", "auto_shortlisted_at")
    op.drop_column("applications", "shortlist_source")
    op.drop_column("applications", "match_score")

    op.drop_column("candidates", "certifications")
    op.drop_column("candidates", "projects")
