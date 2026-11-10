"""Initial schema (matches the tables previously created by Base.metadata.create_all).

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('auth_sessions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('auth_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_auth_sessions_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_auth_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('projects',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('source_type', sa.String(length=16), nullable=False),
    sa.Column('source_url', sa.String(length=500), nullable=True),
    sa.Column('default_branch', sa.String(length=200), nullable=True),
    sa.Column('llm_consent', sa.Boolean(), nullable=False),
    sa.Column('llm_consent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_projects_owner_id'), ['owner_id'], unique=False)

    op.create_table('audits',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=False),
    sa.Column('previous_audit_id', sa.String(length=36), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('stage', sa.String(length=64), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('commit_sha', sa.String(length=64), nullable=True),
    sa.Column('workspace_path', sa.String(length=500), nullable=True),
    sa.Column('workspace_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('summary', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audits', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audits_project_id'), ['project_id'], unique=False)

    op.create_table('ai_artifacts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('audit_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('target', sa.String(length=1000), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('content', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('ai_artifacts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_artifacts_audit_id'), ['audit_id'], unique=False)

    op.create_table('findings',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('audit_id', sa.String(length=36), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('tool', sa.String(length=32), nullable=False),
    sa.Column('rule_id', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('confidence', sa.String(length=16), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('principle', sa.String(length=64), nullable=True),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('file', sa.String(length=1000), nullable=True),
    sa.Column('line', sa.Integer(), nullable=True),
    sa.Column('end_line', sa.Integer(), nullable=True),
    sa.Column('evidence', sa.Text(), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('impact', sa.Text(), nullable=False),
    sa.Column('remediation', sa.Text(), nullable=False),
    sa.Column('references', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('findings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_findings_audit_id'), ['audit_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_findings_fingerprint'), ['fingerprint'], unique=False)

    op.create_table('pull_requests',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('audit_id', sa.String(length=36), nullable=False),
    sa.Column('url', sa.String(length=500), nullable=False),
    sa.Column('branch', sa.String(length=200), nullable=False),
    sa.Column('fix_ids', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('pull_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pull_requests_audit_id'), ['audit_id'], unique=False)

    op.create_table('fix_proposals',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('audit_id', sa.String(length=36), nullable=False),
    sa.Column('finding_id', sa.String(length=36), nullable=False),
    sa.Column('file', sa.String(length=1000), nullable=False),
    sa.Column('edits', sa.JSON(), nullable=False),
    sa.Column('diff', sa.Text(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('generator', sa.String(length=100), nullable=False),
    sa.Column('caveats', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['finding_id'], ['findings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('fix_proposals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_fix_proposals_audit_id'), ['audit_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_fix_proposals_finding_id'), ['finding_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('fix_proposals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fix_proposals_finding_id'))
        batch_op.drop_index(batch_op.f('ix_fix_proposals_audit_id'))

    op.drop_table('fix_proposals')
    with op.batch_alter_table('pull_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_pull_requests_audit_id'))

    op.drop_table('pull_requests')
    with op.batch_alter_table('findings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_findings_fingerprint'))
        batch_op.drop_index(batch_op.f('ix_findings_audit_id'))

    op.drop_table('findings')
    with op.batch_alter_table('ai_artifacts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_artifacts_audit_id'))

    op.drop_table('ai_artifacts')
    with op.batch_alter_table('audits', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audits_project_id'))

    op.drop_table('audits')
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_projects_owner_id'))

    op.drop_table('projects')
    with op.batch_alter_table('auth_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_auth_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_auth_sessions_token_hash'))

    op.drop_table('auth_sessions')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
