from django.db import transaction

from kaxi.shared.outbox import OutboxEvent
from kaxi.shared.outbox_service import append_outbox_event
from kaxi.system.models import DictionaryItem, NumberRule, NumberSequence


def test_db02_tables_are_explicitly_named() -> None:
    assert DictionaryItem._meta.db_table == "sys_dictionary_item"
    assert NumberRule._meta.db_table == "sys_number_rule"
    assert NumberSequence._meta.db_table == "sys_number_sequence"
    assert OutboxEvent._meta.db_table == "evt_outbox"


def test_outbox_aggregate_version_is_unique() -> None:
    names = {constraint.name for constraint in OutboxEvent._meta.constraints}
    assert "evt_outbox_aggregate_event_version_uniq" in names


def test_outbox_write_requires_atomic_transaction() -> None:
    assert not transaction.get_connection().in_atomic_block
    try:
        append_outbox_event(
            company=None,  # type: ignore[arg-type]
            aggregate_type="test",
            aggregate_id="1",
            aggregate_version=1,
            event_type="TEST_EVENT",
            payload={},
        )
    except RuntimeError as exc:
        assert str(exc) == "Outbox事件必须在数据库事务中写入"
    else:
        raise AssertionError("Outbox write outside transaction must fail")
