"""Financial Lens desktop (PySide6).

Main screen (§13): balance, income, expenses, treemap, time filter,
unconfirmed operations, unpaid invoices, recent documents. Other screens:
Inbox, Documents, Transactions, AI Activity. Drop files anywhere to import.

Run: FL_DSN=... FL_DATA=... python -m financial_lens.desktop.main
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QPainter, QPen
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QMainWindow, QMessageBox, QPushButton, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from .. import analytics, assistant
from ..service import FinancialLens
from ..views.layout import squarify

# Colours mirror the Helvetic Lens dark tokens (site/assets/design-tokens.css).
TOKENS = {
    "bg": "#090b0e", "surface": "#111418", "surface2": "#181a1e", "raised": "#1b1d21", "text": "#e6e3e1",
    "muted": "#a7adb5", "line": "#343a44", "line_strong": "#73777e", "success": "#a4d2b7", "warning": "#e6c083",
    "danger": "#f2b0a9", "signal": "#e63b32",
}
# Expenses in red/orange, income in greens, transfers neutral, unclassified grey (§6.1).
EXPENSE_SHADES = ["#7a2f2a", "#8a4127", "#6f3a2c", "#93502a", "#5f2f2f", "#7d4a33", "#6a3324", "#8c5a3a"]
INCOME_SHADES = ["#2f5a43", "#3a6a4c", "#2c4f3f", "#44735a"]
GREY = "#3b3f46"

QSS = f"""
* {{ font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif; font-size: 13px; color: {TOKENS['text']}; }}
QMainWindow, QWidget#root {{ background: {TOKENS['bg']}; }}
QFrame#card {{ background: {TOKENS['surface']}; border: 1px solid {TOKENS['line']}; border-radius: 12px; }}
QLabel#muted {{ color: {TOKENS['muted']}; }}
QLabel#kpi {{ font-size: 22px; font-weight: 600; }}
QListWidget#nav {{ background: {TOKENS['surface']}; border: none; border-right: 1px solid {TOKENS['line']}; padding: 8px; }}
QListWidget#nav::item {{ padding: 8px 10px; border-radius: 6px; }}
QListWidget#nav::item:selected {{ background: {TOKENS['raised']}; }}
QTableWidget, QTextBrowser {{ background: {TOKENS['surface']}; border: 1px solid {TOKENS['line']}; border-radius: 8px;
  gridline-color: {TOKENS['line']}; selection-background-color: {TOKENS['raised']}; }}
QHeaderView::section {{ background: {TOKENS['surface2']}; color: {TOKENS['muted']}; border: none; padding: 6px; }}
QPushButton, QComboBox {{ background: {TOKENS['surface2']}; border: 1px solid {TOKENS['line_strong']}; border-radius: 6px; padding: 6px 12px; }}
QPushButton#primary {{ background: {TOKENS['text']}; color: {TOKENS['bg']}; border-color: {TOKENS['text']}; font-weight: 600; }}
QToolBar {{ background: {TOKENS['surface']}; border: none; border-bottom: 1px solid {TOKENS['line']}; padding: 6px; spacing: 6px; }}
QToolBar QToolButton {{ background: {TOKENS['surface2']}; border: 1px solid {TOKENS['line_strong']}; border-radius: 6px; padding: 5px 12px; }}
QToolBar QLabel {{ color: {TOKENS['muted']}; }}
QPushButton#crumb {{ background: transparent; border: none; color: {TOKENS['muted']}; padding: 2px 4px; }}
"""

STATUS_LABEL = {"confirmed": "Confirmed", "needs_review": "Needs review", "unconfirmed": "Unconfirmed"}


def chf(value) -> str:
    v = Decimal(str(value)).quantize(Decimal("0.01"))
    sign = "-" if v < 0 else ""
    whole, frac = f"{abs(v):.2f}".split(".")
    return f"{sign}CHF {int(whole):,}".replace(",", "’") + "." + frac


def periods(today: date) -> dict[str, tuple[date, date]]:
    first = today.replace(day=1)
    prev_end = first - timedelta(days=1)
    q = (today.month - 1) // 3
    return {
        "Today": (today, today),
        "This week": (today - timedelta(days=today.weekday()), today),
        "This month": (first, today),
        "Last month": (prev_end.replace(day=1), prev_end),
        "This quarter": (date(today.year, 3 * q + 1, 1), today),
        "This year": (date(today.year, 1, 1), today),
        "Last year": (date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)),
        "All time": (date(1970, 1, 1), date(2999, 12, 31)),
    }


class Treemap(QWidget):
    """Area ∝ amount. Click a category to drill down, a record to inspect it."""

    category_opened = Signal(tuple)
    operation_selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(420, 300)
        self.setMouseTracking(True)
        self.node: Optional[dict] = None
        self.mode = "expenses"
        self.path: tuple[str, ...] = ()
        self.items: list[tuple[QRectF, dict]] = []
        self.selected: Optional[str] = None

    def show_node(self, node: dict, path: tuple[str, ...], mode: str) -> None:
        self.node, self.path, self.mode = node, path, mode
        self.update()

    def _entries(self) -> list[dict]:
        if not self.node:
            return []
        out = [{"type": "category", "name": c["name"], "value": Decimal(c["total"]), "count": c["count"]}
               for c in self.node["children"]]
        out += [{"type": "operation", "name": o["counterparty"] or o["kind"], "value": Decimal(o["amount"]),
                 "op": o} for o in self.node["operations"]]
        return sorted([e for e in out if e["value"] > 0], key=lambda e: -e["value"])

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(TOKENS["surface"]))
        entries = self._entries()
        self.items = []
        if not entries:
            p.setPen(QColor(TOKENS["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, "No records in this period yet.\nDrop receipts, invoices or bank statements here.")
            return
        rects = squarify([e["value"] for e in entries], 0, 0, self.width(), self.height())
        shades = INCOME_SHADES if self.mode == "income" else EXPENSE_SHADES
        for k, (e, (x, y, w, h)) in enumerate(zip(entries, rects)):
            r = QRectF(x + 1, y + 1, max(w - 2, 0), max(h - 2, 0))
            self.items.append((r, e))
            name = e["name"]
            colour = GREY if name in ("Unclassified",) else shades[k % len(shades)]
            if e["type"] == "operation" and e["op"]["kind"] == "transfer":
                colour = GREY
            p.fillRect(r, QColor(colour))
            if e["type"] == "operation":
                status = e["op"]["verification"]
                if status != "confirmed":  # problem/unconfirmed records get their own indicator (§6.1)
                    pen = QPen(QColor(TOKENS["warning"] if status == "needs_review" else TOKENS["muted"]), 2,
                               Qt.SolidLine if status == "needs_review" else Qt.DashLine)
                    p.setPen(pen)
                    p.drawRect(r.adjusted(2, 2, -2, -2))
                if e["op"]["id"] == self.selected:
                    p.setPen(QPen(QColor(TOKENS["text"]), 2))
                    p.drawRect(r.adjusted(1, 1, -1, -1))
            if w > 60 and h > 34:
                p.setPen(QColor(TOKENS["text"]))
                f = QFont(p.font())
                f.setBold(True)
                p.setFont(f)
                p.drawText(r.adjusted(8, 6, -6, -6), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, name)
                f.setBold(False)
                p.setFont(f)
                p.setPen(QColor(TOKENS["muted"]))
                sub = chf(e["value"]) + (f" · {e['count']}" if e["type"] == "category" else "")
                p.drawText(r.adjusted(8, 6, -6, -6), Qt.AlignLeft | Qt.AlignBottom, sub)

    def entry_at(self, pos: QPointF) -> Optional[dict]:
        return next((e for r, e in self.items if r.contains(pos)), None)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        e = self.entry_at(event.position())
        if not e:
            return
        if e["type"] == "category":
            self.category_opened.emit(self.path + (e["name"],))
        else:
            self.selected = e["op"]["id"]
            self.update()
            self.operation_selected.emit(e["op"]["id"])

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        e = self.entry_at(event.position())
        self.setToolTip(f"{e['name']} · {chf(e['value'])}" if e else "")


def card(widget: QWidget, title: str = "") -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(14, 12, 14, 12)
    if title:
        t = QLabel(title)
        t.setObjectName("muted")
        lay.addWidget(t)
    lay.addWidget(widget)
    return frame


def table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    return t


def fill(t: QTableWidget, rows: list[list], keys: Optional[list[str]] = None) -> None:
    t.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            item = QTableWidgetItem("" if value is None else str(value))
            if keys:
                item.setData(Qt.UserRole, keys[i])
            t.setItem(i, j, item)


class MainWindow(QMainWindow):
    def __init__(self, lens: FinancialLens, today: Optional[date] = None) -> None:
        super().__init__()
        self.lens = lens
        self.today = today or date.today()
        self.path: tuple[str, ...] = ()
        self.mode = "expenses"
        self.current_doc: Optional[str] = None
        self.setWindowTitle("Financial Lens")
        self.resize(1440, 900)
        self.setAcceptDrops(True)
        self.setStyleSheet(QSS)

        root = QWidget()
        root.setObjectName("root")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(190)
        self.nav.addItems(["Overview", "Inbox", "Documents", "Transactions", "Analytics", "Ask", "AI Activity"])
        outer.addWidget(self.nav)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        # --- toolbar
        bar = self.addToolBar("Main")
        bar.setMovable(False)
        self.period = QComboBox()
        self.period.addItems(list(periods(self.today)))
        self.period.setCurrentText("This month")
        self.view_mode = QComboBox()
        self.view_mode.addItems(["Expenses", "Income"])
        imp = QAction("Import files…", self)
        imp.triggered.connect(self.import_dialog)
        self.org_box = QComboBox()
        self.org_box.addItems([o["name"] for o in self.lens.organizations()])
        self.org_box.setCurrentText(next(o["name"] for o in self.lens.organizations() if o["id"] == self.lens.org))
        self.org_box.currentTextChanged.connect(self._switch_org)
        self.group_box = QComboBox()
        self.group_box.addItems(["By category", "By account", "By project", "By counterparty", "By object"])
        self.group_box.currentTextChanged.connect(lambda _: (setattr(self, "path", ()), self.refresh()))
        exp = QAction("Export…", self)
        exp.triggered.connect(self.export_dialog)
        bar.addWidget(QLabel("  Profile "))
        bar.addWidget(self.org_box)
        bar.addWidget(QLabel("  Period "))
        bar.addWidget(self.period)
        bar.addWidget(QLabel("  Show "))
        bar.addWidget(self.view_mode)
        bar.addWidget(self.group_box)
        bar.addSeparator()
        bar.addAction(imp)
        bar.addAction(exp)
        add = QAction("Add record…", self)
        add.triggered.connect(self.add_record_dialog)
        pair = QAction("Pair phone…", self)
        pair.triggered.connect(self.pair_phone_dialog)
        mail = QAction("Fetch mail", self)
        mail.triggered.connect(self.fetch_mail)
        bar.addAction(add)
        bar.addAction(pair)
        bar.addAction(mail)

        self.stack.addWidget(self._overview())
        self.inbox = table(["Type", "Item", "Status", "Reason"])
        self.inbox_accept = QPushButton("Confirm proposed link")
        self.inbox_reject = QPushButton("Reject proposed link")
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.addWidget(self.inbox)
        row = QHBoxLayout()
        row.addWidget(self.inbox_accept)
        row.addWidget(self.inbox_reject)
        row.addStretch()
        lay.addLayout(row)
        self.stack.addWidget(box)
        self.docs = table(["Received", "File", "Type", "Status", "Folder", "Records"])
        self.stack.addWidget(self.docs)
        self.txs = table(["Date", "Kind", "Counterparty", "Category", "Amount", "Status"])
        self.stack.addWidget(self.txs)
        self.stack.addWidget(self._analytics())
        self.stack.addWidget(self._ask())
        self.ai = table(["When", "Task", "Provider", "Where", "Summary"])
        self.stack.addWidget(self.ai)

        self.nav.currentRowChanged.connect(self._switch)
        self.period.currentTextChanged.connect(lambda _: self.refresh())
        self.view_mode.currentTextChanged.connect(self._mode)
        self.treemap.category_opened.connect(self.open_category)
        self.treemap.operation_selected.connect(self.show_operation)
        self.ops.itemSelectionChanged.connect(self._op_from_table)
        self.unconfirmed.itemSelectionChanged.connect(lambda: self._op_from(self.unconfirmed))
        self.unpaid.itemSelectionChanged.connect(lambda: self._op_from(self.unpaid))
        self.txs.itemDoubleClicked.connect(lambda item: (self.nav.setCurrentRow(0), self.show_operation(item.data(Qt.UserRole))))
        self.docs.itemDoubleClicked.connect(lambda item: self.open_original(item.data(Qt.UserRole)))
        self.inbox_accept.clicked.connect(lambda: self._decide(True))
        self.inbox_reject.clicked.connect(lambda: self._decide(False))
        self.nav.setCurrentRow(0)
        self.refresh()

    # ------------------------------------------------------------ layout
    def _overview(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setSpacing(12)
        self.kpi = {}
        for i, (key, label) in enumerate([("balance", "Balance (income − expenses)"), ("income", "Income"),
                                          ("expenses", "Expenses"), ("open", "Unconfirmed / unpaid")]):
            v = QLabel("—")
            v.setObjectName("kpi")
            self.kpi[key] = v
            grid.addWidget(card(v, label), 0, i)
        self.crumbs = QHBoxLayout()
        crumb_box = QWidget()
        crumb_box.setLayout(self.crumbs)
        self.treemap = Treemap()
        centre = QWidget()
        cl = QVBoxLayout(centre)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(crumb_box)
        cl.addWidget(self.treemap, 1)
        self.ops = table(["Date", "Counterparty", "Amount", "Status"])
        split = QSplitter(Qt.Vertical)
        split.addWidget(card(centre))
        split.addWidget(card(self.ops, "Operations in this category"))
        split.setSizes([560, 220])
        self.evidence = QTextBrowser()
        self.evidence.setOpenLinks(False)
        self.evidence.anchorClicked.connect(self._anchor)
        self.evidence.setHtml("<p style='color:#a7adb5'>Select a record to see its evidence.</p>")
        self.open_btn = QPushButton("Open original")
        self.open_btn.setObjectName("primary")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(lambda: self.open_original(self.current_doc))
        ev = QWidget()
        evl = QVBoxLayout(ev)
        evl.setContentsMargins(0, 0, 0, 0)
        evl.addWidget(self.evidence, 1)
        evl.addWidget(self.open_btn)
        self.unconfirmed = table(["Date", "Counterparty", "Amount", "Status"])
        self.unpaid = table(["Due", "Counterparty", "Amount"])
        self.recent = table(["File", "Type", "Status"])
        side = QSplitter(Qt.Vertical)
        side.addWidget(card(ev, "Evidence"))
        side.addWidget(card(self.unconfirmed, "Unconfirmed operations"))
        side.addWidget(card(self.unpaid, "Unpaid invoices"))
        side.addWidget(card(self.recent, "Recent documents"))
        side.setSizes([420, 160, 120, 120])
        main = QSplitter(Qt.Horizontal)
        main.addWidget(split)
        main.addWidget(side)
        main.setSizes([900, 420])
        grid.addWidget(main, 1, 0, 1, 4)
        grid.setRowStretch(1, 1)
        return w

    def _analytics(self) -> QWidget:
        w = QWidget()
        lay = QGridLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        self.flow = table(["Month", "Income", "Expenses", "Net", "Savings (cumulative)"])
        self.cmp = table(["Category", "Previous period", "This period", "Change", "%"])
        self.cps = table(["Counterparty", "Total", "Records"])
        self.rec = table(["Counterparty", "Cadence", "Typical amount", "Next expected"])
        lay.addWidget(card(self.flow, "Cash flow and savings by month"), 0, 0)
        lay.addWidget(card(self.cmp, "Compared with the previous period"), 0, 1)
        lay.addWidget(card(self.cps, "Spending by counterparty"), 1, 0)
        lay.addWidget(card(self.rec, "Recurring payments"), 1, 1)
        return w

    def _ask(self) -> QWidget:
        from PySide6.QtWidgets import QLineEdit

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        self.question = QLineEdit()
        self.question.setPlaceholderText("e.g. How much did I spend on food this year?  ·  unpaid invoices  ·  Alle Zahlungen an Swisscom")
        self.answer = QLabel("")
        self.answer.setObjectName("kpi")
        self.answer.setWordWrap(True)
        self.answer_items = table(["Result", "Status"])
        note = QLabel("Answers are computed from your ledger, not by a language model. Double-click a result to open its evidence.")
        note.setObjectName("muted")
        lay.addWidget(self.question)
        lay.addWidget(self.answer)
        lay.addWidget(self.answer_items, 1)
        lay.addWidget(note)
        self.question.returnPressed.connect(lambda: self.ask(self.question.text()))
        self.answer_items.itemDoubleClicked.connect(
            lambda item: item.data(Qt.UserRole) and (self.nav.setCurrentRow(0), self.show_operation(item.data(Qt.UserRole))))
        return w

    def ask(self, text: str) -> dict:
        result = assistant.ask(self.lens, text, self.today)
        self.answer.setText(result["answer"])
        fill(self.answer_items, [[i.get("label", ""), STATUS_LABEL.get(i.get("verification", ""), "")] for i in result["items"]],
             [i.get("id") for i in result["items"]])
        return result

    def _refresh_analytics(self) -> None:
        start, end = self.span()
        if start.year < 1990:
            start = date(self.today.year - 4, 1, 1)
        end = min(end, self.today)
        flow = analytics.cash_flow(self.lens, start, end)
        fill(self.flow, [[f["month"], chf(f["income"]), chf(f["expenses"]), chf(f["net"]), chf(f["cumulative"])] for f in flow])
        prev = analytics.previous_period(start, end)
        fill(self.cmp, [[" / ".join(r["category"]), chf(r["a"]), chf(r["b"]), chf(r["change"]),
                         (r["change_pct"] + " %") if r["change_pct"] else "new"] for r in analytics.compare(self.lens, prev, (start, end))])
        fill(self.cps, [[c["counterparty"], chf(c["total"]), c["count"]] for c in analytics.by_counterparty(self.lens, start, end)])
        fill(self.rec, [[r.counterparty, r.cadence, chf(r.typical_amount), r.next_expected.isoformat()]
                        for r in analytics.detect_recurring(self.lens, self.today)])

    # ------------------------------------------------------------ data
    def span(self) -> tuple[date, date]:
        return periods(self.today)[self.period.currentText()]

    def refresh(self) -> None:
        start, end = self.span()
        d = self.lens.dashboard(start, end)
        self.kpi["balance"].setText(chf(d["balance"]))
        self.kpi["income"].setText(chf(d["income"]))
        self.kpi["expenses"].setText(chf(d["expenses"]))
        self.kpi["open"].setText(f"{len(d['unconfirmed'])} / {len(d['unpaid'])}")
        fill(self.unconfirmed, [[r["op_date"], r["counterparty"], chf(abs(Decimal(r["amount"]))),
                                 STATUS_LABEL[r["verification"]]] for r in d["unconfirmed"]],
             [r["operation_id"] for r in d["unconfirmed"]])
        fill(self.unpaid, [[r["due_date"] or r["op_date"], r["counterparty"], chf(r["amount"])] for r in d["unpaid"]],
             [r["operation_id"] for r in d["unpaid"]])
        fill(self.recent, [[r["filename"], r["doc_type"], r["processing_status"]] for r in d["recent_documents"]],
             [r["id"] for r in d["recent_documents"]])
        group = self.group_box.currentText().removeprefix("By ").lower()
        self.tree = self.lens.treemap(start, end, self.mode, group)
        self.open_category(self.path)
        self._other_screens()

    def node_for(self, path: tuple[str, ...]) -> Optional[dict]:
        node = self.tree
        for part in path:
            node = next((c for c in node["children"] if c["name"] == part), None)
            if node is None:
                return None
        return node

    def open_category(self, path: tuple) -> None:
        node = self.node_for(tuple(path))
        if node is None:
            path, node = (), self.tree
        self.path = tuple(path)
        self.treemap.show_node(node, self.path, self.mode)
        while self.crumbs.count():
            item = self.crumbs.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for i, name in enumerate(("All",) + self.path):
            b = QPushButton(name if i else ("All " + self.mode))
            b.setObjectName("crumb")
            b.clicked.connect(lambda _=False, p=self.path[:i]: self.open_category(p))
            self.crumbs.addWidget(b)
            if i < len(self.path):
                self.crumbs.addWidget(QLabel("/"))
        total = QLabel(f"{chf(node['total'])} · {node['count']} records")
        total.setObjectName("muted")
        self.crumbs.addStretch()
        self.crumbs.addWidget(total)
        ops = []

        def walk(n):
            ops.extend(n["operations"])
            for c in n["children"]:
                walk(c)
        walk(node)
        ops.sort(key=lambda o: o["date"], reverse=True)
        fill(self.ops, [[o["date"], o["counterparty"], chf(o["amount"]), STATUS_LABEL[o["verification"]]] for o in ops],
             [o["id"] for o in ops])

    def _mode(self, text: str) -> None:
        self.mode = text.lower()
        self.path = ()
        self.refresh()

    def _op_from(self, t: QTableWidget) -> None:
        items = t.selectedItems()
        if items:
            self.show_operation(items[0].data(Qt.UserRole))

    def _op_from_table(self) -> None:
        self._op_from(self.ops)

    def show_operation(self, op_id: str) -> None:
        d = self.lens.operation_detail(op_id)
        self.current_doc = next((str(x["id"]) for x in d["documents"] if x["role"] == "source"), None) or \
            next((str(x["id"]) for x in d["documents"]), None)
        self.open_btn.setEnabled(self.current_doc is not None)
        self.evidence.setHtml(evidence_html(d))

    def _anchor(self, url: QUrl) -> None:
        kind, _, ident = url.toString().partition(":")
        if kind == "op":
            self.show_operation(ident)
        elif kind == "doc":
            self.open_original(ident)

    def open_original(self, document_id: Optional[str]) -> Optional[Path]:
        if not document_id:
            return None
        data, media, name = self.lens.original(document_id)
        target = Path(tempfile.gettempdir()) / "financial-lens" / f"{document_id}-{Path(name).name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)  # a copy; the stored original stays read-only
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        return target

    def _other_screens(self) -> None:
        docs = self.lens.documents()
        fill(self.docs, [[d["received_at"][:16] if isinstance(d["received_at"], str) else d["received_at"],
                          d["filename"], d["doc_type"], d["processing_status"], d["folder"], d["operations"]]
                         for d in docs], [d["id"] for d in docs])
        start, end = self.span()
        rows = self.lens.db.execute(
            "SELECT operation_id, kind, op_date, counterparty, category_id, amount, verification FROM operations_current "
            "WHERE organization_id=%s AND op_date BETWEEN %s AND %s ORDER BY op_date DESC", (self.lens.org, start, end)).fetchall()
        fill(self.txs, [[r["op_date"], r["kind"], r["counterparty"], " / ".join(self.lens.category_path(r["category_id"])),
                         chf(r["amount"]), STATUS_LABEL[r["verification"]]] for r in rows],
             [str(r["operation_id"]) for r in rows])
        self._refresh_analytics()
        acts = self.lens.ai_activity()
        fill(self.ai, [[str(a["at"])[:19], a["task"], a["provider"], a["locality"], a["summary"]] for a in acts])
        proposed = self.lens.db.execute(
            "SELECT l.id, l.reasons, f.counterparty, f.amount FROM links l JOIN operations_current f "
            "ON f.operation_id=l.from_operation_id WHERE l.organization_id=%s AND l.status='proposed'",
            (self.lens.org,)).fetchall()
        review = [d for d in docs if d["processing_status"] in ("needs_review", "failed")]
        fill(self.inbox, [["Proposed link", f"{p['counterparty']} · {chf(p['amount'])}", "proposed", "; ".join(p["reasons"])]
                          for p in proposed] + [["Document", d["filename"], d["processing_status"], d["doc_type"]] for d in review],
             [("link", str(p["id"])) for p in proposed] + [("doc", d["id"]) for d in review])

    # ---------------------------------------------------- manual entry
    def add_record_dialog(self) -> None:
        dlg = ManualDialog(self, [c["path"] for c in self.lens.categories() if c["kind"] in ("expense", "income")],
                           self.today)
        if dlg.exec():
            self.add_record(**dlg.values())

    def add_record(self, kind: str, amount: str, currency: str, op_date: date, counterparty: str,
                   category: Optional[tuple] = None, description: str = "", attachment: Optional[str] = None) -> str:
        op = self.lens.add_manual(kind, amount, currency, op_date, counterparty, category, description)
        if attachment:  # keep the supporting file as evidence of this manual record
            res = self.lens.ingest(Path(attachment).read_bytes(), Path(attachment).name)
            with self.lens.db.transaction():
                self.lens.db.execute("INSERT INTO document_operations VALUES (%s,%s,'attachment') ON CONFLICT DO NOTHING",
                                     (res.document_id, op))
                self.lens._audit("attach", "operation", op, {"document": res.document_id})
        self.refresh()
        return op

    # ---------------------------------------------------- phone and mail
    def pair_phone_dialog(self) -> None:
        from ..api.mobile import pair_device

        self._ensure_lan_server()
        info = pair_device(self.lens, "Phone")
        PairDialog(self, info["url"]).exec()

    def _ensure_lan_server(self) -> None:
        if getattr(self, "_server", None):
            return
        import threading

        import uvicorn

        os.environ.setdefault("FL_DSN", self.lens.dsn)
        os.environ.setdefault("FL_DATA", str(self.lens.files.root.parent))
        os.environ.setdefault("FL_ORG", next(o["name"] for o in self.lens.organizations() if o["id"] == self.lens.org))
        config = uvicorn.Config("financial_lens.api.app:app", host="0.0.0.0", port=int(os.environ.get("FL_PORT", "8765")),
                                log_level="warning")
        self._server = uvicorn.Server(config)
        threading.Thread(target=self._server.run, daemon=True).start()

    def fetch_mail(self) -> None:
        from .. import mail

        host, user = os.environ.get("FL_MAIL_HOST"), os.environ.get("FL_MAIL_USER")
        if not host or not user or not os.environ.get("FL_MAIL_PASSWORD"):
            QMessageBox.information(self, "Mail", "Set FL_MAIL_HOST, FL_MAIL_USER and FL_MAIL_PASSWORD (and optionally "
                                    "FL_MAIL_PORT, FL_MAIL_FOLDER), then try again.")
            return
        try:
            res = mail.fetch(self.lens, host, user, os.environ["FL_MAIL_PASSWORD"], os.environ.get("FL_MAIL_FOLDER", "INBOX"),
                             int(os.environ.get("FL_MAIL_PORT", "993")))
        except Exception as exc:
            QMessageBox.warning(self, "Mail", str(exc))
            return
        self.refresh()
        QMessageBox.information(self, "Mail", f"{res.messages} new messages, {len(res.documents)} documents, "
                                f"{res.skipped} already imported." + ("\n" + "\n".join(res.notes[:10]) if res.notes else ""))

    def _switch_org(self, name: str) -> None:
        if name:
            self.lens.open_organization(name)
            self.path = ()
            self.refresh()

    def export_dialog(self) -> None:
        from .. import reports

        path, _ = QFileDialog.getSaveFileName(self, "Export", f"financial-lens-{self.today}.zip",
                                              "Full archive (*.zip);;Report CSV (*.csv);;Report Excel (*.xlsx);;Report PDF (*.pdf)")
        if path:
            self.export_to(Path(path))

    def export_to(self, path: Path) -> Path:
        from .. import reports

        start, end = self.span()
        if path.suffix == ".zip":
            reports.export_archive(self.lens, path)
            return path
        rows = reports.report(self.lens, start, end, "category", "month", self.mode)
        data = {".csv": reports.to_csv, ".xlsx": reports.to_xlsx, ".json": reports.to_json}.get(path.suffix)
        path.write_bytes(data(rows) if data else reports.to_pdf(f"{self.mode.title()} {start} – {end}", rows,
                                                                ["period", "category", "total", "count"]))
        return path

    def _decide(self, accept: bool) -> None:
        items = self.inbox.selectedItems()
        if not items:
            return
        kind, ident = items[0].data(Qt.UserRole)
        if kind == "link":
            self.lens.decide_link(ident, accept)
            self.refresh()

    # ------------------------------------------------------------ import
    def _switch(self, row: int) -> None:
        self.stack.setCurrentIndex(row)

    def import_paths(self, paths: list[str]) -> list:
        results = [self.lens.ingest(Path(p).read_bytes(), Path(p).name) for p in paths]
        self.refresh()
        return results

    def import_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Import documents and statements")
        if paths:
            results = self.import_paths(paths)
            notes = [m for r in results for m in r.messages]
            if notes:
                QMessageBox.information(self, "Import", "\n".join(notes))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.import_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])


class ManualDialog(QDialog):
    """Enter a record by hand (cash, a lost receipt). It stays Unconfirmed until evidence arrives."""

    def __init__(self, parent, categories: list[tuple], today: date) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add record")
        self.setStyleSheet(QSS)
        form = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.addItems(["expense", "receipt", "invoice", "income"])
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("e.g. 42.50")
        self.currency = QComboBox()
        self.currency.addItems(["CHF", "EUR", "USD", "GBP"])
        self.when = QDateEdit(QDate(today.year, today.month, today.day))
        self.when.setCalendarPopup(True)
        self.counterparty = QLineEdit()
        self.category = QComboBox()
        self.category.addItem("Choose automatically", None)
        for path in categories:
            self.category.addItem(" / ".join(path), path)
        self.description = QLineEdit()
        self.attachment: Optional[str] = None
        attach = QPushButton("Attach receipt or file…")
        attach.clicked.connect(self._attach)
        self.attach_label = QLabel("No file")
        self.attach_label.setObjectName("muted")
        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {TOKENS['danger']}")
        for label, w in (("Kind", self.kind), ("Amount", self.amount), ("Currency", self.currency), ("Date", self.when),
                         ("Counterparty", self.counterparty), ("Category", self.category), ("Note", self.description),
                         ("Evidence", attach), ("", self.attach_label), ("", self.error)):
            form.addRow(label, w)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _attach(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Attach evidence")
        if path:
            self.attachment = path
            self.attach_label.setText(Path(path).name)

    def _accept(self) -> None:
        try:
            value = Decimal(self.amount.text().replace("'", "").replace(",", ".").strip())
            if value <= 0:
                raise ValueError
            value.quantize(Decimal("0.01"))
            if value != value.quantize(Decimal("0.01")):
                raise ValueError
        except Exception:
            self.error.setText("Enter a positive amount with at most two decimals.")
            return
        if not self.counterparty.text().strip():
            self.error.setText("Enter who you paid or who paid you.")
            return
        self.accept()

    def values(self) -> dict:
        d = self.when.date()
        return {"kind": self.kind.currentText(), "amount": self.amount.text().replace("'", "").replace(",", ".").strip(),
                "currency": self.currency.currentText(), "op_date": date(d.year(), d.month(), d.day()),
                "counterparty": self.counterparty.text().strip(), "category": self.category.currentData(),
                "description": self.description.text().strip(), "attachment": self.attachment}


class PairDialog(QDialog):
    def __init__(self, parent, url: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pair phone")
        self.setStyleSheet(QSS)
        lay = QVBoxLayout(self)
        import io

        import qrcode
        from PySide6.QtGui import QPixmap

        buf = io.BytesIO()
        qrcode.make(url, border=2, box_size=8).save(buf, "PNG")
        pix = QPixmap()
        pix.loadFromData(buf.getvalue())
        img = QLabel()
        img.setPixmap(pix)
        img.setAlignment(Qt.AlignCenter)
        lay.addWidget(QLabel("Scan with the phone camera (same Wi-Fi). The link works once per phone; revoke it any time."))
        lay.addWidget(img)
        link = QLabel(url.split("#")[0])
        link.setObjectName("muted")
        lay.addWidget(link)
        self.url = url


def _e(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def evidence_html(d: dict) -> str:
    t = TOKENS
    status_colour = {"confirmed": t["success"], "needs_review": t["warning"], "unconfirmed": t["muted"]}[d["verification"]]
    rows = [("Amount", chf(abs(Decimal(d["amount"]))) if d["currency"] == "CHF" else f"{d['currency']} {d['amount']}"),
            ("Date", d["op_date"]), ("Due", d.get("due_date") or "—"), ("Counterparty", d["counterparty"] or "—"),
            ("Category", " / ".join(d["category_path"])), ("Kind", d["kind"]), ("Method", d["method"]),
            ("Confidence", f"{float(d['confidence']):.0%}" if d.get("confidence") else "—")]
    html = [f"<h3 style='margin:0'>{_e(d['counterparty'] or d['kind'])}</h3>",
            f"<p style='color:{status_colour}'>● {STATUS_LABEL[d['verification']]} — {_e(d['verification_reason'])}</p>",
            "<table cellspacing=4>"] + [f"<tr><td style='color:{t['muted']}'>{k}</td><td>{_e(v)}</td></tr>" for k, v in rows]
    html.append("</table>")
    prov = d.get("provenance") or {}
    if prov:
        html.append(f"<h4>Where each value came from</h4><table cellspacing=3>")
        for name, p in prov.items():
            where = f"line {p['line']}" if p.get("line") else p.get("location", p.get("method", ""))
            quote = p.get("quote") or p.get("reason") or ""
            conf = f" · {float(p['confidence']):.0%}" if p.get("confidence") not in (None, "") else ""
            html.append(f"<tr><td style='color:{t['muted']}'>{_e(name)}</td><td>{_e(where)}{conf}<br>"
                        f"<code>{_e(quote)[:140]}</code></td></tr>")
        html.append("</table>")
    if d["documents"]:
        html.append("<h4>Documents</h4>")
        for doc in d["documents"]:
            html.append(f"<p><a href='doc:{doc['id']}'>{_e(doc['filename'])}</a> · {_e(doc['role'])} · "
                        f"sha256 {doc['sha256'][:12]}…</p>")
    if d["links"]:
        html.append("<h4>Linked operations</h4>")
        for l in d["links"]:
            html.append(f"<p><a href='op:{l['from_operation_id'] if str(l['to_operation_id']) == d['operation_id'] else l['to_operation_id']}'>"
                        f"{_e(l['other_kind'])} {_e(l['other_date'])} · {chf(abs(Decimal(l['other_amount'])))} · "
                        f"{_e(l['other_counterparty'])}</a> — {_e(l['status'])} ({_e(l['rule'])})<br>"
                        f"<span style='color:{t['muted']}'>{_e('; '.join(l['reasons']))}</span></p>")
    html.append("<h4>History</h4>")
    for h in d["history"]:
        html.append(f"<p>r{h['revision']} · {str(h['created_at'])[:19]} · {_e(h['agent'])} · "
                    f"{_e(h['change_reason'])} → {STATUS_LABEL[h['verification']]}</p>")
    return "".join(html)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Financial Lens")
    from .. import local_db, privacy

    dsn = local_db.dsn()  # own PostgreSQL via FL_DSN, otherwise the embedded one
    lens = FinancialLens(dsn, local_db.data_dir())
    lens.migrate()
    lens.open_organization(os.environ.get("FL_ORG", "Personal"))
    if lens.privacy_level() == "local_only":
        host = lens.db.info.host
        privacy.enforce_local_only([host] if host and not host.startswith("/") else [])
    window = MainWindow(lens)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
