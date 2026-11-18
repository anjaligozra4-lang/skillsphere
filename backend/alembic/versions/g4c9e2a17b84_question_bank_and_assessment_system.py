"""Add centralized Question Bank, reusable Assessments, Assignments, Candidate Answers, and Results.

Revision ID: g4c9e2a17b84
Revises: f2a8b4c91e03
Create Date: 2026-11-11 16:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "g4c9e2a17b84"
down_revision: Union[str, None] = "f2a8b4c91e03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    existing = set(insp.get_table_names())

    # Replace empty legacy Round-1 auto-generated tables cleanly without touching any user/application records
    for legacy_table in ("assessment_questions", "assessments", "assessment_invitations"):
        if legacy_table in existing:
            op.drop_table(legacy_table)

    insp = inspect(bind)
    existing = set(insp.get_table_names())

    if "platform_settings" not in existing:
        op.create_table(
            "platform_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("setting_key", sa.String(length=100), nullable=False),
            sa.Column("setting_value", sa.String(length=255), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_platform_settings_setting_key", "platform_settings", ["setting_key"], unique=True)

    if "question_bank" not in existing:
        op.create_table(
            "question_bank",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("question_type", sa.String(length=20), nullable=False),
            sa.Column("skill", sa.String(length=100), nullable=False),
            sa.Column("category", sa.String(length=100), nullable=False),
            sa.Column("difficulty", sa.String(length=20), nullable=False),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("options_json", sa.Text(), nullable=False),
            sa.Column("correct_option_index", sa.Integer(), nullable=False),
            sa.Column("marks", sa.Integer(), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_question_bank_skill", "question_bank", ["skill"])
        op.create_index("ix_question_bank_category", "question_bank", ["category"])
        op.create_index("ix_question_bank_difficulty", "question_bank", ["difficulty"])
        op.create_index("ix_question_bank_is_active", "question_bank", ["is_active"])

    if "assessments" not in existing:
        op.create_table(
            "assessments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("recruiter_id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("instructions", sa.Text(), nullable=False),
            sa.Column("duration_minutes", sa.Integer(), nullable=False),
            sa.Column("passing_marks", sa.Integer(), nullable=False),
            sa.Column("total_questions", sa.Integer(), nullable=False),
            sa.Column("total_marks", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["recruiter_id"], ["recruiters.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_assessments_recruiter_id", "assessments", ["recruiter_id"])
        op.create_index("ix_assessments_job_id", "assessments", ["job_id"])
        op.create_index("ix_assessments_status", "assessments", ["status"])
        op.create_index("ix_assessments_expires_at", "assessments", ["expires_at"])

    if "assessment_questions" not in existing:
        op.create_table(
            "assessment_questions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("assessment_id", sa.Integer(), nullable=False),
            sa.Column("question_bank_id", sa.Integer(), nullable=True),
            sa.Column("order_index", sa.Integer(), nullable=False),
            sa.Column("skill", sa.String(length=100), nullable=False),
            sa.Column("category", sa.String(length=100), nullable=False),
            sa.Column("difficulty", sa.String(length=20), nullable=False),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("options_json", sa.Text(), nullable=False),
            sa.Column("correct_option_index", sa.Integer(), nullable=False),
            sa.Column("marks", sa.Integer(), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["question_bank_id"], ["question_bank.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("assessment_id", "order_index", name="uq_assessment_question_order"),
        )
        op.create_index("ix_assessment_questions_assessment_id", "assessment_questions", ["assessment_id"])
        op.create_index("ix_assessment_questions_question_bank_id", "assessment_questions", ["question_bank_id"])

    if "assessment_assignments" not in existing:
        op.create_table(
            "assessment_assignments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("assessment_id", sa.Integer(), nullable=False),
            sa.Column("application_id", sa.Integer(), nullable=False),
            sa.Column("candidate_id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("assigned_by_recruiter_id", sa.Integer(), nullable=True),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("recipient_email", sa.String(length=255), nullable=False),
            sa.Column("invitation_status", sa.String(length=20), nullable=False),
            sa.Column("invitation_error", sa.Text(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("test_status", sa.String(length=20), nullable=False),
            sa.Column("assigned_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("deadline_at", sa.DateTime(), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("submitted_automatically", sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["assigned_by_recruiter_id"], ["recruiters.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("assessment_id", "application_id", name="uq_assessment_application_assignment"),
        )
        op.create_index("ix_assessment_assignments_assessment_id", "assessment_assignments", ["assessment_id"])
        op.create_index("ix_assessment_assignments_application_id", "assessment_assignments", ["application_id"])
        op.create_index("ix_assessment_assignments_candidate_id", "assessment_assignments", ["candidate_id"])
        op.create_index("ix_assessment_assignments_job_id", "assessment_assignments", ["job_id"])
        op.create_index("ix_assessment_assignments_token_hash", "assessment_assignments", ["token_hash"], unique=True)
        op.create_index("ix_assessment_assignments_invitation_status", "assessment_assignments", ["invitation_status"])
        op.create_index("ix_assessment_assignments_test_status", "assessment_assignments", ["test_status"])
        op.create_index("ix_assessment_assignments_assigned_at", "assessment_assignments", ["assigned_at"])
        op.create_index("ix_assessment_assignments_expires_at", "assessment_assignments", ["expires_at"])

    if "candidate_answers" not in existing:
        op.create_table(
            "candidate_answers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("assignment_id", sa.Integer(), nullable=False),
            sa.Column("assessment_question_id", sa.Integer(), nullable=False),
            sa.Column("selected_option_index", sa.Integer(), nullable=True),
            sa.Column("is_correct", sa.Boolean(), nullable=True),
            sa.Column("marks_awarded", sa.Integer(), nullable=False),
            sa.Column("answered_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["assessment_question_id"], ["assessment_questions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["assignment_id"], ["assessment_assignments.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("assignment_id", "assessment_question_id", name="uq_assignment_question_answer"),
        )
        op.create_index("ix_candidate_answers_assignment_id", "candidate_answers", ["assignment_id"])
        op.create_index("ix_candidate_answers_assessment_question_id", "candidate_answers", ["assessment_question_id"])

    if "assessment_results" not in existing:
        op.create_table(
            "assessment_results",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("assignment_id", sa.Integer(), nullable=False),
            sa.Column("assessment_id", sa.Integer(), nullable=False),
            sa.Column("application_id", sa.Integer(), nullable=False),
            sa.Column("candidate_id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("obtained_marks", sa.Integer(), nullable=False),
            sa.Column("total_marks", sa.Integer(), nullable=False),
            sa.Column("passing_marks", sa.Integer(), nullable=False),
            sa.Column("percentage", sa.Numeric(5, 2), nullable=False),
            sa.Column("is_passed", sa.Boolean(), nullable=False),
            sa.Column("result_status", sa.String(length=40), nullable=False),
            sa.Column("result_message", sa.String(length=255), nullable=False),
            sa.Column("submitted_at", sa.DateTime(), nullable=False),
            sa.Column("submitted_automatically", sa.Boolean(), nullable=False),
            sa.Column("summary_json", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["assignment_id"], ["assessment_assignments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("assignment_id"),
        )
        op.create_index("ix_assessment_results_assessment_id", "assessment_results", ["assessment_id"])
        op.create_index("ix_assessment_results_application_id", "assessment_results", ["application_id"])
        op.create_index("ix_assessment_results_candidate_id", "assessment_results", ["candidate_id"])
        op.create_index("ix_assessment_results_job_id", "assessment_results", ["job_id"])
        op.create_index("ix_assessment_results_submitted_at", "assessment_results", ["submitted_at"])


def downgrade() -> None:
    op.drop_table("assessment_results")
    op.drop_table("candidate_answers")
    op.drop_table("assessment_assignments")
    op.drop_table("assessment_questions")
    op.drop_table("assessments")
    op.drop_table("question_bank")
    op.drop_table("platform_settings")
