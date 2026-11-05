// Talks only to the paired Financial Lens. TLS is pinned to the certificate fingerprint from the
// pairing QR code: no public certificate authority is trusted, so nothing else can impersonate it.
// Every request is signed with the device key (method, path, time, nonce, body hash).
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:uuid/uuid.dart';

import 'device_key.dart';

class PairingOffer {
  PairingOffer(this.address, this.fingerprint, this.offer, this.otp, this.scopes);
  final String address, fingerprint, offer, otp;
  final List<String> scopes;

  static PairingOffer parse(String text) {
    final uri = Uri.parse(text.trim());
    if (uri.scheme != 'fl' || uri.host != 'pair' || uri.queryParameters['v'] != '1') {
      throw const FormatException('This is not a Financial Lens pairing code.');
    }
    final q = uri.queryParameters;
    for (final k in ['addr', 'fp', 'offer', 'otp']) {
      if ((q[k] ?? '').isEmpty) throw FormatException('Pairing code is missing "$k".');
    }
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(q['fp']!)) throw const FormatException('Bad certificate fingerprint.');
    return PairingOffer(q['addr']!, q['fp']!, q['offer']!, q['otp']!, (q['scopes'] ?? '').split(','));
  }
}

class LensException implements Exception {
  LensException(this.status, this.message);
  final int status;
  final String message;
  @override
  String toString() => message;
}

class LensClient {
  LensClient({required this.address, required this.fingerprint, required this.key, this.deviceId});

  final String address; // host:port
  final String fingerprint; // SHA-256 of the server certificate (DER), hex
  final DeviceKey key;
  String? deviceId;

  HttpClient _http() {
    final ctx = SecurityContext(withTrustedRoots: false); // trust no CA: only the pinned certificate
    return HttpClient(context: ctx)
      ..connectionTimeout = const Duration(seconds: 8)
      ..badCertificateCallback = (X509Certificate cert, String host, int port) =>
          sha256.convert(cert.der).toString() == fingerprint;
  }

  static List<int> canonical(String method, String path, String ts, String nonce, List<int> body) =>
      utf8.encode([method.toUpperCase(), path, ts, nonce, sha256.convert(body).toString()].join('\n'));

  Future<Map<String, dynamic>> _send(String method, String pathAndQuery,
      {List<int> body = const [], String? contentType, bool sign = true, bool raw = false}) async {
    final uri = Uri.parse('https://$address$pathAndQuery');
    final http = _http();
    try {
      final req = await http.openUrl(method, uri);
      if (contentType != null) req.headers.contentType = ContentType.parse(contentType);
      if (sign) {
        final ts = DateTime.now().toUtc().toIso8601String().replaceFirst('Z', '+00:00');
        final nonce = const Uuid().v4();
        req.headers
          ..set('X-FL-Device', deviceId!)
          ..set('X-FL-Timestamp', ts)
          ..set('X-FL-Nonce', nonce)
          ..set('X-FL-Signature', key.sign(canonical(method, uri.path, ts, nonce, body)));
      }
      req.contentLength = body.length;
      req.add(body);
      final res = await req.close();
      // Defence in depth: the connection must have been made with the pinned certificate.
      if (res.certificate == null || sha256.convert(res.certificate!.der).toString() != fingerprint) {
        throw LensException(0, 'Certificate does not match the paired Financial Lens.');
      }
      final bytes = await res.fold<List<int>>([], (a, b) => a..addAll(b));
      if (res.statusCode >= 400) {
        String msg = 'Error ${res.statusCode}';
        try {
          msg = (jsonDecode(utf8.decode(bytes)) as Map)['detail']?.toString() ?? msg;
        } catch (_) {}
        throw LensException(res.statusCode, msg);
      }
      if (raw) return {'bytes': Uint8List.fromList(bytes), 'type': res.headers.contentType?.mimeType ?? ''};
      return jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
    } finally {
      http.close(force: true);
    }
  }

  Future<String> pair(PairingOffer offer, String name, String platform) async {
    final body = utf8.encode(jsonEncode({
      'offer': offer.offer,
      'otp': offer.otp,
      'name': name,
      'platform': platform,
      'public_key': key.publicKeyB64,
    }));
    final r = await _send('POST', '/mobile/v1/pair', body: body, contentType: 'application/json', sign: false);
    deviceId = r['device_id'] as String;
    return deviceId!;
  }

  Future<Map<String, dynamic>> get(String pathAndQuery) => _send('GET', pathAndQuery);

  Future<Map<String, dynamic>> original(String documentId) =>
      _send('GET', '/mobile/v1/documents/$documentId/original', raw: true);

  Future<Map<String, dynamic>> decide(String linkId, bool accept) => _send('POST', '/mobile/v1/links/$linkId/decision',
      body: utf8.encode(jsonEncode({'accept': accept})), contentType: 'application/json');

  /// Upload one file as multipart/form-data. The exact bytes sent are the bytes signed.
  Future<Map<String, dynamic>> upload(String filename, List<int> data, String mime) {
    final boundary = 'fl${const Uuid().v4().replaceAll('-', '')}';
    final safeName = filename.replaceAll('"', '');
    final body = <int>[
      ...utf8.encode('--$boundary\r\nContent-Disposition: form-data; name="files"; filename="$safeName"\r\n'
          'Content-Type: $mime\r\n\r\n'),
      ...data,
      ...utf8.encode('\r\n--$boundary--\r\n'),
    ];
    return _send('POST', '/mobile/v1/documents', body: body, contentType: 'multipart/form-data; boundary=$boundary');
  }
}
