"""Initial schema: the ten tables of blueprint section 14.

The first migration builds the schema from the models so the two cannot drift.
Every later migration must use explicit op.* calls.

Revision ID: 0001
"""

from alembic import op

from app.db import models  # noqa: F401
from app.db.session import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
