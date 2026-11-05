"""Financial Lens as a local service with a web page.

One process per user, no administrator rights:
  * starts the embedded PostgreSQL (or uses FL_DSN), migrates, opens the ledger;
  * serves the API and the web interface on 127.0.0.1 only, protected by a per-user key;
  * shows a tray icon (Open · Start with my computer · Quit) where the desktop has one;
  * opens the browser with a one-time key in the URL fragment; the page swaps it for a cookie.
Starting it again while it runs only opens the browser.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import local_db

PORT = int(os.environ.get("FL_PORT", "8765"))
APP_ID = "FinancialLens"


def url(key: str) -> str:
    return f"http://127.0.0.1:{PORT}/ui#k={key}"


def running() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
            return r.headers.get("X-Financial-Lens") == "1"
    except Exception:
        return False


def _logs() -> None:
    """Windowed builds have no console; uvicorn and our own errors go to a file."""
    logs = local_db.data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None or os.environ.get("FL_LOG_TO_FILE"):
        stream = open(logs / "service.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream


# ------------------------------------------------------------------ autostart (per user, no admin)
def _exe_command() -> list[str]:
    if os.environ.get("APPIMAGE"):  # sys.executable is inside a temporary mount; the AppImage file stays
        return [os.environ["APPIMAGE"], "--service"]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--service"]
    return [sys.executable, "-m", "financial_lens.launcher", "--service"]


def _autostart_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / "ch.helveticlens.financial-lens.plist"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart" / "financial-lens.desktop"


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_enabled() -> bool:
    if os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, APP_ID)
                return True
        except OSError:
            return False
    return _autostart_path().exists()


def set_autostart(on: bool) -> None:
    if os.name == "nt":  # the user's own Run key: no administrator rights, no console window
        import subprocess
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if on:
                winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, subprocess.list2cmdline(_exe_command()))
            else:
                try:
                    winreg.DeleteValue(k, APP_ID)
                except OSError:
                    pass
        return
    p = _autostart_path()
    if not on:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    cmd = _exe_command()
    if sys.platform == "darwin":
        args = "".join(f"<string>{c}</string>" for c in cmd)
        p.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>Label</key><string>ch.helveticlens.financial-lens</string>
<key>ProgramArguments</key><array>{args}</array><key>RunAtLoad</key><true/></dict></plist>
""")
    else:
        exec_line = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        p.write_text(f"[Desktop Entry]\nType=Application\nName=Financial Lens\nExec={exec_line}\n"
                     "X-GNOME-Autostart-enabled=true\nNoDisplay=false\n")


# ------------------------------------------------------------------ service
class Service:
    def __init__(self) -> None:
        self.server = None
        self.key = ""

    def start(self) -> str:
        import uvicorn

        from .api import app as api
        from .api import webui

        data = local_db.data_dir()
        os.environ.setdefault("FL_DATA", str(data))
        os.environ["FL_DSN"] = local_db.dsn()  # embedded PostgreSQL unless the person set their own
        self.key = webui.load_key(data)
        webui.Settings.key = self.key
        webui.Settings.require_auth = True
        api.lens()  # migrate and open the ledger before the first request
        config = uvicorn.Config(api.app, host="127.0.0.1", port=PORT, log_level="warning", log_config=None)
        self.server = uvicorn.Server(config)
        threading.Thread(target=self.server.run, daemon=True, name="web").start()
        for _ in range(100):
            if self.server.started:
                return self.key
            time.sleep(0.1)
        raise RuntimeError(f"The service did not start on 127.0.0.1:{PORT} (is the port taken?).")

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True
        from .ai import local_model

        local_model.stop()


def _tray(service: Service, open_now: bool) -> int:
    from PySide6.QtGui import QAction, QIcon
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Financial Lens")
    if not QSystemTrayIcon.isSystemTrayAvailable():
        if open_now:
            webbrowser.open(url(service.key))
        return app.exec()
    icon_path = Path(__file__).parent / "webui" / "favicon.svg"
    tray = QSystemTrayIcon(QIcon(str(icon_path)))
    tray.setToolTip(f"Financial Lens · 127.0.0.1:{PORT}")
    menu = QMenu()
    open_act = QAction("Open Financial Lens")
    open_act.triggered.connect(lambda: webbrowser.open(url(service.key)))
    auto = QAction("Start with my computer")
    auto.setCheckable(True)
    auto.setChecked(autostart_enabled())
    auto.toggled.connect(set_autostart)
    quit_act = QAction("Quit")

    def quit_all():
        service.stop()
        app.quit()
    quit_act.triggered.connect(quit_all)
    for a in (open_act, auto):
        menu.addAction(a)
    menu.addSeparator()
    menu.addAction(quit_act)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: webbrowser.open(url(service.key))
                           if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    if open_now:
        webbrowser.open(url(service.key))
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    background = "--service" in argv  # autostart: no browser window
    headless = "--no-tray" in argv or not _has_display()
    _logs()
    from .api import webui

    if running():
        if not background:
            webbrowser.open(url(webui.load_key(local_db.data_dir())))
        return 0
    if "--no-autostart" not in argv and not os.environ.get("FL_NO_AUTOSTART") and not autostart_enabled() \
            and not (local_db.data_dir() / "autostart-asked").exists():
        set_autostart(True)  # on by default; the tray menu turns it off and we remember that
        (local_db.data_dir() / "autostart-asked").write_text("1")
    service = Service()
    key = service.start()
    print(f"Financial Lens is running on http://127.0.0.1:{PORT}/ui", flush=True)
    if headless:
        if not background and "--no-browser" not in argv:
            webbrowser.open(url(key))
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            service.stop()
            return 0
    return _tray(service, open_now=not background and "--no-browser" not in argv)


def _has_display() -> bool:
    if os.name == "nt" or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def port_free(port: int = PORT) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


if __name__ == "__main__":
    raise SystemExit(main())


# ------------------------------------------------------------------ corporate edition
def corporate_env(org: str = "") -> Path:
    """Database, data folder and organisation of the corporate server, shared by `server`, `user` and `license`.
    The organisation's name is fixed at the first start, so a later start without --org opens the same books."""
    data = local_db.data_dir()
    os.environ.setdefault("FL_DATA", str(data))
    os.environ["FL_DSN"] = local_db.dsn()
    marker = data / "corporate-org"
    if marker.exists():
        os.environ["FL_ORG"] = marker.read_text(encoding="utf-8").strip()
    else:
        name = org or os.environ.get("FL_ORG") or "Company"
        data.mkdir(parents=True, exist_ok=True)
        marker.write_text(name, encoding="utf-8")
        os.environ["FL_ORG"] = name
    os.environ.setdefault("FL_ORG_KIND", "business")
    return data


def serve_corporate(host: str = "0.0.0.0", port: int = PORT, org: str = "", certfile: str = "", keyfile: str = "") -> int:
    """One server for a whole company: people sign in from their browsers (see docs/CORPORATE.md)."""
    import uvicorn

    from . import corporate, licensing
    from .api import app as api
    from .api import corporate as web_corp
    from .api import webui

    _logs()
    data = corporate_env(org)
    webui.Settings.edition = "corporate"
    web_corp.Config.data_dir = str(data)
    if certfile:
        web_corp.Config.secure_cookie = True
    fl = api._lens()
    st = licensing.status(fl)
    print(f"Financial Lens corporate server · organisation “{os.environ.get('FL_ORG', 'Personal')}” · "
          f"licence: {st.state}" + (f", {st.days_left} days left" if st.state in ("trial", "active") else ""), flush=True)
    if st.message:
        print("  " + st.message, flush=True)
    if not corporate.has_logins(fl):
        code = corporate.setup_code(data)
        print(f"  First start: open http://<this server>:{port}/ui and create the first administrator "
              f"with the setup code {code}", flush=True)
    print(f"Listening on {'https' if certfile else 'http'}://{host}:{port}/ui", flush=True)
    kw = {"ssl_certfile": certfile, "ssl_keyfile": keyfile} if certfile else {}
    uvicorn.run(api.app, host=host, port=port, log_level="warning", proxy_headers=True,
                forwarded_allow_ips=os.environ.get("FL_SSO_TRUSTED_PROXIES", "127.0.0.1"), **kw)
    return 0
