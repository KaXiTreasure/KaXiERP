from django.db import migrations


CREATE_FUNCTIONS = r"""
CREATE OR REPLACE FUNCTION fin_guard_posted_journal_line() RETURNS trigger AS $$
DECLARE parent_status varchar(16);
BEGIN
    SELECT status INTO parent_status
      FROM fin_journal_entry
     WHERE id = COALESCE(OLD.entry_id, NEW.entry_id);
    IF parent_status IN ('posted', 'reversed') THEN
        RAISE EXCEPTION 'posted journal lines are immutable';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER fin_journal_line_immutable_trg
BEFORE UPDATE OR DELETE ON fin_journal_entry_line
FOR EACH ROW EXECUTE FUNCTION fin_guard_posted_journal_line();

CREATE OR REPLACE FUNCTION fin_guard_posted_journal() RETURNS trigger AS $$
BEGIN
    IF OLD.status IN ('posted', 'reversed') THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'posted journals are immutable';
        END IF;
        IF NOT (
            OLD.status = 'posted' AND NEW.status = 'reversed'
            AND OLD.company_id = NEW.company_id
            AND OLD.ledger_id = NEW.ledger_id
            AND OLD.period_id = NEW.period_id
            AND OLD.voucher_no = NEW.voucher_no
            AND OLD.entry_type = NEW.entry_type
            AND OLD.entry_date = NEW.entry_date
            AND OLD.description = NEW.description
            AND OLD.source_type = NEW.source_type
            AND OLD.source_id = NEW.source_id
            AND OLD.total_debit_base = NEW.total_debit_base
            AND OLD.total_credit_base = NEW.total_credit_base
        ) THEN
            RAISE EXCEPTION 'posted journals are immutable';
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER fin_journal_immutable_trg
BEFORE UPDATE OR DELETE ON fin_journal_entry
FOR EACH ROW EXECUTE FUNCTION fin_guard_posted_journal();
"""

DROP_FUNCTIONS = r"""
DROP TRIGGER IF EXISTS fin_journal_immutable_trg ON fin_journal_entry;
DROP FUNCTION IF EXISTS fin_guard_posted_journal();
DROP TRIGGER IF EXISTS fin_journal_line_immutable_trg ON fin_journal_entry_line;
DROP FUNCTION IF EXISTS fin_guard_posted_journal_line();
"""


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]
    operations = [migrations.RunSQL(CREATE_FUNCTIONS, DROP_FUNCTIONS)]
