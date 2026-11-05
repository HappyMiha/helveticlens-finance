"""Windows Firewall: let paired phones on the same Wi-Fi reach Financial Lens.

The phone talks to this computer on port 8766 (HTTPS, pinned certificate). Financial Lens installs per user,
without administrator rights, so the installer cannot open that port. The first time the app listened, Windows
showed "allow access?"; dismissing it (or a standard user who cannot allow) leaves a rule that BLOCKS the app,
and the phone then times out. One elevated command, confirmed by the person through the Windows prompt, removes
those inbound rules for this program and allows the phone port from the local network only.
"""

from __future__ import annotations

import os
import subprocess
import sys

RULE = "Financial Lens phones"


def applies() -> bool:
    return os.name == "nt"


def _program() -> str:
    return sys.executable


def rule_present() -> bool:
    if not applies():
        return True
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE}"],
                           capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def commands(port: int, program: str) -> str:
    """The elevated command line (cmd.exe /c …)."""
    return " & ".join([
        f'netsh advfirewall firewall delete rule name=all dir=in program="{program}"',
        f'netsh advfirewall firewall delete rule name="{RULE}"',
        f'netsh advfirewall firewall add rule name="{RULE}" dir=in action=allow protocol=TCP localport={port} '
        f'remoteip=localsubnet profile=any program="{program}"',
    ])


def allow(port: int) -> bool:
    """Ask Windows (UAC prompt) to run the firewall change. Returns False if it could not even be started."""
    if not applies():
        return True
    import ctypes

    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", "/c " + commands(port, _program()), None, 0)
    return rc > 32
