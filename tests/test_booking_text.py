"""Bank booking texts become recognisable merchants, categories and own transfers."""

from decimal import Decimal

import pytest

from docgen import statement_bkb_en
from financial_lens.ingest.booking_text import label, owners_from_header, parse

ME = ["Mykhailo Shavrytskyi"]

CASES = [
    ("purchase of goods and services abroad Withdrawal location: BKGBOOKINGCOM HOTE Transaction date: / 11:36:30 "
     "Card no.: 487", "card", "Booking.com", ("Leisure", "Travel")),
    ("atm Cash withdrawal ATM Withdrawal location: BKB VOGESENPLATZ 63 Transaction date: / 20:31:21 Card no.: 4871 52** "
     "**** 7", "cash", "Cash withdrawal, BKB Vogesenplatz 63", ("Cash", "Withdrawals")),
    ("debit collective order of 2 4 4 0 1 BKB Booking No. 1236984944 7 8 1 - 3 0 6 9 3 2 4 Wartenbergstrasse 40 "
     "4052 Basel - P", "collective", "Collective payment order", ("Bills", "Collective payment orders")),
    ("debit Money transfer to H +41791520003 T M _ T D _ T M BKB Booking No. 1234864973 T S _ C C",
     "p2p_out", "To +41791520003", ("Transfers", "To people")),
    ("payment SBB EASYRIDE, BERN H +41798629811 T M _ T D _ T M BKB Booking No. 1237488234 T S _ C C",
     "bill", "SBB EasyRide", ("Transport", "Public transport")),
    ("purchase of goods and services abroad a 0 8 7 Withdrawal location: STARLINK DUBLIN 6 7 6 - 5 4 Transaction "
     "date: / 15:40", "card", "Starlink, Dublin", ("Housing", "Telecom")),
    ("purchase of goods and services Withdrawal location: Migros M Mulhauserst Transaction date: / 16:27:06 Card no.: "
     "4871 52*", "card", "Migros", ("Food", "Groceries")),
    ("purchase of goods and services abroad d _ T M T Withdrawal location: 242098 MARKTKAUF S _ C C WE A 0 8 7 "
     "Transaction dat", "card", "Marktkauf", ("Food", "Groceries")),
    ("payment s _ C C RICARDO AG, ZUG A 0 8 7 +41798629811", "bill", "Ricardo", ("Shopping", "Online")),
    ("purchase of goods and services Withdrawal location: Frojer Cafe Basel Transaction date: / 12:00", "card",
     "Frojer Cafe, Basel", ("Food", "Restaurants")),
]


@pytest.mark.parametrize("text,kind,shown,category", CASES)
def test_booking_lines(text, kind, shown, category):
    b = parse(text, ME)
    assert (b.kind, label(b), b.category) == (kind, shown, category)


def test_no_debris_left():
    b = parse("purchase of goods and services 2 4 - P - G Withdrawal location: SUMUP HB N I K N ENTERPRIS A B E - 1 "
              "Transaction date: /", ME)
    assert label(b) == "HB Enterpris" and "SumUp" in b.notes[0]


def test_own_revolut_and_unknown_revolut():
    text = "revolut bank uab Konstitucijos ave. 21B 08130 LT-Vilnius Lithuania Mykhailo Shavrytskyi, CH BKB Booking No. 122"
    own = parse(text, ME)
    assert own.own_account and own.category == ("Own transfers",)
    other = parse(text.replace("Mykhailo Shavrytskyi", "Anna Muster"), ME)
    assert not other.own_account and other.possibly_own


def test_incoming_phone_transfer_keeps_message():
    b = parse("credit Money transfer from +41796375138 Für die Spark+ Kugeln vielen Dank BKB Booking No. 1238033742", ME)
    assert b.kind == "p2p_in" and label(b) == "From +41796375138" and "Kugeln" in b.notes[0]


def test_holder_from_header():
    assert owners_from_header("Basler Kantonalbank\nMykhailo Shavrytskyi\nStatement of account\n") == ME


def test_statement_import_cleans_names_and_skips_own_transfers(lens):
    res = lens.ingest(statement_bkb_en(), "bkb.pdf")
    ops = [lens.operation_detail(o) for o in res.operation_ids]
    by = {o["counterparty"]: o for o in ops}
    assert "Booking.com" in by and by["Booking.com"]["category_path"] == ["Leisure", "Travel"]
    assert by["Migros"]["category_path"] == ["Food", "Groceries"]
    assert by["SBB EasyRide"]["category_path"] == ["Transport", "Public transport"]
    assert by["Collective payment order"]["category_path"] == ["Bills", "Collective payment orders"]
    own = [o for o in ops if o["category_path"] == ["Own transfers"]]
    assert len(own) == 1 and own[0]["kind"] == "transfer" and Decimal(own[0]["amount"]) == Decimal("-1000.00")
    assert all("Booking No" not in o["counterparty"] for o in ops)


def test_old_imports_are_tidied(lens):
    res = lens.ingest(statement_bkb_en(), "bkb.pdf")
    # make the entries look like the old reader's output, then read again
    for o in res.operation_ids:
        d = lens.operation_detail(o)
        lens._revision(o, {"counterparty": (d["description"] or "")[:120], "category_id": lens.category_id(("Unclassified",)),
                           "agent": "analyst:statement"}, "old reader")
    lens.db.execute("UPDATE operations SET kind='payment' WHERE id = ANY(%s::uuid[])", (res.operation_ids,))
    lens.db.execute("DELETE FROM settings WHERE key='bank_text_version'")
    assert lens.tidy_bank_entries() >= 5
    ops = [lens.operation_detail(o) for o in res.operation_ids]
    assert {"Booking.com", "Migros", "SBB EasyRide"} <= {o["counterparty"] for o in ops}
    assert [o["kind"] for o in ops if o["category_path"] == ["Own transfers"]] == ["transfer"]
    assert lens.tidy_bank_entries() == 0  # once per reader version
