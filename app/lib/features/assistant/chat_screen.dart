import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';
import '../../core/app_state.dart';
import '../../core/theme.dart';
import '../../core/widgets/primitives.dart';
import '../voice/wake_word_service.dart';

class ChatMessage {
  ChatMessage({required this.role, required this.text, this.events = const [], this.approval});

  final String role; // user | assistant
  final String text;
  final List<Map<String, dynamic>> events;
  final Map<String, dynamic>? approval;
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<ChatMessage> _messages = [];

  String? _conversationId;
  String? _runId;
  Map<String, dynamic>? _pendingApproval;
  bool _busy = false;
  String? _error;
  StreamSubscription<String>? _wakeSub;

  @override
  void initState() {
    super.initState();
    _wakeSub = context.read<WakeWordService>().commands.listen((command) {
      if (command.isNotEmpty) _send(command);
    });
  }

  @override
  void dispose() {
    _wakeSub?.cancel();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 220), curve: Curves.easeOut);
      }
    });
  }

  Future<void> _send(String raw) async {
    final text = raw.trim();
    if (text.isEmpty || _busy) return;
    final api = context.read<AuthController>().api;
    setState(() {
      _busy = true;
      _error = null;
      _messages.add(ChatMessage(role: 'user', text: text));
      _input.clear();
    });
    _scrollToEnd();

    try {
      final data = await api.post('/assistant/chat', {
        'message': text,
        if (_conversationId != null) 'conversation_id': _conversationId,
      }) as Map<String, dynamic>;

      _conversationId = data['conversation_id'] as String?;
      _runId = data['run_id'] as String?;
      final approval = data['approval'] as Map<String, dynamic>?;
      final events = ((data['tool_events'] as List?) ?? const []).cast<Map<String, dynamic>>();

      setState(() {
        _messages.add(ChatMessage(
          role: 'assistant',
          text: (data['reply'] as String?)?.trim().isNotEmpty == true
              ? data['reply'] as String
              : (approval != null ? 'This action needs your approval before it runs.' : ''),
          events: events,
          approval: approval,
        ));
        _pendingApproval = approval;
      });

      if (approval != null && mounted) {
        final approved = await showApprovalSheet(
          context,
          tool: approval['tool'] as String,
          risk: approval['risk'] as String,
          args: (approval['args'] as Map?)?.cast<String, dynamic>() ?? const {},
          description: approval['description'] as String?,
        );
        await _decide(approved ? 'approve' : 'reject', approval['id'] as String);
      }
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
      _scrollToEnd();
    }
  }

  Future<void> _decide(String decision, String approvalId) async {
    if (_runId == null) return;
    final api = context.read<AuthController>().api;
    setState(() => _busy = true);
    try {
      final data = await api.post('/assistant/runs/$_runId/approve', {
        'approval_id': approvalId,
        'decision': decision,
      }) as Map<String, dynamic>;
      final events = ((data['tool_events'] as List?) ?? const []).cast<Map<String, dynamic>>();
      setState(() {
        _messages.add(ChatMessage(
          role: 'assistant',
          text: decision == 'reject'
              ? 'Cancelled — nothing was executed.'
              : ((data['reply'] as String?) ?? 'Done.'),
          events: events,
        ));
        _pendingApproval = null;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
      _scrollToEnd();
    }
  }

  @override
  Widget build(BuildContext context) {
    final wake = context.watch<WakeWordService>();

    return Column(
      children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            border: Border(bottom: BorderSide(color: Theme.of(context).dividerColor)),
          ),
          child: Row(
            children: [
              ArmxBadge(
                wake.isListening ? 'wake word listening' : 'wake word off',
                tone: wake.isListening ? ArmxTone.success : ArmxTone.neutral,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Say “hey armx …”. Detection runs on-device; Android keeps a notification visible while listening.',
                  style: Theme.of(context).textTheme.bodySmall,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Switch(
                value: wake.isListening,
                onChanged: (value) async {
                  if (value) {
                    final ok = await wake.enable();
                    if (!ok && context.mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(content: Text(wake.lastError ?? 'Could not start listening')),
                      );
                    }
                  } else {
                    await wake.disable();
                  }
                },
              ),
            ],
          ),
        ),
        Expanded(
          child: _messages.isEmpty
              ? ArmxEmptyState(
                  title: 'Ask for something real',
                  description:
                      'Anything that touches a device, a repo or another person asks you first. Voice works with a wake word here, push-to-talk on web.',
                  action: Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    alignment: WrapAlignment.center,
                    children: [
                      for (final suggestion in const [
                        'Check system health',
                        'Turn on the living room light',
                        'Build a landing page for a bakery in Dhaka',
                      ])
                        ActionChip(label: Text(suggestion), onPressed: () => _send(suggestion)),
                    ],
                  ),
                )
              : ListView.separated(
                  controller: _scroll,
                  padding: const EdgeInsets.all(16),
                  itemCount: _messages.length + (_error != null ? 1 : 0),
                  separatorBuilder: (_, __) => const SizedBox(height: 12),
                  itemBuilder: (context, index) {
                    if (index == _messages.length && _error != null) {
                      return ArmxErrorState(message: _error!, onRetry: () => setState(() => _error = null));
                    }
                    return _MessageBubble(message: _messages[index]);
                  },
                ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: TextField(
                    controller: _input,
                    minLines: 1,
                    maxLines: 4,
                    textInputAction: TextInputAction.send,
                    onSubmitted: _send,
                    decoration: const InputDecoration(hintText: 'Ask A.R.M.X anything…'),
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  height: ArmxTheme.touchTarget,
                  child: ElevatedButton(
                    onPressed: _busy ? null : () => _send(_input.text),
                    child: _busy
                        ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Text('Send'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == 'user';
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.86),
        child: Column(
          crossAxisAlignment: isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: isUser ? ArmxColors.accent : Theme.of(context).cardColor,
                borderRadius: BorderRadius.circular(ArmxTheme.radiusLg),
                border: isUser ? null : Border.all(color: Theme.of(context).dividerColor),
              ),
              child: Text(
                message.text,
                style: Theme.of(context)
                    .textTheme
                    .bodyMedium
                    ?.copyWith(color: isUser ? ArmxColors.ink : null),
              ),
            ),
            for (final event in message.events) _ToolEventCard(event: event),
            if (message.approval != null && message.text.isEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text('Approval request', style: Theme.of(context).textTheme.bodySmall),
              ),
          ],
        ),
      ),
    );
  }
}

class _ToolEventCard extends StatelessWidget {
  const _ToolEventCard({required this.event});

  final Map<String, dynamic> event;

  @override
  Widget build(BuildContext context) {
    final result = (event['result'] as Map?)?.cast<String, dynamic>();
    final data = (result?['data'] as Map?)?.cast<String, dynamic>() ?? const {};
    final ok = event['ok'] == true;
    final preview = data['preview_url'] as String?;
    final live = data['url'] as String?;
    final simulated = data['simulated'] == true;

    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: ArmxCard(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 8,
              runSpacing: 6,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                ArmxBadge(event['tool']?.toString() ?? 'tool', tone: ArmxTone.accent),
                if (event['risk'] != null) ArmxBadge('${event['risk']} risk', tone: riskTone(event['risk'].toString())),
                ArmxBadge(ok ? 'succeeded' : 'blocked/failed', tone: ok ? ArmxTone.success : ArmxTone.danger),
                if (simulated) const ArmxBadge('simulated', tone: ArmxTone.warning),
              ],
            ),
            if ((result?['message'] as String?)?.isNotEmpty == true) ...[
              const SizedBox(height: 8),
              Text(result!['message'] as String, style: Theme.of(context).textTheme.bodySmall),
            ],
            if ((result?['error'] as String?)?.isNotEmpty == true) ...[
              const SizedBox(height: 6),
              Text(result!['error'] as String, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: ArmxColors.danger)),
            ],
            if (preview != null) ...[
              const SizedBox(height: 8),
              Text('Preview ready: $preview', style: Theme.of(context).textTheme.bodySmall),
            ],
            if (live != null) ...[
              const SizedBox(height: 6),
              Text('Live: $live', style: Theme.of(context).textTheme.bodySmall?.copyWith(color: ArmxColors.accent)),
            ],
          ],
        ),
      ),
    );
  }
}
