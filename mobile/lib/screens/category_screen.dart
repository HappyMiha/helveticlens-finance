import 'package:flutter/material.dart';

import '../src/client.dart';
import '../src/theme.dart';
import 'operation_screen.dart';

class CategoryScreen extends StatelessWidget {
  const CategoryScreen({super.key, required this.client, required this.path, required this.start, required this.end});
  final LensClient client;
  final List<String> path;
  final String start, end;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(path.join(' / '))),
        body: FutureBuilder<Map<String, dynamic>>(
          future: client.get('/mobile/v1/treemap?path=${Uri.encodeComponent(path.join('/'))}&start=$start&end=$end'),
          builder: (context, snap) {
            if (snap.hasError) return Center(child: Text('${snap.error}', style: const TextStyle(color: T.warning)));
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final n = snap.data!;
            final children = List<Map<String, dynamic>>.from(n['children'] ?? []);
            final ops = List<Map<String, dynamic>>.from(n['operations'] ?? []);
            return ListView(children: [
              ListTile(title: Text(T.chf(n['total']), style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600)),
                  subtitle: Text('${n['count']} records · $start – $end', style: const TextStyle(color: T.muted))),
              for (final c in children)
                ListTile(
                  title: Text(c['name']),
                  trailing: Text(T.chf(c['total'])),
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) =>
                      CategoryScreen(client: client, path: [...path, c['name']], start: start, end: end))),
                ),
              for (final o in ops)
                ListTile(
                  leading: Icon(Icons.circle, size: 10, color: T.status(o['verification'])),
                  title: Text((o['counterparty'] ?? '').toString().isEmpty ? o['kind'] : o['counterparty']),
                  subtitle: Text('${o['date']} · ${T.statusLabel(o['verification'])}', style: const TextStyle(color: T.muted)),
                  trailing: Text(T.chf(o['amount'])),
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) =>
                      OperationScreen(client: client, id: o['id']))),
                ),
            ]);
          },
        ),
      );
}
