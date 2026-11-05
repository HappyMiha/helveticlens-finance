"""Reading a document again (e.g. after switching the local model on) replaces the earlier records
instead of adding a second copy, and never touches what was already confirmed."""

import pytest

RECEIPT = b"""Migros Zuerich
Quittung
Datum 12.10.2026
Brot 3.20
Milch 1.80
Total CHF 5.00
"""


def _spend(lens):
    from datetime import date

    return lens.treemap(date(2026, 10, 1), date(2026, 10, 31))["total"]


def test_same_file_twice_is_reported_and_can_be_read_again(lens):
    first = lens.ingest(RECEIPT, "receipt.txt", "text/plain")
    again = lens.ingest(RECEIPT, "receipt.txt", "text/plain")
    assert again.duplicate_of == first.document_id and not again.operation_ids
    before = _spend(lens)
    res = lens.reread(first.document_id)
    after = _spend(lens)
    assert res.operation_ids and res.operation_ids != first.operation_ids
    if first.operation_ids:
        assert any("replaced" in m for m in res.messages)
        old = lens.operation_detail(first.operation_ids[0])
        assert "Replaced by a new reading" in old["verification_reason"]
    assert str(after) == str(before) == "5.00"  # counted once, not twice
    assert lens.db.execute("SELECT count(*) AS n FROM audit_log WHERE action='reread'").fetchone()["n"] == 1
    from datetime import date

    shown = lens.dashboard(date(2026, 10, 1), date(2026, 10, 31))["unconfirmed"]
    assert [o["operation_id"] for o in shown] == res.operation_ids  # the replaced record is not listed


def test_confirmed_records_are_not_read_again(lens):
    first = lens.ingest(RECEIPT, "receipt.txt", "text/plain")
    if not first.operation_ids:
        pytest.skip("rules did not make a record from the sample")
    lens.correct(first.operation_ids[0], {"confirm": True}, "checked by hand")
    with pytest.raises(ValueError, match="already confirmed"):
        lens.reread(first.document_id)
