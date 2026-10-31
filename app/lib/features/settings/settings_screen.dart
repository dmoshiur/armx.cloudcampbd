import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/app_state.dart';
import '../../core/widgets/primitives.dart';
import '../device_bridge/device_bridge.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final bridge = context.watch<DeviceBridge>();

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        ArmxCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const ArmxSectionHeader(title: 'Account'),
              Text(auth.user?.email ?? '—', style: Theme.of(context).textTheme.bodyMedium),
              const SizedBox(height: 6),
              Wrap(
                spacing: 8,
                children: [
                  ArmxBadge(auth.user?.role ?? 'user', tone: ArmxTone.accent),
                  if (auth.user?.canLinkDevices != true)
                    const ArmxBadge('VIP needed for devices', tone: ArmxTone.warning),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        ArmxCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const ArmxSectionHeader(title: 'Appearance'),
              RadioListTile<String>(
                value: 'dark',
                groupValue: auth.themeMode,
                onChanged: (value) => auth.setTheme(value ?? 'dark'),
                title: const Text('Dark (default)'),
                contentPadding: EdgeInsets.zero,
              ),
              RadioListTile<String>(
                value: 'light',
                groupValue: auth.themeMode,
                onChanged: (value) => auth.setTheme(value ?? 'dark'),
                title: const Text('Light'),
                contentPadding: EdgeInsets.zero,
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        ArmxCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const ArmxSectionHeader(
                title: 'This device',
                description: 'Linking is visible on this device at all times. Unlinking needs the password you set here.',
              ),
              Text(bridge.linked ? 'Linked as ${bridge.deviceName ?? 'device'}' : 'Not linked',
                  style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 8),
              if (bridge.linked)
                OutlinedButton(
                  onPressed: () async {
                    final controller = TextEditingController();
                    final ok = await showDialog<bool>(
                      context: context,
                      builder: (context) => AlertDialog(
                        title: const Text('Unlink this device'),
                        content: TextField(
                          controller: controller,
                          obscureText: true,
                          decoration: const InputDecoration(labelText: 'Unlink password'),
                        ),
                        actions: [
                          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
                          ElevatedButton(onPressed: () => Navigator.pop(context, true), child: const Text('Unlink')),
                        ],
                      ),
                    );
                    if (ok == true) {
                      await bridge.unlinkWithPassword(controller.text);
                    }
                  },
                  child: const Text('Unlink this device'),
                ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        ArmxCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const ArmxSectionHeader(title: 'What this app can and cannot do'),
              const _Capability(text: 'Wake word and background listening: available here, on-device detection only.'),
              const _Capability(text: 'Push-to-talk: always available. Web has push-to-talk only.'),
              const _Capability(text: 'Call control and app launch: only on your own linked device, always visible.'),
              const _Capability(text: 'Call recording, SMS reading, silent capture: never implemented.'),
            ],
          ),
        ),
        const SizedBox(height: 16),
        OutlinedButton(
          onPressed: auth.logout,
          child: const Text('Sign out'),
        ),
      ],
    );
  }
}

class _Capability extends StatelessWidget {
  const _Capability({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('•  '),
            Expanded(child: Text(text, style: Theme.of(context).textTheme.bodySmall)),
          ],
        ),
      );
}
