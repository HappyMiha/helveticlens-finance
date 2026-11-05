// End-to-end on a real Android runtime against a real Financial Lens server:
// pinned TLS, pairing with the one-time code, signed upload, ledger values read back.
// Run with --dart-define=FL_PAIR_URI=fl://pair?... (the server prints it).
import 'dart:convert';

import 'package:financial_lens_mobile/src/client.dart';
import 'package:financial_lens_mobile/src/session.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const uri = String.fromEnvironment('FL_PAIR_URI');

  testWidgets('pair, upload, read back', (tester) async {
    expect(uri, isNotEmpty, reason: 'pass --dart-define=FL_PAIR_URI');
    final offer = PairingOffer.parse(uri);

    // A look-alike server (wrong fingerprint) must be refused before anything is sent.
    final impostor = PairingOffer.parse(uri.replaceFirst(RegExp(r'fp=[0-9a-f]{64}'), 'fp=${'0' * 64}'));
    await expectLater(Session.pair(impostor, 'Emulator', 'android'), throwsA(anything));

    final client = await Session.pair(offer, 'Emulator', 'android');
    expect(client.deviceId, isNotNull);
    final again = await Session.load();
    expect(again!.deviceId, client.deviceId);

    final receipt = utf8.encode('Bäckerei Frey AG\nQuittung\nDatum 03.10.2026\nTotal CHF 12.80\n');
    final up = await client.upload('receipt.txt', receipt, 'text/plain');
    final r = (up['results'] as List).first as Map<String, dynamic>;
    expect(r['amount'], '12.80');

    final s = await client.get('/mobile/v1/summary?start=2026-10-01&end=2026-10-31');
    expect(s['expenses'], '12.80');
    final op = await client.get('/mobile/v1/operations/${r['operation_id']}');
    expect(op['documents'], isNotEmpty);
    final orig = await client.original((op['documents'] as List).first['id']);
    expect(utf8.decode(orig['bytes']), contains('Bäckerei Frey'));
    // ignore: avoid_print
    print('E2E OK ${jsonEncode({'device': client.deviceId, 'amount': r['amount'], 'expenses': s['expenses']})}');
    await Session.forget();
  });
}
