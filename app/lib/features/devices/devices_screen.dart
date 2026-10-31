import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/app_state.dart';
import '../../core/theme.dart';
import '../../core/widgets/primitives.dart';
import '../device_bridge/device_bridge.dart';

class DevicesScreen extends StatefulWidget {
  const DevicesScreen({super.key});

  @override
  State<DevicesScreen> createState() => _DevicesScreenState();
}

class _DevicesScreenState extends State<DevicesScreen> {
  List<Map<String, dynamic>> _devices = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final api = context.read<AuthController>().api;
    try {
      final data = await api.get('/devices') as List;
      setState(() => _devices = data.cast<Map<String, dynamic>>());
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _confirmPairing() async {
    final codeController = TextEditingController();
    final passwordController = TextEditingController();
    final nameController = TextEditingController(text: 'This device');

    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Pair this device'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Enter the 6-digit code shown in the web app. The unlink password is stored hashed on the server and only you can use it.',
            ),
            const SizedBox(height: 12),
            TextField(controller: codeController, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Pairing code')),
            const SizedBox(height: 8),
            TextField(controller: passwordController, obscureText: true, decoration: const InputDecoration(labelText: 'Unlink password (min 8 chars)')),
            const SizedBox(height: 8),
            TextField(controller: nameController, decoration: const InputDecoration(labelText: 'Device name')),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Pair')),
        ],
      ),
    );

    if (ok != true || !mounted) return;
    final bridge = context.read<DeviceBridge>();
    final success = await bridge.confirmPairing(
      code: codeController.text.trim(),
      password: passwordController.text,
      name: nameController.text.trim(),
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(success ? 'Device paired. The linked notification is now visible.' : bridge.error ?? 'Pairing failed')),
    );
    await _load();
  }

  Future<void> _unlink(Map<String, dynamic> device) async {
    final passwordController = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Unlink this device?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Enter the unlink password that was set on the device. Administrators cannot bypass this.'),
            const SizedBox(height: 12),
            TextField(controller: passwordController, obscureText: true, decoration: const InputDecoration(labelText: 'Unlink password')),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Unlink')),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    final api = context.read<AuthController>().api;
    try {
      final data = await api.post('/devices/${device['id']}/unlink/verify', {'password': passwordController.text})
          as Map<String, dynamic>;
      await api.post('/devices/${device['id']}/unlink', {'ticket': data['ticket']});
      if (device['id'] == context.read<DeviceBridge>().deviceId) {
        await context.read<DeviceBridge>().unlinkLocally();
      }
      await _load();
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final bridge = context.watch<DeviceBridge>();
    final auth = context.watch<AuthController>();

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Row(
            children: [
              ArmxBadge(bridge.linked ? 'this device is linked' : 'not linked', tone: bridge.linked ? ArmxTone.success : ArmxTone.neutral),
              const Spacer(),
              if (auth.user?.canLinkDevices == true)
                ElevatedButton(onPressed: _confirmPairing, child: const Text('Pair this device')),
            ],
          ),
        ),
        Expanded(
          child: _loading
              ? const ArmxLoading(label: 'Loading devices')
              : _error != null
                  ? Padding(padding: const EdgeInsets.all(16), child: ArmxErrorState(message: _error!, onRetry: _load))
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: _devices.isEmpty
                          ? ListView(children: const [
                              SizedBox(height: 80),
                              ArmxEmptyState(
                                title: 'No devices linked',
                                description: 'Pairing is one explicit action on the device, and it always shows a persistent Linked notification.',
                              ),
                            ])
                          : ListView.separated(
                              padding: const EdgeInsets.all(16),
                              itemCount: _devices.length,
                              separatorBuilder: (_, __) => const SizedBox(height: 10),
                              itemBuilder: (context, index) {
                                final device = _devices[index];
                                final active = device['status'] == 'active';
                                return ArmxCard(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Row(
                                        children: [
                                          Expanded(child: Text(device['name'].toString(), style: Theme.of(context).textTheme.titleMedium)),
                                          ArmxBadge(device['status'].toString(), tone: active ? ArmxTone.success : ArmxTone.neutral),
                                        ],
                                      ),
                                      const SizedBox(height: 4),
                                      Text(
                                        '${device['platform']} · ${(device['capabilities'] as List).join(', ')}',
                                        style: Theme.of(context).textTheme.bodySmall,
                                      ),
                                      if (active) ...[
                                        const SizedBox(height: 10),
                                        Row(
                                          children: [
                                            Expanded(
                                              child: Text(
                                                'Persistent Linked notification is on.',
                                                style: Theme.of(context).textTheme.bodySmall,
                                              ),
                                            ),
                                            TextButton(
                                              onPressed: () => _unlink(device),
                                              child: const Text('Unlink', style: TextStyle(color: ArmxColors.danger)),
                                            ),
                                          ],
                                        ),
                                      ],
                                    ],
                                  ),
                                );
                              },
                            ),
                    ),
        ),
      ],
    );
  }
}
