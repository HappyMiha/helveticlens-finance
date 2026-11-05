import 'dart:io';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../src/client.dart';
import '../src/session.dart';
import '../src/theme.dart';

class PairScreen extends StatefulWidget {
  const PairScreen({super.key, required this.onPaired});
  final void Function(LensClient) onPaired;
  @override
  State<PairScreen> createState() => _PairScreenState();
}

class _PairScreenState extends State<PairScreen> {
  final _scanner = MobileScannerController(formats: [BarcodeFormat.qrCode]);
  String? _error;
  bool _busy = false;

  Future<void> _handle(String raw) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final offer = PairingOffer.parse(raw);
      await _scanner.stop();
      final client = await Session.pair(offer, Platform.isIOS ? 'iPhone' : 'Android phone', Platform.operatingSystem);
      widget.onPaired(client);
    } on FormatException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = 'Could not pair: $e');
      await _scanner.start();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _scanner.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Connect to Financial Lens')),
        body: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('On your computer open Financial Lens → “Pair phone”, then scan the code. '
                'Both devices must be on the same Wi-Fi. The code works once and expires after 5 minutes.',
                style: TextStyle(color: T.muted)),
            const SizedBox(height: 16),
            Expanded(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(16),
                child: MobileScanner(
                  controller: _scanner,
                  onDetect: (c) {
                    final v = c.barcodes.isEmpty ? null : c.barcodes.first.rawValue;
                    if (v != null) _handle(v);
                  },
                ),
              ),
            ),
            if (_busy) const Padding(padding: EdgeInsets.all(12), child: LinearProgressIndicator()),
            if (_error != null) Padding(padding: const EdgeInsets.only(top: 12),
                child: Text(_error!, style: const TextStyle(color: T.danger))),
          ]),
        ),
      );
}
