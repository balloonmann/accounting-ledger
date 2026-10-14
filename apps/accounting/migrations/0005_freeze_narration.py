"""
Migration 0005: Freeze narration and version on POSTED journal entries.

Updates the accounting_posted_entry_immutable() trigger function to enforce
that once an entry is POSTED, neither narration nor version can be modified.
"""

from django.db import migrations

_ENTRY_IMMUTABILITY_FUNC_V2 = r"""
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
        IF NEW.narration          IS DISTINCT FROM OLD.narration THEN
            RAISE EXCEPTION 'posted_entry_narration_frozen' USING ERRCODE = 'check_violation'; END IF;
        IF NEW.version            <> OLD.version            THEN
            RAISE EXCEPTION 'posted_entry_version_frozen'  USING ERRCODE = 'check_violation'; END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

_ENTRY_IMMUTABILITY_FUNC_V1 = r"""
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


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0004_posting_engine"),
    ]

    operations = [
        migrations.RunSQL(
            sql=_ENTRY_IMMUTABILITY_FUNC_V2,
            reverse_sql=_ENTRY_IMMUTABILITY_FUNC_V1,
        ),
    ]
