// Financial Lens Mobile: a window and a camera for your own Financial Lens.
// The ledger, the money maths and the originals stay on your computer (or your Swiss server).
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:local_auth/local_auth.dart';

import 'screens/capture_screen.dart';
import 'screens/overview_screen.dart';
import 'screens/pair_screen.dart';
import 'src/client.dart';
import 'src/session.dart';
import 'src/theme.dart';
import 'src/upload_queue.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final queue = UploadQueue();
  await queue.init();
  runApp(LensApp(queue: queue, client: await Session.load()));
}

class LensApp extends StatefulWidget {
  const LensApp({super.key, required this.queue, this.client});
  final UploadQueue queue;
  final LensClient? client;
  @override
  State<LensApp> createState() => _LensAppState();
}

class _LensAppState extends State<LensApp> with WidgetsBindingObserver {
  LensClient? _client;
  bool _locked = true;
  bool _hidden = false;

  @override
  void initState() {
    super.initState();
    _client = widget.client;
    WidgetsBinding.instance.addObserver(this);
    _unlock();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Hide content in the app switcher; ask for Face ID / fingerprint again after leaving the app.
    if (state == AppLifecycleState.inactive || state == AppLifecycleState.paused) {
      setState(() {
        _hidden = true;
        if (state == AppLifecycleState.paused) _locked = true;
      });
    } else if (state == AppLifecycleState.resumed) {
      setState(() => _hidden = false);
      if (_locked) _unlock();
      if (_client != null) widget.queue.flush(_client!);
    }
  }

  Future<void> _unlock() async {
    final auth = LocalAuthentication();
    bool ok;
    try {
      ok = !await auth.isDeviceSupported() ||
          await auth.authenticate(localizedReason: 'Unlock Financial Lens', persistAcrossBackgrounding: true);
    } on PlatformException {
      ok = true; // no screen lock set up on this device: nothing to check against
    } catch (_) {
      ok = true;
    }
    if (mounted) setState(() => _locked = !ok);
  }

  @override
  Widget build(BuildContext context) {
    Widget body;
    if (_locked || _hidden) {
      body = Scaffold(body: Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
        const Icon(Icons.lock_outline, size: 40, color: T.muted),
        const SizedBox(height: 12),
        if (_locked && !_hidden) FilledButton(onPressed: _unlock, child: const Text('Unlock')),
      ])));
    } else if (_client == null) {
      body = PairScreen(onPaired: (c) {
        setState(() => _client = c);
        widget.queue.flush(c);
      });
    } else {
      body = Home(client: _client!, queue: widget.queue, onForget: () async {
        await Session.forget();
        setState(() => _client = null);
      });
    }
    return MaterialApp(title: 'Financial Lens', theme: T.theme(), debugShowCheckedModeBanner: false, home: body);
  }
}

class Home extends StatefulWidget {
  const Home({super.key, required this.client, required this.queue, required this.onForget});
  final LensClient client;
  final UploadQueue queue;
  final VoidCallback onForget;
  @override
  State<Home> createState() => _HomeState();
}

class _HomeState extends State<Home> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Financial Lens'), actions: [
          PopupMenuButton<String>(
            onSelected: (v) async {
              if (v != 'forget') return;
              final yes = await showDialog<bool>(context: context, builder: (c) => AlertDialog(
                    title: const Text('Disconnect this phone?'),
                    content: const Text('The phone forgets its key. To connect again, pair it from the computer. '
                        'You can also revoke it there.'),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
                      FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Disconnect')),
                    ]));
              if (yes == true) widget.onForget();
            },
            itemBuilder: (_) => const [PopupMenuItem(value: 'forget', child: Text('Disconnect this phone'))],
          ),
        ]),
        body: IndexedStack(index: _tab, children: [
          CaptureScreen(client: widget.client, queue: widget.queue),
          OverviewScreen(client: widget.client),
        ]),
        bottomNavigationBar: NavigationBar(
          selectedIndex: _tab,
          onDestinationSelected: (i) => setState(() => _tab = i),
          destinations: const [
            NavigationDestination(icon: Icon(Icons.add_a_photo_outlined), label: 'Add'),
            NavigationDestination(icon: Icon(Icons.pie_chart_outline), label: 'Overview'),
          ],
        ),
      );
}
