import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../core/theme.dart';
import '../../core/widgets/primitives.dart';
import '../device_bridge/device_bridge.dart';
import 'managed_device_controller.dart';

class ManagedDeviceScreen extends StatefulWidget {
  const ManagedDeviceScreen({super.key});

  @override
  State<ManagedDeviceScreen> createState() => _ManagedDeviceScreenState();
}

class _ManagedDeviceScreenState extends State<ManagedDeviceScreen> {
  bool desiredKiosk = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final controller = context.read<ManagedDeviceController>();
      controller.refresh().then((_) {
        if (mounted) setState(() => desiredKiosk = controller.kioskEnabled);
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ManagedDeviceController>();
    final bridge = context.watch<DeviceBridge>();
    if (!controller.supported && !controller.loading) {
      return const ArmxEmptyState(
        title: 'Android Device Owner only',
        description: 'Managed launcher and kiosk policy are available on Android dedicated devices.',
      );
    }
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const ArmxSectionHeader(
          title: 'Managed device',
          description: 'Visible, owner-controlled Device Owner mode. There is no hidden capture or uninstall bypass.',
        ),
        if (controller.loading) const LinearProgressIndicator(minHeight: 2),
        if (controller.error != null) ...[
          const SizedBox(height: 12),
          ArmxErrorState(message: controller.error!, onRetry: controller.refresh),
        ],
        const SizedBox(height: 12),
        if (!controller.deviceOwner) _ProvisioningCard(state: controller.state),
        if (controller.deviceOwner) ...[
          _StatusCard(controller: controller),
          if (bridge.pendingPolicy != null || bridge.pendingScreenShare != null || bridge.pendingVoiceSession != null) ...[
            const SizedBox(height: 16),
            _PendingOwnerActions(bridge: bridge),
          ],
          const SizedBox(height: 16),
          if (!controller.notificationPermission)
            ArmxCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Visibility permission required', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 6),
                  Text('Management and consent sessions must keep a visible notification. Kiosk policy stays blocked until notifications are allowed.', style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 12),
                  ElevatedButton(onPressed: controller.requestNotificationPermission, child: const Text('Allow visible notifications')),
                ],
              ),
            ),
          if (!controller.passcodeConfigured) ...[
            const SizedBox(height: 16),
            _InitialPasscodeCard(controller: controller),
          ],
          if (controller.passcodeConfigured) ...[
            const SizedBox(height: 16),
            _PolicyCard(
              controller: controller,
              desiredKiosk: desiredKiosk,
              onKioskChanged: (value) => setState(() => desiredKiosk = value),
            ),
            const SizedBox(height: 16),
            _TelemetryCard(controller: controller),
            const SizedBox(height: 16),
            _DeprovisionCard(controller: controller),
          ],
        ],
      ],
    );
  }
}

class _ProvisioningCard extends StatelessWidget {
  const _ProvisioningCard({required this.state});
  final Map<String, dynamic> state;

  @override
  Widget build(BuildContext context) {
    final command = state['provisioningCommand'] as String? ?? 'Provision with Android Enterprise QR or adb.';
    return ArmxCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const ArmxBadge('NOT ENROLLED', tone: ArmxTone.warning),
          const SizedBox(height: 12),
          Text('Provision a dedicated device', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 6),
          Text(
            'Android only allows Device Owner enrollment during initial setup on a factory-reset device with no accounts. This app cannot bypass that platform rule.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 12),
          SelectableText(command, style: const TextStyle(fontFamily: 'monospace', color: ArmxColors.accent)),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: command));
              if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Provisioning command copied')));
            },
            icon: const Icon(Icons.copy_outlined),
            label: const Text('Copy test-device command'),
          ),
        ],
      ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.controller});
  final ManagedDeviceController controller;

  @override
  Widget build(BuildContext context) => ArmxCard(
        child: Wrap(
          spacing: 8,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            const ArmxBadge('DEVICE OWNER', tone: ArmxTone.success),
            ArmxBadge(controller.kioskEnabled ? 'KIOSK ACTIVE' : 'KIOSK OFF', tone: controller.kioskEnabled ? ArmxTone.accent : ArmxTone.neutral),
            ArmxBadge(controller.notificationPermission ? 'VISIBLE' : 'NOTIFICATIONS BLOCKED', tone: controller.notificationPermission ? ArmxTone.success : ArmxTone.danger),
            ArmxBadge(controller.usageAccess ? 'USAGE ALLOWED' : 'USAGE OFF', tone: controller.usageAccess ? ArmxTone.success : ArmxTone.neutral),
          ],
        ),
      );
}

class _PendingOwnerActions extends StatelessWidget {
  const _PendingOwnerActions({required this.bridge});
  final DeviceBridge bridge;

  @override
  Widget build(BuildContext context) => ArmxCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const ArmxBadge('LOCAL DECISION REQUIRED', tone: ArmxTone.warning),
            const SizedBox(height: 10),
            Text('Pending owner actions', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            Text('Remote requests cannot cross these gates. Approve or decline on this device.', style: Theme.of(context).textTheme.bodySmall),
            if (bridge.pendingPolicy != null) ...[
              const Divider(height: 24),
              const Text('A management policy is waiting for the local owner passcode.'),
              const SizedBox(height: 8),
              ElevatedButton(
                onPressed: () async {
                  final passcode = await _passcodeDialog(context, title: 'Apply pending policy');
                  if (passcode != null) await bridge.applyPendingPolicy(passcode);
                },
                child: const Text('Review and apply with passcode'),
              ),
            ],
            if (bridge.pendingScreenShare != null) ...[
              const Divider(height: 24),
              const Text('Screen-share request. Android will show its own capture-consent dialog, system indicator and an ongoing Stop notification.'),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                children: [
                  OutlinedButton(onPressed: () => bridge.decidePendingScreenShare(false), child: const Text('Decline')),
                  ElevatedButton(onPressed: () => bridge.decidePendingScreenShare(true), child: const Text('Review Android consent')),
                ],
              ),
            ],
            if (bridge.pendingVoiceSession != null) ...[
              const Divider(height: 24),
              const Text('Voice-session request. Microphone permission and an ongoing Stop notification are mandatory.'),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                children: [
                  OutlinedButton(onPressed: () => bridge.decidePendingVoiceSession(false), child: const Text('Decline')),
                  ElevatedButton(onPressed: () => bridge.decidePendingVoiceSession(true), child: const Text('Start visible voice session')),
                ],
              ),
            ],
          ],
        ),
      );
}

class _InitialPasscodeCard extends StatefulWidget {
  const _InitialPasscodeCard({required this.controller});
  final ManagedDeviceController controller;

  @override
  State<_InitialPasscodeCard> createState() => _InitialPasscodeCardState();
}

class _InitialPasscodeCardState extends State<_InitialPasscodeCard> {
  final first = TextEditingController();
  final second = TextEditingController();

  @override
  void dispose() {
    first.dispose();
    second.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ArmxCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Set local owner passcode', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            Text('Required for policy changes and deprovisioning. It never leaves this device and cannot be reset remotely.', style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            TextField(controller: first, obscureText: true, autocorrect: false, decoration: const InputDecoration(labelText: 'Passcode', helperText: '8+ characters with a letter and number')),
            const SizedBox(height: 10),
            TextField(controller: second, obscureText: true, autocorrect: false, decoration: const InputDecoration(labelText: 'Confirm passcode')),
            const SizedBox(height: 12),
            ElevatedButton(
              onPressed: widget.controller.loading
                  ? null
                  : () async {
                      if (first.text != second.text) {
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Passcodes do not match')));
                        return;
                      }
                      final ok = await widget.controller.setInitialPasscode(first.text);
                      first.clear();
                      second.clear();
                      if (ok && context.mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Owner passcode secured')));
                    },
              child: const Text('Secure owner controls'),
            ),
          ],
        ),
      );
}

class _PolicyCard extends StatelessWidget {
  const _PolicyCard({required this.controller, required this.desiredKiosk, required this.onKioskChanged});
  final ManagedDeviceController controller;
  final bool desiredKiosk;
  final ValueChanged<bool> onKioskChanged;

  @override
  Widget build(BuildContext context) => ArmxCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Launcher and app allowlist', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            Text('Only third-party launcher apps outside this allowlist are suspended. System apps are never silently removed.', style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            SwitchListTile.adaptive(
              contentPadding: EdgeInsets.zero,
              value: desiredKiosk,
              onChanged: onKioskChanged,
              title: const Text('Managed launcher and lock task'),
              subtitle: const Text('Notifications and the power menu remain available.'),
            ),
            const Divider(),
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 360),
              child: ListView.builder(
                shrinkWrap: true,
                itemCount: controller.applications.length,
                itemBuilder: (context, index) {
                  final app = controller.applications[index];
                  return CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: controller.selectedPackages.contains(app.packageName),
                    onChanged: app.packageName == 'ai.armx.managed' ? null : (value) => controller.selectPackage(app.packageName, value ?? false),
                    title: Text(app.label),
                    subtitle: Text('${app.packageName}${app.systemApp ? ' · system' : ''}', style: Theme.of(context).textTheme.bodySmall),
                  );
                },
              ),
            ),
            const SizedBox(height: 12),
            ElevatedButton.icon(
              onPressed: !controller.notificationPermission || controller.loading
                  ? null
                  : () async {
                      final passcode = await _passcodeDialog(context, title: 'Authorize policy change');
                      if (passcode != null) await controller.applyPolicy(passcode: passcode, kiosk: desiredKiosk);
                    },
              icon: const Icon(Icons.admin_panel_settings_outlined),
              label: const Text('Apply with owner passcode'),
            ),
          ],
        ),
      );
}

class _TelemetryCard extends StatelessWidget {
  const _TelemetryCard({required this.controller});
  final ManagedDeviceController controller;

  @override
  Widget build(BuildContext context) => ArmxCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('App-usage telemetry', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 6),
            Text('Optional Android usage access reports only package name, foreground seconds and launch count. It never captures content, typing or notifications.', style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: controller.openUsageAccessSettings,
              child: Text(controller.usageAccess ? 'Review usage permission' : 'Grant usage permission'),
            ),
          ],
        ),
      );
}

class _DeprovisionCard extends StatelessWidget {
  const _DeprovisionCard({required this.controller});
  final ManagedDeviceController controller;

  @override
  Widget build(BuildContext context) => ArmxCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Owner deprovisioning', style: Theme.of(context).textTheme.titleMedium?.copyWith(color: ArmxColors.danger)),
            const SizedBox(height: 6),
            Text('Clears kiosk policy, unsuspends apps and relinquishes Device Owner. Android still requires a separate system-confirmed uninstall.', style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: controller.loading
                  ? null
                  : () async {
                      final confirmed = await showDialog<bool>(
                            context: context,
                            builder: (context) => AlertDialog(
                              title: const Text('Deprovision this device?'),
                              content: const Text('Managed restrictions and launcher ownership will be removed. This cannot be undone without factory-reset provisioning.'),
                              actions: [
                                TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
                                ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Continue')),
                              ],
                            ),
                          ) ??
                          false;
                      if (!confirmed || !context.mounted) return;
                      final passcode = await _passcodeDialog(context, title: 'Enter owner passcode to deprovision');
                      if (passcode != null) await controller.deprovision(passcode);
                    },
              icon: const Icon(Icons.phonelink_erase_outlined),
              label: const Text('Deprovision with passcode'),
            ),
          ],
        ),
      );
}

Future<String?> _passcodeDialog(BuildContext context, {required String title}) async {
  final input = TextEditingController();
  final value = await showDialog<String>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(title),
      content: TextField(
        controller: input,
        obscureText: true,
        autofocus: true,
        autocorrect: false,
        decoration: const InputDecoration(labelText: 'Local owner passcode'),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        ElevatedButton(onPressed: () => Navigator.pop(context, input.text), child: const Text('Authorize')),
      ],
    ),
  );
  input.clear();
  input.dispose();
  return value?.isEmpty == true ? null : value;
}
