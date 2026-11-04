"""Desktop shell (PySide6). Phase 1 placeholder window.

Run with: python -m financial_lens.desktop.main
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication, QLabel, QMainWindow
    except ImportError:
        print("Install the desktop extra: pip install -e '.[desktop]'", file=sys.stderr)
        return 1
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("Financial Lens")
    window.setCentralWidget(QLabel("Financial Lens — treemap view arrives in phase 1."))
    window.resize(1100, 720)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
