"""financial-lens command line.

  financial-lens init                      create the schema and the default profile
  financial-lens import FILE...            import documents and statements
  financial-lens watch FOLDER              import new files dropped into a folder (§4.1)
  financial-lens ask "QUESTION"            answer from the ledger
  financial-lens serve [--host 127.0.0.1]  local API
  financial-lens desktop                   desktop app
  financial-lens backup DIR                encrypted backup (passphrase from FL_BACKUP_PASSPHRASE or prompt)
  financial-lens restore FILE              restore into this database
  financial-lens check                     security self-check
  financial-lens privacy L0|L1|L2          set the privacy level

Corporate edition (one server for a company, see docs/CORPORATE.md):
  financial-lens server [--host 0.0.0.0] [--org "Muster AG"]   serve the office network, people sign in
  financial-lens user add LOGIN --name "…" --role admin        create a login (password is asked)
  financial-lens user list | passwd LOGIN | disable LOGIN
  financial-lens license status | request | install KEY
  financial-lens license keygen | issue REQUEST --plan monthly|2y --seats N [--months M]   (Helvetic Lens only)

Configuration: FL_DSN, FL_DATA, FL_ORG, FL_CONFIG (JSON with "level", "providers", "routes").
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path


def _lens():
    from .service import FinancialLens

    lens = FinancialLens(os.environ.get("FL_DSN", "dbname=financial_lens"),
                         os.path.expanduser(os.environ.get("FL_DATA", "~/FinancialLens")))
    lens.migrate()
    lens.open_organization(os.environ.get("FL_ORG", "Personal"), os.environ.get("FL_ORG_KIND", "personal"))
    level = lens.privacy_level()
    if level == "local_only":
        from . import privacy

        host = lens.db.info.host
        privacy.enforce_local_only([host] if host and not host.startswith("/") else [])
    cfg = os.environ.get("FL_CONFIG", os.path.expanduser("~/.config/financial-lens/config.json"))
    if os.path.exists(cfg):
        from .ai.providers import orchestrator_from_config

        lens.attach_ai(orchestrator_from_config(json.loads(Path(cfg).read_text())))
    return lens


def _passphrase(confirm: bool) -> str:
    value = os.environ.get("FL_BACKUP_PASSPHRASE")
    if value:
        return value
    value = getpass.getpass("Backup passphrase: ")
    if confirm and getpass.getpass("Repeat: ") != value:
        sys.exit("Passphrases differ.")
    return value


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="financial-lens", description="Evidence-first, offline-first finance.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    imp = sub.add_parser("import")
    imp.add_argument("files", nargs="+")
    imp.add_argument("--privacy", default="local_only", choices=["local_only", "swiss_hosted", "cloud_ai"])
    w = sub.add_parser("watch")
    w.add_argument("folder")
    w.add_argument("--interval", type=float, default=5.0)
    a = sub.add_parser("ask")
    a.add_argument("question")
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    sub.add_parser("desktop")
    sv = sub.add_parser("service", help="run the local service and open the web interface")
    sv.add_argument("--no-browser", action="store_true")
    sv.add_argument("--no-tray", action="store_true")
    b = sub.add_parser("backup")
    b.add_argument("dir")
    r = sub.add_parser("restore")
    r.add_argument("file")
    sub.add_parser("check")
    ml = sub.add_parser("mail", help="import documents from a mailbox (password in FL_MAIL_PASSWORD)")
    ml.add_argument("--host", default=os.environ.get("FL_MAIL_HOST", "127.0.0.1"))
    ml.add_argument("--port", type=int, default=int(os.environ.get("FL_MAIL_PORT", "993")))
    ml.add_argument("--user", default=os.environ.get("FL_MAIL_USER", ""))
    ml.add_argument("--folder", default=os.environ.get("FL_MAIL_FOLDER", "INBOX"))
    ml.add_argument("--from", dest="senders", action="append", help="only accept these senders (repeatable)")
    ev = sub.add_parser("eval", help="compare document understanding with and without a model")
    ev.add_argument("--model", help="OpenAI-compatible URL of a local model, e.g. http://127.0.0.1:18765/v1")
    ev.add_argument("--model-name", default="apertus-8b")
    ev.add_argument("--n", type=int, default=6, help="documents per type and language")
    ev.add_argument("--photos", action="store_true", help="also test photo versions (OCR)")
    ev.add_argument("--hard", action="store_true", help="also test wording the rules were not written for")
    ev.add_argument("--verbose", action="store_true")
    ai = sub.add_parser("ai", help="local AI model (Apertus): status, install, start, remove")
    ai.add_argument("action", choices=["status", "install", "start", "remove"])
    pr = sub.add_parser("pair", help="pair a phone for uploads; prints the link and a QR code")
    pr.add_argument("--name", default="Phone")
    pv = sub.add_parser("privacy")
    pv.add_argument("level", choices=["L0", "L1", "L2"])
    srv = sub.add_parser("server", help="corporate edition: one server for a company, people sign in")
    srv.add_argument("--host", default=os.environ.get("FL_HOST", "0.0.0.0"))
    srv.add_argument("--port", type=int, default=int(os.environ.get("FL_PORT", "8765")))
    srv.add_argument("--org", default=os.environ.get("FL_ORG", ""), help="organisation name (kept after the first start)")
    srv.add_argument("--cert", default=os.environ.get("FL_TLS_CERT", ""), help="TLS certificate (PEM) for HTTPS")
    srv.add_argument("--key", default=os.environ.get("FL_TLS_KEY", ""), help="TLS private key (PEM)")
    us = sub.add_parser("user", help="corporate edition: logins")
    us.add_argument("action", choices=["add", "list", "passwd", "disable", "enable"])
    us.add_argument("login", nargs="?")
    us.add_argument("--name", default="")
    us.add_argument("--email", default="")
    us.add_argument("--role", default="viewer", choices=["owner", "admin", "editor", "viewer", "member"])
    li = sub.add_parser("license", help="corporate edition: licence")
    li.add_argument("action", choices=["status", "request", "install", "keygen", "issue", "backup-key", "restore-key"])
    li.add_argument("value", nargs="?", help="the key (install) or the request code (issue)")
    li.add_argument("--plan", choices=["monthly", "2y"], default="monthly")
    li.add_argument("--seats", type=int, default=0)
    li.add_argument("--months", type=int, default=12)
    li.add_argument("--customer", default=None)
    args = p.parse_args(argv)

    if args.cmd == "server":
        from .launcher import serve_corporate

        return serve_corporate(args.host, args.port, args.org, args.cert, args.key)
    if args.cmd == "license" and args.action in ("keygen", "issue", "backup-key", "restore-key"):
        return _issuer(args)

    if args.cmd == "serve":
        import uvicorn

        if args.host not in ("127.0.0.1", "::1", "localhost"):
            print("Listening on the network: other devices can reach only the paired-phone upload page (/m); "
                  "everything else answers this machine only.", file=sys.stderr)
        uvicorn.run("financial_lens.api.app:app", host=args.host, port=args.port)
        return 0
    if args.cmd == "ai":
        from .ai import local_model as L

        if args.action == "install":
            last = [""]

            def show(label, frac):
                line = f"{label} {frac:.0%}"
                if line != last[0]:
                    print("\r" + line, end="", flush=True)
                    last[0] = line
            L.install(show)
            print()
        elif args.action == "start":
            print(L.start())
            input("Running on this computer only. Press Enter to stop.")
            L.stop()
        elif args.action == "remove":
            L.remove()
        print(L.status())
        return 0
    if args.cmd == "eval":
        from . import evaluation as E
        from .ai.providers import OpenAICompatible, Orchestrator

        sets = [("standard", E.corpus(args.n, args.photos))] + ([("unseen wording", E.corpus(args.n, hard=True))] if args.hard else [])
        model = None
        if args.model:
            p = OpenAICompatible("eval-model", args.model, args.model_name, "local", timeout=600)
            model = Orchestrator(routes={"understand": [p]})
        print(E.HEADER)
        for label, docs in sets:
            say = print if args.verbose else None
            print(E.report(f"{label} · rules only", E.run(docs, None, say)))
            if model:
                print(E.report(f"{label} · rules + {args.model_name}", E.run(docs, model, say)))
        return 0
    if args.cmd == "service":
        from .launcher import main as service_main

        return service_main((["--no-browser"] if args.no_browser else []) + (["--no-tray"] if args.no_tray else []))
    if args.cmd == "desktop":
        from .desktop.main import main as desktop

        return desktop()
    if args.cmd in ("user", "license"):
        from .launcher import corporate_env

        corporate_env()
    lens = _lens()
    if args.cmd == "init":
        print(f"Ready: organisation {lens.org}, privacy {lens.privacy_level()}")
    elif args.cmd == "import":
        for f in args.files:
            res = lens.ingest(Path(f).read_bytes(), Path(f).name, privacy=args.privacy)
            print(f"{f}: {res.doc_type}, {len(res.operation_ids)} records, {len(res.links)} links. " + " ".join(res.messages))
    elif args.cmd == "watch":
        folder = Path(args.folder).expanduser()
        done = folder / "imported"
        done.mkdir(parents=True, exist_ok=True)
        print(f"Watching {folder}; imported files move to {done}")
        while True:
            for f in sorted(folder.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    res = lens.ingest(f.read_bytes(), f.name)
                    f.rename(done / f.name)
                    print(f"{f.name}: {res.doc_type}, {len(res.operation_ids)} records. " + " ".join(res.messages))
            time.sleep(args.interval)
    elif args.cmd == "ask":
        from .assistant import ask

        res = ask(lens, args.question)
        print(res["answer"])
        for item in res["items"][:30]:
            print("  -", item.get("label", item))
    elif args.cmd == "backup":
        from .backup import create

        print(create(lens, Path(args.dir).expanduser(), _passphrase(True)))
    elif args.cmd == "restore":
        from .backup import restore

        print("Restored organisation", restore(lens, Path(args.file), _passphrase(False)))
    elif args.cmd == "check":
        from .security import self_check

        rep = self_check(lens)
        for c in rep["checks"]:
            print(("OK   " if c["ok"] else "WARN ") + f"{c['check']}: {c['detail']}")
        return 0 if rep["ok"] else 1
    elif args.cmd == "mail":
        from .mail import fetch

        res = fetch(lens, args.host, args.user, os.environ.get("FL_MAIL_PASSWORD") or getpass.getpass("Mail password: "),
                    args.folder, args.port, args.senders)
        print(f"{res.messages} new messages, {len(res.documents)} documents, {res.skipped} already imported")
        for n in res.notes:
            print("  -", n)
    elif args.cmd == "pair":
        from .api.mobile import pair_device

        info = pair_device(lens, args.name)
        print("Open on the phone (same Wi-Fi), with `financial-lens serve --host 0.0.0.0` running:")
        print(info["url"])
        try:
            import qrcode

            q = qrcode.QRCode(border=1)
            q.add_data(info["url"])
            q.print_ascii(invert=True)
        except ImportError:
            pass
    elif args.cmd == "privacy":
        lens.set_privacy_level(args.level)
        print("Privacy level", args.level)
    elif args.cmd == "user":
        return _users(lens, args)
    elif args.cmd == "license":
        from . import licensing as L

        if args.action == "install":
            p = L.install_key(lens, args.value or input("Licence key: "))
            print(f"Installed: {p['customer']}, {p['seats']} users, {p['plan']}, until {p['expires']}")
        elif args.action == "request":
            print("Send this request code to Helvetic Lens to receive a licence key:")
            print(L.request_code(lens))
        st = L.status(lens)
        print(f"Licence: {st.state} · {st.users} active users" + (f" of {st.seats}" if st.seats else "")
              + (f" · {st.days_left} days left" if st.state in ("trial", "active") else ""))
        if st.message:
            print(st.message)
        print(f"Price for {max(st.users, 1)} users: CHF {st.prices['monthly']} per month, or CHF {st.prices['2y']} for 2 years")
    return 0


def _users(lens, args) -> int:
    from . import corporate as C

    def pw(login: str) -> str:
        a = os.environ.get("FL_NEW_PASSWORD") or getpass.getpass(f"Password for {login}: ")
        if not os.environ.get("FL_NEW_PASSWORD") and getpass.getpass("Repeat: ") != a:
            sys.exit("Passwords differ.")
        return a

    def find(login: str) -> dict:
        for u in C.users(lens):
            if u["login"].casefold() == (login or "").casefold():
                return u
        sys.exit(f"No user {login!r}.")

    if args.action == "list":
        for u in C.users(lens):
            print(f"{u['login']:<24} {u['role']:<8} {u['name']}" + ("  (disabled)" if u["disabled_at"] else ""))
    elif args.action == "add":
        if not args.login:
            sys.exit("financial-lens user add LOGIN --name NAME --role ROLE")
        C.create_user(lens, args.login, args.name or args.login, args.role, pw(args.login), args.email)
        print(f"Created {args.login} ({args.role}).")
    elif args.action == "passwd":
        C.set_password(lens, find(args.login)["id"], pw(args.login))
        print("Password changed; the person's open sessions were ended.")
    else:
        C.update_user(lens, find(args.login)["id"], disabled=args.action == "disable")
        print(f"{args.login}: {args.action}d.")
    return 0


def _issuer(args) -> int:
    """Helvetic Lens side: make the issuer key once, then sign keys for customers' request codes."""
    from . import licensing as L

    path = L.issuer_key_path()
    def passphrase(confirm: bool) -> str:
        value = os.environ.get("FL_ISSUER_PASSPHRASE") or getpass.getpass("Passphrase for the key backup: ")
        if confirm and not os.environ.get("FL_ISSUER_PASSPHRASE") and getpass.getpass("Repeat: ") != value:
            sys.exit("Passphrases differ.")
        return value

    def write_key(priv: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        path.write_text(priv)
        path.chmod(0o600)

    if args.action == "restore-key":
        from .backup import decrypt

        if path.exists():
            sys.exit(f"An issuer key already exists at {path}; it is not replaced.")
        write_key(decrypt(Path(args.value or "issuer.key.enc").read_bytes(), passphrase(False)).decode())
        print(f"Restored to {path}. Public key: {L.public_of(path.read_text().strip())}")
        return 0
    if args.action in ("keygen", "backup-key"):
        from .backup import encrypt

        if args.action == "keygen":
            if path.exists():
                sys.exit(f"An issuer key already exists at {path}; it is not replaced.")
            write_key(L.keygen()[0])
            print(f"Private key written to {path}.")
        elif not path.exists():
            sys.exit(f"No issuer key at {path}.")
        priv = path.read_text().strip()
        target = Path(args.value or "issuer.key.enc")
        target.write_bytes(encrypt(priv.encode(), passphrase(True)))
        print(f"Encrypted backup: {target} (AES-256-GCM, scrypt; safe to keep in a private repository).")
        print("Also keep the passphrase, and ideally the key itself, in your password manager:")
        print(f"  private key: {priv}")
        print(f"Public key (goes into ISSUER_PUBLIC_KEYS): {L.public_of(priv)}")
        return 0
    if not path.exists():
        sys.exit(f"No issuer key at {path}. Run `financial-lens license keygen` first.")
    code = args.value or input("Request code: ")
    req = L.read_request(code)
    seats = args.seats or max(int(req.get("users", 1)), 1)
    key = L.issue(path.read_text().strip(), code, args.plan, seats, args.months, args.customer)
    months = 24 if args.plan == "2y" else args.months
    print(f"Customer: {args.customer or req.get('org')} · {seats} users · {args.plan} · {months} months · "
          f"price CHF {L.price(args.plan, seats, months)}")
    print(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
