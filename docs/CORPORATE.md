# Corporate edition

One Financial Lens server for a whole company. It runs on a computer or server in the office (or a Swiss
server), keeps one shared PostgreSQL ledger, and people open it in their browsers with their own login.
Documents and data never leave the company's machine.

| | Personal edition | Corporate edition |
| --- | --- | --- |
| Start | `financial-lens service` (tray icon, browser) | `financial-lens server` |
| Reachable from | this computer only (127.0.0.1) | the office network (or behind your HTTPS proxy) |
| People | one | many, each with a login and a role |
| Audit log | yes | yes, with who did what, sign-ins and refusals |
| Price | free | 3 months free, then CHF 1 per user per month, or CHF 10 per user for 2 years |

## Start the server

```bash
pip install 'financial-lens[api,db,security,ocr,embedded]'
financial-lens server --org "Muster AG"            # http://<server>:8765/ui
```

On the first start the console (and `<data>/logs/service.log`) prints a **setup code**. Open the address in a
browser, enter the code and create the first administrator (the owner). The code works once.
The organisation name is fixed at the first start; later starts open the same books without `--org`.

The data folder is the same as the personal edition's (`~/.local/share/FinancialLens`,
`%LOCALAPPDATA%\FinancialLens`, `~/Library/Application Support/FinancialLens`, or `FL_DATA`), with an embedded
PostgreSQL unless `FL_DSN` points to your own database server.

### HTTPS

Passwords cross the network, so use HTTPS for anything beyond a trusted office LAN:

* `financial-lens server --cert server.pem --key server.key` serves HTTPS itself, or
* put the server behind your reverse proxy (nginx, Caddy, Traefik) and set `FL_COOKIE_SECURE=1`.

`FL_ALLOWED_HOSTS=finance.muster.ch` makes the server answer only under its own name.

### Single sign-on

If your company already has a sign-on proxy (Authentik, Keycloak with oauth2-proxy, Azure App Proxy, …) that
puts the signed-in person into a header:

```bash
FL_SSO_HEADER=X-Forwarded-User FL_SSO_TRUSTED_PROXIES=10.0.0.5 financial-lens server
```

The header is believed only from the listed proxy addresses. The person must already exist in *Team*; they are
matched by login or e-mail. Nobody is created automatically.

## People and roles

Administrators manage people under **Team** (or `financial-lens user add LOGIN --name "…" --role editor`).

| Role | Can |
| --- | --- |
| Owner | everything, including other owners |
| Administrator | everything except changing owners: team, licence, audit log, settings |
| Bookkeeper (`editor`) | add documents and records, correct them, decide matches, export |
| Viewer | read and export |
| Member | only their own member statement (cooperatives) |

* Passwords: at least 10 characters, stored as scrypt hashes. Five wrong attempts lock that login (and that
  address) for 10 minutes.
* Sessions end after 12 hours without use and after 7 days at the latest (`FL_SESSION_IDLE_HOURS`,
  `FL_SESSION_MAX_DAYS`). Disabling a person or resetting a password ends their sessions at once.
* There is always at least one active administrator; the last one cannot be demoted or disabled.

## Audit log

**Audit log** shows every sign-in (and failed attempt), every change to people and roles, every record, correction,
decision, export and licence change, with the person who did it. Each entry carries a hash over the previous one,
and the database refuses to change or delete entries, so the page can confirm that nothing was altered
afterwards. *Download CSV* gives the whole log for the auditor.

## Licence

* The **trial** runs for 90 days from the first start of the server, with any number of people.
* After that, an administrator opens **Licence**, copies the **request code** and sends it with the plan and
  number of users to Helvetic Lens. The key that comes back is pasted into the same page (or
  `financial-lens license install KEY`).
* **Prices:** CHF 1 per user per month, or CHF 10 per user for two years.
* The key is checked on the server without any internet connection: it is signed by Helvetic Lens and valid for
  this installation only.
* Without a valid key (trial over, licence ended, or more active users than licensed) **nothing is lost**:
  everyone can still sign in, read, ask and export everything. Only new records and changes wait for the key.
  Administrators can still manage people (e.g. disable users to get within the licence) and install a key.

## Issuing keys (Helvetic Lens)

Requests arrive at info@helveticlens.ch (the Licence page has an *E-mail the request* button).

Once, on the issuer's own computer:

```bash
financial-lens license keygen issuer.key.enc
```

This writes the private key to `~/.config/financial-lens-issuer/issuer.key`, asks for a passphrase and writes an
encrypted backup (`issuer.key.enc`, AES-256-GCM with a scrypt-derived key) that is safe to keep in a private
repository. It also prints the private and public key: put the private key and the passphrase in a password
manager. The public key goes into `ISSUER_PUBLIC_KEYS` in `src/financial_lens/licensing.py`.

On a new computer: `financial-lens license restore-key issuer.key.enc`.
If the private key is ever lost or leaked, make a new one and add its public key next to the old one
(or replace it, if leaked); keys already sold stay valid as long as their public key stays in the list.

For each customer:

```bash
financial-lens license issue FLR1.… --plan monthly --seats 25 --months 12   # CHF 300
financial-lens license issue FLR1.… --plan 2y --seats 25                    # CHF 250, valid 24 months
```

It prints the customer, number of users, period and price, then the key (`FLK1.…`) to send back.
Payment is arranged outside the software.
