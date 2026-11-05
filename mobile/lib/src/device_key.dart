// Device key: ECDSA P-256. The private key is created on the phone and stored only in the
// platform keystore (iOS Keychain, Android Keystore-backed encrypted storage); it is never sent.
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:pointycastle/export.dart';

class DeviceKey {
  DeviceKey._(this._private, this._public);

  static final ECDomainParameters _curve = ECDomainParameters('secp256r1');
  final ECPrivateKey _private;
  final ECPublicKey _public;

  static DeviceKey generate() {
    final seed = Uint8List.fromList(List<int>.generate(32, (_) => Random.secure().nextInt(256)));
    final random = FortunaRandom()..seed(KeyParameter(seed));
    final gen = ECKeyGenerator()..init(ParametersWithRandom(ECKeyGeneratorParameters(_curve), random));
    final pair = gen.generateKeyPair();
    return DeviceKey._(pair.privateKey, pair.publicKey);
  }

  static DeviceKey fromHex(String hex) {
    final d = BigInt.parse(hex, radix: 16);
    return DeviceKey._(ECPrivateKey(d, _curve), ECPublicKey(_curve.G * d, _curve));
  }

  String get privateHex => _private.d!.toRadixString(16);

  /// SubjectPublicKeyInfo (DER) for an uncompressed P-256 point, base64.
  String get publicKeyB64 {
    const prefix = [
      0x30, 0x59, 0x30, 0x13, 0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01, //
      0x06, 0x08, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x03, 0x01, 0x07, 0x03, 0x42, 0x00,
    ];
    return base64.encode([...prefix, ..._public.Q!.getEncoded(false)]);
  }

  /// Deterministic (RFC 6979) ECDSA-SHA256 signature, DER encoded, base64.
  String sign(List<int> message) {
    final signer = ECDSASigner(SHA256Digest(), HMac(SHA256Digest(), 64))
      ..init(true, PrivateKeyParameter<ECPrivateKey>(_private));
    final sig = signer.generateSignature(Uint8List.fromList(message)) as ECSignature;
    return base64.encode(_der(sig.r, sig.s));
  }

  static List<int> _int(BigInt v) {
    var bytes = <int>[];
    var x = v;
    while (x > BigInt.zero) {
      bytes.insert(0, (x & BigInt.from(0xff)).toInt());
      x = x >> 8;
    }
    if (bytes.isEmpty) bytes = [0];
    if (bytes.first & 0x80 != 0) bytes.insert(0, 0);
    return [0x02, bytes.length, ...bytes];
  }

  static List<int> _der(BigInt r, BigInt s) {
    final body = [..._int(r), ..._int(s)];
    return [0x30, body.length, ...body];
  }
}
