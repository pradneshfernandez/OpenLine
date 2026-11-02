"""interview full transcript and resume link

Revision ID: a7d3e1b9c2f4
Revises: f0c9824a094e
Create Date: 2026-11-02 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d3e1b9c2f4'
down_revision: Union[str, Sequence[str], None] = 'f0c9824a094e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('interview', sa.Column('transcript_state', sa.String(length=20), nullable=False, server_default='none'))
    op.add_column('interview', sa.Column('transcript', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('interview', sa.Column('transcript_error', sa.Text(), nullable=False, server_default=''))
    op.add_column('interview', sa.Column('resumed_from_id', sa.Integer(), nullable=True))
    op.create_foreign_key('interview_resumed_from_id_fkey', 'interview', 'interview',
                          ['resumed_from_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('interview_resumed_from_id_fkey', 'interview', type_='foreignkey')
    op.drop_column('interview', 'resumed_from_id')
    op.drop_column('interview', 'transcript_error')
    op.drop_column('interview', 'transcript')
    op.drop_column('interview', 'transcript_state')
