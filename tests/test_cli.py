import os

from test_mvp_cycle import CAMT


def test_cli_import_ask_check(lens, tmp_path, capsys, monkeypatch):
    from financial_lens import cli, privacy

    f = tmp_path / "camt.xml"
    f.write_bytes(CAMT)
    monkeypatch.setattr(cli, "_lens", lambda: lens)
    assert cli.main(["import", str(f)]) == 0
    assert "bank_statement, 3 records" in capsys.readouterr().out
    cli.main(["ask", "all payments to Migros"])
    assert "67.80" in capsys.readouterr().out
    os.environ["FL_BACKUP_PASSPHRASE"] = "a long test passphrase"
    cli.main(["backup", str(tmp_path / "bk")])
    assert list((tmp_path / "bk").glob("*.flbk"))
    with privacy.local_only(["db"]):
        code = cli.main(["check"])
    out = capsys.readouterr().out
    assert "OK   outbound network blocked" in out and "OK   audit log chain" in out
    assert code == 1  # disk encryption is not declared in the test container: reported, not hidden
