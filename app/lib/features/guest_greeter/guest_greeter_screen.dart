import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/app_state.dart';
import '../../core/widgets/primitives.dart';

/// Speaks a fixed, generic welcome through a linked device.
/// It can never identify an unknown visitor - the backend refuses anything that
/// tries (see tools/guest_greet.py).
class GuestGreeterScreen extends StatefulWidget {
  const GuestGreeterScreen({super.key});

  @override
  State<GuestGreeterScreen> createState() => _GuestGreeterScreenState();
}

class _GuestGreeterScreenState extends State<GuestGreeterScreen> {
  String _greeting = 'arrival';
  bool _busy = false;
  String? _result;

  static const _options = {
    'arrival': 'Welcome. The owner will be with you shortly.',
    'evening': 'Good evening, and welcome.',
    'delivery': 'Hello - please leave the parcel at the door. Thank you.',
  };

  Future<void> _greet() async {
    setState(() {
      _busy = true;
      _result = null;
    });
    final api = context.read<AuthController>().api;
    try {
      final data = await api.post('/assistant/chat', {'message': 'greet my guest with the $_greeting greeting'})
          as Map<String, dynamic>;
      final events = ((data['tool_events'] as List?) ?? const []).cast<Map<String, dynamic>>();
      final result = events.isNotEmpty ? (events.first['result'] as Map?)?.cast<String, dynamic>() : null;
      setState(() => _result = (result?['message'] ?? result?['error'] ?? 'No response').toString());
    } on ApiException catch (e) {
      setState(() => _result = e.message);
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
                title: 'Guest welcome',
                description:
                    'A short, generic greeting spoken on a linked device. No camera, no face check, no identification of unknown visitors.',
              ),
              for (final entry in _options.entries)
                RadioListTile<String>(
                  value: entry.key,
                  groupValue: _greeting,
                  onChanged: (value) => setState(() => _greeting = value ?? 'arrival'),
                  title: Text(entry.value),
                  contentPadding: EdgeInsets.zero,
                ),
              const SizedBox(height: 8),
              ElevatedButton(
                onPressed: _busy ? null : _greet,
                child: _busy
                    ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Text('Speak greeting'),
              ),
              if (_result != null) ...[
                const SizedBox(height: 12),
                Text(_result!, style: Theme.of(context).textTheme.bodySmall),
              ],
            ],
          ),
        ),
      ],
    );
  }
}
