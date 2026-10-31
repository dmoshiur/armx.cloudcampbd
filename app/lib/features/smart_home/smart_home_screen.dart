import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/app_state.dart';
import '../../core/widgets/primitives.dart';

class SmartHomeScreen extends StatefulWidget {
  const SmartHomeScreen({super.key});

  @override
  State<SmartHomeScreen> createState() => _SmartHomeScreenState();
}

class _SmartHomeScreenState extends State<SmartHomeScreen> {
  List<Map<String, dynamic>> _entities = [];
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
      // Asking the assistant keeps Home Assistant behind the gateway.
      final data = await api.post('/assistant/chat', {'message': 'check the state of my allowlisted devices'})
          as Map<String, dynamic>;
      final events = ((data['tool_events'] as List?) ?? const []).cast<Map<String, dynamic>>();
      final result = events.isNotEmpty ? (events.first['result'] as Map?)?.cast<String, dynamic>() : null;
      final payload = (result?['data'] as Map?)?.cast<String, dynamic>();
      setState(() {
        _entities = ((payload?['entities'] as List?) ?? const []).cast<Map<String, dynamic>>();
      });
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _toggle(Map<String, dynamic> entity, bool on) async {
    final api = context.read<AuthController>().api;
    final entityId = entity['entity_id']?.toString() ?? '';
    try {
      await api.post('/assistant/chat', {
        'message': on ? 'turn on $entityId' : 'turn off $entityId',
      });
      await _load();
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const ArmxLoading(label: 'Reading allowlisted entities');
    if (_error != null) return ArmxErrorState(message: _error!, onRetry: _load);
    if (_entities.isEmpty) {
      return ArmxEmptyState(
        title: 'No entities allowlisted',
        description:
            'Add entities to HOME_ASSISTANT_ALLOWED_ENTITIES on the server. The assistant can never reach an entity outside that list.',
        action: OutlinedButton(onPressed: _load, child: const Text('Refresh')),
      );
    }

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: _entities.length,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          final entity = _entities[index];
          final state = entity['state']?.toString() ?? 'unknown';
          final on = state == 'on';
          return ArmxCard(
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(entity['friendly_name']?.toString().isNotEmpty == true
                          ? entity['friendly_name'].toString()
                          : entity['entity_id'].toString()),
                      const SizedBox(height: 2),
                      Text(entity['entity_id'].toString(), style: Theme.of(context).textTheme.bodySmall),
                    ],
                  ),
                ),
                ArmxBadge(state, tone: on ? ArmxTone.success : ArmxTone.neutral),
                const SizedBox(width: 8),
                Switch(value: on, onChanged: (value) => _toggle(entity, value)),
              ],
            ),
          );
        },
      ),
    );
  }
}
