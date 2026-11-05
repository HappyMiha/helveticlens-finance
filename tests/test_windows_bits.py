"""Windows-only helpers, checked on any platform."""

from financial_lens import local_db, winfirewall


def test_firewall_command_opens_only_the_phone_port_to_the_local_network():
    cmd = winfirewall.commands(8766, r"C:\Users\A B\AppData\Local\Programs\Financial Lens\FinancialLens.exe")
    assert 'delete rule name=all dir=in program="C:\\Users\\A B' in cmd  # removes the block rule Windows made
    assert "action=allow protocol=TCP localport=8766 remoteip=localsubnet" in cmd
    assert cmd.count(" & ") == 2


def test_helpers_do_nothing_elsewhere():
    import subprocess

    before = subprocess.Popen.__init__
    local_db.no_console_windows()
    assert subprocess.Popen.__init__ is before or subprocess.os.name == "nt"
    assert winfirewall.rule_present() is True and winfirewall.allow(8766) is True
