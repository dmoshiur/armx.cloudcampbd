import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/app_state.dart';
import '../../core/theme.dart';
import '../../core/widgets/primitives.dart';

/// The watch companion and small screens get a read-only admin view:
/// overview counts, tool toggles and the kill-switch. The full audit browser
/// lives on the web app.
class AdminScreen extends StatefulWidget {
  const AdminScreen({super.key});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  Map<String, dynamic>? _overview;
  List<Map<String, dynamic>> _tools = [];
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
      final overview = await api.get('/admin/overview') as Map<String, dynamic>;
      final tools = await api.get('/admin/tools') as List;
      setState(() {
        _overview = overview;
        _tools = tools.cast<Map<String, dynamic>>();
        _error = null;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _toggleKillSwitch() async {
    final engaged = _overview?['kill_switch'] == 'on';
    final approved = await showApprovalSheet(
      context,
      tool: 'kill_switch',
      risk: 'high',
      args: {'engaged': !engaged},
      description: engaged
          ? 'Release the kill-switch: tools and integrations become available again.'
          : 'Engage the kill-switch: every integration and tool halts instantly, independent of the AI.',
    );
    if (approved == false || !mounted) return;
    final api = context.read<AuthController>().api;
    try {
      await api.post('/admin/kill-switch', {'engaged': !engaged});
      await _load();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _toggleTool(Map<String, dynamic> tool) async {
    final api = context.read<AuthController>().api;
    try {
      await api.patch('/admin/tools', {
        'name': tool['name'],
        'enabled': !(tool['enabled_global'] == true),
      });
      await _load();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const ArmxLoading(label: 'Loading admin data');
    if (_error != null) return Padding(padding: const EdgeInsets.all(16), child: ArmxErrorState(message: _error!, onRetry: _load));

    final engaged = _overview?['kill_switch'] == 'on';
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        ArmxCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const ArmxSectionHeader(title: 'Platform', description: 'Counts and global controls.'),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  ArmxBadge('users ${_overview?['users']}'),
                  ArmxBadge('linked devices ${_overview?['linked_devices']}'),
                  ArmxBadge('audit ${_overview?['audit_events']}'),
                  ArmxBadge('pending ${_overview?['pending_approvals']}',
                      tone: (_overview?['pending_approvals'] ?? 0) > 0 ? ArmxTone.warning : ArmxTone.neutral),
                ],
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: engaged ? ArmxColors.accent : ArmxColors.danger,
                    foregroundColor: engaged ? ArmxColors.ink : Colors.white,
                  ),
                  onPressed: _toggleKillSwitch,
                  child: Text(engaged ? 'Release kill-switch' : 'Engage kill-switch'),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        const ArmxSectionHeader(title: 'Tools', description: 'Disable a tool globally; the gateway blocks it even if the model asks.'),
        for (final tool in _tools)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: ArmxCard(
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(tool['name'].toString(), style: Theme.of(context).textTheme.bodyMedium),
                        const SizedBox(height: 4),
                        Wrap(spacing: 6, children: [
                          ArmxBadge('${tool['risk']}', tone: riskTone(tool['risk'].toString())),
                          ArmxBadge(tool['category'].toString()),
                        ]),
                      ],
                    ),
                  ),
                  Switch(
                    value: tool['enabled_global'] != false,
                    onChanged: (_) => _toggleTool(tool),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
