import 'package:flutter/material.dart';

import '../theme.dart';

/// The shared component set. Screens compose these - no ad-hoc styling.
class ArmxCard extends StatelessWidget {
  const ArmxCard({super.key, required this.child, this.padding = const EdgeInsets.all(16)});

  final Widget child;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) => Card(child: Padding(padding: padding, child: child));
}

class ArmxSectionHeader extends StatelessWidget {
  const ArmxSectionHeader({super.key, required this.title, this.description, this.trailing});

  final String title;
  final String? description;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: theme.textTheme.headlineMedium),
                if (description != null) ...[
                  const SizedBox(height: 4),
                  Text(description!, style: theme.textTheme.bodySmall),
                ],
              ],
            ),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

class ArmxBadge extends StatelessWidget {
  const ArmxBadge(this.label, {super.key, this.tone = ArmxTone.neutral});

  final String label;
  final ArmxTone tone;

  @override
  Widget build(BuildContext context) {
    final color = switch (tone) {
      ArmxTone.neutral => ArmxColors.muted,
      ArmxTone.accent => ArmxColors.accent,
      ArmxTone.success => ArmxColors.success,
      ArmxTone.warning => ArmxColors.warning,
      ArmxTone.danger => ArmxColors.danger,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withOpacity(0.45)),
      ),
      child: Text(
        label,
        style: TextStyle(color: color, fontSize: 12.5, fontWeight: FontWeight.w600),
      ),
    );
  }
}

enum ArmxTone { neutral, accent, success, warning, danger }

ArmxTone riskTone(String risk) => switch (risk) {
      'high' => ArmxTone.danger,
      'medium' => ArmxTone.warning,
      _ => ArmxTone.success,
    };

class ArmxEmptyState extends StatelessWidget {
  const ArmxEmptyState({super.key, required this.title, this.description, this.action});

  final String title;
  final String? description;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.auto_awesome_outlined, size: 32, color: theme.hintColor),
            const SizedBox(height: 12),
            Text(title, style: theme.textTheme.titleMedium, textAlign: TextAlign.center),
            if (description != null) ...[
              const SizedBox(height: 6),
              Text(description!, style: theme.textTheme.bodySmall, textAlign: TextAlign.center),
            ],
            if (action != null) ...[const SizedBox(height: 16), action!],
          ],
        ),
      ),
    );
  }
}

class ArmxErrorState extends StatelessWidget {
  const ArmxErrorState({super.key, this.title = 'Something went wrong', required this.message, this.onRetry});

  final String title;
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: ArmxColors.danger.withOpacity(0.08),
        borderRadius: BorderRadius.circular(ArmxTheme.radiusMd),
        border: Border.all(color: ArmxColors.danger.withOpacity(0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: theme.textTheme.titleMedium?.copyWith(color: ArmxColors.danger)),
          const SizedBox(height: 4),
          Text(message, style: theme.textTheme.bodySmall),
          if (onRetry != null) ...[
            const SizedBox(height: 12),
            OutlinedButton(onPressed: onRetry, child: const Text('Try again')),
          ],
        ],
      ),
    );
  }
}

class ArmxLoading extends StatelessWidget {
  const ArmxLoading({super.key, this.label = 'Loading'});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2)),
          const SizedBox(width: 12),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}

/// Every MEDIUM/HIGH action goes through this before it can run.
Future<bool> showApprovalSheet(
  BuildContext context, {
  required String tool,
  required String risk,
  required Map<String, dynamic> args,
  String? description,
}) async {
  final approved = await showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Theme.of(context).cardColor,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(ArmxTheme.radiusLg)),
    ),
    builder: (context) => Padding(
      padding: EdgeInsets.fromLTRB(20, 20, 20, 20 + MediaQuery.viewInsetsOf(context).bottom),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            risk == 'high' ? 'High-risk action needs approval' : 'Medium-risk action needs approval',
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 6),
          Text(
            'Nothing runs until you approve. The approval is single-use and expires in two minutes.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              ArmxBadge(tool, tone: ArmxTone.accent),
              const SizedBox(width: 8),
              ArmxBadge('${risk.toUpperCase()} risk', tone: riskTone(risk)),
            ],
          ),
          if (description != null) ...[
            const SizedBox(height: 12),
            Text(description, style: Theme.of(context).textTheme.bodySmall),
          ],
          const SizedBox(height: 12),
          ...args.entries.map(
            (entry) => Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text('${entry.key}: ${entry.value}', style: Theme.of(context).textTheme.bodySmall),
            ),
          ),
          const SizedBox(height: 20),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: () => Navigator.of(context).pop(false),
                  child: const Text('Cancel'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: ElevatedButton(
                  onPressed: () => Navigator.of(context).pop(true),
                  child: const Text('Approve'),
                ),
              ),
            ],
          ),
        ],
      ),
    ),
  );
  return approved ?? false;
}
