"""lex esignature schema (lex_esign_* 四表，change lex-contract-esignature)

Revision ID: 0002_lex_esignature
Revises: 0001_lex_initial
Create Date: 2026-10-29 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '0002_lex_esignature'
down_revision: Union[str, None] = '0001_lex_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('lex_esign_documents',
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('file_name', sa.String(length=500), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('sha256'),
    )
    op.create_table('lex_esign_tasks',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('customer_identity', sa.String(length=255), nullable=False),
        sa.Column('customer_principal', sa.String(length=255), nullable=True),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('anchor_sha256', sa.String(length=64), nullable=False),
        sa.Column('file_name', sa.String(length=500), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('adapter_name', sa.String(length=64), nullable=True),
        sa.Column('envelope_ref', sa.String(length=255), nullable=True),
        sa.Column('evidence_path', sa.String(length=1000), nullable=True),
        sa.Column('initiated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_esign_tasks_customer_identity', 'lex_esign_tasks', ['customer_identity'])
    op.create_index('ix_esign_tasks_customer_time', 'lex_esign_tasks', ['customer_identity', 'created_at'])
    op.create_table('lex_esign_signers',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('task_id', sa.String(length=32), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('role_label', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('link_token_hash', sa.String(length=64), nullable=True),
        sa.Column('session_token_hash', sa.String(length=64), nullable=True),
        sa.Column('session_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('realname_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('realname_record_json', sa.Text(), nullable=True),
        sa.Column('intent_confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('signature_value', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id', 'seq', name='uq_esign_signer_task_seq'),
        sa.UniqueConstraint('link_token_hash'),
    )
    op.create_index('ix_esign_signers_task_id', 'lex_esign_signers', ['task_id'])
    op.create_table('lex_esign_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('task_id', sa.String(length=32), nullable=False),
        sa.Column('signer_id', sa.String(length=32), nullable=True),
        sa.Column('actor', sa.String(length=255), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('detail_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_esign_events_task_id', 'lex_esign_events', ['task_id'])
    op.create_index('ix_esign_events_task_time', 'lex_esign_events', ['task_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_esign_events_task_time', table_name='lex_esign_events')
    op.drop_index('ix_esign_events_task_id', table_name='lex_esign_events')
    op.drop_table('lex_esign_events')
    op.drop_index('ix_esign_signers_task_id', table_name='lex_esign_signers')
    op.drop_table('lex_esign_signers')
    op.drop_index('ix_esign_tasks_customer_time', table_name='lex_esign_tasks')
    op.drop_index('ix_esign_tasks_customer_identity', table_name='lex_esign_tasks')
    op.drop_table('lex_esign_tasks')
    op.drop_table('lex_esign_documents')
