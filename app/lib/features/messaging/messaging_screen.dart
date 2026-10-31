import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/app_state.dart';
import '../../core/widgets/primitives.dart';

class MessagingScreen extends StatefulWidget {
  const MessagingScreen({super.key});

  @override
  State<MessagingScreen> createState() => _MessagingScreenState();
}

class _MessagingScreenState extends State<MessagingScreen> {
  List<Map<String, dynamic>> _profiles = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final api = context.read<AuthController>().api;
    try {
      final data = await api.get('/messaging/profiles') as List;
      setState(() {
        _profiles = data.cast<Map<String, dynamic>>();
        _error = null;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _add() async {
    final contact = TextEditingController();
    final name = TextEditingController();
    final personality = TextEditingController();
    var autoSend = false;

    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Add a contact'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('Only people who agreed to receive automated replies should be added here.'),
                const SizedBox(height: 12),
                TextField(controller: contact, decoration: const InputDecoration(labelText: 'Phone (E.164) or PSID')),
                const SizedBox(height: 8),
                TextField(controller: name, decoration: const InputDecoration(labelText: 'Name')),
                const SizedBox(height: 8),
                TextField(controller: personality, maxLines: 2, decoration: const InputDecoration(labelText: 'Reply personality')),
                const SizedBox(height: 8),
                SwitchListTile(
                  value: autoSend,
                  onChanged: (value) => setDialogState(() => autoSend = value),
                  title: const Text('Allow auto-send'),
                  subtitle: const Text('MEDIUM risk. Without it every send is HIGH risk and needs approval.'),
                  contentPadding: EdgeInsets.zero,
                ),
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Save')),
          ],
        ),
      ),
    );
    if (ok != true || !mounted) return;

    final api = context.read<AuthController>().api;
    try {
      await api.post('/messaging/profiles', {
        'channel': 'whatsapp',
        'contact_id': contact.text.trim(),
        'display_name': name.text.trim(),
        'personality': personality.text.trim(),
        'auto_send': autoSend,
      });
      await _load();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: Row(
            children: [
              const Expanded(
                child: Text('The assistant only messages contacts you add here.'),
              ),
              ElevatedButton(onPressed: _add, child: const Text('Add contact')),
            ],
          ),
        ),
        Expanded(
          child: _loading
              ? const ArmxLoading(label: 'Loading contacts')
              : _error != null
                  ? Padding(padding: const EdgeInsets.all(16), child: ArmxErrorState(message: _error!, onRetry: _load))
                  : _profiles.isEmpty
                      ? const ArmxEmptyState(title: 'No contacts yet', description: 'Add someone with their consent to enable replies.')
                      : ListView.separated(
                          padding: const EdgeInsets.all(16),
                          itemCount: _profiles.length,
                          separatorBuilder: (_, __) => const SizedBox(height: 10),
                          itemBuilder: (context, index) {
                            final profile = _profiles[index];
                            return ArmxCard(
                              child: Row(
                                children: [
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        Text(profile['display_name'].toString().isEmpty
                                            ? profile['contact_id'].toString()
                                            : profile['display_name'].toString()),
                                        Text('${profile['channel']} · ${profile['contact_id']}',
                                            style: Theme.of(context).textTheme.bodySmall),
                                      ],
                                    ),
                                  ),
                                  ArmxBadge(profile['auto_send'] == true ? 'auto-send' : 'draft only',
                                      tone: profile['auto_send'] == true ? ArmxTone.warning : ArmxTone.neutral),
                                  IconButton(
                                    tooltip: 'Remove contact',
                                    onPressed: () async {
                                      final api = context.read<AuthController>().api;
                                      await api.delete('/messaging/profiles/${profile['id']}');
                                      await _load();
                                    },
                                    icon: const Icon(Icons.delete_outline),
                                  ),
                                ],
                              ),
                            );
                          },
                        ),
        ),
      ],
    );
  }
}
