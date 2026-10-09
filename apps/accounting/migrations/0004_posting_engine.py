"""
Migration 0004: posting-number sequence and database integrity triggers.

Creates:
  - accounting_posting_number_seq  — gap-tolerant sequence for posting numbers.
  - Trigger: posted_entry_immutable — prevents UPDATE of frozen financial fields
    and DELETE of POSTED journal headers.
  - Trigger: posted_lines_immutable — prevents INSERT/UPDATE/DELETE of lines
    that belong to POSTED journal entries.
  - Constraint trigger: check_posted_balance — DEFERRABLE INITIALLY DEFERRED;
    fires per-row when a JournalEntry reaches state='POSTED'. Verifies:
      * at least two lines exist for that entry, and
      * SUM(debit) = SUM(credit).
    This covers A11 (immutability) and A19 (invalid direct DB posts rejected).
"""

from django.db import migrations

# ---------------------------------------------------------------------------
# Posting number sequence
# ---------------------------------------------------------------------------

_CREATE_SEQUENCE = """
CREATE SEQUENCE IF NOT EXISTS accounting_posting_number_seq
    START WITH 1 INCREMENT BY 1 NO CYCLE;
"""
_DROP_SEQUENCE = "DROP SEQUENCE IF EXISTS accounting_posting_number_seq;"

# ---------------------------------------------------------------------------
# Trigger: posted_entry_immutable
# BEFORE UPDATE OR DELETE on accounting_journalentry
# ---------------------------------------------------------------------------
_ENTRY_IMMUTABILITY_FUNC = r"""
CREATE OR REPLACE FUNCTION accounting_posted_entry_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.state = 'POSTED' THEN
            RAISE EXCEPTION
                'posted_entry_delete_denied: posted entry % cannot be deleted.', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN OLD;
    END IF;

    -- UPDATE
    IF OLD.state = 'POSTED' THEN
        IF NEW.state              <> OLD.state              THEN
            RAISE EXCEPTION 'posted_entry_state_frozen'    USING ERRCODE = 'check_violation'; END IF;
        IF NEW.date               <> OLD.date               THEN
            RAISE EXCEPTION 'posted_entry_date_frozen'     USING ERRCODE = 'check_violation'; END IF;
        IF NEW.posting_number     IS DISTINCT FROM OLD.posting_number THEN
            RAISE EXCEPTION 'posted_entry_number_frozen'   USING ERRCODE = 'check_violation'; END IF;
        IF NEW.kind               <> OLD.kind               THEN
            RAISE EXCEPTION 'posted_entry_kind_frozen'     USING ERRCODE = 'check_violation'; END IF;
        IF NEW.creator_id         <> OLD.creator_id         THEN
            RAISE EXCEPTION 'posted_entry_creator_frozen'  USING ERRCODE = 'check_violation'; END IF;
        IF NEW.reversal_of_id     IS DISTINCT FROM OLD.reversal_of_id THEN
            RAISE EXCEPTION 'posted_entry_reversal_frozen' USING ERRCODE = 'check_violation'; END IF;
        IF NEW.replacement_of_id  IS DISTINCT FROM OLD.replacement_of_id THEN
            RAISE EXCEPTION 'posted_entry_replacement_frozen' USING ERRCODE = 'check_violation'; END IF;
        IF NEW.posted_at          IS DISTINCT FROM OLD.posted_at THEN
            RAISE EXCEPTION 'posted_entry_posted_at_frozen' USING ERRCODE = 'check_violation'; END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

_ENTRY_IMMUTABILITY_TRIGGER = """
DROP TRIGGER IF EXISTS posted_entry_immutable ON accounting_journalentry;
CREATE TRIGGER posted_entry_immutable
BEFORE UPDATE OR DELETE ON accounting_journalentry
FOR EACH ROW EXECUTE FUNCTION accounting_posted_entry_immutable();
"""

_DROP_ENTRY_TRIGGER = """
DROP TRIGGER IF EXISTS posted_entry_immutable ON accounting_journalentry;
DROP FUNCTION IF EXISTS accounting_posted_entry_immutable();
"""

# ---------------------------------------------------------------------------
# Trigger: posted_lines_immutable
# BEFORE INSERT OR UPDATE OR DELETE on accounting_journalline
# ---------------------------------------------------------------------------
_LINE_IMMUTABILITY_FUNC = r"""
CREATE OR REPLACE FUNCTION accounting_posted_lines_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    s TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT state INTO s FROM accounting_journalentry WHERE id = NEW.entry_id;
        IF s = 'POSTED' THEN
            RAISE EXCEPTION
                'posted_line_insert_denied: cannot add lines to posted entry %.', NEW.entry_id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        SELECT state INTO s FROM accounting_journalentry WHERE id = OLD.entry_id;
        IF s = 'POSTED' THEN
            RAISE EXCEPTION
                'posted_line_delete_denied: cannot delete lines of posted entry %.', OLD.entry_id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN OLD;
    END IF;

    -- UPDATE: check both old and new entry
    SELECT state INTO s FROM accounting_journalentry WHERE id = OLD.entry_id;
    IF s = 'POSTED' THEN
        RAISE EXCEPTION 'posted_line_update_denied (old entry)' USING ERRCODE = 'check_violation';
    END IF;
    SELECT state INTO s FROM accounting_journalentry WHERE id = NEW.entry_id;
    IF s = 'POSTED' THEN
        RAISE EXCEPTION 'posted_line_update_denied (new entry)' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""

_LINE_IMMUTABILITY_TRIGGER = """
DROP TRIGGER IF EXISTS posted_lines_immutable ON accounting_journalline;
CREATE TRIGGER posted_lines_immutable
BEFORE INSERT OR UPDATE OR DELETE ON accounting_journalline
FOR EACH ROW EXECUTE FUNCTION accounting_posted_lines_immutable();
"""

_DROP_LINE_TRIGGER = """
DROP TRIGGER IF EXISTS posted_lines_immutable ON accounting_journalline;
DROP FUNCTION IF EXISTS accounting_posted_lines_immutable();
"""

# ---------------------------------------------------------------------------
# Deferred constraint trigger: check_posted_balance
# Fires AFTER INSERT OR UPDATE on accounting_journalentry WHEN state='POSTED'.
# Deferred to end of transaction so all lines are already present.
# ---------------------------------------------------------------------------
_BALANCE_CHECK_FUNC = r"""
CREATE OR REPLACE FUNCTION accounting_check_posted_balance()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    line_count   INTEGER;
    total_debit  NUMERIC(18,2);
    total_credit NUMERIC(18,2);
BEGIN
    SELECT COUNT(*),
           COALESCE(SUM(debit),  0),
           COALESCE(SUM(credit), 0)
    INTO   line_count, total_debit, total_credit
    FROM   accounting_journalline
    WHERE  entry_id = NEW.id;

    IF line_count < 2 THEN
        RAISE EXCEPTION
            'posted_entry_too_few_lines: entry % has % line(s) (need >= 2).',
            NEW.id, line_count
            USING ERRCODE = 'check_violation';
    END IF;

    IF total_debit <> total_credit THEN
        RAISE EXCEPTION
            'posted_entry_unbalanced: entry % debits=% credits=%.',
            NEW.id, total_debit, total_credit
            USING ERRCODE = 'check_violation';
    END IF;

    IF total_debit = 0 THEN
        RAISE EXCEPTION
            'posted_entry_zero_total: entry % has zero total.', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NULL;
END;
$$;
"""

_BALANCE_CHECK_TRIGGER = """
DROP TRIGGER IF EXISTS check_posted_balance ON accounting_journalentry;
CREATE CONSTRAINT TRIGGER check_posted_balance
AFTER INSERT OR UPDATE ON accounting_journalentry
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
WHEN (NEW.state = 'POSTED')
EXECUTE FUNCTION accounting_check_posted_balance();
"""

_DROP_BALANCE_TRIGGER = """
DROP TRIGGER IF EXISTS check_posted_balance ON accounting_journalentry;
DROP FUNCTION IF EXISTS accounting_check_posted_balance();
"""

# ---------------------------------------------------------------------------
# Grant sequence to runtime role (idempotent; silently skips if role absent)
# ---------------------------------------------------------------------------
_GRANT_SEQUENCE = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ledger_app') THEN
        GRANT USAGE, SELECT ON SEQUENCE accounting_posting_number_seq TO ledger_app;
    END IF;
END
$$;
"""

_GRANT_SEQ_TEST = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ledger_test_app') THEN
        GRANT USAGE, SELECT ON SEQUENCE accounting_posting_number_seq TO ledger_test_app;
    END IF;
END
$$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0003_initialize_book"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_CREATE_SEQUENCE,
            reverse_sql=_DROP_SEQUENCE,
        ),
        migrations.RunSQL(
            sql=_ENTRY_IMMUTABILITY_FUNC + _ENTRY_IMMUTABILITY_TRIGGER,
            reverse_sql=_DROP_ENTRY_TRIGGER,
        ),
        migrations.RunSQL(
            sql=_LINE_IMMUTABILITY_FUNC + _LINE_IMMUTABILITY_TRIGGER,
            reverse_sql=_DROP_LINE_TRIGGER,
        ),
        migrations.RunSQL(
            sql=_BALANCE_CHECK_FUNC + _BALANCE_CHECK_TRIGGER,
            reverse_sql=_DROP_BALANCE_TRIGGER,
        ),
        migrations.RunSQL(
            sql=_GRANT_SEQUENCE + _GRANT_SEQ_TEST,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
