"""add jobs.parent_job_id (follow-up jobs)

Revision ID: 5b7c1d9e2a41
Revises: 4a2ef40cbff9
Create Date: 2026-11-17 12:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '5b7c1d9e2a41'
down_revision = '4a2ef40cbff9'
branch_labels = None
depends_on = None


def upgrade():
    # Plain ALTER TABLE on purpose. Alembic's batch mode would rebuild `jobs`
    # (create copy, DROP jobs, rename); with PRAGMA foreign_keys=ON that DROP
    # performs an implicit DELETE and the ON DELETE CASCADE rules would wipe
    # every job's send_logs and job_allocations.
    op.execute("ALTER TABLE jobs ADD COLUMN parent_job_id INTEGER REFERENCES jobs(id)")
    op.execute("CREATE INDEX idx_jobs_parent ON jobs (parent_job_id)")


def downgrade():
    # SQLite cannot drop a column that carries a foreign key without rebuilding
    # the table (see the note in upgrade()), so this is deliberately unsupported.
    raise NotImplementedError(
        "Downgrading 5b7c1d9e2a41 would require rebuilding the jobs table, "
        "which cascade-deletes send history. Restore from a backup instead."
    )
