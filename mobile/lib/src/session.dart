// Pairing state lives only in the platform keystore (flutter_secure_storage).
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'client.dart';
import 'device_key.dart';

class Session {
  static const _store = FlutterSecureStorage(
    aOptions: AndroidOptions(resetOnError: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
  );

  static Future<LensClient?> load() async {
    final all = await _store.readAll();
    if (!all.containsKey('device_id')) return null;
    return LensClient(
      address: all['address']!,
      fingerprint: all['fingerprint']!,
      key: DeviceKey.fromHex(all['key']!),
      deviceId: all['device_id'],
    );
  }

  static Future<LensClient> pair(PairingOffer offer, String name, String platform) async {
    final key = DeviceKey.generate();
    final client = LensClient(address: offer.address, fingerprint: offer.fingerprint, key: key);
    await client.pair(offer, name, platform);
    await _store.write(key: 'key', value: key.privateHex);
    await _store.write(key: 'address', value: offer.address);
    await _store.write(key: 'fingerprint', value: offer.fingerprint);
    await _store.write(key: 'scopes', value: offer.scopes.join(','));
    await _store.write(key: 'device_id', value: client.deviceId!);
    return client;
  }

  static Future<void> forget() => _store.deleteAll();
}
