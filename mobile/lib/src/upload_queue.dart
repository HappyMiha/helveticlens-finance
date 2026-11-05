// Offline queue: documents wait in the app's private storage until the Financial Lens is reachable.
// Retries are harmless: the server recognises a file it already has by its SHA-256.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:uuid/uuid.dart';

import 'client.dart';

class QueuedItem {
  QueuedItem(this.id, this.name, this.mime, this.path, {this.result, this.error});
  final String id, name, mime, path;
  Map<String, dynamic>? result;
  String? error;
  bool get done => result != null;

  Map<String, dynamic> toJson() => {'id': id, 'name': name, 'mime': mime, 'path': path, 'result': result, 'error': error};
  static QueuedItem fromJson(Map<String, dynamic> j) =>
      QueuedItem(j['id'], j['name'], j['mime'], j['path'], result: j['result'], error: j['error']);
}

class UploadQueue extends ChangeNotifier {
  final List<QueuedItem> items = [];
  late Directory _dir;
  bool _sending = false;

  Future<void> init() async {
    _dir = Directory('${(await getApplicationSupportDirectory()).path}/queue')..createSync(recursive: true);
    final index = File('${_dir.path}/index.json');
    if (index.existsSync()) {
      items.addAll((jsonDecode(index.readAsStringSync()) as List).map((e) => QueuedItem.fromJson(e)));
    }
  }

  void _save() {
    File('${_dir.path}/index.json').writeAsStringSync(jsonEncode(items.map((e) => e.toJson()).toList()));
    notifyListeners();
  }

  int get pending => items.where((i) => !i.done).length;

  Future<void> add(String name, String mime, List<int> bytes) async {
    final id = const Uuid().v4();
    final path = '${_dir.path}/$id';
    await File(path).writeAsBytes(bytes, flush: true);
    items.insert(0, QueuedItem(id, name, mime, path));
    _save();
  }

  Future<void> flush(LensClient client) async {
    if (_sending) return;
    _sending = true;
    try {
      for (final item in items.where((i) => !i.done).toList().reversed) {
        try {
          final r = await client.upload(item.name, await File(item.path).readAsBytes(), item.mime);
          item.result = (r['results'] as List).first as Map<String, dynamic>;
          item.error = null;
          File(item.path).deleteSync(); // the original now lives in the ledger
        } on LensException catch (e) {
          item.error = e.message;
          if (e.status == 401 || e.status == 403) break; // revoked or not allowed: do not hammer
        } on SocketException {
          item.error = 'Waiting for your Financial Lens (same Wi-Fi, app running)…';
          break;
        } catch (e) {
          item.error = e.toString();
        }
        _save();
      }
    } finally {
      _sending = false;
      _save();
    }
  }

  void clearDone() {
    items.removeWhere((i) => i.done);
    _save();
  }
}
