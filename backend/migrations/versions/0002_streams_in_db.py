"""streams and offers in db

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'offers',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column('name', sa.String(512), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'campaigns',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('keitaro_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('alias', sa.String(255), nullable=True),
        sa.Column('state', sa.String(32), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_campaigns_keitaro_id', 'campaigns', ['keitaro_id'], unique=True)

    op.create_table(
        'streams',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('keitaro_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('type', sa.String(32), nullable=True),
        sa.Column('schema', sa.String(32), nullable=True),
        sa.Column('synced_schema', sa.String(32), nullable=True),
        sa.Column('state', sa.String(32), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('action_type', sa.String(64), nullable=True),
        sa.Column('action_payload', sa.Text(), nullable=True),
        sa.Column('filters', sa.JSON(), nullable=False),
        sa.Column('synced_offers', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_streams_campaign_id', 'streams', ['campaign_id'])
    op.create_index('ix_streams_keitaro_id', 'streams', ['keitaro_id'], unique=True)

    op.create_table(
        'stream_offers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('stream_id', sa.Integer(), sa.ForeignKey('streams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('offer_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(512), nullable=False),
        sa.Column('share', sa.Integer(), nullable=False),
        sa.Column('pinned', sa.Boolean(), nullable=False),
        sa.Column('keitaro_state', sa.String(32), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('stream_id', 'offer_id', name='uq_stream_offers_stream_offer'),
    )
    op.create_index('ix_stream_offers_stream_id', 'stream_offers', ['stream_id'])
    op.create_index('ix_stream_offers_offer_id', 'stream_offers', ['offer_id'])

    with op.batch_alter_table('offer_changes') as batch_op:
        batch_op.add_column(sa.Column('stream_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_offer_changes_stream_id', ['stream_id'])

    op.execute(
        'INSERT INTO campaigns (keitaro_id, name, created_at) '
        'SELECT keitaro_id, name, created_at FROM campaign_records'
    )


def downgrade() -> None:
    with op.batch_alter_table('offer_changes') as batch_op:
        batch_op.drop_index('ix_offer_changes_stream_id')
        batch_op.drop_column('stream_id')

    op.drop_index('ix_stream_offers_offer_id', table_name='stream_offers')
    op.drop_index('ix_stream_offers_stream_id', table_name='stream_offers')
    op.drop_table('stream_offers')

    op.drop_index('ix_streams_keitaro_id', table_name='streams')
    op.drop_index('ix_streams_campaign_id', table_name='streams')
    op.drop_table('streams')

    op.drop_index('ix_campaigns_keitaro_id', table_name='campaigns')
    op.drop_table('campaigns')

    op.drop_table('offers')
