import 'package:flutter/material.dart';

import '../src/client.dart';
import '../src/theme.dart';
import 'category_screen.dart';

class OverviewScreen extends StatefulWidget {
  const OverviewScreen({super.key, required this.client});
  final LensClient client;
  @override
  State<OverviewScreen> createState() => _OverviewScreenState();
}

class _OverviewScreenState extends State<OverviewScreen> {
  Map<String, dynamic>? _data;
  String? _error;
  int _months = 0; // 0 = this month, 12 = last 12 months

  ({String start, String end}) _range() {
    final now = DateTime.now();
    final start = _months == 0 ? DateTime(now.year, now.month, 1) : DateTime(now.year - 1, now.month, now.day);
    String d(DateTime x) => '${x.year}-${x.month.toString().padLeft(2, '0')}-${x.day.toString().padLeft(2, '0')}';
    return (start: d(start), end: d(now));
  }

  Future<void> _load() async {
    final r = _range();
    try {
      final d = await widget.client.get('/mobile/v1/summary?start=${r.start}&end=${r.end}');
      setState(() {
        _data = d;
        _error = null;
      });
    } catch (e) {
      setState(() => _error = e.toString());
    }
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    final r = _range();
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(16), children: [
        SegmentedButton<int>(
          segments: const [ButtonSegment(value: 0, label: Text('This month')), ButtonSegment(value: 12, label: Text('12 months'))],
          selected: {_months},
          onSelectionChanged: (s) {
            setState(() => _months = s.first);
            _load();
          },
        ),
        const SizedBox(height: 12),
        if (_error != null) Card(child: Padding(padding: const EdgeInsets.all(16),
            child: Text(_error!, style: const TextStyle(color: T.warning)))),
        if (d == null && _error == null) const Center(child: Padding(padding: EdgeInsets.all(40), child: CircularProgressIndicator())),
        if (d != null) ...[
          Row(children: [
            Expanded(child: _Kpi('Expenses', T.chf(d['expenses']))),
            const SizedBox(width: 12),
            Expanded(child: _Kpi('Income', T.chf(d['income']))),
          ]),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: _Kpi('Balance', T.chf(d['balance']))),
            const SizedBox(width: 12),
            Expanded(child: _Kpi('To check', '${d['unconfirmed']} · ${d['unpaid']} unpaid')),
          ]),
          const SizedBox(height: 20),
          Text('Where the money went', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          _Bars(categories: List<Map<String, dynamic>>.from(d['categories'] ?? []), onTap: (name) {
            Navigator.of(context).push(MaterialPageRoute(builder: (_) =>
                CategoryScreen(client: widget.client, path: [name], start: r.start, end: r.end)));
          }),
        ],
      ]),
    );
  }
}

class _Kpi extends StatelessWidget {
  const _Kpi(this.label, this.value);
  final String label, value;
  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, style: const TextStyle(color: T.muted, fontSize: 12)),
            const SizedBox(height: 4),
            FittedBox(child: Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600,
                fontFeatures: [FontFeature.tabularFigures()]))),
          ]),
        ),
      );
}

/// Proportional bars (a treemap row on a narrow screen): width ∝ amount, values from the ledger.
class _Bars extends StatelessWidget {
  const _Bars({required this.categories, required this.onTap});
  final List<Map<String, dynamic>> categories;
  final void Function(String) onTap;
  @override
  Widget build(BuildContext context) {
    if (categories.isEmpty) {
      return const Text('No spending recorded in this period yet.', style: TextStyle(color: T.muted));
    }
    final max = categories.map((c) => double.tryParse('${c['total']}') ?? 0).reduce((a, b) => a > b ? a : b);
    return Column(children: [
      for (var i = 0; i < categories.length; i++)
        InkWell(
          onTap: () => onTap(categories[i]['name']),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: Text(categories[i]['name'], style: const TextStyle(fontWeight: FontWeight.w600))),
                Text(T.chf(categories[i]['total']), style: const TextStyle(fontFeatures: [FontFeature.tabularFigures()])),
                const Icon(Icons.chevron_right, color: T.muted, size: 18),
              ]),
              const SizedBox(height: 4),
              LayoutBuilder(builder: (context, c) => Container(
                    height: 10,
                    width: c.maxWidth * ((double.tryParse('${categories[i]['total']}') ?? 0) / (max == 0 ? 1 : max)),
                    decoration: BoxDecoration(color: T.expense[i % T.expense.length], borderRadius: BorderRadius.circular(3)),
                  )),
            ]),
          ),
        ),
    ]);
  }
}
