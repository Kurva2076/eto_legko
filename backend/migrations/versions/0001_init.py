"""init

Revision ID: 0001
Revises:
Create Date: 2026-11-26
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'campaign_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('keitaro_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('geo', sa.String(255), nullable=False),
        sa.Column('offer_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_campaign_records_keitaro_id', 'campaign_records', ['keitaro_id'], unique=True)

    op.create_table(
        'offer_changes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('offer_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_offer_changes_campaign_id', 'offer_changes', ['campaign_id'])


def downgrade() -> None:
    op.drop_index('ix_offer_changes_campaign_id', table_name='offer_changes')
    op.drop_table('offer_changes')
    op.drop_index('ix_campaign_records_keitaro_id', table_name='campaign_records')
    op.drop_table('campaign_records')
