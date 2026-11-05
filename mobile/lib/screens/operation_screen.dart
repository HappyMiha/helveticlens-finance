import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../src/client.dart';
import '../src/theme.dart';

class OperationScreen extends StatelessWidget {
  const OperationScreen({super.key, required this.client, required this.id});
  final LensClient client;
  final String id;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Evidence')),
        body: FutureBuilder<Map<String, dynamic>>(
          future: client.get('/mobile/v1/operations/$id'),
          builder: (context, snap) {
            if (snap.hasError) return Center(child: Text('${snap.error}', style: const TextStyle(color: T.warning)));
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final d = snap.data!;
            final prov = Map<String, dynamic>.from(d['provenance'] ?? {});
            return ListView(padding: const EdgeInsets.all(16), children: [
              Text(d['counterparty']?.toString().isNotEmpty == true ? d['counterparty'] : d['kind'],
                  style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 4),
              Text(T.chf(d['amount']), style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w600)),
              const SizedBox(height: 4),
              Text('● ${T.statusLabel(d['verification'])} — ${d['verification_reason']}',
                  style: TextStyle(color: T.status(d['verification']))),
              const SizedBox(height: 12),
              _Row('Date', d['op_date']),
              if (d['due_date'] != null) _Row('Due', d['due_date']),
              _Row('Category', (d['category_path'] as List?)?.join(' / ')),
              _Row('Read by', d['method']),
              if (prov.isNotEmpty) ...[
                const SizedBox(height: 16),
                Text('Where each value came from', style: Theme.of(context).textTheme.titleSmall),
                for (final e in prov.entries)
                  if ((e.value as Map)['quote'] != null)
                    _Row(e.key, '“${(e.value as Map)['quote']}”'
                        '${(e.value as Map)['line'] != null ? ' · line ${(e.value as Map)['line']}' : ''}'),
              ],
              const SizedBox(height: 16),
              Text('Documents', style: Theme.of(context).textTheme.titleSmall),
              for (final doc in List<Map<String, dynamic>>.from(d['documents'] ?? []))
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.description_outlined),
                  title: Text(doc['filename']),
                  subtitle: Text('${doc['role']} · sha256 ${doc['sha256'].toString().substring(0, 12)}…',
                      style: const TextStyle(color: T.muted)),
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) =>
                      _Original(client: client, id: doc['id'], name: doc['filename']))),
                ),
              if ((d['links'] as List?)?.isNotEmpty == true) ...[
                const SizedBox(height: 16),
                Text('Linked', style: Theme.of(context).textTheme.titleSmall),
                for (final l in List<Map<String, dynamic>>.from(d['links']))
                  _Row('${l['other_kind']} ${l['other_date']}',
                      '${T.chf(l['other_amount'])} · ${l['status']}\n${(l['reasons'] as List).join('; ')}'),
              ],
              const SizedBox(height: 16),
              Text('History', style: Theme.of(context).textTheme.titleSmall),
              for (final h in List<Map<String, dynamic>>.from(d['history'] ?? []))
                _Row('r${h['revision']}', '${h['change_reason']} · ${T.statusLabel(h['verification'])}\n${h['agent']}'),
            ]);
          },
        ),
      );
}

class _Row extends StatelessWidget {
  const _Row(this.k, this.v);
  final String k;
  final Object? v;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 110, child: Text(k, style: const TextStyle(color: T.muted))),
          Expanded(child: Text('${v ?? '—'}')),
        ]),
      );
}

class _Original extends StatelessWidget {
  const _Original({required this.client, required this.id, required this.name});
  final LensClient client;
  final String id, name;
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(name)),
        body: FutureBuilder<Map<String, dynamic>>(
          future: client.original(id),
          builder: (context, snap) {
            if (snap.hasError) return Center(child: Text('${snap.error}'));
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final type = snap.data!['type'] as String;
            final bytes = snap.data!['bytes'] as Uint8List;
            if (type.startsWith('image/') && type != 'image/heic') {
              return InteractiveViewer(child: Center(child: Image.memory(bytes)));
            }
            return Center(child: Text('$type · ${(bytes.length / 1024).toStringAsFixed(0)} KB\n'
                'Open it on your computer to view this file type.', textAlign: TextAlign.center));
          },
        ),
      );
}
