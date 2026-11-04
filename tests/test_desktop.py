"""Desktop UI walks the §16 cycle: treemap → category → record → evidence → original."""

import os
from datetime import date
from pathlib import Path

import pytest

from conftest import render_invoice_photo
from test_mvp_cycle import CAMT, INVOICE

pytest.importorskip("PySide6")


def test_desktop_drilldown(lens, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    from financial_lens.desktop.main import MainWindow

    app = QApplication.instance() or QApplication([])
    photo = tmp_path / "IMG_4471.jpg"
    photo.write_bytes(render_invoice_photo(INVOICE))
    stmt = tmp_path / "camt053.xml"
    stmt.write_bytes(CAMT)
    w = MainWindow(lens, today=date(2026, 10, 31))
    w.resize(1440, 900)
    w.show()
    w.import_paths([str(photo), str(stmt)])
    app.processEvents()
    assert w.kpi["expenses"].text() == "CHF 252.30"
    assert w.kpi["income"].text() == "CHF 6’200.00"

    names = {e["name"] for e in w.treemap._entries()}
    assert names == {"Housing", "Food"}
    w.open_category(("Housing",))
    w.open_category(("Housing", "Electricity"))
    app.processEvents()
    w.treemap.repaint()
    rect, entry = w.treemap.items[0]
    assert entry["type"] == "operation"
    w.treemap.operation_selected.emit(entry["op"]["id"])
    html = w.evidence.toHtml()
    assert "IMG_4471.jpg" in html and "Confirmed" in html and "camt053" not in html.split("Linked")[0]
    copy = w.open_original(w.current_doc)
    assert copy.read_bytes() == photo.read_bytes()
    out = Path(os.environ.get("FL_SCREENSHOTS", tmp_path))
    out.mkdir(parents=True, exist_ok=True)
    w.open_category(("Housing",))
    app.processEvents()
    w.grab().save(str(out / "desktop-drilldown.png"))
    w.open_category(())
    app.processEvents()
    w.grab().save(str(out / "desktop-overview.png"))
