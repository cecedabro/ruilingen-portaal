"""rename shift type I to Inwerk

Revision ID: 410c76a25636
Revises: 73538935c3ff
Create Date: 2026-10-14 17:40:04.691075

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "410c76a25636"
down_revision: str | None = "73538935c3ff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# "I" (inwerkdienst) is shown as "Inwerk". Data-only: rename it everywhere it's stored,
# including inside the comma-separated wanted_types lists.
def upgrade() -> None:
    op.execute("UPDATE listings SET shift_type = 'Inwerk' WHERE shift_type = 'I'")
    op.execute("UPDATE reactions SET offer_type = 'Inwerk' WHERE offer_type = 'I'")
    op.execute(
        "UPDATE listings SET wanted_types = "
        "trim(replace(',' || wanted_types || ',', ',I,', ',Inwerk,'), ',') "
        "WHERE ',' || wanted_types || ',' LIKE '%,I,%'"
    )


def downgrade() -> None:
    op.execute("UPDATE listings SET shift_type = 'I' WHERE shift_type = 'Inwerk'")
    op.execute("UPDATE reactions SET offer_type = 'I' WHERE offer_type = 'Inwerk'")
    op.execute(
        "UPDATE listings SET wanted_types = "
        "trim(replace(',' || wanted_types || ',', ',Inwerk,', ',I,'), ',') "
        "WHERE ',' || wanted_types || ',' LIKE '%,Inwerk,%'"
    )
