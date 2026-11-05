"""Model assistance is accepted only when the document's arithmetic then reconciles."""

import json
import random

from financial_lens import evaluation as E
from financial_lens.ai.providers import Orchestrator, Scripted
from financial_lens.extract import ocr, understand


class Reader(Scripted):
    """Plays a model: answers by looking at the numbered lines, optionally lying."""

    def __init__(self, lie=False):
        super().__init__(name="test-model", locality="local")
        self.lie = lie
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        roles = []
        rows = [l.split(": ", 1) for l in user.splitlines()]
        order = ["gross", "deduction", "deduction", "deduction", "deduction", "deduction", "total_deductions", "allowance_after",
                 "net", "allowance_after", "payout"]
        amount_lines = [(n, t) for n, t in rows if any(ch.isdigit() for ch in t) and ("." in t) and n not in ("L1", "L2", "L3")]
        # a crude but honest reader: second amount line is gross, last is payout, the one before expenses is net
        for i, (n, t) in enumerate(amount_lines):
            amt = t.split()[-1].lstrip("-")
            if i == 0:
                continue  # base salary, implied by gross
            role = "gross" if i == 1 else ("payout" if i == len(amount_lines) - 1 else "deduction")
            if "Lohn nach" in t or "Verbleibender" in t or "Take-home" in t or "Remaining" in t:
                role = "net"
            if "Summe Abzüge" in t or "Sum of deductions" in t:
                role = "total_deductions"
            if "Kinderzulage" in t or "Family allowance" in t or "Spesen" in t or "Expenses" in t:
                role = "allowance_after" if i > 1 else role
            if self.lie and role == "payout":
                amt = "9999.95"
            roles.append({"line": n.lstrip("L"), "role": role, "amount": amt})
        return json.dumps({"doc_type": "payslip", "roles": roles})


def _hard_docs():
    rng = random.Random(3)
    return [E.gen_payslip(rng, "de", hard=True) for _ in range(4)]


def test_model_fills_in_where_rules_do_not_know_the_wording():
    reader = Reader()
    orch = Orchestrator(routes={"understand": [reader]})
    docs = _hard_docs()
    without = E.run(docs, None)
    with_model = E.run(docs, orch)
    assert without.value_ok == 0 and without.false_confirmations == 0
    assert with_model.false_confirmations == 0
    assert reader.calls == len(docs)
    # whatever the model got right was verified by arithmetic; nothing unverified is confirmed
    assert with_model.consistent == with_model.value_ok


def test_invented_amounts_are_never_used():
    orch = Orchestrator(routes={"understand": [Reader(lie=True)]})
    d = _hard_docs()[0]
    an = understand.analyse(ocr.recognise(d.data, d.media), model=orch)
    got = (an.facts.get("payout") or an.facts.get("net") or {}).get("value")
    assert str(got) != "9999.95"  # the invented number is not printed, so it can never be accepted
    if an.consistent:  # the arithmetic found the true reading on its own
        assert got == d.truth["amount"]


def test_model_not_called_when_rules_reconcile():
    reader = Reader()
    orch = Orchestrator(routes={"understand": [reader]})
    d = E.gen_payslip(random.Random(1), "de")
    an = understand.analyse(ocr.recognise(d.data, d.media), model=orch)
    assert an.consistent and reader.calls == 0
