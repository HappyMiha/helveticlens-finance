import 'dart:io';

import 'package:cunning_document_scanner/cunning_document_scanner.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../src/client.dart';
import '../src/theme.dart';
import '../src/upload_queue.dart';

String mimeFor(String name) {
  final n = name.toLowerCase();
  if (n.endsWith('.pdf')) return 'application/pdf';
  if (n.endsWith('.png')) return 'image/png';
  if (n.endsWith('.heic') || n.endsWith('.heif')) return 'image/heic';
  if (n.endsWith('.xml')) return 'application/xml';
  if (n.endsWith('.csv')) return 'text/csv';
  if (n.endsWith('.xlsx')) return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  if (n.endsWith('.txt')) return 'text/plain';
  return 'image/jpeg';
}

class CaptureScreen extends StatelessWidget {
  const CaptureScreen({super.key, required this.client, required this.queue});
  final LensClient client;
  final UploadQueue queue;

  Future<void> _addPaths(List<String> paths) async {
    for (final p in paths) {
      await queue.add(p.split(Platform.pathSeparator).last, mimeFor(p), await File(p).readAsBytes());
    }
    await queue.flush(client);
  }

  Future<void> _photo() async {
    final x = await ImagePicker().pickImage(source: ImageSource.camera, imageQuality: 90, maxWidth: 3000);
    if (x != null) await _addPaths([x.path]);
  }

  Future<void> _scan() async {
    final pages = await CunningDocumentScanner.getPictures() ?? [];
    await _addPaths(pages);
  }

  Future<void> _gallery() async {
    final xs = await ImagePicker().pickMultiImage(imageQuality: 92);
    await _addPaths(xs.map((x) => x.path).toList());
  }

  Future<void> _files() async {
    final r = await FilePicker.pickFiles(allowMultiple: true, type: FileType.custom,
        allowedExtensions: ['pdf', 'jpg', 'jpeg', 'png', 'heic', 'xml', 'csv', 'xlsx', 'txt']);
    await _addPaths([for (final f in r?.files ?? <PlatformFile>[]) if (f.path != null) f.path!]);
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: queue,
        builder: (context, _) => ListView(padding: const EdgeInsets.all(16), children: [
          Row(children: [
            Expanded(child: _Big(icon: Icons.photo_camera_outlined, label: 'Photo', onTap: _photo)),
            const SizedBox(width: 12),
            Expanded(child: _Big(icon: Icons.document_scanner_outlined, label: 'Scan', onTap: _scan)),
          ]),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: _Big(icon: Icons.photo_library_outlined, label: 'Photos', onTap: _gallery, small: true)),
            const SizedBox(width: 12),
            Expanded(child: _Big(icon: Icons.folder_open_outlined, label: 'Files', onTap: _files, small: true)),
          ]),
          const SizedBox(height: 20),
          Row(children: [
            Text(queue.pending == 0 ? 'Sent' : '${queue.pending} waiting',
                style: Theme.of(context).textTheme.titleMedium),
            const Spacer(),
            if (queue.pending > 0) TextButton(onPressed: () => queue.flush(client), child: const Text('Send now')),
            if (queue.items.any((i) => i.done)) TextButton(onPressed: queue.clearDone, child: const Text('Clear')),
          ]),
          for (final i in queue.items) _QueueTile(item: i),
          const SizedBox(height: 12),
          const Text('Originals go only to your own Financial Lens. Amounts and categories are read there, '
              'and every record links back to the photo.', style: TextStyle(color: T.muted, fontSize: 12)),
        ]),
      );
}

class _Big extends StatelessWidget {
  const _Big({required this.icon, required this.label, required this.onTap, this.small = false});
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool small;
  @override
  Widget build(BuildContext context) => Card(
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: onTap,
          child: SizedBox(
            height: small ? 72 : 120,
            child: Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(icon, size: small ? 24 : 36),
              const SizedBox(height: 6),
              Text(label, style: const TextStyle(fontWeight: FontWeight.w600)),
            ])),
          ),
        ),
      );
}

class _QueueTile extends StatelessWidget {
  const _QueueTile({required this.item});
  final QueuedItem item;
  @override
  Widget build(BuildContext context) {
    final r = item.result;
    String subtitle;
    Color dot;
    if (r != null && r['amount'] != null) {
      subtitle = '${T.chf(r['amount'])} · ${(r['category'] as List?)?.join(' / ') ?? ''} · ${T.statusLabel(r['status'])}';
      dot = T.status(r['status']);
    } else if (r != null) {
      subtitle = r['duplicate'] == true ? 'Already in your ledger' : ((r['messages'] as List?)?.join(' ') ?? 'Saved');
      dot = T.warning;
    } else {
      subtitle = item.error ?? 'Waiting to send…';
      dot = T.muted;
    }
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(Icons.circle, size: 10, color: dot),
      title: Text(r?['counterparty']?.toString().isNotEmpty == true ? r!['counterparty'] : item.name),
      subtitle: Text(subtitle, style: const TextStyle(color: T.muted)),
    );
  }
}
