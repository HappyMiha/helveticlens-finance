# Financial Lens Mobile — architecture and security

Status: design, 2026-11-05. Decisions open for Miha are marked **[decision]**.

## Principle
The phone is a **window and a camera**, not a second ledger. The ledger, the
money maths and the originals stay on the user's own Financial Lens (desktop
or a Swiss server). The phone shows numbers the ledger computed and sends
documents to it. Nothing about the privacy levels (L0/L1/L2) changes.

```
 Phone app ──(end-to-end encrypted, device key)──► Financial Lens "home" (desktop / Swiss server)
     │                                                   │  PostgreSQL, originals, OCR, matching
     └── same Wi-Fi: direct ─────────────────────────────┤
     └── away: optional relay finance.helveticlens.ch ───┘  relay sees only ciphertext
```

## Pairing by QR code
1. Desktop → *Pair phone*. It creates a one-time pairing offer, valid 5 minutes, shown as a QR code:
   `fl://pair?v=1&addr=192.168.1.20:8765&relay=<id>&pk=<desktop X25519 public key>&fp=<TLS cert SHA-256>&otp=<128-bit one-time secret>`
2. The phone generates its own key pair **inside the Secure Enclave (iOS) / StrongBox-Keystore (Android)**; the private key never leaves the chip.
3. The phone connects to the address, pins the TLS certificate by `fp` (no public CA, no trust-on-first-use), and proves knowledge of `otp` (HMAC). The desktop records the phone's public key, name and **scopes**, then deletes the offer. A replayed or late QR code is useless.
4. The desktop shows "Miha's iPhone is paired — Upload + Read"; the user can revoke it any time (all access ends immediately).

## Transport and authentication
- Every request is signed by the device key (or mutual TLS with the device key); the server checks signature, scope, a nonce and the timestamp. No passwords, no long-lived bearer tokens on the wire.
- **Same Wi-Fi:** direct HTTPS to the desktop, certificate pinned.
- **Away from home [decision]:** (a) LAN only; or (b) an **end-to-end encrypted relay** on finance.helveticlens.ch: phone and desktop each open an outbound connection; payloads are encrypted with keys from the pairing (Noise/X25519 + ChaCha20-Poly1305), so the relay can see only sizes and timing. The desktop must be running (uploads queue on the phone until it is). For cooperatives the "home" can be the L1 Swiss server instead.
- In L2 (local only) the relay is off by design; only the local network works.

## Scopes per device
`upload` (send documents), `read` (view own data and statistics), `review` (confirm proposed links). A cooperative member's phone gets `upload` + `read_own` (own statement only) — the server enforces the existing roles; the phone never filters data itself.

## Features
| Feature | How |
| --- | --- |
| Take a photo and send | Native camera; image compressed on device, original kept |
| Scan a document | iOS VisionKit document camera, Android ML Kit Document Scanner — both on-device, edge detection, multi-page PDF |
| Upload photos and files | System photo picker and Files / Storage Access Framework; **Share sheet** extension ("Share to Financial Lens") from any app or mail |
| Offline queue | Documents encrypted on the phone, sent when the home is reachable; idempotent by SHA-256, so retries never create duplicates |
| Browse own data | Dashboard (balance, income, expenses), treemap with drill-down, operations, document originals, evidence and history — read-only views of server results |
| Statistics widget | iOS WidgetKit and Android Glance widgets showing this month's spending and unconfirmed items; data from an encrypted snapshot the app refreshes; **amounts can be hidden on the lock screen** |
| Notifications | Optional: "receipt matched", "invoice overdue" — via the relay as encrypted content-free pings, the phone fetches details itself |

## Data on the phone
- Cached views and the widget snapshot are encrypted (iOS Data Protection *complete until first unlock*; Android EncryptedFile with a Keystore key), expire, and are wiped on revoke or after N failed unlocks.
- App lock with Face ID / fingerprint / device PIN (on by default); screenshots blocked on sensitive screens (Android `FLAG_SECURE`, iOS blur in app switcher).
- No analytics SDKs, no third-party crash reporters, no ads. Only network destinations: the paired home and (if chosen) the relay.

## Technology
- **Flutter** (one code base for Android and iOS, good camera/scanner plugins, AOT-compiled), with small native parts where the platform requires them: iOS share extension and WidgetKit widget (Swift), Android Glance widget (Kotlin), Secure Enclave / Keystore access.
- Server side: a new `/mobile/v1` API in Financial Lens (pairing, signed requests, scopes, upload, read endpoints returning ledger-computed values), plus the relay service.
- Builds in GitHub Actions: Android on Linux, iOS on macOS runners; each build runs automated UI tests on an emulator/simulator.

## Distribution [decision]
- **Android:** signed APK downloadable from finance.helveticlens.ch (works now), Google Play later (one-time USD 25 developer account).
- **iPhone:** Apple allows installs only via the App Store / TestFlight (or EU alternative marketplaces). This needs an **Apple Developer account (USD 99/year)** in Miha's name; until then the iOS build can be tested only in the simulator.

## Phases
1. Pairing protocol, signed requests and scopes on the server; Flutter app with camera, scanner, file upload, share sheet; Android APK on the site.
2. Read views: dashboard, treemap, operations, evidence; widgets; app lock.
3. End-to-end encrypted relay (if chosen) and notifications; iOS via TestFlight once the Apple account exists.
