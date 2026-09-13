"""Add user-managed AI providers and per-run provider selection."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_llm_providers"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANALYSIS_RUN_PROVIDER_FK = "fk_analysis_runs_llm_provider_id_llm_providers"


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("config_json", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("encrypted_secrets", sa.Text(), nullable=True),
        sa.Column("models_json", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("default_model", sa.Text(), nullable=False),
        sa.Column("default_reasoning_effort", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name"),
    )
    with op.batch_alter_table("analysis_runs") as batch_op:
        batch_op.add_column(sa.Column("llm_provider_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("llm_provider_name", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("reasoning_effort", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            ANALYSIS_RUN_PROVIDER_FK,
            "llm_providers",
            ["llm_provider_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("analysis_runs") as batch_op:
        batch_op.drop_constraint(ANALYSIS_RUN_PROVIDER_FK, type_="foreignkey")
        batch_op.drop_column("reasoning_effort")
        batch_op.drop_column("llm_provider_name")
        batch_op.drop_column("llm_provider_id")
    op.drop_table("llm_providers")
