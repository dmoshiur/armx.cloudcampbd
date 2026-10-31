import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/app_state.dart';
import '../../core/widgets/primitives.dart';

class AlarmsScreen extends StatefulWidget {
  const AlarmsScreen({super.key});

  @override
  State<AlarmsScreen> createState() => _AlarmsScreenState();
}

class _AlarmsScreenState extends State<AlarmsScreen> {
  @override
  void dispose() {
    _labelController.dispose();
    super.dispose();
  }

  TimeOfDay _time = const TimeOfDay(hour: 7, minute: 0);
  final TextEditingController _labelController = TextEditingController(text: 'Wake up');
  String get _label => _labelController.text.trim().isEmpty ? 'Alarm' : _labelController.text.trim();
  bool _busy = false;
  final List<Map<String, dynamic>> _created = [];

  Future<void> _pickTime() async {
    final picked = await showTimePicker(context: context, initialTime: _time);
    if (picked != null) setState(() => _time = picked);
  }

  Future<void> _setAlarm() async {
    setState(() => _busy = true);
    final api = context.read<AuthController>().api;
    final formatted = '${_time.hour.toString().padLeft(2, '0')}:${_time.minute.toString().padLeft(2, '0')}';
    try {
      final data = await api.post('/assistant/chat', {
        'message': 'set an alarm for $formatted labelled $_label',
      }) as Map<String, dynamic>;
      final events = ((data['tool_events'] as List?) ?? const []).cast<Map<String, dynamic>>();
      if (mounted) {
        setState(() {
          _created.insert(0, {
            'time': formatted,
            'label': _label,
            'ok': events.isNotEmpty && events.first['ok'] == true,
            'message': ((events.isNotEmpty ? (events.first['result'] as Map?)?['message'] : null) ?? '').toString(),
          });
        });
      }
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        ArmxCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const ArmxSectionHeader(
                title: 'Set an alarm',
                description: 'Alarms run on your paired device. The device shows every alarm it receives.',
              ),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _pickTime,
                      child: Text('Ring at ${_time.format(context)}'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: ElevatedButton(
                      onPressed: _busy ? null : _setAlarm,
                      child: _busy
                          ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Text('Set alarm'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextField(
                decoration: const InputDecoration(labelText: 'Label'),
                controller: _labelController,
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        if (_created.isNotEmpty) const ArmxSectionHeader(title: 'Just queued'),
        for (final alarm in _created)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: ArmxCard(
              child: Row(
                children: [
                  Expanded(
                    child: Text('${alarm['time']} · ${alarm['label']}',
                        style: Theme.of(context).textTheme.bodyMedium),
                  ),
                  ArmxBadge(alarm['ok'] == true ? 'queued' : 'failed',
                      tone: alarm['ok'] == true ? ArmxTone.success : ArmxTone.danger),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
