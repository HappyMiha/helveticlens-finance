import 'dart:convert';

import 'package:financial_lens_mobile/src/client.dart';
import 'package:financial_lens_mobile/src/device_key.dart';
import 'package:financial_lens_mobile/src/theme.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('pairing code is parsed and validated', () {
    final o = PairingOffer.parse('fl://pair?v=1&addr=192.168.1.20%3A8766&fp=${'ab' * 32}&offer=o1&otp=s3cret&scopes=upload,read');
    expect(o.address, '192.168.1.20:8766');
    expect(o.scopes, ['upload', 'read']);
    expect(() => PairingOffer.parse('https://evil.example/pair'), throwsFormatException);
    expect(() => PairingOffer.parse('fl://pair?v=1&addr=x&fp=short&offer=o&otp=s'), throwsFormatException);
  });

  test('device key survives storage and signs deterministically', () {
    final k = DeviceKey.generate();
    final again = DeviceKey.fromHex(k.privateHex);
    final msg = LensClient.canonical('GET', '/mobile/v1/summary', '2026-11-05T09:00:00+00:00', 'n1', []);
    expect(again.publicKeyB64, k.publicKeyB64);
    expect(again.sign(msg), k.sign(msg));
    expect(base64.decode(k.publicKeyB64).length, 91); // P-256 SubjectPublicKeyInfo
  });

  test('amount formatting is display only', () {
    expect(T.chf('1234.5'), 'CHF 1’234.50');
    expect(T.chf('-184.50'), '-CHF 184.50');
  });

  test('emit a signature for the server-side cross-check', () {
    final k = DeviceKey.fromHex('1f' * 32);
    final msg = LensClient.canonical('POST', '/mobile/v1/documents', '2026-11-05T09:00:00+00:00', 'n2', utf8.encode('body'));
    // ignore: avoid_print
    print('XCHECK ${jsonEncode({'pk': k.publicKeyB64, 'sig': k.sign(msg), 'msg': base64.encode(msg)})}');
  });
}
