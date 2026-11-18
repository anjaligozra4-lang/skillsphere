"""add livekit interviews and video assessments

Revision ID: b2e8a1c93f07
Revises: a1d67ac1e07c
Create Date: 2026-11-17 23:55:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'b2e8a1c93f07'
down_revision: Union[str, None] = 'a1d67ac1e07c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update interviews table
    op.add_column('interviews', sa.Column('livekit_room_name', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_interviews_livekit_room_name'), 'interviews', ['livekit_room_name'], unique=False)
    op.add_column('interviews', sa.Column('interview_type', sa.String(length=50), nullable=True))
    op.add_column('interviews', sa.Column('started_at', sa.DateTime(), nullable=True))
    op.add_column('interviews', sa.Column('ended_at', sa.DateTime(), nullable=True))
    op.add_column('interviews', sa.Column('is_waiting_room_enabled', sa.Boolean(), server_default='1', nullable=False))
    op.add_column('interviews', sa.Column('candidate_joined_at', sa.DateTime(), nullable=True))
    op.add_column('interviews', sa.Column('recruiter_joined_at', sa.DateTime(), nullable=True))

    # 2. Update assessments table
    op.add_column('assessments', sa.Column('assessment_type', sa.String(length=30), server_default='mcq', nullable=False))
    op.create_index(op.f('ix_assessments_assessment_type'), 'assessments', ['assessment_type'], unique=False)
    op.add_column('assessments', sa.Column('prep_time_seconds', sa.Integer(), server_default='30', nullable=False))
    op.add_column('assessments', sa.Column('response_time_seconds', sa.Integer(), server_default='120', nullable=False))
    op.add_column('assessments', sa.Column('allow_review', sa.Boolean(), server_default='1', nullable=False))
    op.add_column('assessments', sa.Column('max_recordings_per_question', sa.Integer(), server_default='1', nullable=False))

    # 3. Update assessment_questions table
    op.add_column('assessment_questions', sa.Column('question_type', sa.String(length=30), server_default='mcq', nullable=False))
    op.add_column('assessment_questions', sa.Column('instructions', sa.Text(), nullable=True))
    op.add_column('assessment_questions', sa.Column('prep_time_seconds', sa.Integer(), nullable=True))
    op.add_column('assessment_questions', sa.Column('response_time_seconds', sa.Integer(), nullable=True))

    # 4. Update assessment_recordings table
    op.add_column('assessment_recordings', sa.Column('assessment_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_assessment_recordings_assessment_id', 'assessment_recordings', 'assessments', ['assessment_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_assessment_recordings_assessment_id'), 'assessment_recordings', ['assessment_id'], unique=False)

    op.add_column('assessment_recordings', sa.Column('application_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_assessment_recordings_application_id', 'assessment_recordings', 'applications', ['application_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_assessment_recordings_application_id'), 'assessment_recordings', ['application_id'], unique=False)

    op.add_column('assessment_recordings', sa.Column('candidate_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_assessment_recordings_candidate_id', 'assessment_recordings', 'candidates', ['candidate_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_assessment_recordings_candidate_id'), 'assessment_recordings', ['candidate_id'], unique=False)

    op.add_column('assessment_recordings', sa.Column('question_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_assessment_recordings_question_id', 'assessment_recordings', 'assessment_questions', ['question_id'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_assessment_recordings_question_id'), 'assessment_recordings', ['question_id'], unique=False)

    op.add_column('assessment_recordings', sa.Column('cloudinary_secure_url', sa.String(length=1000), nullable=True))
    op.add_column('assessment_recordings', sa.Column('duration', sa.Integer(), nullable=True))
    op.add_column('assessment_recordings', sa.Column('format', sa.String(length=20), nullable=True))
    op.add_column('assessment_recordings', sa.Column('file_size', sa.Integer(), nullable=True))
    op.add_column('assessment_recordings', sa.Column('upload_status', sa.String(length=30), server_default='uploaded', nullable=False))
    op.create_index(op.f('ix_assessment_recordings_upload_status'), 'assessment_recordings', ['upload_status'], unique=False)

    # 5. Create interview_recordings table
    op.create_table(
        'interview_recordings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('interview_id', sa.Integer(), nullable=False),
        sa.Column('candidate_id', sa.Integer(), nullable=False),
        sa.Column('cloudinary_public_id', sa.String(length=255), nullable=True),
        sa.Column('cloudinary_secure_url', sa.String(length=1000), nullable=True),
        sa.Column('duration', sa.Integer(), nullable=True),
        sa.Column('format', sa.String(length=20), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('upload_status', sa.String(length=30), server_default='pending', nullable=False),
        sa.Column('egress_id', sa.String(length=255), nullable=True),
        sa.Column('local_temp_path', sa.String(length=1000), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['interview_id'], ['interviews.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_interview_recordings_candidate_id'), 'interview_recordings', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_interview_recordings_cloudinary_public_id'), 'interview_recordings', ['cloudinary_public_id'], unique=False)
    op.create_index(op.f('ix_interview_recordings_created_at'), 'interview_recordings', ['created_at'], unique=False)
    op.create_index(op.f('ix_interview_recordings_egress_id'), 'interview_recordings', ['egress_id'], unique=False)
    op.create_index(op.f('ix_interview_recordings_interview_id'), 'interview_recordings', ['interview_id'], unique=False)
    op.create_index(op.f('ix_interview_recordings_upload_status'), 'interview_recordings', ['upload_status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_interview_recordings_upload_status'), table_name='interview_recordings')
    op.drop_index(op.f('ix_interview_recordings_interview_id'), table_name='interview_recordings')
    op.drop_index(op.f('ix_interview_recordings_egress_id'), table_name='interview_recordings')
    op.drop_index(op.f('ix_interview_recordings_created_at'), table_name='interview_recordings')
    op.drop_index(op.f('ix_interview_recordings_cloudinary_public_id'), table_name='interview_recordings')
    op.drop_index(op.f('ix_interview_recordings_candidate_id'), table_name='interview_recordings')
    op.drop_table('interview_recordings')

    op.drop_index(op.f('ix_assessment_recordings_upload_status'), table_name='assessment_recordings')
    op.drop_column('assessment_recordings', 'upload_status')
    op.drop_column('assessment_recordings', 'file_size')
    op.drop_column('assessment_recordings', 'format')
    op.drop_column('assessment_recordings', 'duration')
    op.drop_column('assessment_recordings', 'cloudinary_secure_url')
    op.drop_index(op.f('ix_assessment_recordings_question_id'), table_name='assessment_recordings')
    op.drop_constraint('fk_assessment_recordings_question_id', 'assessment_recordings', type_='foreignkey')
    op.drop_column('assessment_recordings', 'question_id')
    op.drop_index(op.f('ix_assessment_recordings_candidate_id'), table_name='assessment_recordings')
    op.drop_constraint('fk_assessment_recordings_candidate_id', 'assessment_recordings', type_='foreignkey')
    op.drop_column('assessment_recordings', 'candidate_id')
    op.drop_index(op.f('ix_assessment_recordings_application_id'), table_name='assessment_recordings')
    op.drop_constraint('fk_assessment_recordings_application_id', 'assessment_recordings', type_='foreignkey')
    op.drop_column('assessment_recordings', 'application_id')
    op.drop_index(op.f('ix_assessment_recordings_assessment_id'), table_name='assessment_recordings')
    op.drop_constraint('fk_assessment_recordings_assessment_id', 'assessment_recordings', type_='foreignkey')
    op.drop_column('assessment_recordings', 'assessment_id')

    op.drop_column('assessment_questions', 'response_time_seconds')
    op.drop_column('assessment_questions', 'prep_time_seconds')
    op.drop_column('assessment_questions', 'instructions')
    op.drop_column('assessment_questions', 'question_type')

    op.drop_column('assessments', 'max_recordings_per_question')
    op.drop_column('assessments', 'allow_review')
    op.drop_column('assessments', 'response_time_seconds')
    op.drop_column('assessments', 'prep_time_seconds')
    op.drop_index(op.f('ix_assessments_assessment_type'), table_name='assessments')
    op.drop_column('assessments', 'assessment_type')

    op.drop_column('interviews', 'recruiter_joined_at')
    op.drop_column('interviews', 'candidate_joined_at')
    op.drop_column('interviews', 'is_waiting_room_enabled')
    op.drop_column('interviews', 'ended_at')
    op.drop_column('interviews', 'started_at')
    op.drop_column('interviews', 'interview_type')
    op.drop_index(op.f('ix_interviews_livekit_room_name'), table_name='interviews')
    op.drop_column('interviews', 'livekit_room_name')
