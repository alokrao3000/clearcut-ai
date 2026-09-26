"""Postgres row-level audit trigger.

The application ledger in `audit_log` records who changed what and why. It cannot record a
change the application did not make — a psql session, a bad migration, a bug that bypasses
the ORM. This trigger writes every row-level change to `db_audit_log` regardless of who made
it, and the value is the *gap* between the two tables: a `db_audit_log` row with no matching
application entry is a change made outside the app, which is exactly what an E&O reviewer
needs surfaced rather than hidden.

Postgres only. SQLite has no equivalent that survives a batch-mode table rewrite, so the test
suite and a keyless dev box simply never write here, and the reconciliation report says so
rather than implying a clean bill of health.

Revision ID: a17c9e4b2d10
Revises: 3f41307b22ba
"""

from alembic import op

revision = "a17c9e4b2d10"
down_revision = "3f41307b22ba"
branch_labels = None
depends_on = None

# The tables worth watching: the ones a clearance file is actually made of. Deliberately not
# every table — mail bodies and job payloads are bulky and prove nothing about rights.
AUDITED = (
    "projects", "assets", "clearance_tasks", "rightsholders", "rate_cards",
    "outreach_packets", "context_views", "proposed_changes", "users",
)

FUNCTION = """
CREATE OR REPLACE FUNCTION clearcut_db_audit() RETURNS trigger AS $$
DECLARE
    key text;
BEGIN
    -- Primary keys here are either `id` or a composite we do not need to reconstruct;
    -- `id` covers every audited table.
    IF (TG_OP = 'DELETE') THEN
        key := OLD.id::text;
        INSERT INTO db_audit_log (table_name, row_id, action, old_row, new_row, db_user, at)
        VALUES (TG_TABLE_NAME, key, 'delete', to_jsonb(OLD), NULL, session_user, now());
        RETURN OLD;
    ELSIF (TG_OP = 'UPDATE') THEN
        key := NEW.id::text;
        -- A row rewritten to identical values is not a change worth recording.
        IF to_jsonb(OLD) IS NOT DISTINCT FROM to_jsonb(NEW) THEN
            RETURN NEW;
        END IF;
        INSERT INTO db_audit_log (table_name, row_id, action, old_row, new_row, db_user, at)
        VALUES (TG_TABLE_NAME, key, 'update', to_jsonb(OLD), to_jsonb(NEW), session_user, now());
        RETURN NEW;
    ELSE
        key := NEW.id::text;
        INSERT INTO db_audit_log (table_name, row_id, action, old_row, new_row, db_user, at)
        VALUES (TG_TABLE_NAME, key, 'insert', NULL, to_jsonb(NEW), session_user, now());
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite dev and test databases keep the application ledger only.

    op.execute(FUNCTION)
    for table in AUDITED:
        op.execute(f"DROP TRIGGER IF EXISTS clearcut_db_audit_{table} ON {table};")
        op.execute(
            f"CREATE TRIGGER clearcut_db_audit_{table} "
            f"AFTER INSERT OR UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION clearcut_db_audit();"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    for table in AUDITED:
        op.execute(f"DROP TRIGGER IF EXISTS clearcut_db_audit_{table} ON {table};")
    op.execute("DROP FUNCTION IF EXISTS clearcut_db_audit();")
