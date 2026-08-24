from django.db import migrations


FORWARD = r"""
CREATE OR REPLACE FUNCTION fin_guard_immutable_cost() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'cost records are immutable; use reversal records';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER fin_cost_record_immutable_trg
BEFORE UPDATE OR DELETE ON fin_cost_record
FOR EACH ROW EXECUTE FUNCTION fin_guard_immutable_cost();

CREATE TRIGGER fin_serial_cost_immutable_trg
BEFORE UPDATE OR DELETE ON fin_serial_cost
FOR EACH ROW EXECUTE FUNCTION fin_guard_immutable_cost();
"""

REVERSE = r"""
DROP TRIGGER IF EXISTS fin_serial_cost_immutable_trg ON fin_serial_cost;
DROP TRIGGER IF EXISTS fin_cost_record_immutable_trg ON fin_cost_record;
DROP FUNCTION IF EXISTS fin_guard_immutable_cost();
"""


class Migration(migrations.Migration):
    dependencies = [("finance", "0003_costrecord_inventorycostbalance_serialcost")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
