"""ISO 20022 camt.053 / camt.054 bank statement import.

Structured bank data is parsed deterministically; no AI is involved. Each
entry keeps its position in the file as provenance.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal

from ..domain.events import Method, Payment, Provenance
from ..domain.money import Money


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(node: ET.Element, *path: str):
    current = [node]
    for name in path:
        current = [c for n in current for c in n if _local(c.tag) == name]
        if not current:
            return None
    return current[0]


def _text(node: ET.Element, *path: str):
    found = _find(node, *path)
    return found.text.strip() if found is not None and found.text else None


def _date(node: ET.Element, *path: str):
    value = _text(node, *path, "Dt") or _text(node, *path, "DtTm")
    return date.fromisoformat(value[:10]) if value else None


def parse(xml_bytes: bytes, document_id: str) -> list[Payment]:
    root = ET.fromstring(xml_bytes)
    kind = "camt.054" if any(_local(e.tag) == "Ntfctn" for e in root.iter()) else "camt.053"
    payments: list[Payment] = []
    entries = [e for e in root.iter() if _local(e.tag) == "Ntry"]
    for index, entry in enumerate(entries):
        amount_node = _find(entry, "Amt")
        if amount_node is None or amount_node.text is None:
            continue
        amount = Money(Decimal(amount_node.text.strip()), amount_node.attrib["Ccy"])
        if _text(entry, "CdtDbtInd") == "DBIT":
            amount = -amount
        details = _find(entry, "NtryDtls", "TxDtls")
        party_path = ("RltdPties", "Cdtr", "Nm") if amount.amount < 0 else ("RltdPties", "Dbtr", "Nm")
        counterparty = (details is not None and (_text(details, *party_path)
                        or _text(details, *party_path[:-1], "Pty", "Nm"))) or ""
        reference = details is not None and _text(details, "RmtInf", "Strd", "CdtrRefInf", "Ref")
        remittance = details is not None and _text(details, "RmtInf", "Ustrd")
        payments.append(Payment(
            amount=amount,
            booked_on=_date(entry, "BookgDt") or _date(entry, "ValDt"),
            counterparty=counterparty,
            reference=(reference or None) and reference.replace(" ", ""),
            bank_reference=_text(entry, "AcctSvcrRef"),
            remittance=remittance or None,
            provenance=Provenance(
                document_id=document_id,
                location=f"{kind} Ntry[{index}]",
                method=Method.STRUCTURED_IMPORT,
                agent=f"parser:{kind}",
            ),
        ))
    return payments


def account_iban(xml_bytes: bytes):
    """IBAN of the statement's own account, if present."""
    root = ET.fromstring(xml_bytes)
    for stmt in root.iter():
        if _local(stmt.tag) in ("Stmt", "Ntfctn"):
            return _text(stmt, "Acct", "Id", "IBAN")
    return None
