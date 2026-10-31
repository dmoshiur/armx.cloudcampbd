import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/app_state.dart';
import '../../core/widgets/primitives.dart';

class BuilderScreen extends StatefulWidget {
  const BuilderScreen({super.key});

  @override
  State<BuilderScreen> createState() => _BuilderScreenState();
}

class _BuilderScreenState extends State<BuilderScreen> {
  final _prompt = TextEditingController();
  List<Map<String, dynamic>> _projects = [];
  bool _loading = true;
  bool _busy = false;
  String? _error;
  Map<String, dynamic>? _lastPreview;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _prompt.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    final api = context.read<AuthController>().api;
    try {
      final data = await api.get('/projects') as List;
      setState(() {
        _projects = data.cast<Map<String, dynamic>>();
        _error = null;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      setState(() => _loading = false);
    }
  }

  Future<void> _generate() async {
    if (_prompt.text.trim().isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final api = context.read<AuthController>().api;
    try {
      final data = await api.post('/assistant/chat', {'message': 'build a website: ${_prompt.text.trim()}'})
          as Map<String, dynamic>;

      var approval = data['approval'] as Map<String, dynamic>?;
      var runId = data['run_id'] as String?;

      while (approval != null && runId != null) {
        final approved = await showApprovalSheet(
          context,
          tool: approval['tool'] as String,
          risk: approval['risk'] as String,
          args: (approval['args'] as Map?)?.cast<String, dynamic>() ?? const {},
          description: approval['description'] as String?,
        );
        final next = await api.post('/assistant/runs/$runId/approve', {
          'approval_id': approval['id'],
          'decision': approved ? 'approve' : 'reject',
        }) as Map<String, dynamic>;
        if (!approved) break;
        approval = next['approval'] as Map<String, dynamic>?;
        runId = next['run_id'] as String?;
        final events = ((next['tool_events'] as List?) ?? const []).cast<Map<String, dynamic>>();
        for (final event in events) {
          final result = (event['result'] as Map?)?.cast<String, dynamic>();
          final payload = (result?['data'] as Map?)?.cast<String, dynamic>();
          if (payload != null && payload['preview_url'] != null) {
            setState(() => _lastPreview = payload);
          }
        }
      }
      await _load();
    } on ApiException catch (e) {
      setState(() => _error = e.message);
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
                title: 'Describe a site',
                description:
                    'The assistant drafts it in a sandbox, runs the design lint and shows a preview. Deploying is a separate, confirmed step.',
              ),
              TextField(
                controller: _prompt,
                minLines: 3,
                maxLines: 6,
                decoration: const InputDecoration(
                  hintText: 'A landing page for a coffee roastery in Dhaka with hours, menu and contact form',
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: ElevatedButton(
                      onPressed: _busy ? null : _generate,
                      child: _busy
                          ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Text('Generate'),
                    ),
                  ),
                ],
              ),
              if (_lastPreview != null) ...[
                const SizedBox(height: 12),
                Text('Preview: ${_lastPreview!['preview_url']}', style: Theme.of(context).textTheme.bodySmall),
              ],
            ],
          ),
        ),
        const SizedBox(height: 16),
        if (_error != null) ArmxErrorState(message: _error!, onRetry: _load),
        if (_loading)
          const ArmxLoading(label: 'Loading projects')
        else if (_projects.isEmpty)
          const ArmxEmptyState(title: 'No projects yet', description: 'Describe a site above to create your first one.')
        else ...[
          const ArmxSectionHeader(title: 'Your projects'),
          for (final project in _projects)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: ArmxCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(child: Text(project['name'].toString(), style: Theme.of(context).textTheme.titleMedium)),
                        ArmxBadge(project['status'].toString(),
                            tone: project['status'] == 'deployed' ? ArmxTone.success : ArmxTone.neutral),
                        const SizedBox(width: 6),
                        ArmxBadge('lint ${project['lint_status']}',
                            tone: project['lint_status'] == 'pass' ? ArmxTone.success : ArmxTone.warning),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      (project['vercel_url'] as String?)?.isNotEmpty == true
                          ? project['vercel_url'] as String
                          : 'Not deployed yet',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    if (project['repo_is_platform_owned'] == true)
                      Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: Text(
                          'Pushed to the platform GitHub account',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.orange),
                        ),
                      ),
                  ],
                ),
              ),
            ),
        ],
      ],
    );
  }
}
